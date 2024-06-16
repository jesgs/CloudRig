"""
This file is loaded into a self-executing text datablock and attached to all
CloudRig rigs.
It's responsible for drawing the CloudRig panel in the 3D View's Sidebar.
"""

import bpy, json, re, contextlib
from collections import OrderedDict, defaultdict
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
    IntProperty,
)
from bpy.types import (
    bpy_struct,
    ID,
    Object,
    PoseBone,
    UILayout,
    UIList,
    Panel,
    Menu,
    Operator,
    PropertyGroup,
    BoneCollection,
    Bone,
)
from rna_prop_ui import rna_idprop_value_item_type
from bpy.utils import register_class, unregister_class

from mathutils import Matrix
from bl_ui.generic_ui_list import draw_ui_list

#######################################
############ Context Checks ###########
#######################################


def is_active_cloudrig(context) -> Object | bool:
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
    return False


def is_generated_cloudrig(obj: Object) -> bool:
    """Return whether obj is a rig marked as being compatible with cloudrig.py."""
    return (
        obj
        and obj.type == 'ARMATURE'
        and 'is_generated_cloudrig' in obj.data
        and obj.data['is_generated_cloudrig']
    )


def is_active_cloud_metarig(context) -> bool:
    return is_cloud_metarig(context.active_object)


def is_cloud_metarig(obj: Object) -> bool:
    return (
        obj
        and obj.type == 'ARMATURE'
        and hasattr(obj, 'cloudrig')
        and obj.cloudrig.enabled
    )


def find_metarig_of_rig(context, rig: Object) -> Object | None:
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


def find_cloudrig(context, allow_metarigs=True) -> Object | None:
    """Find the CloudRig metarig or generated rig most relevant to the current context.
    For example, if the active object is a mesh which is deformed by a generated rig, return that generated rig.
    """

    def is_good_rig(rig):
        return (
            rig
            and is_generated_cloudrig(rig)
            or (allow_metarigs and is_cloud_metarig(rig))
        )

    active = context.active_object
    if is_good_rig(active):
        return active

    if active and active.parent and is_good_rig(active.parent):
        return active.parent

    pose_ob = context.pose_object
    if is_good_rig(pose_ob):
        return pose_ob

    if active and active.type == 'MESH':
        return get_cloudrig_of_mesh(active)[0]


def get_cloudrig_of_mesh(meshob: Object) -> tuple[Object | None, str | None]:
    """If this mesh is being deformed by a CloudRig rig, return it, and the name of the modifier."""
    for m in meshob.modifiers:
        if m.type == 'ARMATURE' and m.object and (is_generated_cloudrig(m.object)):
            return m.object, m.name
    return None, None


class CloudRigOperator(Operator):
    """This class implements a basic draw function that just draws all the operator properties.
    This is necessary because of our hotkey system and UI.
    In order to avoid creating duplicate keymap entries, we insert a "hash" value in each keymap's
    operator properties. But normally, this "hash" value gets drawn in the redo panel, which we don't want.

    So, by letting every class inherit this draw function, we can fix that.
    """

    def draw(self, context):
        layout = self.layout
        props = type(self).__annotations__
        for prop in props:
            layout.prop(self, prop)


#######################################
########## Snapping & Baking ##########
#######################################


class SnappingOpMixin:
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

    @classmethod
    def poll(cls, context) -> bool:
        rig = find_cloudrig(context)
        if not rig or rig.mode != 'POSE':
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

    def get_affected_pbones(self, rig: Object) -> set[PoseBone]:
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
            pb = rig.pose.bones[bone_name]
            pb.matrix = mat.copy()
            context.view_layer.update()
            pb.matrix = mat.copy()


class SnapBakeOpMixin(SnappingOpMixin):
    do_bake: BoolProperty(name="Bake", default=False)
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")
    key_before_start: BoolProperty(
        name="Key Before Start",
        description="Insert a keyframe of the original values one frame before the bake range. This is to avoid undesired interpolation towards the bake",
    )
    key_after_end: BoolProperty(
        name="Key After End",
        description="Insert a keyframe of the original values one frame after the bake range. This is to avoid undesired interpolation after the bake",
    )

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
        rig = find_cloudrig(context)
        if not rig:
            return
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def get_frame_range(self, context) -> list[int]:
        if not self.do_bake:
            return [context.scene.frame_current]

        return list(range(self.frame_start, self.frame_end + 1))

    @staticmethod
    def ensure_action(rig: Object):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.action = bpy.data.actions.new("ACT-" + rig.name)

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
    ) -> OrderedDict[str, Matrix]:
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        return self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

    def keyframe_bones(
        self,
        context,
        rig: Object,
        frame_matrix_map: OrderedDict[int, OrderedDict[str, Matrix]],
        prop_pb: PoseBone,
    ):
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
            context.scene.frame_set(frame_numbers[0] - 1)
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)
            bpy.ops.anim.keyframe_insert()

        if self.key_after_end:
            # Key original value and transforms one frame after the selected bake range.
            context.scene.frame_set(frame_numbers[-1] + 1)
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


class POSE_OT_cloudrig_snap_bake(SnapBakeOpMixin, CloudRigOperator):
    bl_idname = "pose.cloudrig_snap_bake"
    bl_label = "Snap & Bake Bones"
    bl_description = (
        "Flip a custom property's value while preserving the world-matrix of some bones"
    )
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        return self.execute_bone_snap_bake(context)

    def execute_bone_snap_bake(self, context) -> set:
        rig = find_cloudrig(context)
        if not rig:
            return {'CANCELLED'}
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
            self.keyframe_bones(context, rig, frame_matrix_map, prop_pb)
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


class POST_OT_cloudrig_switch_parent_bake(POSE_OT_cloudrig_snap_bake, CloudRigOperator):
    bl_idname = "pose.cloudrig_switch_parent_bake"
    bl_label = "Switch Parents & Preserve Transforms"
    bl_description = "Change the parent while preserving the world-matrix of the affected bones, even in a frame range"
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


class POSE_OT_cloudrig_toggle_ikfk_bake(SnapBakeOpMixin, CloudRigOperator):
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

    def invoke(self, context, _event):
        self.rig = context.active_object
        self.prop_pb = self.get_properties_bone(self.rig)
        self.current_value = self.prop_pb[self.prop_id]
        self.target_value = self.get_prop_target_value(self.prop_pb, self.prop_id)
        self.bone_map = self.get_bone_map(self.current_value)
        return super().invoke(context, _event)

    def execute(self, context):
        rig = context.active_object
        active_frame_bkp = context.scene.frame_current

        # Store (copies!) of world matrices.
        bones_to_snap = [self.rig.pose.bones[name] for name in self.bone_map.keys()]
        snap_to_bones = [self.rig.pose.bones[name] for name in self.bone_map.values()]
        frame_matrix_map = self.map_frames_to_bone_matrices(
            context, bones_to_snap, snap_to_bones
        )

        if self.do_bake:
            self.keyframe_bones(context, rig, frame_matrix_map, self.prop_pb)
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
        mat.translation = fk_first.tail + fk_first.vector / 2
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
            fk_upperarm = snap_to_bones[-1]
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


class POSE_OT_cloudrig_keyframe_all_settings(CloudRigOperator):
    """Keyframe all rig settings that are being drawn in the below UI"""

    bl_idname = "pose.cloudrig_keyframe_all_settings"
    bl_label = "Keyframe CloudRig Settings"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context, allow_metarigs=False)
        if not rig:
            return False
        return 'ui_data' in rig.data

    def execute(self, context):
        rig, ui_data = get_rig_and_ui(context)

        props_to_key: list[tuple[ID | PoseBone, str]] = []

        def add_props_to_key_recursive(ui_data: OrderedDict):
            for _elem_name, elem_data in ui_data.items():
                if type(elem_data) == str:
                    continue
                if 'owner_path' in elem_data:
                    # This is a property, so it can be keyed.
                    try:
                        owner = rig.path_resolve(elem_data['owner_path'])
                        if not owner:
                            continue
                    except ValueError:
                        # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
                        continue

                    props_to_key.append((owner, elem_data['prop_name']))

                add_props_to_key_recursive(elem_data)

        add_props_to_key_recursive(ui_data)

        for prop_owner, prop_name in props_to_key:
            prop_owner.keyframe_insert(prop_name, group=prop_owner.name)

        return {'FINISHED'}


class POSE_OT_cloudrig_reset(CloudRigOperator):
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
        return find_cloudrig(context)

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        rig = find_cloudrig(context)
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

                property_settings = None
                try:
                    property_settings = pb.id_properties_ui(key)
                    if not property_settings:
                        continue
                    property_settings = property_settings.as_dict()
                    if not 'default' in property_settings:
                        continue
                except TypeError:
                    # Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
                    pass

                if not property_settings:
                    continue

                if type(pb[key]) not in (float, int, bool):
                    continue
                pb[key] = property_settings['default']

        return {'FINISHED'}


#######################################
########### Dynamic Rig UI ############
#######################################


class CLOUDRIG_PT_base(Panel):
    """Base class for all CloudRig sidebar panels."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context)

    def draw(self, context):
        pass


class CLOUDRIG_PT_settings(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_settings"
    bl_label = "Settings"

    def draw(self, context):
        layout = self.layout
        rig, ui_data = get_rig_and_ui(context)
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
        if hasattr(rig, 'cloudrig') and rig.cloudrig.enabled:
            # If CloudRig add-on is enabled, and this is a metarig.
            layout.separator()
            layout.prop(rig.cloudrig, 'ui_edit_mode', icon='GREASEPENCIL')
            if rig.cloudrig.ui_edit_mode:
                if hasattr(bpy.ops.pose, 'cloudrig_add_property_to_ui'):
                    layout.operator(
                        'pose.cloudrig_add_property_to_ui', icon='ADD'
                    )

        if ui_data:
            for panel_name, panel_data in ui_data.items():
                if panel_name == "":
                    layout.separator()
                    for label_name, label_data in panel_data.items():
                        if type(label_data) == str:
                            # It's a flag, not a UI element...
                            continue
                        draw_rig_settings_per_label(
                            layout=layout,
                            rig=rig,
                            ui_path=[""],
                            panel_name="",
                            panel_data=panel_data,
                            label_name=label_name,
                            label_data=label_data,
                        )
                else:
                    sane_name = re.sub(r'\W+', '', panel_name)
                    full_name = "CLOUDRIG_PT_custom_" + sane_name.lower().replace(" ", "")
                    header, body = layout.panel(full_name)
                    self.draw_panel_header(context, header, panel_name)
                    if body:
                        self.draw_panel_contents(context, body, panel_name)
    
    def draw_panel_header(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)
        panel_data = ui_data[panel_name]

        draw_drag_operator(rig, ui_data, panel_data, panel_name, [], layout)

        layout.label(text=panel_name)
    
    def draw_panel_contents(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)

        panel_data = ui_data.get(panel_name)
        if panel_data:
            """Panel data contains a list of tuples.
            The first entry of each tuple is a string telling us the type of UI element to draw.
            The second entry is the for drawiong the element. Can be str, list, or dict, depending on the type.
            """
            for label_name, label_data in panel_data.items():
                if type(label_data) == str:
                    # This is a flag, not a label.
                    continue
                draw_rig_settings_per_label(
                    layout=layout,
                    rig=rig,
                    ui_path=[panel_name],
                    panel_name=panel_name,
                    panel_data=panel_data,
                    label_name=label_name,
                    label_data=label_data,
                )


def read_rig_panels(obj) -> OrderedDict:
    """Return the rig's UI data as a nested OrderedDict."""

    def tuples_to_dict(tuples: list[tuple[str, list]]) -> OrderedDict:
        """Convert a nested list of (string, data) tuples to a nested OrderedDict."""
        ordered_dict = OrderedDict()
        for key, value in tuples:
            if key not in {'op_kwargs'}:
                if type(value) == dict:
                    # We also want to convert regular dicts to OrderedDict,
                    # especially because they might contain tuple-lists.
                    value = [(k, v) for k, v in value.items()]
                if type(value) == list:
                    value = tuples_to_dict(value)

            ordered_dict[key] = value
        return ordered_dict

    if 'ui_data' not in obj.data:
        return OrderedDict()
    panels = obj.data['ui_data'].to_dict()['panels']
    return tuples_to_dict(panels)


def write_rig_panels(obj, panels: OrderedDict):
    # Convert back to a list of tuples so Blender can store it without mangling it.

    def dict_to_tuples(ordered_dict: OrderedDict) -> list[tuple[str, list]]:
        """Convert a nested OrderedDict to a nested list of tuples."""
        tuples = []
        for key, value in ordered_dict.items():
            if type(value) in {dict, OrderedDict}:
                value = dict_to_tuples(value)
            tuples.append((key, value))
        return tuples

    # If we store it in a custom property as a list, each element gets
    # converted to a weird type by Blender.
    # So, just put it in a dictionary with a single 'panels' key.
    # Then it can easily be converted back to python, see read_rig_panels().
    panels = {'panels': dict_to_tuples(panels)}
    obj.data['ui_data'] = panels


def get_rig_and_ui(context) -> tuple[Object, OrderedDict] | tuple[None, None]:
    """Find the most relevant CloudRig in the context, return it and its UI."""
    rig = find_cloudrig(context)

    if not rig:
        return None, None

    return rig, read_rig_panels(rig)


def draw_rig_settings_per_label(
    layout: UILayout,
    rig: Object,
    ###
    ui_path: list[str],
    panel_name: str,
    panel_data: OrderedDict,
    label_name: str,
    label_data: OrderedDict,
):
    if label_name:
        row = layout.row()
        draw_drag_operator(rig, panel_data, label_data, label_name, ui_path, row)
        row.label(text=label_name)

    ui_path += [label_name]

    for row_name, row_data in label_data.items():
        if type(row_data) == str:
            # It's a flag, not a UI element.
            continue
        column = layout
        sub_row = column.row(align=True)
        draw_drag_operator(rig, label_data, row_data, row_name, ui_path, sub_row)
        sub_row.separator()

        for slider_name, slider_data in row_data.items():
            if type(slider_data) == str:
                # It's a flag, not a UI element.
                continue
            if slider_data.get('owner_path') != None:
                texts = slider_data.get('texts', [])
                if texts:
                    if texts.startswith("["):
                        texts = json.loads(texts)
                    else:
                        texts = [t.strip() for t in texts]
                draw_slider(
                    rig=rig,
                    column=column,
                    sub_row=sub_row,
                    owner_path=slider_data.get('owner_path'),
                    prop_name=slider_data.get('prop_name'),
                    ui_path=ui_path + [row_name, slider_name],
                    panel_name=panel_name,
                    label_name=label_name,
                    row_name=row_name,
                    slider_name=slider_name,
                    texts=texts,
                    operator=slider_data.get('operator'),
                    op_icon=slider_data.get('op_icon'),
                    op_kwargs=slider_data.get('op_kwargs'),
                    children=slider_data.get('children'),
                )
            elif slider_data.get('operator'):
                # Allow drawing an operator, even without a property.
                # TODO: Test this.
                draw_operator(sub_row, **slider_data)


def draw_slider(
    *,
    rig,
    column: UILayout,
    sub_row: UILayout,
    ###
    owner_path: str,
    prop_name: str,
    ###
    ui_path: list[str] = [],
    panel_name="",
    label_name="",
    row_name="",
    slider_name="",
    ###
    texts=[],
    operator="",
    op_icon='BLANK1',
    op_kwargs={},
    ###
    children={},
):

    if owner_path == "":
        owner = rig
    else:
        try:
            owner = rig.path_resolve(owner_path)
        except ValueError:
            # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
            owner = None
            pass

    prop_value = None
    if not owner:
        sub_row.alert = True
        sub_row.label(
            text=f"Missing property owner: '{owner_path}' for property '{prop_name}'.",
            icon='ERROR',
        )
    else:
        try:
            prop_value = owner.path_resolve(prop_name)
        except ValueError:
            sub_row.alert = True
            sub_row.label(
                text=f"Missing property '{prop_name}' of owner '{owner_path}'.",
                icon='ERROR',
            )

    if not sub_row.alert:
        draw_property(
            layout=sub_row,
            prop_owner=owner,
            prop_name=prop_name,
            slider_name=slider_name,
            texts=texts,
        )
        if operator:
            draw_operator(
                sub_row, bl_idname=operator, op_icon=op_icon, op_kwargs=op_kwargs
            )

        prop_value_str = str(prop_value)
        if children:
            box_col = None
            for child_value, child_data in children.items():
                child_values = [v.strip() for v in child_value.split(",")]
                if prop_value_str in child_values:
                    for child_label_name, child_label_data in child_data.items():
                        if not box_col:
                            box_col = column.box().column()
                        draw_rig_settings_per_label(
                            layout=box_col,
                            rig=rig,
                            ui_path=ui_path + ['children', child_value],
                            panel_name=panel_name,
                            panel_data=child_data,
                            label_name=child_label_name,
                            label_data=child_label_data,
                        )

    if is_ui_edit_mode(rig):
        bracketless_prop_name = unquote_custom_prop_name(prop_name)

        if not sub_row.alert:
            if type(prop_value) in {int, bool}:
                child_op = sub_row.operator(
                    'pose.cloudrig_add_child_property_to_ui', icon='ADD', text=""
                )
                child_op.parent_value = prop_value_str
                child_op.parent_ui_path = json.dumps(ui_path)
                if type(owner) == PoseBone:
                    child_op.init_owner_path = f'pose.bones["{owner.name}"]'

            if (
                bracketless_prop_name not in owner.__dir__()
                and bracketless_prop_name in owner
            ):
                data_path = "active_object"
                if owner_path.startswith('['):
                    data_path += owner_path
                elif owner_path != "":
                    data_path += "." + owner_path
                edit_op = sub_row.operator(
                    "wm.properties_edit", text="", icon='PREFERENCES'
                )
                edit_op.data_path = data_path
                edit_op.property_name = bracketless_prop_name

        edit_op = sub_row.operator(
            'pose.cloudrig_edit_property_in_ui', text="", icon='GREASEPENCIL'
        )
        edit_op.init_owner_path = owner_path
        edit_op.prop_name = bracketless_prop_name
        ui_path_str = json.dumps(ui_path)
        edit_op.ui_path = ui_path_str
        if 'children' in ui_path:
            edit_op.parent_ui_path = json.dumps(ui_path[:-5])
            edit_op.parent_value = str(ui_path[-4])
        else:
            edit_op.panel_name = panel_name
        edit_op.label_name = label_name
        edit_op.row_name = row_name
        edit_op.slider_name = slider_name
        if operator:
            edit_op.operator = operator
            edit_op.op_icon = op_icon
            edit_op.op_kwargs = json.dumps(op_kwargs)
        if children:
            edit_op.children = json.dumps(children)
        if texts:
            edit_op.texts = ", ".join(texts)
        sub_row.operator(
            'pose.cloudrig_remove_property_from_ui', text="", icon='X'
        ).ui_path = ui_path_str
    sub_row.separator()


def draw_property(
    layout: UILayout,
    prop_owner: bpy_struct,
    prop_name: str,
    *,
    slider_name="",
    icon_true="CHECKBOX_HLT",
    icon_false='CHECKBOX_DEHLT',
    texts=[],
):
    prop_value = prop_owner.path_resolve(prop_name)

    bracketless_prop_name = unquote_custom_prop_name(prop_name)
    if not slider_name:
        slider_name = bracketless_prop_name

    value_type, is_array = rna_idprop_value_item_type(prop_value)

    if value_type is type(None) or issubclass(value_type, ID):
        # Property is a Datablock Pointer.
        layout.prop(prop_owner, prop_name, text=slider_name)
    elif value_type in {int, float, bool}:
        if texts and not is_array and len(texts) - 1 >= int(prop_value) >= 0:
            text = texts[int(prop_value)].strip()
            if text:
                slider_name += ": " + text
        if value_type == bool:
            icon = icon_true if prop_value else icon_false
            layout.prop(prop_owner, prop_name, toggle=True, text=slider_name, icon=icon)
        elif value_type in {int, float}:
            if bracketless_prop_name != prop_name:
                # If this is a custom property.

                # Property is a float/int/color
                # For large ranges, a slider doesn't make sense.
                try:
                    if bracketless_prop_name in prop_owner:
                        prop_settings = prop_owner.id_properties_ui(
                            bracketless_prop_name
                        ).as_dict()
                except TypeError:
                    # This happens for Python properties. There's no point drawing them.
                    return
                is_slider = (
                    not is_array
                    and prop_settings['soft_max'] - prop_settings['soft_min'] < 100
                )
                layout.prop(prop_owner, prop_name, slider=is_slider, text=slider_name)
            else:
                layout.prop(prop_owner, prop_name, text=slider_name)
    elif value_type == str:
        if (
            issubclass(type(prop_owner), bpy.types.Constraint)
            and prop_name == 'subtarget'
            and prop_owner.target
            and prop_owner.target.type == 'ARMATURE'
        ):
            # Special case for nice constraint sub-target selectors.
            layout.prop_search(prop_owner, prop_name, prop_owner.target.pose, 'bones')
        else:
            layout.prop(prop_owner, prop_name)
    else:
        layout.prop(prop_owner, prop_name, text=slider_name)


def draw_operator(
    layout: UILayout,
    bl_idname: str,
    op_icon='BLANK1',
    op_kwargs={},
    text="",
):
    if not op_icon or op_icon == 'NONE':
        op_icon = 'BLANK1'
    op_props = layout.operator(bl_idname, text=text, icon=op_icon)
    feed_op_props(op_props, op_kwargs)
    return op_props


def draw_drag_operator(
    rig: Object,
    parent_ui_data: OrderedDict,
    ui_data: OrderedDict,
    ui_name: str,
    ui_path: list[str],
    layout: UILayout,
):
    sub_elements = [elem for key, elem in parent_ui_data.items() if type(elem) != str]
    if len(sub_elements) > 1 and is_ui_edit_mode(rig):
        is_dragged = ui_data.get('is_dragged', False)
        if is_dragged:
            icon = 'VIEW_PAN'
            icon_value = 0
        else:
            icon = 'NONE'
            from CloudRig import icons

            icon_value = icons.get_cloudrig_icon_id('vertical_twoway_arrows')
        op = layout.operator(
            'pose.cloudrig_reorder_rows', text="", icon=icon, icon_value=icon_value
        )
        op.ui_path = json.dumps(ui_path + [ui_name])
        return op


def is_ui_edit_mode(obj):
    return (
        hasattr(obj, 'cloudrig') and obj.cloudrig.enabled and obj.cloudrig.ui_edit_mode
    )


def feed_op_props(op_props, op_kwargs: str or dict or list):
    """Set the arguments of an OperatorProperties instance, such as one returned by
    `UILayout.operator()`.
    """

    if type(op_kwargs) == str:
        op_kwargs = json.loads(op_kwargs)
    if type(op_kwargs) == dict:
        op_kwargs = [(key, value) for key, value in op_kwargs.items()]

    # Pass on any paramteres to the operator that it will accept.
    for key, value in op_kwargs:
        if hasattr(op_props, key):
            desired_type = type(getattr(op_props, key))
            # Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
            if type(value) in {list, dict}:
                value = json.dumps(value)
            if desired_type != type(value):
                value = desired_type(value)
            setattr(op_props, key, value)


def unquote_custom_prop_name(prop_name: str) -> str:
    if prop_name.startswith('["') or prop_name.startswith("['"):
        return prop_name[2:-2]
    return prop_name


#######################################
########### Rig Preferences ###########
#######################################


class CloudRig_RigPreferences(PropertyGroup):
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


class CloudRigBoneCollection(PropertyGroup):
    """Properties stored on BoneCollection.cloudrig_info.
    Used for implementing and drawing the nested collections UIList.
    Also some other functionality like Solo Collection and Preserve on Regenerate.
    """

    def get_collection(self) -> BoneCollection:
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

    is_dragged: BoolProperty(
        name="Is Dragged",
        description="Internal. Flag to mark that this collection is currently dragged by the reorder operator. Used to change the icon",
        default=False
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
    def parent_collection(self) -> BoneCollection:
        # TODO 4.2: Redundant, delete.
        return self.get_collection().parent

    @parent_collection.setter
    def parent_collection(self, coll: BoneCollection):
        # TODO 4.2: Redundant, delete.
        self.get_collection().parent = coll
        self.parent_name = coll.name

    def unfold_parents(self):
        for parent in self.parents_recursive:
            parent.is_expanded = True

    def update_is_expanded(self, context):
        coll = self.get_collection()
        coll.is_expanded = self.is_expanded
        rig = find_cloudrig(context)
        if rig:
            rig.cloudrig_prefs.active_collection_index = coll.index

    is_expanded: BoolProperty(name="Is Expanded", description="Whether to show the children of this collection", default=False, update=update_is_expanded)

    @property
    def children(self) -> list[BoneCollection]:
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
    def children_recursive(self) -> list[BoneCollection]:
        children = self.children[:]
        for child in children:
            children += child.cloudrig_info.children
        return children

    @property
    def parents_recursive(self) -> list[BoneCollection]:
        parents = []
        parent = self.parent_collection
        while parent:
            parents.append(parent)
            parent = parent.cloudrig_info.parent_collection
        return parents

    @property
    def all_bones(self) -> list[Bone]:
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


class CLOUDRIG_UL_collections(UIList):
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
            row.prop(collection.cloudrig_info, 'is_expanded', text="", icon=icon, emboss=False)
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

            icon = 'TRACKER'
            if collection.cloudrig_info.is_dragged:
                icon = 'VIEW_PAN'
            row.operator(CLOUDRIG_OT_reorder_collections.bl_idname, text="", icon=icon).collection_name=collection.name

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
    def get_visual_collection_order(rig, filtered=False) -> list[BoneCollection]:
        """Return the collections of the rig in the order they are currently to be displayed in the UIList.
        If filtered, only include those collections in the list which aren't being filtered, eg. by collapsing parents, or search."""

        # Find collections without any parent
        all_collections = rig.data.collections_all
        root_colls = [coll for coll in all_collections if not coll.parent]
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.cloudrig_info.children:
                add_children_recursive(child)

        for root_coll in root_colls:
            add_children_recursive(root_coll)

        flt_flags = CLOUDRIG_UL_collections.get_filter_flags(
            all_collections, rig.cloudrig_prefs.collection_filter
        )

        if filtered:
            for i, flag in enumerate(flt_flags):
                if flag == 0:
                    sorted_colls.remove(all_collections[i])

        return sorted_colls

    @staticmethod
    def get_collection_order(rig) -> list[int]:
        # Order collections by CloudRig hierarchy, such that children come after their
        # parents, but the original order is otherwise preserved.

        sorted_colls = CLOUDRIG_UL_collections.get_visual_collection_order(rig)
        # NOTE: THIS MUST BE BOMBPROOF, OR BLENDER WILL CRASH!
        return [sorted_colls.index(coll) for coll in rig.data.collections_all]

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
        rig = find_cloudrig(context)

        flt_flags = self.get_filter_flags(
            all_collections, rig.cloudrig_prefs.collection_filter
        )
        flt_neworder = self.get_collection_order(rig)

        return flt_flags, flt_neworder


def draw_cloudrig_collections(self, context, rig: Object):
    layout = self.layout
    layout.use_property_split = True
    layout.use_property_decorate = False

    prop_owner = 'pose_object'
    if context.active_object:
        prop_owner = 'active_object'
        if context.active_object != rig:
            _rig, modifier_name = get_cloudrig_of_mesh(context.active_object)
            if modifier_name:
                prop_owner = f'active_object.modifiers["{modifier_name}"].object'

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

    prefs = rig.cloudrig_prefs
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

    active_coll = rig.data.collections.active
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
    if context.mode not in {'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}:
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

    @classmethod
    def poll(cls, context):
        return bool(find_cloudrig(context))

    def draw(self, context):
        rig = find_cloudrig(context)
        draw_cloudrig_collections(self, context, rig)


class CLOUDRIG_PT_collections_filter(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_label = "Filter"
    bl_options = {'INSTANCED'}

    def draw(self, context):
        layout = self.layout
        rig = find_cloudrig(context)
        prefs = rig.cloudrig_prefs
        row = layout.row(align=True)
        row.prop(prefs, 'show_visibility', text="", icon='HIDE_OFF')
        row.prop(prefs, 'show_solo', text="", icon='SOLO_OFF')
        row.prop(prefs, 'show_select', text="", icon='RESTRICT_SELECT_OFF')

        row.separator()
        row.prop(prefs, "show_editing", text="", icon='PREFERENCES')
        row.prop(prefs, 'show_bone_count', text="", icon='GROUP_BONE')
        if rig.data.override_library:
            row.prop(
                prefs, 'show_local_overrides', text="", icon='LIBRARY_DATA_OVERRIDE'
            )


class CLOUDRIG_MT_collections_specials(Menu):
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


class CLOUDRIG_MT_collections_quick_select(Menu):
    """Quick select menu, so favourite bone collections can be selected quickly with a hotkey"""

    bl_label = "Quick Select"
    bl_idname = 'CLOUDRIG_MT_collections_quick_select'

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context, allow_metarigs=False)

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"

        rig = find_cloudrig(context, allow_metarigs=False)

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


class POSE_OT_cloudrig_collections_reveal_all(CloudRigOperator):
    """Reveal all collections"""

    bl_idname = "pose.cloudrig_collections_reveal_all"
    bl_label = "Show All Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = find_cloudrig(context, allow_metarigs=False)
        for coll in rig.data.collections_all:
            coll.is_visible = True
            coll.is_solo = False

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


class POSE_OT_cloudrig_collection_select(CloudRigOperator):
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
        return bool(find_cloudrig(context))

    def invoke(self, context, event):
        self.extend_selection = event.shift
        self.select = not event.alt
        self.flip = event.ctrl

        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)

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


class POSE_OT_cloudrig_collection_parent_set(CloudRigOperator):
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

    @classmethod
    def poll(cls, context):
        return bool(find_cloudrig(context))

    def invoke(self, context, _event):
        rig = find_cloudrig(context)
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
        rig = find_cloudrig(context)
        layout.prop_search(self, 'parent_name', rig.data, 'collections_all')

    def execute(self, context):
        rig = find_cloudrig(context)
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

        coll.cloudrig_info.unfold_parents()
        index = all_colls.find(coll.name)
        rig.cloudrig_prefs.active_collection_index = index

        self.report({'INFO'}, "Collection parent set.")
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_delete(CloudRigOperator):
    """Remove the active bone collection. Shift+Click to delete hierarchy"""

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
        rig = find_cloudrig(context)
        if not rig:
            return False
        active_coll = rig.data.collections.active
        if active_coll:
            if not active_coll.is_editable:
                cls.poll_message_set("Cannot delete linked collection")
                return False
            return True

    def invoke(self, context, event):
        if self.mode == 'ACTIVE' and event.shift:
            self.mode = 'HIERARCHY'
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        visual_index = self.get_visual_active_index(rig)

        if self.mode == 'ALL':
            self.delete_all(rig)
            self.report({'INFO'}, "Deleted all editable bone collections.")
            return {'FINISHED'}

        if self.mode == 'ACTIVE' and not self.delete_active(rig):
            return {'CANCELLED'}

        elif self.mode == 'HIERARCHY':
            ret = self.delete_hierarchy(rig)
            if ret:
                return ret
            self.report(
                {'INFO'}, "Deleted editable bone collections of selected hierarchy."
            )

        self.set_visual_active_index(rig, visual_index)

        return {'FINISHED'}

    @staticmethod
    def get_visual_active_index(rig) -> int:
        """Get the index of the active collection as it is in the current UIList. 
        Eg., if the active collection is the 3rd one that is drawn, this will return 2."""
        sorted_collections = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        return sorted_collections.index(rig.data.collections.active)

    def set_visual_active_index(self, rig, index):
        """Set the index of the active collection as they appear in the UIList.
        Eg., if index==2, the 3rd collection from the top of the list will become active."""
        sorted_collections = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        if index <= len(sorted_collections) - 1:
            coll = sorted_collections[index]
        elif len(sorted_collections) > 0:
            coll = sorted_collections[index - 1]
        else:
            return
        rig.cloudrig_prefs.active_collection_index = coll.index

    def delete_active(self, rig) -> bool:
        """Try to delete the active bone collection, and return success state."""
        coll = rig.data.collections.active
        if not coll:
            self.report({'ERROR'}, "There is no active collection.")
            return False
        if not coll.is_editable:
            self.report({'ERROR'}, "Cannot delete linked collection.")
            return False

        coll_name = coll.name
        rig.data.collections.remove(coll)
        self.report({'INFO'}, f"Deleted active collection: '{coll_name}'")
        return True

    def delete_hierarchy(self, rig):
        colls = rig.data.collections
        active = colls.active

        for child in active.cloudrig_info.children_recursive:
            if child.is_editable:
                colls.remove(child)
        colls.remove(active)

    def delete_all(self, rig):
        for coll in rig.data.collections_all[:]:
            if coll.is_editable:
                rig.data.collections.remove(coll)

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_add(CloudRigOperator):
    """Add a new bone collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Add Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(find_cloudrig(context))

    def execute(self, context):
        rig = find_cloudrig(context)
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


class POSE_OT_cloudrig_collection_reorder(CloudRigOperator):
    """Move the collection in the list"""

    bl_idname = "pose.cloudrig_collection_reorder"
    bl_label = "Move Active Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction", items=[('UP', "Up", "Up"), ('DOWN', "Down", "Down")]
    )

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context)
        if not rig:
            return False
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
        rig = find_cloudrig(context)

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


class CLOUDRIG_OT_reorder_collections(CloudRigOperator):
    """Rearrange this collection by moving the mouse up and down. Left-click to confirm, right-click to cancel"""

    bl_idname = "pose.cloudrig_reorder_collections"
    bl_label = "Reorder Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    collection_name: StringProperty()

    def invoke(self, context, event):
        self.mouse_initial = event.mouse_y
        self.index_offset = 0

        rig = find_cloudrig(context)
        self.collection = rig.data.collections.get(self.collection_name)
        if not self.collection:
            return {'CANCELLED'}
        self.collection.cloudrig_info.is_dragged = True
        rig.cloudrig_prefs.active_collection_index = self.initial_index = self.collection.index

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rig = find_cloudrig(context)
        self.index_offset = 0
        if event.type in {'W', 'UP_ARROW'} and not event.is_repeat and event.value != 'RELEASE':
            self.index_offset = -1
        elif event.type in {'S', 'DOWN_ARROW'} and not event.is_repeat and event.value != 'RELEASE':
            self.index_offset = 1
        elif event.type == 'MOUSEMOVE':
            self.index_offset = int((event.mouse_y - self.mouse_initial) / -20)
        elif event.type in {'LEFTMOUSE', 'NUMPAD_ENTER', 'RET'}:
            self.collection.cloudrig_info.is_dragged = False
            # redraw_viewport()
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.collection.cloudrig_info.is_dragged = False
            rig.data.collections.move(self.collection.index, self.initial_index)
            rig.cloudrig_prefs.active_collection_index = self.collection.index

            # TODO: Restore the collection order, somehow.
            # redraw_viewport()
            return {'CANCELLED'}

        if self.index_offset != 0:
            ret = self.execute(context)
            if ret == {'FINISHED'}:
                self.mouse_initial = event.mouse_y
                # redraw_viewport()

        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = find_cloudrig(context)

        visual_order = CLOUDRIG_UL_collections.get_visual_collection_order(rig, filtered=True)
        visual_index = POSE_OT_cloudrig_collection_delete.get_visual_active_index(rig)

        done = False
        while not done:
            visual_index += self.index_offset
            if visual_index < 0 or visual_index > len(visual_order)-1:
                return {'CANCELLED'}

            other_coll = visual_order[visual_index]
            if other_coll.parent == self.collection.parent:
                done = True

        rig.data.collections.move(self.collection.index, other_coll.index)
        rig.cloudrig_prefs.active_collection_index = self.collection.index
        # redraw_viewport()

        return {'FINISHED'}

class POSE_OT_cloudrig_collection_assign(CloudRigOperator):
    """Assign to collections"""

    bl_idname = "pose.cloudrig_collection_assign"
    bl_label = "(Un)Assign Bones to Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    assign: BoolProperty(default=True)
    all_collections: BoolProperty(default=False)
    assign_to_children: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context)
        return bool(rig and rig.data.collections.active)

    @classmethod
    def description(cls, context, props):
        words = ("Assign", "to") if props.assign else ("Unassign", "from")
        colls = "all collections" if props.all_collections else "active collection"
        return f"{words[0]} selected bones {words[1]} {colls}"

    def execute(self, context):
        rig = find_cloudrig(context)
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


class POSE_OT_cloudrig_collection_clipboard_copy(CloudRigOperator):
    """Copy visible collections to Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_copy"
    bl_label = "Copy Visible Collections To Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(find_cloudrig(context))

    def execute(self, context):
        rig = find_cloudrig(context)

        json_obj = defaultdict(dict)
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


class POSE_OT_cloudrig_collection_clipboard_paste(CloudRigOperator):
    """Paste collections from the Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_paste"
    bl_label = "Paste Collections From Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    overwrite_existing: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return bool(find_cloudrig(context))

    def execute(self, context):
        counter = 0
        try:
            json_obj = json.loads(context.window_manager.clipboard)
            rig = find_cloudrig(context)
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
    """Override the Bone Collections ui in the Properties Editor.
    Editor drawing code should use context.object, since this accounts for pinning.
    """
    pinned_obj = context.object
    if is_cloud_metarig(pinned_obj) or is_generated_cloudrig(pinned_obj):
        self.layout.prop(pinned_obj.cloudrig_prefs, 'collection_ui_type', expand=True)

        if pinned_obj.cloudrig_prefs.collection_ui_type == 'CLOUDRIG':
            return draw_cloudrig_collections(self, context, pinned_obj)

    return bpy.types.DATA_PT_bone_collections.draw_bkp(self, context)


#######################################
############## Hotkeys ################
#######################################


class CLOUDRIG_PT_hotkeys_panel(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_hotkeys_panel"
    bl_label = "Hotkeys"

    cloudrig_keymap_items: dict[int, tuple["KeyConfig", "KeyMap", "KeyMapItem"]] = {}

    def draw(self, context):
        type(self).draw_hotkey_list(self.layout.column(), context)

    @classmethod
    def draw_hotkey_list(cls, layout, context):
        hotkey_class = cls
        user_kc = context.window_manager.keyconfigs.user

        keymap_data = list(hotkey_class.cloudrig_keymap_items.items())
        keymap_data = sorted(keymap_data, key=lambda tup: tup[1][2].name)

        prev_kmi = None
        for kmi_hash, kmi_tup in keymap_data:
            addon_kc, addon_km, addon_kmi = kmi_tup

            user_km = user_kc.keymaps.get(addon_km.name)
            if not user_km:
                # This really shouldn't happen.
                continue
            user_kmi = hotkey_class.find_kmi_in_km_by_hash(user_km, kmi_hash)

            col = layout.column()
            col.context_pointer_set("keymap", user_km)
            if user_kmi and prev_kmi and prev_kmi.name != user_kmi.name:
                col.separator()
            user_row = col.row()

            if False:
                # Debug code: Draw add-on and user KeyMapItems side-by-side.
                split = user_row.split(factor=0.5)
                addon_row = split.row()
                user_row = split.row()
                hotkey_class.draw_kmi(addon_km, addon_kmi, addon_row)
            if not user_kmi:
                # This should only happen for one frame during Reload Scripts.
                print(
                    "CloudRig: Can't find this hotkey to draw: ",
                    addon_kmi.name,
                    addon_kmi.to_string(),
                    kmi_hash,
                )
                continue

            hotkey_class.draw_kmi(user_km, user_kmi, user_row)
            prev_kmi = user_kmi

    @staticmethod
    def draw_kmi(km, kmi, layout):
        """A simplified version of draw_kmi from rna_keymap_ui.py."""

        map_type = kmi.map_type

        col = layout.column()

        split = col.split(factor=0.7)

        # header bar
        row = split.row(align=True)
        row.prop(kmi, "active", text="", emboss=False)
        row.label(text=f'{kmi.name} ({km.name})')

        row = split.row(align=True)
        sub = row.row(align=True)
        sub.enabled = kmi.active
        sub.prop(kmi, "type", text="", full_event=True)

        if kmi.is_user_modified:
            row.operator(
                "preferences.keyitem_restore", text="", icon='BACK'
            ).item_id = kmi.id

    @staticmethod
    def print_kmi(kmi):
        idname = kmi.idname
        keys = kmi.to_string()
        props = str(list(kmi.properties.items()))
        print(idname, props, keys)

    @staticmethod
    def find_kmi_in_km_by_hash(keymap, kmi_hash):
        """There's no solid way to match modified user keymap items to their
        add-on equivalent, which is necessary to draw them in the UI reliably.

        To remedy this, we store a hash in the KeyMapItem's properties.

        This function lets us find a KeyMapItem with a stored hash in a KeyMap.
        Eg., we can pass a User KeyMap and an Addon KeyMapItem's hash, to find the
        corresponding user keymap, even if it was modified.

        The hash value is unfortunately exposed to the users, so we just hope they don't touch that.
        """

        for kmi in keymap.keymap_items:
            if not kmi.properties:
                continue
            if 'hash' not in kmi.properties:
                continue

            if kmi.properties['hash'] == kmi_hash:
                return kmi


def register_hotkey(
    bl_idname, hotkey_kwargs, *, key_cat='Window', space_type='EMPTY', op_kwargs={}
):
    """This function inserts a 'hash' into the created KeyMapItems' properties,
    so they can be compared to each other, and duplicates can be avoided."""

    wm = bpy.context.window_manager
    addon_keyconfig = wm.keyconfigs.addon
    if not addon_keyconfig:
        # This happens when running Blender in background mode.
        return

    # We limit the hash to a few digits, otherwise it errors when trying to store it.
    kmi_hash = (
        hash(json.dumps([bl_idname, hotkey_kwargs, key_cat, space_type, op_kwargs]))
        % 1000000
    )

    # If it already exists, don't create it again.
    for (
        existing_kmi_hash,
        existing_kmi_tup,
    ) in bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.items():
        existing_addon_kc, existing_addon_km, existing_kmi = existing_kmi_tup
        if kmi_hash == existing_kmi_hash:
            # The hash we just calculated matches one that is in storage.
            user_kc = wm.keyconfigs.user
            user_km = user_kc.keymaps.get(existing_addon_km.name)
            # NOTE: It's possible on Reload Scripts that some KeyMapItems remain in storage,
            # but are unregistered by Blender for no reason.
            # I noticed this particularly in the Weight Paint keymap.
            # So it's not enough to check if a KMI with a hash is in storage, we also need to check if a corresponding user KMI exists.
            user_kmi = CLOUDRIG_PT_hotkeys_panel.find_kmi_in_km_by_hash(
                user_km, kmi_hash
            )
            if user_kmi:
                # print("Hotkey already exists, skipping: ", existing_kmi.name, existing_kmi.to_string(), kmi_hash)
                return

    # print("Registering hotkey: ", bl_idname, hotkey_kwargs, key_cat)

    addon_keymaps = addon_keyconfig.keymaps
    addon_km = addon_keymaps.get(key_cat)
    if not addon_km:
        addon_km = addon_keymaps.new(name=key_cat, space_type=space_type)

    addon_kmi = addon_km.keymap_items.new(bl_idname, **hotkey_kwargs)
    for key in op_kwargs:
        value = op_kwargs[key]
        setattr(addon_kmi.properties, key, value)

    addon_kmi.properties['hash'] = kmi_hash

    bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items[kmi_hash] = (
        addon_keyconfig,
        addon_km,
        addon_kmi,
    )
    # print("CloudRig: Registered Hotkey: ", addon_kmi.idname, addon_kmi.to_string(), kmi_hash)


#######################################
############## Register ###############
#######################################

classes = (
    CloudRig_RigPreferences,
    CloudRigBoneCollection,
    CLOUDRIG_UL_collections,
    CLOUDRIG_PT_settings,
    CLOUDRIG_PT_hotkeys_panel,
    CLOUDRIG_PT_collections_sidebar,
    CLOUDRIG_PT_collections_filter,
    CLOUDRIG_MT_collections_specials,
    CLOUDRIG_MT_collections_quick_select,
    POST_OT_cloudrig_switch_parent_bake,
    POSE_OT_cloudrig_snap_bake,
    POSE_OT_cloudrig_toggle_ikfk_bake,
    POSE_OT_cloudrig_keyframe_all_settings,
    POSE_OT_cloudrig_reset,
    POSE_OT_cloudrig_collections_reveal_all,
    POSE_OT_cloudrig_collection_select,
    POSE_OT_cloudrig_collection_parent_set,
    POSE_OT_cloudrig_collection_delete,
    POSE_OT_cloudrig_collection_add,
    POSE_OT_cloudrig_collection_reorder,
    CLOUDRIG_OT_reorder_collections,
    POSE_OT_cloudrig_collection_assign,
    POSE_OT_cloudrig_collection_clipboard_copy,
    POSE_OT_cloudrig_collection_clipboard_paste,
)


def is_registered(cls):
    """Returns whether a BPy class is registered.
    May not always work, needs more testing..."""
    if issubclass(cls, Operator):
        category, op_name = cls.bl_idname.split(".")
        if hasattr(bpy.ops, category):
            category = getattr(bpy.ops, category)
            return op_name in dir(category)
    if hasattr(bpy.types, cls.__name__):
        bl_type = getattr(bpy.types, cls.__name__)
        if bl_type and hasattr(bl_type, 'is_registered'):
            return bl_type.is_registered
        return bl_type
    return False


def register():
    """Runs on rig generation, add-on registration, or when this file is executed
    via the text editor.
    Should be able to run without errors even if things are already registered.
    """

    for c in classes:
        if not is_registered(c):
            # This if statement is important to avoid re-registering UI panels,
            # which would cause them to lose their sub-panels. (They would become top-level.)
            register_class(c)

    bpy.types.Object.cloudrig_prefs = PointerProperty(
        type=CloudRig_RigPreferences, override={'LIBRARY_OVERRIDABLE'}
    )

    bpy.types.BoneCollection.cloudrig_info = PointerProperty(
        type=CloudRigBoneCollection, override={'LIBRARY_OVERRIDABLE'}
    )

    # Inject our custom Bone Collections panel.
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
    if hasattr(bpy.types, 'CLOUDRIG_PT_hotkeys_panel'):
        for (
            kmi_hash,
            kmi_tup,
        ) in bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.items():
            kc, km, kmi = kmi_tup
            km.keymap_items.remove(kmi)
        bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items = {}
    print("CloudRig: Unregistered Hotkeys.")


def unregister():
    """Runs before register() on generation and when executed from the text editor.
    Should be able to run without errors even before there's anything to unregister.
    """

    # This would also unregister add-on hotkeys.
    # unregister_hotkeys()

    for c in classes:
        reg = is_registered(c)
        if reg:
            try:
                unregister_class(c)
            except RuntimeError as e:
                print("Failed to unregister ", c.__name__, str(e))
                pass
        else:
            print("Class was not registered ", c.__name__)

    try:
        # Un-inject our collection UI override.
        bpy.types.DATA_PT_bone_collections.poll = (
            bpy.types.DATA_PT_bone_collections.poll_bkp
        )
    except:
        pass


if (
    __name__ in ['__main__', 'builtins', 'CloudRig.generation.cloudrig']
    or '.generation.cloudrig' in __name__
):
    # __name__ == `__main__` when executed in Blender's Text Editor.
    # __name__ == `builtins` when executed by cloud_generator.
    # __name__ == `CloudRig.generation.cloudrig` when executed by Blender add-on registration.
    # unregister()
    register()
