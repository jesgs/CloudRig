"""
This file is loaded into a self-executing text datablock and attached to all
CloudRig rigs.
It's responsible for drawing the CloudRig panel in the 3D View's Sidebar.
"""

from typing import List, Dict, Tuple, Iterable, Optional
import bpy, traceback, json, re, contextlib
import collections as py_collections
from collections import OrderedDict
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
    IntProperty,
)
from bpy.types import Object, PoseBone
from bpy.utils import register_class, unregister_class

from mathutils import Matrix
from rna_prop_ui import rna_idprop_quote_path
from bl_ui.generic_ui_list import draw_ui_list


def is_generated_cloudrig(arm_ob):
    """Return whether obj is marked as being compatible with cloudrig.py."""
    return (
        'is_generated_cloudrig' in arm_ob.data and arm_ob.data['is_generated_cloudrig']
    )


def get_all_generated_cloudrigs():
    """Find all cloudrig armature objects in the file."""
    return [
        o for o in bpy.data.objects if o.type == 'ARMATURE' and is_generated_cloudrig(o)
    ]


def is_active_cloudrig(context):
    """If the active object is a cloudrig, return it."""
    if not hasattr(context, 'pose_object'):
        # Can happen when a file is saved with the UI open,
        # and that UI is trying to draw during file open, when context isn't
        # initialized yet.
        return False
    rig = context.pose_object or context.active_object
    if not rig:
        return False
    if rig.type != 'ARMATURE':
        return False
    if rig and is_generated_cloudrig(rig):
        return rig


def is_cloud_metarig(rig: Object):
    if not rig:
        return False
    if rig.type != 'ARMATURE':
        return False
    return hasattr(rig, 'cloudrig') and rig.cloudrig.enabled


def is_active_cloud_metarig(context):
    return is_cloud_metarig(context.active_object)


def find_metarig_of_rig(context, rig: Object) -> Optional[Object]:
    # First, try to find it by name, which should work most of the time.
    for prefix in {'RIG-', 'FAILED-RIG-'}:
        if rig.name.startswith(prefix):
            metarig = context.scene.objects.get(rig.name.replace(prefix, ""))
            if not metarig:
                metarig = context.scene.objects.get(rig.name.replace(prefix, "META-"))
            if metarig:
                return metarig

    # If that failed, scan the whole scene.
    for obj in context.scene.objects:
        if obj.type != 'ARMATURE':
            continue
        if obj.cloudrig.generator.target_rig == rig:
            return obj


#######################################
############ Keyframe Baking ##########
#######################################


class SnappingOperator:
    bone_names: StringProperty(
        name="Bone Names",
        description="A python list converted to a string with json.dumps(). The order of the bone names matters, as dependents should come after their dependencies (ie. children after parents)",
    )
    prop_bone: StringProperty(
        name="Property Bone Name",
        description="Name of the pose bone on the active object that should have a custom property named prop_id",
    )
    prop_id: StringProperty(
        name="Custom Property Name",
        description="Name of the custom property on the pose bone, which will be toggled by this operator",
    )

    @staticmethod
    def get_context_rig(context) -> Object | None:
        if context.pose_object:
            return context.pose_object

        if context.active_object.type == 'ARMATURE':
            return context.active_object

    @classmethod
    def poll(cls, context) -> bool:
        rig = cls.get_context_rig(context)
        if not rig:
            return False
        return True

    @staticmethod
    def get_prop_target_value(prop_pb, prop_id) -> float:
        if prop_pb[prop_id] < 1.0:
            return 1.0
        return 0.0

    def get_properties_bone(self, rig: Object) -> PoseBone:
        if self.prop_bone not in rig.pose.bones:
            raise Exception(f"Bone not found in rig: `{self.prop_bone}`.")

        prop_pb = rig.pose.bones[self.prop_bone]
        if self.prop_id not in prop_pb:
            raise Exception(
                f"Property `{self.prop_id}` not found in bone `{self.prop_bone}`."
            )

        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        if int(prop_pb[self.prop_id]) == target_value:
            raise Exception(
                f"Value of property `{self.prop_id}` is already {target_value}."
            )

        return prop_pb

    def get_affected_pbones(self, rig: Object) -> list[PoseBone]:
        affected_pbones = set()
        for bone_name in json.loads(self.bone_names):
            pb = rig.pose.bones.get(bone_name)
            if pb:
                affected_pbones.add(pb)
            else:
                raise Exception(f"Bone `{bone_name}` not found.")
        return affected_pbones

    @staticmethod
    def get_pbone_matrix_map(
        bones_to_snap: list[PoseBone], snap_to_bones: list[PoseBone] = []
    ) -> OrderedDict[str, Matrix]:
        if not snap_to_bones:
            snap_to_bones = bones_to_snap
        assert len(bones_to_snap) == len(snap_to_bones)
        return OrderedDict(
            [
                (snapped_bone.name, snap_target.matrix.copy())
                for snapped_bone, snap_target in zip(bones_to_snap, snap_to_bones)
            ]
        )

    @staticmethod
    def set_bone_selection(rig, select=False, pbones: list[PoseBone] = []):
        if not pbones:
            pbones = rig.pose.bones
        for pb in pbones:
            pb.bone.select = select

    @staticmethod
    def reveal_bones(pbones: list[PoseBone]):
        for pb in pbones:
            if pb.bone.hide:
                pb.bone.hide = False
            if not any([coll.is_visible for coll in pb.bone.collections]):
                coll = pb.bone.collections[0]
                while coll:
                    coll.is_visible = True
                    coll = coll.parent

    def set_bone_matrices(
        self, context, rig: Object, pbone_matrix_map: dict[str, Matrix]
    ):
        for bone_name, mat in pbone_matrix_map.items():
            context.view_layer.update()
            pb = rig.pose.bones[bone_name]
            pb.matrix = mat.copy()


class SnapBakeOperator(SnappingOperator):
    do_bake: BoolProperty(name="Bake", default=False)
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")
    key_before_start: BoolProperty(name="Key Before Start", description="Insert a keyframe of the original values one frame before the bake range. This is to avoid undesired interpolation towards the bake")
    key_after_end: BoolProperty(name="Key After End", description="Insert a keyframe of the original values one frame after the bake range. This is to avoid undesired interpolation after the bake")

    def invoke(self, context, _event):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        self.do_bake = False
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout

        self.layout.prop(self, 'do_bake')
        split = layout.split(factor=0.1)
        split.row()
        col = split.column()
        if self.do_bake:
            time_row = col.row(align=True)
            time_row.prop(self, 'frame_start')
            time_row.prop(self, 'frame_end')
            fix_row = col.row(align=True)
            fix_row.prop(self, 'key_before_start')
            fix_row.prop(self, 'key_after_end')
        
        self.draw_affected_bones(layout, context)

    def draw_affected_bones(self, layout, context):
        rig = self.get_context_rig(context)
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def get_frame_range(self, context) -> list[int]:
        if not self.do_bake:
            return [context.scene.frame_current]

        return range(self.frame_start, self.frame_end+1)

    @staticmethod
    def ensure_action(rig: Object):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.aciton = bpy.data.actions.new("ACT-" + rig.name)

    def map_frames_to_bone_matrices(
        self,
        context,
        bones_to_snap: list[PoseBone],
        snap_to_bones: list[PoseBone] = [],
        frame_numbers: list[int] = [],
    ) -> OrderedDict[int, OrderedDict[PoseBone, Matrix]]:
        if not frame_numbers:
            frame_numbers = self.get_frame_range(context)
        if not snap_to_bones:
            snap_to_bones = bones_to_snap

        frame_matrix_map = OrderedDict()
        for frame_number in frame_numbers:
            frame_matrix_map[frame_number] = self.map_single_frame_to_bone_matrices(
                context, frame_number, bones_to_snap, snap_to_bones
            )

        return frame_matrix_map

    def map_single_frame_to_bone_matrices(
        self,
        context,
        frame_number: int,
        bones_to_snap: list[PoseBone],
        snap_to_bones: list[PoseBone] = [],
    ):
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        return self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

    def keyframe_bones(
        self, context, frame_matrix_map: dict[int, dict[str, Matrix]], prop_pb: PoseBone
    ):
        rig = self.get_context_rig(context)
        pbones = [
            rig.pose.bones[name]
            for name in list(list(frame_matrix_map.values())[0].keys())
        ]

        # Deselect all bones, then reveal and select affected bones.
        self.set_bone_selection(rig, False)
        self.reveal_bones(pbones)
        self.set_bone_selection(rig, True, pbones)

        frame_numbers = list(frame_matrix_map.keys())

        if self.key_before_start:
            # Key original value and transforms one frame before the selected bake range.
            # This is to avoid our bake causing undesired interpolation before the bake range.
            context.scene.frame_set(frame_numbers[0]-1)
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)
            bpy.ops.anim.keyframe_insert()

        if self.key_after_end:
            # Key original value and transforms one frame after the selected bake range.
            context.scene.frame_set(frame_numbers[-1]+1)
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)
            bpy.ops.anim.keyframe_insert()

        # ViewLayer Update is necessary for some reason.
        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        # Idk why we have to go over them twice, but if we don't, we get issues
        # at the start and end of the frame range.
        for i in range(2):
            for frame_number, pbone_matrix_map in frame_matrix_map.items():
                context.scene.frame_set(frame_number)

                # Change & key property value.
                prop_pb[self.prop_id] = target_value
                prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)

                self.set_bone_matrices(context, rig, pbone_matrix_map)
                bpy.ops.anim.keyframe_insert()


class POSE_OT_cloudrig_snap_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_snap_bake"
    bl_label = "Snap & Bake Bones"
    bl_description = "Flip a custom property's value while preserving the world-matrix of some bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        return self.execute_bone_snap_bake(self, context)

    @staticmethod
    def execute_bone_snap_bake(self, context):
        rig = self.get_context_rig(context)
        try:
            prop_pb = self.get_properties_bone(rig)
            affected_pbones = self.get_affected_pbones(rig)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        active_frame_bkp = context.scene.frame_current

        # Save the matrix of each bone at each frame.
        frame_matrix_map = self.map_frames_to_bone_matrices(context, affected_pbones)

        if self.do_bake:
            self.ensure_action(rig)
            self.keyframe_bones(context, frame_matrix_map, prop_pb)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Store (copies!) of world matrices.
        pbone_matrix_map = list(frame_matrix_map.values())[0]

        # Deselect all bones.
        self.set_bone_selection(rig, False)
        # Reveal & select affected bones.
        self.reveal_bones(affected_pbones)
        self.set_bone_selection(rig, True, affected_pbones)

        # Change property value.
        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        prop_pb[self.prop_id] = target_value
        # Restore world matrices.
        self.set_bone_matrices(context, rig, pbone_matrix_map)

        # If property value is no longer what it should be, change it again, 
        # and this time keyframe it.
        if prop_pb[self.prop_id] != target_value:
            # This happens when the property was already keyed, and the depsgraph update
            # caused it to reset to the previously keyed value.
            prop_pb[self.prop_id] = target_value
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)

        context.scene.frame_set(active_frame_bkp)
        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}


class POST_OT_cloudrig_switch_parent_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_switch_parent_bake"
    bl_label = "Switch Parents & Preserve Transforms"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    parent_names: StringProperty(name="Parent Names")

    def parent_items(self, context):
        parents = json.loads(self.parent_names)
        items = [(str(i), name, name) for i, name in enumerate(parents)]
        return items

    selected: EnumProperty(name="Selected Parent", items=parent_items)

    def draw(self, context):
        self.layout.prop(self, 'selected', text='')
        super().draw(context)


    def get_prop_target_value(self, prop_pb, prop_id) -> int:
        return int(self.selected)

class POSE_OT_cloudrig_toggle_ikfk_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_toggle_ikfk_bake"
    bl_label = "Snap & Bake Bones to Other Bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    map_fk_to_ik: StringProperty(
        description="List of tuples of (fk_bone, target_bone) for snapping FK to IK"
    )
    map_ik_to_fk: StringProperty(
        description="List of tuples of (ik_bone, target_bone) for snapping IK to FK"
    )
    ik_pole: StringProperty(
        description="Name of IK pole vector bone, for snapping IK to FK"
    )

    def draw_affected_bones(self, layout, context):
        rig = self.get_context_rig(context)
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def invoke(self, context, _event):
        self.rig = self.get_context_rig(context)
        try:
            self.prop_pb = self.get_properties_bone(self.rig)
            self.current_value = self.prop_pb[self.prop_id]
            self.target_value = self.get_prop_target_value(self.prop_pb, self.prop_id)
            self.bone_map = self.get_bone_map(self.current_value)
        except Exception as exc:
            # NOTE: This doesn't show line number of the error.
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return super().invoke(context, _event)

    def execute(self, context):
        active_frame_bkp = context.scene.frame_current

        # Store (copies!) of world matrices.
        bones_to_snap = [self.rig.pose.bones[name] for name in self.bone_map.keys()]
        snap_to_bones = [self.rig.pose.bones[name] for name in self.bone_map.values()]
        frame_matrix_map = self.map_frames_to_bone_matrices(
            context, bones_to_snap, snap_to_bones
        )

        if self.do_bake:
            self.keyframe_bones(context, frame_matrix_map, self.prop_pb)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Change property value.
        self.prop_pb[self.prop_id] = self.get_prop_target_value(
            self.prop_pb, self.prop_id
        )

        # Deselect all bones.
        self.set_bone_selection(self.rig, False)

        pbone_matrix_map = list(frame_matrix_map.values())[0]
        # Restore world matrices.
        self.set_bone_matrices(context, self.rig, pbone_matrix_map)

        # Reveal & select affected bones.
        if self.target_value == 1 and self.ik_pole:
            bones_to_snap.append(self.rig.pose.bones[self.ik_pole])
        self.reveal_bones(bones_to_snap)
        self.set_bone_selection(self.rig, True, bones_to_snap)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def get_pole_target_matrix(self, ik_pole: PoseBone, fk_first: PoseBone) -> Matrix:
        """Find the matrix where the IK pole should be."""
        """ This is only accurate when the bone chain lies perfectly on a plane
            and the IK Pole Angle is divisible by 90.
            This should be the case for a correct IK chain!
        """
        mat = ik_pole.matrix.copy()
        # Ultra simple solution, we just project the upperarm FK bone an extra length.
        mat.translation = fk_first.tail + fk_first.vector/2
        return mat

    def map_single_frame_to_bone_matrices(
        self, context, frame_number, bones_to_snap, snap_to_bones
    ):
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        pbone_matrix_map = self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

        if self.target_value == 1 and self.ik_pole:
            # Snap IK pole
            pole_pb = self.rig.pose.bones[self.ik_pole]
            fk_upperarm = snap_to_bones[1]
            pbone_matrix_map[pole_pb.name] = self.get_pole_target_matrix(
                pole_pb, fk_upperarm
            )

        return pbone_matrix_map

    def get_bone_map(self, ik_value: float) -> OrderedDict[str, str]:
        map_fk_to_ik = OrderedDict(json.loads(self.map_fk_to_ik))
        map_ik_to_fk = OrderedDict(json.loads(self.map_ik_to_fk))

        bone_map = map_fk_to_ik if ik_value == 1 else map_ik_to_fk

        return bone_map

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Snapped bones:")
        for from_bone, to_bone in self.bone_map.items():
            bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")

        if self.current_value < 1:
            bone_column.label(text=f"{' '*10} {self.ik_pole}")


#######################################
######## Convenience Operators ########
#######################################


class OBJECT_OT_cloudrig_copy_property(bpy.types.Operator):
    """Set the value of a property on all other CloudRig rigs in the scene"""

    # Currently used for the rig Quality setting, to easily switch all characters to Render or Animation quality.
    bl_idname = "object.cloudrig_copy_property"
    bl_label = "Set Property value on All CloudRigs"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    prop_bone: StringProperty()
    prop_id: StringProperty()

    @classmethod
    def poll(cls, context):
        return (is_active_cloudrig(context) is not None) and (
            context.pose_object or context.active_object
        )

    def invoke(self, context, event):
        # Collect and save references to rigs in the scene which have this property somewhere on the rig.
        # TODO: Add an assert that prop_bone and prop_id are found in context.active_object.
        self.rig_bones = {context.active_object.name: self.prop_bone}
        for rig in context.scene.objects:
            if rig.type != 'ARMATURE' or 'cloudrig' not in rig.data:
                continue
            for pb in rig.pose.bones:
                if self.prop_id in pb:
                    self.rig_bones[rig.name] = pb.name

        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object
        prop_value = rig.pose.bones[self.prop_bone][self.prop_id]

        layout.label(
            text=f"{self.prop_id} property will be set to {prop_value} on these bones:"
        )
        for rigname, bonename in self.rig_bones.items():
            split = layout.split(factor=0.4)
            split.alignment = 'RIGHT'
            split.label(text=rigname, icon='ARMATURE_DATA')
            split.label(text=bonename, icon='BONE_DATA')

    def execute(self, context):
        rig = context.pose_object or context.active_object
        prop_value = rig.pose.bones[self.prop_bone][self.prop_id]

        for rigname, bonename in self.rig_bones.items():
            rig = context.scene.objects[rigname]
            pb = rig.pose.bones[bonename]
            pb[self.prop_id] = prop_value

        return {'FINISHED'}


class POSE_OT_cloudrig_keyframe_all_settings(bpy.types.Operator):
    """Keyframe all rig settings that are being drawn in the below UI"""

    bl_idname = "pose.cloudrig_keyframe_all_settings"
    bl_label = "Keyframe CloudRig Settings"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        rig = is_active_cloudrig(context)
        if not rig:
            return False
        return 'ui_data' in rig.data

    def execute(self, context):
        rig = context.pose_object or context.active_object
        data = rig.data

        ui_data = data['ui_data'].to_dict()

        for subpanel, label_dicts in ui_data.items():
            for label_name, row_dicts in label_dicts.items():
                if label_name == 'NODRAW':
                    continue
                if type(row_dicts) == str:
                    # TODO: For some reason, cloud_ik_finger seems to put a string "CLOUDRIG_PT_custom_ik" here, which is the sub-panel that has a sub-panel.
                    continue
                for row_name, col_dicts in row_dicts.items():
                    for col_name, col_dict in col_dicts.items():
                        assert (
                            'prop_bone' in col_dict and 'prop_id' in col_dict
                        ), "Rig UI info entry must have prop_bone and prop_id."
                        prop_bone_name = col_dict['prop_bone']
                        prop_id = col_dict['prop_id']

                        prop_bone = rig.pose.bones.get(prop_bone_name)
                        assert (
                            prop_bone
                        ), f"Property bone non-existent: {prop_bone_name}"

                        value = prop_bone[prop_id]
                        if type(value) not in (int, float):
                            continue

                        prop_bone.keyframe_insert(rna_idprop_quote_path(prop_id), group=prop_bone.name)


        return {'FINISHED'}


class POSE_OT_cloudrig_reset(bpy.types.Operator):
    """Reset all bone transforms and custom properties to their default values"""

    bl_idname = "pose.cloudrig_reset"
    bl_label = "Reset Rig"
    bl_options = {'REGISTER', 'UNDO'}

    reset_transforms: BoolProperty(
        name="Transforms", default=True, description="Reset bone transforms"
    )
    reset_props: BoolProperty(
        name="Properties", default=True, description="Reset custom properties"
    )
    selection_only: BoolProperty(
        name="Selected Only",
        default=False,
        description="Affect selected bones rather than all bones",
    )

    @classmethod
    def poll(cls, context):
        return context.pose_object or context.active_object

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        rig = context.pose_object or context.active_object
        bones = rig.pose.bones
        if self.selection_only:
            bones = context.selected_pose_bones
        for pb in bones:
            if self.reset_transforms:
                pb.location = (0, 0, 0)
                pb.rotation_euler = (0, 0, 0)
                pb.rotation_quaternion = (1, 0, 0, 0)
                pb.scale = (1, 1, 1)

            if not self.reset_props or len(pb.keys()) == 0:
                continue

            rna_properties = [
                prop.identifier for prop in pb.bl_rna.properties if prop.is_runtime
            ]

            # Reset custom property values to their default value
            for key in pb.keys():
                if key.startswith("$"):
                    continue
                if key in rna_properties:
                    continue  # Addon defined property.

                ui_data = None
                try:
                    ui_data = pb.id_properties_ui(key)
                    if not ui_data:
                        continue
                    ui_data = ui_data.as_dict()
                    if not 'default' in ui_data:
                        continue
                except TypeError:
                    # Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
                    pass

                if not ui_data:
                    continue

                if type(pb[key]) not in (float, int, bool):
                    continue
                pb[key] = ui_data['default']

        return {'FINISHED'}


#######################################
############### Rig UI ################
#######################################


class CLOUDRIG_PT_base(bpy.types.Panel):
    """Base class for all CloudRig sidebar panels."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    on_metarigs = False
    on_generated_rigs = True

    @classmethod
    def poll(cls, context):
        if not context.active_object:
            return False
        obj = context.active_object
        if context.pose_object:
            obj = context.pose_object
        if obj.type != 'ARMATURE':
            return False
        if not cls.on_generated_rigs and is_active_cloudrig(context):
            return False
        if not cls.on_metarigs and is_active_cloud_metarig(context):
            return False
        return True

    def draw(self, context):
        pass


class CloudRig_Properties(bpy.types.PropertyGroup):
    """PropertyGroup for special custom properties that rely on callback functions"""

    def items_outfit(self, context):
        """Items callback for outfits EnumProperty.
        Build and return a list of outfit names based on a bone naming convention.
        Bones storing an outfit's properties must be named "Properties_Outfit_OutfitName".
        """
        rig = self.id_data
        if not rig:
            return [(('0', 'Default', 'Default'))]

        outfits = []
        for b in rig.pose.bones:
            if b.name.startswith("Properties_Outfit_"):
                outfits.append(b.name.replace("Properties_Outfit_", ""))

        # Convert the list into what an EnumProperty expects.
        items = []
        for i, outfit in enumerate(outfits):
            items.append(
                (outfit, outfit, outfit, i)
            )  # Identifier, name, description, can all be the outfit name.

        # If no outfits were found, don't return an empty list so the console doesn't spam "'0' matches no enum" warnings.
        if items == []:
            return [(('0', 'Default', 'Default'))]

        return items

    def change_outfit(self, context):
        """Update callback of outfits EnumProperty."""

        rig = self.id_data
        if not rig:
            return

        if self.outfit == '':
            self.outfit = self.items_outfit(context)[0][0]

        outfit_bone = rig.pose.bones.get("Properties_Outfit_" + self.outfit)

        if outfit_bone:
            # Reset all settings to default.
            for key in outfit_bone.keys():
                value = outfit_bone[key]
                if type(value) in [float, int]:
                    pass  # TODO: Can't seem to reset custom properties to their default, or even so much as read their default!?!?

            # For outfit properties starting with "_", update the corresponding character property.
            char_bone = get_char_bone(rig)
            for key in outfit_bone.keys():
                if key.startswith("_") and key[1:] in char_bone:
                    char_bone[key[1:]] = outfit_bone[key]

        context.evaluated_depsgraph_get().update()

    # TODO: This should be implemented as an operator instead, just like parent switching.
    outfit: EnumProperty(
        name="Outfit",
        items=items_outfit,
        update=change_outfit,
        options={"LIBRARY_EDITABLE"},  # Make it not animatable.
        override={'LIBRARY_OVERRIDABLE'},
    )


def get_char_bone(rig):
    for b in rig.pose.bones:
        if b.name.startswith("Properties_Character"):
            return b


def draw_rig_settings_per_label(
    layout: bpy.types.UILayout, rig: Object, main_dict: dict
):
    """Each top-level dictionary within the main dictionary defines a panel.
    Each panel is split into sub-sections via labels.
    """
    top = layout.column()
    for label_name in main_dict.keys():
        ui = layout
        if label_name == 'parent_id':
            continue
        if label_name == 'NODRAW':
            continue
        if label_name != "":
            layout.label(text=label_name)
        else:
            # Label-less properties should be at the top of the sub-panel.
            ui = top
        draw_rig_settings(ui, rig, main_dict[label_name])


def draw_rig_settings(layout: bpy.types.UILayout, rig: Object, ui_data: Dict):
    """
    ui_data: Dictionary containing the UI data, created during rig generation.
    The top-level represents rows, and each row can contain any number of slider definitions.

    A slider definition must have the following keywords:
            prop_bone: Name of the pose bone that holds the custom property.
            prop_id: Name of the custom property on the bone, to be drawn as a slider.

    Optional keywords:
            texts: List of strings to display alongside an integer property slider.
            operator: Specify an operator to draw next to the slider.
            icon: Override the icon of the operator. If not specified, default to 'FILE_REFRESH'.

            Any further arguments will be passed on to the operator button as keyword arguments.
    """

    # Sort the rows alphabetically, just so "Arm" always comes before "Leg".
    # Can get unlucky with "Upperarm" and "Thigh" though, but at least alphabtical is
    # consistent and predictable.
    row_datas = [(row_name, ui_data[row_name]) for row_name in sorted(ui_data.keys())]

    # Each top-level dictionary within the main dictionary defines a row.
    for row_name, row_entries in row_datas:
        row = layout.row()
        # Each second-level dictionary within that defines a slider (and operator, if given).
        # If there is more than one, they will be drawn next to each other, since they're in the same row.
        for entry_name in row_entries.keys():
            info = row_entries[
                entry_name
            ]  # This is the lowest level dictionary that contains the parameters for the slider and its operator, if given.
            if not 'prop_bone' in info and 'prop_id' in info:
                print(
                    f"CloudRig UI Error: Limb definition lacks properties bone or prop ID: {row_name}\n{info}"
                )
                continue
            prop_bone = rig.pose.bones.get(info['prop_bone'])
            prop_id = info['prop_id']
            if not prop_bone and prop_id in prop_bone:
                print(
                    f"CloudRig UI Error: Properties bone or property does not exist: {info}"
                )
                continue
            col = row.column()
            sub_row = col.row(align=True)

            prop_value = prop_bone[prop_id]

            def get_text():
                text = entry_name
                if 'texts' in info:
                    texts = json.loads(info['texts'])
                    value = int(prop_value)
                    if len(texts) > value:
                        text = entry_name + ": " + texts[value]
                return text

            if isinstance(prop_value, bpy.types.Object):
                # Property is an object pointer
                sub_row.prop_search(
                    prop_bone,
                    f'["{prop_id}"]',
                    bpy.data,
                    'objects',
                    icon='OBJECT_DATAMODE',
                    text=entry_name,
                )
            elif type(prop_value) == bool:
                icon = 'CHECKBOX_HLT' if prop_value else 'CHECKBOX_DEHLT'
                sub_row.prop(
                    prop_bone, f'["{prop_id}"]', toggle=True, text=get_text(), icon=icon
                )
            else:
                # Property is a float/int/color

                sub_row.prop(prop_bone, f'["{prop_id}"]', slider=True, text=get_text())

            # Draw an operator if provided.
            if 'operator' in info:
                icon = 'FILE_REFRESH'
                if 'icon' in info:
                    icon = info['icon']

                operator = sub_row.operator(info['operator'], text="", icon=icon)
                # Pass on any paramteres to the operator that it will accept.
                for param in info.keys():
                    if hasattr(operator, param):
                        value = info[param]
                        # Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
                        if type(value) in [list, dict]:
                            value = json.dumps(value)
                        setattr(operator, param, value)


def get_text(prop_owner, prop_id, value):
    """If there is a property on prop_owner named $prop_id, expect it to be a list of strings and return the valueth element."""
    text = prop_id.replace("_", " ")
    if "$" + prop_id in prop_owner and type(value) == int:
        names = prop_owner["$" + prop_id]
        if value > len(names) - 1:
            print(
                f"cloudrig.py Warning: Name list for this property is not long enough for current value: {prop_id}"
            )
            return text
        return text + ": " + names[value]
    else:
        return text


def add_operator(layout, op_info: dict):
    """Add an operator button to layout.
    op_info should include a bl_idname, can include an icon, and operator kwargs.
    """

    icon = 'LAYER_ACTIVE'
    if 'icon' in op_info:
        icon = op_info['icon']

    operator = layout.operator(op_info['bl_idname'], text="", icon=icon)
    # Pass on any paramteres to the operator that it will accept.
    for param in op_info.keys():
        if param in ['bl_idname', 'icon']:
            continue
        if hasattr(operator, param):
            value = op_info[param]
            # Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
            if type(value) in [list, dict]:
                value = json.dumps(value)
            setattr(operator, param, value)


class CLOUDRIG_PT_character(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_character"
    bl_label = "Character"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False

        # Only display this panel if there is either an outfit with options, multiple outfits, or character options.
        rig = is_active_cloudrig(context)
        if not rig:
            return
        rig_props = rig.cloud_rig
        multiple_outfits = len(rig_props.items_outfit(context)) > 1
        outfit_properties_bone = rig.pose.bones.get(
            "Properties_Outfit_" + rig_props.outfit
        )
        char_bone = get_char_bone(rig)

        return multiple_outfits or outfit_properties_bone or char_bone

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object

        rig_props = rig.cloud_rig

        def add_props(prop_owner):
            props_done = []

            def add_prop(layout, prop_owner, prop_id):
                row = layout.row()
                if prop_id in props_done:
                    return

                prop_value = prop_owner[prop_id]
                if type(prop_value) in [int, float]:
                    row.prop(
                        prop_owner,
                        '["' + prop_id + '"]',
                        slider=True,
                        text=get_text(prop_owner, prop_id, prop_value),
                    )
                    if 'op_' + prop_id in prop_owner or prop_id == 'Quality':
                        # HACK: Hard-code behaviour for a property named "Quality", so I don't have to add it on every character manually on Sprite Fright. This needs a more elegant design...
                        if prop_id == 'Quality':
                            op_info = {
                                'bl_idname': 'object.cloudrig_copy_property',
                                'prop_bone': prop_owner.name,
                                'prop_id': 'Quality',
                                'icon': 'WORLD',
                            }
                        else:
                            op_info = prop_owner["op_" + prop_id]
                        if type(op_info) == str:
                            op_info = eval(op_info)
                        add_operator(row, op_info)
                elif str(type(prop_value)) == "<class 'IDPropertyArray'>":
                    # Vectors
                    row.prop(
                        prop_owner, f'["{prop_id}"]', text=prop_id.replace("_", " ")
                    )
                elif type(prop_value) == bool:
                    icon = 'CHECKBOX_HLT' if prop_value else 'CHECKBOX_DEHLT'
                    row.prop(
                        prop_owner,
                        f'["{prop_id}"]',
                        text=prop_id.replace("_", " "),
                        toggle=True,
                        icon=icon,
                    )
                elif isinstance(prop_value, bpy.types.Object):
                    # Property is a pointer
                    row.prop_search(
                        prop_owner,
                        f'["{prop_id}"]',
                        bpy.data,
                        'objects',
                        icon='OBJECT_DATAMODE',
                        text=prop_id,
                    )

            # Drawing properties with hierarchy
            if 'prop_hierarchy' in prop_owner:
                prop_hierarchy = prop_owner['prop_hierarchy']
                if type(prop_hierarchy) == str:
                    prop_hierarchy = eval(prop_hierarchy)

                for parent_prop_name in prop_hierarchy.keys():
                    parent_prop_name_without_values = parent_prop_name
                    values = [
                        1
                    ]  # Values which this property needs to be for its children to show. For bools this is always 1.
                    # Example entry in prop_hierarchy: ['Jacket-23' : ['Hood', 'Belt']] This would mean Hood and Belt are only visible when Jacket is either 2 or 3.
                    if '-' in parent_prop_name:
                        split = parent_prop_name.split('-')
                        parent_prop_name_without_values = split[0]
                        values = [
                            int(val) for val in split[1]
                        ]  # Convert them to an int list ( eg. '23' -> [2, 3] )

                    parent_prop_value = prop_owner[parent_prop_name_without_values]

                    # Drawing parent prop, if it wasn't drawn yet.
                    add_prop(layout, prop_owner, parent_prop_name_without_values)

                    # Marking parent prop as done drawing.
                    props_done.append(parent_prop_name_without_values)

                    # Checking if we should draw children.
                    if parent_prop_value not in values:
                        continue

                    # Drawing children.
                    childrens_box = None
                    for child_prop_name in prop_hierarchy[parent_prop_name]:
                        if not childrens_box:
                            childrens_box = layout.box()
                        add_prop(childrens_box, prop_owner, child_prop_name)

                # Marking child props as done drawing. (Regardless of whether they were actually drawn or not, since if the parent is disabled, we don't want to draw them.)
                for parent in prop_hierarchy.keys():
                    for child in prop_hierarchy[parent]:
                        props_done.append(child)

            # Drawing properties without hierarchy
            for prop_id in sorted(prop_owner.keys()):
                if prop_id.startswith("_"):
                    continue
                if prop_id in props_done:
                    continue
                addon_props = {
                    prop.identifier
                    for prop in prop_owner.bl_rna.properties
                    if prop.is_runtime
                }
                if prop_id in addon_props:
                    continue

                add_prop(layout, prop_owner, prop_id)

        # Add character properties to the UI, if any.
        char_bone = get_char_bone(rig)
        if char_bone:
            add_props(char_bone)
            layout.separator()

        # Add outfit properties to the UI, if any.
        outfit_properties_bone = rig.pose.bones.get(
            "Properties_Outfit_" + rig_props.outfit
        )
        if outfit_properties_bone:
            layout.prop(rig_props, 'outfit')
            add_props(outfit_properties_bone)


class CLOUDRIG_PT_custom_panel(CLOUDRIG_PT_base):
    """Base class for dynamically created sub-panels for the rig UI, created in ensure_custom_panel()"""

    bl_parent_id = "CLOUDRIG_PT_settings"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = is_active_cloudrig(context)
        if not rig:
            return
        if 'ui_data' not in rig.data:
            return
        ui_data = rig.data['ui_data'].to_dict()

        if cls.bl_label in ui_data:
            return True

    def draw(self, context):
        rig = is_active_cloudrig(context)
        ui_data = rig.data['ui_data'].to_dict()
        main_dict = ui_data[self.bl_label]  # bl_label is set in ensure_custom_panel().

        draw_rig_settings_per_label(self.layout, rig, main_dict)


custom_panels = []


def ensure_custom_panel(name, parent_id="CLOUDRIG_PT_settings"):
    # Make sure name is alphanumeric
    sane_name = re.sub(r'\W+', '', name)
    full_name = "CLOUDRIG_PT_custom_" + sane_name.lower().replace(" ", "")

    if hasattr(bpy.types, full_name):
        return
    if not hasattr(bpy.types, parent_id):
        parent_id = "CLOUDRIG_PT_settings"

    # Dynamically create a new class, so it can be registered as a sub-panel.
    new_panel = type(
        full_name,
        (CLOUDRIG_PT_custom_panel,),
        {'bl_idname': full_name, 'bl_label': name, 'bl_parent_id': parent_id},
    )

    bpy.utils.register_class(new_panel)

    # Save a reference so it can be unregistered, even though unregister() is never called.
    global custom_panels
    custom_panels.append(new_panel)


def ensure_custom_panels(_dummy1, _dummy2):
    rig = is_active_cloudrig(bpy.context)
    if not rig:
        return
    if 'ui_data' not in rig.data:
        return
    custom_panels = rig.data['ui_data'].to_dict()

    # We expect a dictionary of {"Panel Name" : {UI data, see draw_rig_settings.}}
    for panel_name in custom_panels.keys():
        parent_id = "CLOUDRIG_PT_settings"
        if 'parent_id' in custom_panels[panel_name]:
            parent_id = custom_panels[panel_name]['parent_id']
        ensure_custom_panel(panel_name, parent_id)


class CLOUDRIG_PT_settings(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_settings"
    bl_label = "Settings"

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context)

    def draw(self, context):
        layout = self.layout
        rig = is_active_cloudrig(context)
        if not rig:
            return

        layout.operator(
            POSE_OT_cloudrig_keyframe_all_settings.bl_idname,
            text='Keyframe All Settings',
            icon='KEYFRAME_HLT',
        )
        layout.operator(
            POSE_OT_cloudrig_reset.bl_idname, text='Reset Rig', icon='LOOP_BACK'
        )


#######################################
########### Rig Preferences ###########
#######################################


class CloudRig_RigPreferences(bpy.types.PropertyGroup):
    collection_ui_type: EnumProperty(
        name="Collections UI Type",
        description="Whether to use Blender's built-in Collections UI or CloudRig's",
        items=[
            ('DEFAULT', 'Default', "Use Blender's built-in collections UI"),
            ('CLOUDRIG', 'CloudRig', "Use CloudRig's custom collections UI"),
        ],
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    show_visibility: BoolProperty(
        name="Hide",
        description="Show the Hide setting",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_solo: BoolProperty(
        name="Isolate",
        description="Show the Isolate operator",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_select: BoolProperty(
        name="Select",
        description="Show the Select operator",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_editing: BoolProperty(
        name="Editing",
        description="Show collection editing functions",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_bone_count: BoolProperty(
        name="Bone Count",
        description="Show number of bones selected/assigned (including child collections)",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_local_overrides: BoolProperty(
        name="Show Link",
        description="Show an icon indicating whether a collection is a local override. Locally created collections can be renamed, removed, sorted, and parented amongst each other, but the linked collection tree from the original file cannot be modified",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    def update_collection_filter(self, context=None):
        self.keep_active_collection_visible()

    collection_filter: bpy.props.StringProperty(
        name="Collection Filter",
        description="Search collections by name (case-sensitive)",
        update=update_collection_filter,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    def keep_active_collection_visible(self):
        colls = self.id_data.data.collections
        all_colls = self.id_data.data.collections_all
        if not colls:
            return

        flt_flags = CLOUDRIG_UL_collections.get_filter_flags(
            all_colls, self.collection_filter
        )

        new_idx = self.active_collection_index

        if new_idx == -1:
            # Means no collection is active, which is allowed, when there is
            # a name search filter entered, resulting in 0 matches.
            colls.active_index = -1
            return
        if new_idx < 0:
            new_idx = -1
        if new_idx > len(all_colls) - 1:
            new_idx = len(all_colls) - 1

        if flt_flags[new_idx] == 0:
            # If the new active element would be hidden, keep going up the list until a visible one is found.
            while flt_flags[new_idx] == 0 and new_idx > 0:
                new_idx -= 1
        if flt_flags[new_idx] == 0:
            # If that failed, go down the list instead.
            new_idx = self.active_collection_index + 1
            while flt_flags[new_idx] == 0 and new_idx < len(all_colls):
                new_idx += 1
        if flt_flags[new_idx] == 0:
            # If that fails too, don't allow an active element.
            new_idx = -1

        if new_idx != self.active_collection_index:
            # This will cause this function to get called again, but this time,
            # none of the if-statements should trigger.
            self.active_collection_index = new_idx
            return

        colls.active_index = self.active_collection_index

    def sync_collection_names(self):
        for coll in self.id_data.data.collections_all:
            coll.cloudrig_info.name = coll.name

    def update_active_collection_index(self, context=None):
        self.sync_collection_names()
        self.keep_active_collection_visible()

    active_collection_index: IntProperty(
        name="Bone Collections",
        description="Bone Collections",
        update=update_active_collection_index,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )


#######################################
###### Nested Bone Collections ########
#######################################


class CloudRigBoneCollection(bpy.types.PropertyGroup):
    """Properties stored on BoneCollection.cloudrig_info.
    Used for implementing and drawing the nested collections UIList.
    Also some other functionality like Solo Collection and Preserve on Regenerate.
    """

    def get_collection(self) -> bpy.types.BoneCollection:
        """Return the BoneCollection that this instance of this class belongs to."""
        armature = self.id_data
        for coll in armature.collections_all:
            if coll.cloudrig_info == self:
                return coll

    def update_name(self, context):
        """Runs when trying to change the name of this instance, which should stay in sync
        with the collection it's masking."""

        coll = self.get_collection()

        # If the name didn't change, don't do anything.
        if coll.name == self.name:
            return

        # If the collection is not editable, don't allow changing the name.
        if not coll.is_editable:
            self.name = coll.name
            return

        # Force the name to be unique.
        if self.name in self.id_data.collections_all:
            counter = 1
            base_name = self.name
            unique_name = base_name
            while unique_name in self.id_data.collections_all:
                unique_name = base_name + "." + str(counter).zfill(3)
                counter += 1
            # This will cause update_name() to be called again,
            # but this time this `if` block won't trigger.
            self.name = unique_name
            return

        # Update child collections to refer to the new name.
        for other_coll in self.id_data.collections_all:
            if other_coll.cloudrig_info.parent_name == coll.name:
                other_coll.cloudrig_info.parent_name = self.name

        # Metarig: Update bone sets with this collection assigned to refer to the new name.
        if is_active_cloud_metarig(context):
            rig = context.pose_object or context.active_object
            for pb in rig.pose.bones:
                comp = pb.cloudrig_component
                for bone_set_name in comp.params.bone_sets.keys():
                    bone_set = getattr(comp.params.bone_sets, bone_set_name)
                    for bone_set_coll in bone_set.collections:
                        if bone_set_coll.name == coll.name:
                            bone_set_coll.name = self.name
                            break

        # Set the actual collection's name to be in sync.
        coll.name = self.name

    name: StringProperty(
        name="Name",
        description="Name of this bone collection",
        update=update_name,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def are_parents_visible(self):
        parent = self.parent_collection
        if not parent:
            return True

        while parent:
            if not parent.is_visible:
                return False
            parent = parent.cloudrig_info.parent_collection

        return True

    parent_name: StringProperty(
        name="Parent",
        description="Parent of this bone collection",
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def parent_collection(self) -> bpy.types.BoneCollection:
        # TODO 4.2: Redundant, delete.
        return self.get_collection().parent

    @parent_collection.setter
    def parent_collection(self, coll: bpy.types.BoneCollection):
        # TODO 4.2: Redundant, delete.
        self.get_collection().parent = coll
        self.parent_name = coll.name

    def unfold_parents(self):
        # TODO 4.2: Redundant, delete
        return self.get_collection().is_expanded

    @property
    def children(self) -> List[bpy.types.BoneCollection]:
        # TODO 4.2: Redundant, delete.
        return self.get_collection().children[:]

    @property
    def siblings(self):
        """Includes self!"""
        if not self.parent_collection:
            all_colls = self.id_data.collections_all
            return [
                coll for coll in all_colls if not coll.cloudrig_info.parent_collection
            ]
        return self.parent_collection.cloudrig_info.children

    @property
    def children_recursive(self) -> List[bpy.types.BoneCollection]:
        children = self.children[:]
        for child in children:
            children += child.cloudrig_info.children
        return children

    @property
    def parents_recursive(self) -> List[bpy.types.BoneCollection]:
        parents = []
        parent = self.parent_collection
        while parent:
            parents.append(parent)
            parent = parent.cloudrig_info.parent_collection
        return parents

    @property
    def all_bones(self) -> List[bpy.types.Bone]:
        # TODO 4.2: Redundant, delete.
        return self.get_collection().bones_recursive

    quick_access: BoolProperty(
        name="Quick Access",
        description="Toggle whether this collection should appear in the quick access list",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def are_parents_unfolded(self):
        """Return False if any parent up the chain has is_expanded=False"""
        if not self.parent_collection:
            return True

        return all([parent.is_expanded for parent in self.parents_recursive])

    @property
    def hierarchy_depth(self):
        """Return number of parents"""
        return len(self.parents_recursive)

    preserve_on_regenerate: BoolProperty(
        name="Preserve On Regenerate",
        description="Should be enabled on manually defined collections, to preserve them and their assigned bones on re-generating from the metarig",
        default=False,
    )


class CLOUDRIG_UL_collections(bpy.types.UIList):
    """Draw bone collections with nesting support"""

    @staticmethod
    def draw_collection(context, layout, collection, idx):
        cloudrig_info = collection.cloudrig_info
        rig = context.pose_object or context.active_object
        prefs = rig.cloudrig_prefs

        row = layout.row(align=True)
        if collection.parent:
            split = row.split(factor=0.02 * cloudrig_info.hierarchy_depth)
            split.row()
            row = split.row(align=True)
            row = row.row(align=True)
        if collection.children:
            icon = 'DOWNARROW_HLT' if collection.is_expanded else 'RIGHTARROW'
            row.prop(collection, 'is_expanded', text="", icon=icon, emboss=False)
        else:
            row.label(text="", icon='BLANK1')

        if prefs.show_local_overrides and collection.is_local_override:
            row.prop(
                cloudrig_info,
                'name',
                text="",
                icon='LIBRARY_DATA_OVERRIDE',
                emboss=False,
            )
        else:
            row.prop(cloudrig_info, 'name', text="", emboss=False)

        if context.mode != 'EDIT_ARMATURE':
            direct_selected_bones = [
                b
                for b in collection.bones
                if not b.hide
                and any([c.is_visible for c in b.collections])
                and b.select
            ]
            indirect_bones = cloudrig_info.all_bones
            indirect_visible_bones = [
                b
                for b in indirect_bones
                if not b.hide and any([c.is_visible for c in b.collections])
            ]
            indirect_selected_bones = [b for b in indirect_visible_bones if b.select]

            if direct_selected_bones:
                row.label(text="", icon='LAYER_ACTIVE')
            elif indirect_selected_bones:
                row.label(text="", icon='LAYER_USED')

            if prefs.show_bone_count:
                row.label(
                    text=f"{len(indirect_selected_bones)}/{len(indirect_bones)}",
                    icon='BONE_DATA',
                )

        vis_row = row.row(align=True)
        vis_row.operator_context = 'INVOKE_DEFAULT'
        vis_row.enabled = cloudrig_info.are_parents_visible
        if prefs.show_visibility:
            icon = 'HIDE_OFF' if collection.is_visible else 'HIDE_ON'
            vis_row.prop(collection, 'is_visible', text="", icon=icon)
        if prefs.show_select:
            sel_op = vis_row.operator(
                POSE_OT_cloudrig_collection_select.bl_idname,
                text="",
                icon='MOUSE_LMB',
            )
            sel_op.collection_name = collection.name
            sel_op.reveal_bones = False
        row = row.row(align=True)
        if prefs.show_solo:
            icon = 'SOLO_ON' if collection.is_solo else 'SOLO_OFF'
            row.prop(collection, 'is_solo', text="", icon=icon)
        if prefs.show_editing:
            row.separator()
            if collection.is_editable:
                row.operator(
                    POSE_OT_cloudrig_collection_parent_set.bl_idname,
                    text="",
                    icon='CON_CHILDOF',
                ).coll_idx = idx

            icon = 'RECORD_ON' if cloudrig_info.quick_access else 'RECORD_OFF'
            row.prop(cloudrig_info, 'quick_access', text="", icon=icon)
            if is_active_cloudrig(context) and find_metarig_of_rig(
                context, context.active_object
            ):
                icon = (
                    'FAKE_USER_ON'
                    if cloudrig_info.preserve_on_regenerate
                    else 'FAKE_USER_OFF'
                )
                row.prop(cloudrig_info, 'preserve_on_regenerate', text="", icon=icon)
        return row

    def draw_item(
        self,
        context,
        layout,
        armature,
        item,
        _icon_value,
        _active_data,
        _active_propname,
    ):
        idx = armature.collections_all.find(item.name)
        self.draw_collection(context, layout, item, idx)

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation.
        """
        rig = context.pose_object or context.active_object
        layout.prop(rig.cloudrig_prefs, "collection_filter", text="")

    @staticmethod
    def get_collection_order(all_collections):
        # Order collections by CloudRig hierarchy, such that children come after their
        # parents, but the original order is otherwise preserved.

        # Find collections without any parent
        root_colls = [coll for coll in all_collections if not coll.parent]
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.cloudrig_info.children:
                add_children_recursive(child)

        for root_coll in root_colls:
            add_children_recursive(root_coll)

        # NOTE: THIS MUST BE BOMBPROOF, OR BLENDER WILL CRASH!
        return [sorted_colls.index(coll) for coll in all_collections]

    @staticmethod
    def get_filter_flags(all_collections, filter_name):
        flt_flags = [1 << 30] * len(all_collections)
        # Filtering by name search.
        if filter_name:
            helper_funcs = bpy.types.UI_UL_list
            flt_flags = helper_funcs.filter_items_by_name(
                filter_name,
                1 << 30,
                all_collections,
                "name",
                reverse=False,
            )

        # Filter out collections whose parents are collapsed
        return [
            flag * int(all_collections[i].cloudrig_info.are_parents_unfolded)
            for i, flag in enumerate(flt_flags)
        ]

    def filter_items(self, context, data, propname):
        all_collections = getattr(data, propname)
        rig = context.pose_object or context.active_object

        flt_flags = self.get_filter_flags(
            all_collections, rig.cloudrig_prefs.collection_filter
        )
        flt_neworder = self.get_collection_order(all_collections)

        return flt_flags, flt_neworder


def draw_cloudrig_collections(self, context):
    layout = self.layout
    layout.use_property_split = True
    layout.use_property_decorate = False

    rig = context.pose_object or context.active_object
    prefs = rig.cloudrig_prefs
    active_coll = rig.data.collections.active

    if context.pose_object:
        prop_owner = 'pose_object'
    else:
        prop_owner = 'active_object'

    list_col = draw_ui_list(
        layout,
        context,
        class_name='CLOUDRIG_UL_collections',
        list_path=prop_owner + ".data.collections_all",
        active_index_path=prop_owner + '.cloudrig_prefs.active_collection_index',
        insertion_operators=False,
        move_operators=False,
        unique_id='CloudRig Nested Collections UI',
    )
    list_col.popover(
        panel="CLOUDRIG_PT_collections_filter",
        text="",
        icon='FILTER',
    )

    list_col.separator()

    if not prefs.show_editing:
        list_col.operator(
            POSE_OT_cloudrig_collections_reveal_all.bl_idname,
            text="",
            icon='HIDE_OFF',
            emboss=False,
        )
        list_col.operator(
            'armature.collection_unsolo_all',
            text="",
            icon='SOLO_OFF',
            emboss=False,
        )
        return

    list_col.operator(POSE_OT_cloudrig_collection_add.bl_idname, text="", icon='ADD')

    list_col.operator(
        POSE_OT_cloudrig_collection_delete.bl_idname, text="", icon='REMOVE'
    ).mode = 'ACTIVE'
    list_col.separator()

    row = list_col.row()
    row.menu(CLOUDRIG_MT_collections_specials.bl_idname, text="", icon='DOWNARROW_HLT')

    list_col.separator()

    if not active_coll:
        return

    siblings, sibling_idx = (
        POSE_OT_cloudrig_collection_reorder.get_siblings_and_target_idx(
            'UP', active_coll
        )
    )
    row = list_col.row()
    row.enabled = sibling_idx >= 0
    row.operator(
        POSE_OT_cloudrig_collection_reorder.bl_idname, text="", icon='TRIA_UP'
    ).direction = 'UP'

    row = list_col.row()
    row.enabled = sibling_idx + 2 < len(siblings)
    row.operator(
        POSE_OT_cloudrig_collection_reorder.bl_idname, text="", icon='TRIA_DOWN'
    ).direction = 'DOWN'

    row = layout.row()
    if context.mode not in {'POSE', 'EDIT_ARMATURE'}:
        row.enabled = False
    sub = row.row(align=True)
    sub.operator(POSE_OT_cloudrig_collection_assign.bl_idname, text="Assign").assign = (
        True
    )
    sub.operator(
        POSE_OT_cloudrig_collection_assign.bl_idname, text="Unassign"
    ).assign = False

    sub = row.row(align=True)
    sel_op = sub.operator(POSE_OT_cloudrig_collection_select.bl_idname, text="Select")
    sel_op.select = True
    sel_op.collection_name = active_coll.name

    desel_op = sub.operator(
        POSE_OT_cloudrig_collection_select.bl_idname, text="Deselect"
    )
    desel_op.select = False
    desel_op.collection_name = active_coll.name


class CLOUDRIG_PT_collections_sidebar(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_collections_sidebar"
    bl_label = "Bone Collections"
    bl_options = {'DEFAULT_CLOSED'}

    on_metarigs = True
    draw = draw_cloudrig_collections


class CLOUDRIG_PT_collections_filter(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_label = "Filter"
    bl_options = {'INSTANCED'}

    def draw(self, context):
        layout = self.layout
        obj = context.pose_object or context.active_object
        prefs = obj.cloudrig_prefs
        row = layout.row(align=True)
        row.prop(prefs, 'show_visibility', text="", icon='HIDE_OFF')
        row.prop(prefs, 'show_solo', text="", icon='SOLO_OFF')
        row.prop(prefs, 'show_select', text="", icon='RESTRICT_SELECT_OFF')

        row.separator()
        row.prop(prefs, "show_editing", text="", icon='PREFERENCES')
        row.prop(prefs, 'show_bone_count', text="", icon='GROUP_BONE')
        if obj.data.override_library:
            row.prop(
                prefs, 'show_local_overrides', text="", icon='LIBRARY_DATA_OVERRIDE'
            )


class CLOUDRIG_MT_collections_specials(bpy.types.Menu):
    bl_label = "Collection Operators"
    bl_idname = 'CLOUDRIG_MT_collections_specials'

    def draw(self, context):
        layout = self.layout
        layout.operator(
            POSE_OT_cloudrig_collections_reveal_all.bl_idname,
            text="Show All",
            icon='HIDE_OFF',
        )
        layout.operator(
            'armature.collection_unsolo_all',
            text="Unsolo All",
            icon='SOLO_OFF',
        )
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_collection_assign.bl_idname,
            text="Unassign Selected Bones from All Collections",
            icon='REMOVE',
        )
        layout.operator(
            POSE_OT_cloudrig_collection_delete.bl_idname,
            text="Delete Hierarchy of Collections",
            icon='OUTLINER',
        ).mode = 'HIERARCHY'
        layout.operator(
            POSE_OT_cloudrig_collection_delete.bl_idname,
            text="Delete All Local Collections",
            icon='TRASH',
        ).mode = 'ALL'
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_collection_clipboard_copy.bl_idname,
            text="Copy Visible Collections to Clipboard",
            icon='COPYDOWN',
        )
        layout.operator(
            POSE_OT_cloudrig_collection_clipboard_paste.bl_idname,
            text="Paste Collections from Clipboard",
            icon='PASTEDOWN',
        )


class CLOUDRIG_MT_collections_quick_select(bpy.types.Menu):
    """Quick select menu, so favourite bone collections can be selected quickly with a hotkey"""

    bl_label = "Quick Select"
    bl_idname = 'CLOUDRIG_MT_collections_quick_select'

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context)

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"

        rig = context.pose_object or context.active_object

        def collections_recursive(colls):
            """This has a different order from collections_all, which aligns with
            user expectation (UI top to bottom order)."""
            for coll in colls:
                yield coll
                if coll.children:
                    yield from collections_recursive(coll.children)

        for coll in collections_recursive(rig.data.collections):
            if coll.cloudrig_info.quick_access:
                op = layout.operator(
                    POSE_OT_cloudrig_collection_select.bl_idname,
                    text=coll.name,
                    icon='RESTRICT_SELECT_OFF',
                )
                op.collection_name = coll.name
                op.select = True
                op.reveal_bones = False


class POSE_OT_cloudrig_collections_reveal_all(bpy.types.Operator):
    """Reveal all collections"""

    bl_idname = "pose.cloudrig_collections_reveal_all"
    bl_label = "Show All Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.pose_object or context.active_object
        for coll in rig.data.collections_all:
            coll.is_visible = True

        return {'FINISHED'}


@contextlib.contextmanager
def pose_mode(rig):
    if rig.mode == 'POSE':
        yield

    else:
        mode_bkp = rig.mode
        bpy.ops.object.mode_set(mode='POSE')
        yield
        bpy.ops.object.mode_set(mode=mode_bkp)


class POSE_OT_cloudrig_collection_select(bpy.types.Operator):
    """Reveal and Select this collection, its children, and all bones within.\n\nShift: Extend selection. \nCtrl: Mirror selection. \nAlt: Deselect"""

    bl_idname = "pose.cloudrig_collection_select"
    bl_label = "Select Bones of Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    collection_name: StringProperty(
        name="Name",
        description="Name of the collection to operate on",
        options={'SKIP_SAVE'},
    )
    extend_selection: BoolProperty(
        name="Expand Selection",
        description="Whether the existing selection should be preserved",
        default=False,
        options={'SKIP_SAVE'},
    )
    select: BoolProperty(
        name="Selection State",
        description="Whether the collection's bones should be selected or deselected",
        default=True,
        options={'SKIP_SAVE'},
    )
    reveal_bones: BoolProperty(
        name="Reveal Bones",
        description="Whether bones of the collection should be un-hidden",
        default=False,
        options={'SKIP_SAVE'},
    )
    flip: BoolProperty(
        name="Flip",
        description="Whether to operate on the opposite side of this collection's bones",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        ob = context.pose_object or context.active_object
        return ob and ob.type == 'ARMATURE'

    def invoke(self, context, event):
        self.extend_selection = event.shift
        self.select = not event.alt
        self.flip = event.ctrl

        return self.execute(context)

    def execute(self, context):
        rig = context.pose_object or context.active_object

        collection = rig.data.collections_all.get(self.collection_name)

        if not collection:
            collection = rig.data.collections.active
        if not collection:
            return {'CANCELLED'}

        reveal_colls = [collection]
        if self.select and self.reveal_bones:
            reveal_colls += collection.cloudrig_info.children_recursive

        for reveal_coll in reveal_colls:
            reveal_coll.is_visible = True

        with pose_mode(rig):
            if not self.extend_selection and self.select:
                for bone in rig.data.bones:
                    bone.select = False

            for bone in collection.cloudrig_info.all_bones:
                if self.flip:
                    bone = rig.data.bones.get(bpy.utils.flip_name(bone.name))
                    if not bone:
                        continue
                if self.reveal_bones and self.select:
                    bone.hide = False
                bone.select = self.select

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_parent_set(bpy.types.Operator):
    """Set parent collection"""

    bl_idname = "pose.cloudrig_collection_parent_set"
    bl_label = "Set Parent Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    coll_idx: IntProperty(
        name="Collection Index",
        description="Index of the collection to change the parent of",
        options={'SKIP_SAVE'},
    )
    parent_name: StringProperty(
        name="Parent",
        description="Parent to set as this bone collection's parent",
    )

    def invoke(self, context, _event):
        rig = context.pose_object or context.active_object
        coll = rig.data.collections_all[self.coll_idx]
        if not coll.is_editable:
            self.report({'ERROR'}, "Cannot change the parent of linked collections.")
            return {'CANCELLED'}
        if coll.parent:
            self.parent_name = coll.parent.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        rig = context.pose_object or context.active_object
        layout.prop_search(self, 'parent_name', rig.data, 'collections_all')

    def execute(self, context):
        rig = context.pose_object or context.active_object
        all_colls = rig.data.collections_all
        parent = all_colls.get(self.parent_name)
        coll = all_colls[self.coll_idx]

        if coll.parent == parent:
            self.report({'INFO'}, "This parent is already set. Nothing was done.")
            return {'CANCELLED'}
        if coll.parent == coll:
            self.report({'ERROR'}, "Cannot set a collection's parent to be itself.")
            return {'CANCELLED'}
        if parent and not parent.is_editable:
            self.report(
                {'ERROR'},
                "Parenting to a linked collection is currently not supported.",
            )
            return {'CANCELLED'}
        if not coll.is_editable:
            self.report(
                {'ERROR'},
                "Changing parent of linked collection is currently not supported.",
            )
            return {'CANCELLED'}

        coll.parent = parent
        rig.cloudrig_prefs.active_collection_index = all_colls.find(coll.name)

        self.report({'INFO'}, "Collection parent set.")
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_delete(bpy.types.Operator):
    """Remove the active bone collection"""

    bl_idname = "pose.cloudrig_collection_delete"
    bl_label = "Remove Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    mode: EnumProperty(
        items=[
            ('ACTIVE', "Active", "Delete the Active collection"),
            ('HIERARCHY', "Hierarchy", "Delete the Active collection and its children"),
            ('ALL', "All", "Delete all local collections"),
        ]
    )

    @classmethod
    def poll(cls, context):
        rig = context.object
        active_coll = rig.data.collections.active
        if active_coll:
            if not active_coll.is_editable:
                cls.poll_message_set("Cannot delete linked collection")
                return False
            return True

    def execute(self, context):
        if self.mode == 'ACTIVE':
            return self.delete_active(context)
        elif self.mode == 'HIERARCHY':
            return self.delete_hierarchy(context)
        elif self.mode == 'ALL':
            return self.delete_all(context)

    def delete_active(self, context):
        rig = context.pose_object or context.active_object
        coll = rig.data.collections.active
        if not coll.is_editable:
            self.report({'ERROR'}, "Cannot delete linked collection.")
            return {'CANCELLED'}

        rig.data.collections.remove(coll)

        rig.cloudrig_prefs.active_collection_index -= 1
        return {'FINISHED'}

    def delete_hierarchy(self, context):
        rig = context.pose_object or context.active_object
        colls = rig.data.collections
        if not colls.active.is_editable:
            self.report({'ERROR'}, "Cannot remove linked collection.")
            return {'CANCELLED'}

        for child in colls.active.cloudrig_info.children_recursive:
            colls.remove(child)
        colls.remove(colls.active)

        rig.cloudrig_prefs.active_collection_index -= 1
        return {'FINISHED'}

    def delete_all(self, context):
        rig = context.pose_object or context.active_object

        for coll in rig.data.collections_all[:]:
            if coll.is_editable:
                rig.data.collections.remove(coll)

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_add(bpy.types.Operator):
    """Add a new bone collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Add Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.pose_object or context.active_object
        if rig.data.override_library:
            rig.data.override_library.is_system_override = False
        colls = rig.data.collections
        all_colls = rig.data.collections_all
        active_coll = colls.active
        active_idx = colls.active_index

        parent_name = ""
        if active_coll:
            parent_name = active_coll.cloudrig_info.parent_name

        coll = colls.new(name="Collection")
        coll.parent = active_coll.parent
        coll.cloudrig_info.parent_name = parent_name
        coll_idx = all_colls.find(coll.name)
        colls.move(coll_idx, active_idx + 1)

        coll.cloudrig_info.unfold_parents()

        rig.cloudrig_prefs.active_collection_index = all_colls.find(coll.name)

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_reorder(bpy.types.Operator):
    """Move the collection in the list"""

    bl_idname = "pose.cloudrig_collection_reorder"
    bl_label = "Move Active Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction", items=[('UP', "Up", "Up"), ('DOWN', "Down", "Down")]
    )

    @classmethod
    def poll(cls, context):
        rig = context.object
        active_coll = rig.data.collections.active
        if active_coll:
            if not active_coll.is_editable:
                cls.poll_message_set(
                    "Re-ordering the linked collection tree is currently not supported"
                )
                return False
            return True

    @classmethod
    def description(cls, context, props):
        direction = "up" if props.direction == 'UP' else "down"
        return f"Move active collection {direction} in the list"

    @staticmethod
    def get_siblings_and_target_idx(direction, coll):
        siblings = coll.cloudrig_info.siblings

        for sibling_idx, sibling in enumerate(siblings):
            if sibling == coll:
                break

        delta = 1 if direction == 'DOWN' else -1
        sibling_idx += delta

        return siblings, sibling_idx

    def execute(self, context):
        rig = context.pose_object or context.active_object

        collections = rig.data.collections

        old_idx = collections.active_index
        new_idx = old_idx + 1
        if self.direction == 'UP':
            new_idx = old_idx - 1

        collections.move(old_idx, new_idx)

        rig.cloudrig_prefs.active_collection_index = rig.data.collections_all.find(
            collections.active.name
        )

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_assign(bpy.types.Operator):
    """Assign to collections"""

    bl_idname = "pose.cloudrig_collection_assign"
    bl_label = "(Un)Assign Bones to Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    assign: BoolProperty(default=True)
    all_collections: BoolProperty(default=False)
    assign_to_children: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        rig = context.pose_object or context.active_object
        return rig and rig.type == 'ARMATURE' and rig.data.collections.active

    @classmethod
    def description(cls, context, props):
        words = ("Assign", "to") if props.assign else ("Unassign", "from")
        colls = "all collections" if props.all_collections else "active collection"
        return f"{words[0]} selected bones {words[1]} {colls}"

    def execute(self, context):
        rig = context.active_object
        colls = [rig.data.collections.active]
        if self.assign_to_children:
            colls += rig.data.collections.active.cloudrig_info.children_recursive

        if self.all_collections:
            colls = rig.data.collections_all

        with pose_mode(rig):
            if context.selected_bones:
                pbs = [rig.pose.bones.get(eb.name) for eb in context.selected_bones]
            else:
                pbs = context.selected_pose_bones
            for coll in colls:
                for pb in pbs:
                    if self.assign:
                        coll.assign(pb.bone)
                    else:
                        coll.unassign(pb.bone)

        # Report pretty info; Assigned/Unassigned, to/from, number of bones and collections,
        # or use the name if just 1.
        words = ("Assigned", "to") if self.assign else ("Unassigned", "from")
        bones = f"{len(pbs)} bones" if len(pbs) > 0 else pbs[0].name
        colls = f"{len(colls)} collections" if len(colls) > 0 else colls[0].name
        self.report({'INFO'}, f"{words[0]} {bones} {words[1]} {colls}.")

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_clipboard_copy(bpy.types.Operator):
    """Copy visible collections to Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_copy"
    bl_label = "Copy Visible Collections To Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        import json

        rig = context.pose_object or context.active_object

        json_obj = py_collections.defaultdict(dict)
        counter = 0
        for coll in rig.data.collections_all:
            if coll.is_visible:
                counter += 1
                json_obj[coll.name]['bone_names'] = [bone.name for bone in coll.bones]
                json_obj[coll.name]['cloudrig_info'] = coll['cloudrig_info'].to_dict()

        if counter == 0:
            self.report({'ERROR'}, "No visible collections to copy.")
            return {'CANCELLED'}

        context.window_manager.clipboard = json.dumps(json_obj)

        self.report({'INFO'}, f"Copied {counter} collections to Blender clipboard.")
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_clipboard_paste(bpy.types.Operator):
    """Paste collections from the Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_paste"
    bl_label = "Paste Collections From Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    overwrite_existing: BoolProperty(default=True)

    def execute(self, context):
        counter = 0
        try:
            json_obj = json.loads(context.window_manager.clipboard)
            rig = context.pose_object or context.active_object
            collections = rig.data.collections
            collections_all = rig.data.collections_all

            for coll_name, coll_data in json_obj.items():
                coll = collections_all.get(coll_name)

                if not coll or not self.overwrite_existing:
                    coll = collections.new(coll_name)
                    coll.cloudrig_info.name = coll.name

                if type(coll_data) == list:
                    # Selection Set.
                    bone_names = coll_data
                    coll.cloudrig_info.quick_access = True
                    coll.cloudrig_info.preserve_on_regenerate = True
                elif type(coll_data) == dict:
                    # CloudRig Collection.
                    cloudrig_info = coll_data['cloudrig_info']
                    bone_names = coll_data['bone_names']
                    coll['cloudrig_info'] = cloudrig_info

                for bone_name in bone_names:
                    pb = rig.pose.bones.get(bone_name)
                    if not pb:
                        continue
                    coll.assign(pb)
                counter += 1

        except Exception as e:
            self.report(
                {'ERROR'},
                'The clipboard does not contain Bone Collections or Selection Sets.',
            )
            raise e

        if counter == 0:
            self.report({'ERROR'}, "No collections in clipboard to be pasted.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Pasted {counter} collections from clipboard.")
        return {'FINISHED'}


def builtin_collections_draw_override(self, context):
    if is_active_cloud_metarig(context) or is_active_cloudrig(context):
        self.layout.prop(context.object.cloudrig_prefs, 'collection_ui_type', expand=True)

        if context.object.cloudrig_prefs.collection_ui_type == 'CLOUDRIG':
            return draw_cloudrig_collections(self, context)

    return bpy.types.DATA_PT_bone_collections.draw_bkp(self, context)


#######################################
############## Hotkeys ################
#######################################


class CLOUDRIG_PT_hotkeys(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_hotkeys"
    bl_label = "Hotkeys"

    on_metarigs = True
    keymap_items = []

    @staticmethod
    def draw_kmi(km, kmi, layout):
        """A simplified version of draw_kmi from rna_keymap_ui.py."""

        map_type = kmi.map_type

        col = layout.column()

        split = col.split(factor=0.7)

        # header bar
        row = split.row(align=True)
        row.prop(kmi, "active", text="", emboss=False)
        row.label(text=km.name + ": " + kmi.name)

        row = split.row(align=True)
        row.enabled = kmi.active
        row.prop(kmi, "type", text="", full_event=True)

        if kmi.is_user_modified:
            row.operator(
                "preferences.keyitem_restore", text="", icon='BACK'
            ).item_id = kmi.id

    def draw(self, context):
        layout = self.layout

        for addon_kc, km, kmi in type(self).keymap_items:
            user_kc = context.window_manager.keyconfigs.user

            user_km = user_kc.keymaps.get(km.name)
            if not user_km:
                continue
            user_kmi = user_km.keymap_items.get(kmi.idname)
            if not user_kmi:
                continue

            col = layout.column()
            col.context_pointer_set("keymap", user_km)
            self.draw_kmi(user_km, user_kmi, col)


def register_hotkey(
    bl_idname, hotkey_kwargs, *, key_cat='Window', space_type='EMPTY', op_kwargs={}
):
    wm = bpy.context.window_manager
    addon_keyconfig = wm.keyconfigs.addon
    if not addon_keyconfig:
        # This happens when running Blender in background mode.
        return

    # If it already exists, don't create it again.
    for existing_kmi in bpy.types.CLOUDRIG_PT_hotkeys.keymap_items:
        kc, km, kmi = existing_kmi
        if km.name == key_cat and kmi.idname == bl_idname:
            # NOTE: I'm pretty sure there are cases of corrupted KeyMapItems 
            # where accessing .properties segfaults.
            # NOTE: This prevents duplicates of the same operator, even if it's
            # trying to register a different key combo.
            if kmi.properties and dict(kmi.properties) == op_kwargs:
                return
            elif not kmi.properties and not op_kwargs:
                return

    keymaps = addon_keyconfig.keymaps

    km = keymaps.get(key_cat)
    if not km:
        km = keymaps.new(name=key_cat, space_type=space_type)

    kmi = km.keymap_items.new(bl_idname, **hotkey_kwargs)
    bpy.types.CLOUDRIG_PT_hotkeys.keymap_items.append((addon_keyconfig, km, kmi))

    for key in op_kwargs:
        value = op_kwargs[key]
        setattr(kmi.properties, key, value)


#######################################
############## Register ###############
#######################################

classes = (
    CloudRig_Properties,
    CloudRig_RigPreferences,
    CloudRigBoneCollection,
    CLOUDRIG_UL_collections,
    CLOUDRIG_PT_character,
    CLOUDRIG_PT_settings,
    CLOUDRIG_PT_hotkeys,
    CLOUDRIG_PT_collections_sidebar,
    CLOUDRIG_PT_collections_filter,
    CLOUDRIG_MT_collections_specials,
    CLOUDRIG_MT_collections_quick_select,
    OBJECT_OT_cloudrig_copy_property,
    POSE_OT_cloudrig_snap_bake,
    POST_OT_cloudrig_switch_parent_bake,
    POSE_OT_cloudrig_toggle_ikfk_bake,
    POSE_OT_cloudrig_keyframe_all_settings,
    POSE_OT_cloudrig_reset,
    POSE_OT_cloudrig_collections_reveal_all,
    POSE_OT_cloudrig_collection_select,
    POSE_OT_cloudrig_collection_parent_set,
    POSE_OT_cloudrig_collection_delete,
    POSE_OT_cloudrig_collection_add,
    POSE_OT_cloudrig_collection_reorder,
    POSE_OT_cloudrig_collection_assign,
    POSE_OT_cloudrig_collection_clipboard_copy,
    POSE_OT_cloudrig_collection_clipboard_paste,
)


def is_registered(cls):
    """Returns whether a BPy class is registered.
    May not always work, needs more testing..."""
    if issubclass(cls, bpy.types.Operator):
        category, op_name = cls.bl_idname.split(".")
        if hasattr(bpy.ops, category):
            category = getattr(bpy.ops, category)
            return op_name in dir(category)
    if hasattr(bpy.types, cls.__name__):
        bl_type = getattr(bpy.types, cls.__name__)
        if bl_type and hasattr(bl_type, 'is_registered'):
            return bl_type.is_registered
        return True
    return False


def register():
    """Runs on rig generation, add-on registration, or when this file is executed
    via the text editor.
    Should be able to run without errors even if things are already registered.
    """

    for c in classes:
        if not is_registered(c):
            register_class(c)

    # TODO 4.0: These properties for outfit stuff are legacy, remove!
    bpy.types.Object.cloud_rig = PointerProperty(type=CloudRig_Properties)
    bpy.types.Object.cloudrig_prefs = PointerProperty(
        type=CloudRig_RigPreferences, override={'LIBRARY_OVERRIDABLE'}
    )

    bpy.types.BoneCollection.cloudrig_info = PointerProperty(
        type=CloudRigBoneCollection, override={'LIBRARY_OVERRIDABLE'}
    )

    # Ensure custom panels.
    if __name__ != 'CloudRig.generation.cloudrig':
        # This doesn't work during add-on registration, since it relies on context.
        ensure_custom_panels(None, None)
    bpy.app.handlers.load_post.append(ensure_custom_panels)
    bpy.app.handlers.depsgraph_update_post.append(ensure_custom_panels)

    # Hide the built-in Bone Collections panel.
    if not hasattr(bpy.types.DATA_PT_bone_collections, 'draw_bkp'):
        bpy.types.DATA_PT_bone_collections.draw_bkp = (
            bpy.types.DATA_PT_bone_collections.draw
        )
        bpy.types.DATA_PT_bone_collections.draw = builtin_collections_draw_override

    register_hotkey(
        bl_idname='wm.call_menu',
        hotkey_kwargs={
            'type': 'W',
            'value': 'PRESS',
            'shift': True,
            'alt': True,
        },
        key_cat='Pose',
        op_kwargs={'name': CLOUDRIG_MT_collections_quick_select.bl_idname},
    )


def unregister_hotkeys():
    if hasattr(bpy.types, 'CLOUDRIG_PT_hotkeys'):
        for kc, km, kmi in bpy.types.CLOUDRIG_PT_hotkeys.keymap_items:
            km.keymap_items.remove(kmi)
        bpy.types.CLOUDRIG_PT_hotkeys.keymap_items = []


def unregister():
    """Runs before register() on generation and when executed from the text editor.
    Should be able to run without errors even before there's anything to unregister.
    """

    for c in classes:
        if is_registered(c):
            try:
                unregister_class(c)
            except RuntimeError:
                pass

    global custom_panels
    for c in custom_panels[:]:
        if is_registered(c):
            unregister_class(c)
    custom_panels = []

    try:
        del bpy.types.Object.cloud_rig
        bpy.app.handlers.load_post.remove(ensure_custom_panels)
        bpy.app.handlers.depsgraph_update_post.remove(ensure_custom_panels)

        # Unhide the built-in Bone Collections panel.
        bpy.types.DATA_PT_bone_collections.poll = (
            bpy.types.DATA_PT_bone_collections.poll_bkp
        )
    except:
        pass


if __name__ in ['__main__', 'builtins', 'CloudRig.generation.cloudrig'] or '.generation.cloudrig' in __name__:
    # __name__ == `__main__`` when executed in Blender's Text Editor.
    # __name__ == `builtins`` when executed by cloud_generator.
    # __name__ == `CloudRig.generation.cloudrig` when executed by Blender add-on registration.
    unregister()
    register()
