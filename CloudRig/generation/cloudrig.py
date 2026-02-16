# SPDX-License-Identifier: GPL-3.0-or-later

"""
This file is loaded into a self-executing text datablock and attached to all
CloudRig rigs.
It's responsible for drawing the CloudRig panel in the 3D View's Sidebar.
"""

import ast
import contextlib
import importlib
import json
import re
import sys
from collections import OrderedDict, defaultdict
from typing import Any

import bpy
from bl_ui.generic_ui_list import draw_ui_list
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import (
    ID,
    Bone,
    BoneCollection,
    EditBone,
    Menu,
    Object,
    Operator,
    Panel,
    PoseBone,
    PropertyGroup,
    UILayout,
    UIList,
    bpy_struct,
)
from bpy.utils import register_class, unregister_class
from mathutils import Matrix, Vector
from rna_prop_ui import rna_idprop_value_item_type

cloudrig_installed = False
submodule = next((m for m in sys.modules if m.endswith('generation.cloudrig')), None)
if submodule:
    cloudrig_installed = True
    cr_module_name = ".".join(submodule.split(".")[:-2])
    icons = importlib.import_module(cr_module_name + ".icons")
    hotkeys = importlib.import_module(cr_module_name + ".bs_utils.hotkeys")

#######################################
############ Context Checks ###########
#######################################

def active_rig(context) -> Object | None:
    """Return the active rig even if we're in weight paint mode."""
    rig = context.pose_object or context.active_object
    if not rig:
        return
    if rig.type == 'ARMATURE':
        return rig

def is_active_cloudrig(context) -> Object | bool:
    """If the active object is a cloudrig, return it."""
    if not hasattr(context, 'pose_object'):
        # Can happen when a file is saved with the UI open,
        # and that UI is trying to draw during file open, when context isn't
        # initialized yet.
        return False
    rig = active_rig(context)
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
    return is_cloud_metarig(active_rig(context))


def is_cloud_metarig(obj: Object) -> bool:
    return (
        obj
        and obj.type == 'ARMATURE'
        and hasattr(obj, 'cloudrig')
        and obj.cloudrig.enabled
    )


def find_metarig_of_rig(context, rig: Object) -> Object | None:
    if not hasattr(rig, 'cloudrig'):
        # If the CloudRig add-on is not installed, this function won't work.
        return

    # First, scan the scene for any armatures that reference this rig.
    for obj in context.scene.objects:
        if obj.type != 'ARMATURE':
            continue
        if obj.cloudrig.generator.target_rig == rig:
            return obj

    # If that failed, try to find it by name as a last resort.
    for prefix in {'RIG-', 'FAILED-RIG-'}:
        if rig.name.startswith(prefix):
            metarig = (
                context.scene.objects.get(rig.name.replace(prefix, "META-")) or
                context.scene.objects.get(rig.name.replace(prefix, ""))
            )
            if metarig and metarig.type != 'ARMATURE':
                metarig = None

            if (
                metarig
                and hasattr(metarig, 'cloudrig')
                and metarig.cloudrig.generator.target_rig
                and metarig.cloudrig.generator.target_rig != rig
                and metarig.cloudrig.generator.target_rig != metarig
            ):
                # Edge cases:
                # The names match, but this metarig is targetting another rig.
                # The names match, but this "metarig" is targetting itself. This should never happen.
                # In this case, don't match the metarig.
                metarig = None

            if metarig:
                return metarig


def find_cloudrig(
    context, *, allow_metarigs=True, filter_func: callable = None
) -> Object | None:
    """Find the CloudRig Metarig or Target Rig most relevant to the current context.
    For example, if the active object is a mesh which is deformed by a generated rig,
    return that generated rig.
    """

    def is_good_rig(rig):
        return rig and (
            is_generated_cloudrig(rig) or (allow_metarigs and is_cloud_metarig(rig))
        )

    if not filter_func:
        filter_func = is_good_rig

    active = context.active_object
    if filter_func(active):
        return active

    if active and active.parent and filter_func(active.parent):
        return active.parent

    pose_ob = context.pose_object
    if filter_func(pose_ob):
        return pose_ob

    if active and active.type == 'MESH':
        return get_cloudrig_of_mesh(active)[0]


def get_cloudrig_of_mesh(meshob: Object) -> tuple[Object | None, str | None]:
    """If this mesh is being deformed by a CloudRig rig, return it, and the name of the modifier."""
    return get_deforming_armature(meshob, is_generated_cloudrig)


def get_deforming_armature(meshob: Object, filter_func=lambda o: True):
    for m in meshob.modifiers:
        if m.type == 'ARMATURE' and m.object and (filter_func(m.object)):
            return m.object, m.name
    return None, None


def poll_cloudrig_operator(operator, context, modes={}, **kwargs):
    if modes and context.mode not in modes:
        operator.poll_message_set(f"Must be in mode: {modes}")
        return False
    rig = find_cloudrig(context, **kwargs)
    if not rig:
        operator.poll_message_set(
            "Could not find a CloudRig metarig or generated rig in this context."
        )
        return False
    return rig


#######################################
########## Snapping & Baking ##########
#######################################

class SnappingOpMixin:
    bone_names: StringProperty(
        name="Bone Names",
        description="A Python string list of bone names in hierarchical order.",
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
        rig = poll_cloudrig_operator(cls, context, modes={'POSE'})
        if not rig:
            return False
        return True

    def invoke(self, context, event):
        self.init(context)

    def init(self, context):
        self.rig = find_cloudrig(context)
        self.initial_prop_value = self.prop_value
        self._target_prop_value = 1.0 if self.prop_value < 1.0 else 0.0

    def set_target_prop_value(self, key=False, options={'INSERTKEY_AVAILABLE'}):
        self.prop_pbone[self.prop_id] = self._target_prop_value
        if key:
            self.key_target_prop_value(options)

    def key_target_prop_value(self, options={'INSERTKEY_AVAILABLE'}):
        self.prop_pbone.keyframe_insert(f'["{self.prop_id}"]', group=self.prop_pbone.name, keytype='GENERATED', options=options)

    @property
    def prop_pbone(self) -> PoseBone:
        # Return the PoseBone holding the custom property that will be toggled.
        pbone = self.rig.pose.bones.get(self.prop_bone)
        if not pbone:
            raise Exception(f"Bone not found in rig: `{self.prop_bone}`.")
        return pbone

    @property
    def prop_value(self) -> float:
        # Return the current value of the custom property that will be toggled.
        if self.prop_id not in self.prop_pbone:
            raise ValueError(
                f"Property `{self.prop_id}` not found in bone `{self.prop_bone}`."
            )
        return self.prop_pbone[self.prop_id]

    def get_affected_pbones(self) -> set[PoseBone]:
        affected_pbones = set()
        for bone_name in ast.literal_eval(self.bone_names):
            pb = self.rig.pose.bones.get(bone_name)
            if pb:
                affected_pbones.add(pb)
            else:
                raise ValueError(f"Bone `{bone_name}` not found.")
        return affected_pbones

    def key_bones_single_frame(
        self, context, pbone_matrix_map: OrderedDict[PoseBone, Matrix], options=set()
    ):
        for pbone, mat in pbone_matrix_map.items():
            pbone.matrix = mat.copy()
            context.view_layer.update()
            pbone.matrix = mat.copy()

            key_transforms(pbone, options)

def get_pbone_matrix_map(
    bones_to_snap: list[PoseBone], snap_to_bones: list[PoseBone] = []
) -> OrderedDict[PoseBone, Matrix]:
    if not snap_to_bones:
        snap_to_bones = bones_to_snap
    assert len(bones_to_snap) == len(snap_to_bones)
    return OrderedDict(
        [
            (snapped_bone, snap_target.matrix.copy())
            for snapped_bone, snap_target in zip(bones_to_snap, snap_to_bones)
        ]
    )

def set_bone_selection(rig, select=False, pbones: list[PoseBone] = None, extend=False):
    if select and not extend:
        set_bone_selection(rig, False)
    if not pbones:
        pbones = rig.pose.bones
    last = None
    for pb in pbones:
        pb.select = select
        if select:
            last = pb
    if last and select:
        rig.data.bones.active = last.bone

def key_transforms(pb: PoseBone, options={'INSERTKEY_AVAILABLE'}):
    if pb.rotation_mode == 'QUATERNION':
        props = ['rotation_quaternion']
    elif pb.rotation_mode == 'AXIS_ANGLE':
        props = ['rotation_axis_angle']
    else:
        props = ['rotation_euler']

    props += ['location', 'scale']

    for prop in props:
        pb.keyframe_insert(prop, keytype='GENERATED', options=options)

def reveal_bones(bones: list[Bone | EditBone | PoseBone]):
    for bone in bones:
        reveal_bone(bone)

def reveal_bone(bone: Bone | EditBone | PoseBone):
    ensure_visible_bone_collection(bone)
    bone.hide = False

def ensure_visible_bone_collection(bone: Bone | EditBone | PoseBone):
    """If target bone not in any enabled collections, enable first one."""
    if isinstance(bone, PoseBone):
        bone = bone.bone

    armature = bone.id_data
    collections = armature.collections

    if len(bone.collections) == 0:
        return

    if not any([coll.is_visible_effectively for coll in bone.collections]):
        coll = bone.collections[0]
        while coll:
            if collections.is_solo_active:
                coll.is_solo = True
            else:
                coll.is_visible = True
            coll = coll.parent

class SnapBakeOpMixin(SnappingOpMixin):
    do_bake: BoolProperty(name="Bake", default=False)

    def nudge_end(self, context):
        if self.frame_start >= self.frame_end:
            self.frame_end = self.frame_start + 1
    def nudge_start(self, context):
        if self.frame_start >= self.frame_end:
            self.frame_start = self.frame_end - 1
    frame_start: IntProperty(name="First Frame", default=-999, update=nudge_end)
    frame_end: IntProperty(name="Last Frame", default=-999, update=nudge_start)

    key_before_start: BoolProperty(
        name="Key Before First",
        description="Insert a keyframe of the original values one frame before the bake range. This is to avoid undesired interpolation towards the bake",
    )
    key_after_end: BoolProperty(
        name="Key After Last",
        description="Insert a keyframe of the original values one frame after the bake range. This is to avoid undesired interpolation after the bake",
    )

    def invoke(self, context, event):
        super().invoke(context, event)
        # If the op wasn't run before, initialize with scene's frame range.
        if self.frame_start == -999:
            self.frame_start = context.scene.frame_start
        if self.frame_end == -999:
            self.frame_end = context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout

        self.draw_affected_bones(layout.box())

        box = layout.box()
        box.prop(self, 'do_bake')
        col = box.column()
        if self.do_bake:
            time_row = col.row(align=True)
            time_row.prop(self, 'frame_start')
            time_row.prop(self, 'frame_end')
            fix_row = col.row(align=True)
            fix_row.prop(self, 'key_before_start')
            fix_row.prop(self, 'key_after_end')

    def draw_affected_bones(self, layout):
        affected_pbones = self.get_affected_pbones()
        self.draw_bones(layout, {pb:None for pb in affected_pbones})

    def draw_bones(self, layout, bone_map: dict[PoseBone, PoseBone | None]):
        col = layout.column(align=True)
        row = col.row()
        row.label(text="Snapped bones:")
        if bone_map:
            row.enabled = False
            pb = list(bone_map.keys())[0]
            row.prop(pb, 'name', text="", icon='BONE_DATA')
            return

        for from_pb, to_pb in bone_map.items():
            split = col.row().split(align=True, factor=0.45)
            split.enabled = False
            row = split.row()
            row.prop(from_pb, 'name', text="", icon='BONE_DATA')
            if to_pb:
                split = split.row().split(factor=0.08)
                split.row().label(text="\u279C")
                split.row().prop(to_pb, 'name', text="", icon='BONE_DATA')
            else:
                # When there's no target, this helps align the bone selectors.
                split.row()

    def get_frame_range(self, context) -> list[int]:
        if not self.do_bake:
            return [context.scene.frame_current]

        return list(range(self.frame_start, self.frame_end + 1))

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
            context.scene.frame_set(frame_number)
            context.view_layer.update()

            frame_matrix_map[frame_number] = get_pbone_matrix_map(bones_to_snap, snap_to_bones)

        return frame_matrix_map

    def key_bones_across_frames(
        self,
        context,
        rig: Object,
        frame_matrix_map: OrderedDict[int, OrderedDict[PoseBone, Matrix]],
    ):
        affected_pbones = list(list(frame_matrix_map.values())[0].keys())

        # Deselect all bones, then reveal and select affected bones.
        set_bone_selection(rig, True, affected_pbones, extend=False)

        frame_numbers = list(frame_matrix_map.keys())

        # Avoid undesired interpolation before/after the bake range.
        def key_all_on_frame(frame: int):
            context.scene.frame_set(frame)
            self.key_target_prop_value()
            for pb in affected_pbones:
                key_transforms(pb, options=set())
        if self.key_before_start:
            # Key original value and transforms one frame before the selected bake range.
            key_all_on_frame(frame_numbers[0] - 1)
        if self.key_after_end:
            # Key original value and transforms one frame after the selected bake range.
            key_all_on_frame(frame_numbers[-1] + 1)

        for frame_number, pbone_matrix_map in frame_matrix_map.items():
            context.scene.frame_set(frame_number)
            # Change & key property value.
            self.set_target_prop_value(key=True)
            # Pose & key the bones.
            self.key_bones_single_frame(context, pbone_matrix_map, options=set())

class POSE_OT_cloudrig_snap_bake(SnapBakeOpMixin, Operator):
    "Invert property value while preserving the transforms of affected bones."
    bl_idname = 'pose.cloudrig_snap_bake'
    bl_label = "Snap & Bake Bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        if not hasattr(self, 'rig'):
            self.init(context)
        return self.execute_bone_snap_bake(context)

    def execute_bone_snap_bake(self, context) -> set:
        rig = find_cloudrig(context)
        if not rig:
            return {'CANCELLED'}
        try:
            affected_pbones = self.get_affected_pbones()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        active_frame_bkp = context.scene.frame_current

        # Save the matrix of each bone at each frame.
        frame_matrix_map = self.map_frames_to_bone_matrices(context, affected_pbones)

        if self.do_bake:
            self.key_bones_across_frames(context, rig, frame_matrix_map)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Store (copies!) of world matrices.
        pbone_matrix_map = list(frame_matrix_map.values())[0]

        # Reveal & select (only) affected bones.
        set_bone_selection(rig, True, affected_pbones, extend=False)

        # Set & key property value.
        self.set_target_prop_value(key=True)

        # Restore (and key if needed) world matrices.
        self.key_bones_single_frame(context, pbone_matrix_map)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

class POSE_OT_cloudrig_switch_parent_bake(POSE_OT_cloudrig_snap_bake, Operator):
    "Change the parent while preserving the world-matrix of the children."
    # This operator's implementation is so simple because it does nothing more
    # than base Snap&Bake other than using an Enum selector for the property value.

    bl_idname = 'pose.cloudrig_switch_parent_bake'
    bl_label = "Switch Parents & Preserve Transforms"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    parent_names: StringProperty(name="Parent UI Names")
    parent_bones: StringProperty(name="Parent Bone Names", default="[]")

    def parent_items(self, context):
        ui_names = ast.literal_eval(self.parent_names)
        bone_names = ast.literal_eval(self.parent_bones)
        if not bone_names:
            bone_names = [""] * len(ui_names)
        items = [(str(i), ui_name, bone_name) for i, (ui_name, bone_name) in enumerate(zip(ui_names, bone_names))]
        return items

    selected: EnumProperty(name="Selected Parent", items=parent_items)

    def draw(self, context):
        row = self.layout.row()
        row.prop(self, 'selected', text='Parent')
        rig = find_cloudrig(context)
        if rig:
            parent_bone_name = self.parent_items(context)[int(self.selected)][2]
            parent_pbone = rig.pose.bones.get(parent_bone_name)
            if parent_pbone:
                row = row.row()
                row.enabled = False
                row.prop(parent_pbone, 'name', text="", icon='BONE_DATA')
        super().draw(context)

    def execute(self, context):
        if not hasattr(self, 'rig'):
            self.init(context)
        self._target_prop_value = int(self.selected)
        return super().execute(context)

class POSE_OT_cloudrig_toggle_ikfk_bake(SnapBakeOpMixin, Operator):
    "Switch between IK <-> FK modes."

    bl_idname = 'pose.cloudrig_toggle_ikfk_bake'
    bl_label = "Snap & Bake"
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
    ik_first: StringProperty(
        description="Name of the first bone in the IK chain. Necessary for IK pole snapping logic"
    )
    fk_first: StringProperty(
        description="Name of the first bone in the FK chain. Necessary for IK pole snapping logic"
    )

    @property
    def pole_pbone(self):
        return self.rig.pose.bones[self.ik_pole]

    @property
    def bone_map(self) -> OrderedDict[PoseBone, PoseBone]:
        if not hasattr(self, '_bone_map'):
            fk_to_ik_names = ast.literal_eval(self.map_fk_to_ik)
            ik_to_fk_names = ast.literal_eval(self.map_ik_to_fk)

            self.fk_to_ik = OrderedDict([(self.rig.pose.bones[k], self.rig.pose.bones[v]) for k, v in fk_to_ik_names])
            self.ik_to_fk = OrderedDict([(self.rig.pose.bones[k], self.rig.pose.bones[v]) for k, v in ik_to_fk_names])

            self._bone_map = self.fk_to_ik if self._target_prop_value == 0 else self.ik_to_fk
            self._other_bone_map = self.fk_to_ik if self._target_prop_value == 1 else self.ik_to_fk
        return self._bone_map

    ####################################
    ### Inherited functions

    def invoke(self, context, _event):
        self.init(context)
        return super().invoke(context, _event)

    def execute(self, context):
        if not hasattr(self, 'rig'):
            self.init(context)
        rig = find_cloudrig(context)
        active_frame_bkp = context.scene.frame_current

        # Store (copies!) of world matrices.
        bones_to_snap = list(self.bone_map.keys())
        snap_to_bones = list(self.bone_map.values())

        # Insert keys on the bones which define the current pose, in case user
        # has moved them but hasn't keyed them.
        for pb in list(self._other_bone_map.keys()):
            context.view_layer.update()
            key_transforms(pb)

        # Store bone matrices.
        frame_matrix_map = self.map_frames_to_bone_matrices(
            context, bones_to_snap, snap_to_bones
        )

        self.ik_last = bones_to_snap[0]
        if self.do_bake:
            self.key_bones_across_frames(context, rig, frame_matrix_map)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Set & key property value.
        self.set_target_prop_value(key=True)

        # Deselect all bones.
        set_bone_selection(self.rig, False)

        pbone_matrix_map = list(frame_matrix_map.values())[0]
        # Restore world matrices.
        self.key_bones_single_frame(context, pbone_matrix_map)

        # Reveal & select affected bones.
        affected_pbones = self.get_affected_pbones()
        reveal_bones(affected_pbones)
        set_bone_selection(self.rig, True, affected_pbones, extend=False)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def get_affected_pbones(self) -> set[PoseBone]:
        affected_pbones = set(self.bone_map.keys())
        if self._target_prop_value == 1.0:
            affected_pbones.add(self.pole_pbone)
        return affected_pbones

    def key_bones_single_frame(
        self, context, pbone_matrix_map: OrderedDict[PoseBone, Matrix], options={'INSERTKEY_AVAILABLE'}
    ):
        super().key_bones_single_frame(context, pbone_matrix_map, options=options)
        if self._target_prop_value == 1:
            ik_first = context.active_object.pose.bones.get(self.ik_first)
            if ik_first and (3.0 - sum(ik_first.scale)) < 0.3:
                ik_first.scale = (1.0, 1.0, 1.0)
            if self.ik_pole:
                self.snap_pole_target()
                key_transforms(self.pole_pbone)

    def snap_pole_target(self):
        """Snap the pole target based on the first IK bone.
        This needs to run after the IK wrist control had already been snapped.
        This can have perfect results as long as you ensure:
            - IK chain lies flat on a plane (Else, Generator Log warns you.)
            - FK and IK rolls match perfectly. (Generator makes sure.)
            - FK elbow has Y/Z rotation locked. (See "fk_chain.limit_elbow_axes" param.)
        """

        fk_first = self.rig.pose.bones[self.fk_first]
        fk_second = list(self.fk_to_ik.keys())[1]
        _pole_angle_deg, _elbow_dir, pole_loc = calculate_ik_pole_vector(fk_first, fk_second)

        self.pole_pbone.matrix.translation = pole_loc

    def draw_affected_bones(self, layout):
        bone_map = self.bone_map.copy()
        if self._target_prop_value == 1.0:
            bone_map[self.pole_pbone] = None
        self.draw_bones(layout, bone_map)

    ### End of inherited functions
    ####################################


def calculate_ik_pole_vector(
    meta_first: PoseBone | Bone | EditBone,
    meta_second: PoseBone | Bone | EditBone
) -> tuple[float, Vector, Vector]:
    """Based on the first two bones of a chain,
    return some data useful in creating an IK pole target:
        float ik_angle: Best angle (in degrees) for the IK constraint's pole_angle param.
        Vector pole_direction: Normalized direction of the elbow.
        Vector pole_location: Final location of the pole target in object space.
    """

    if isinstance(meta_second, Bone):
        first_head = meta_first.head_local
        first_tail = meta_first.tail_local
        second_head = meta_second.head_local
        second_tail = meta_second.tail_local
    elif hasattr(meta_second, 'head'):
        first_head = meta_first.head
        first_tail = meta_first.tail
        second_head = meta_second.head
        second_tail = meta_second.tail
    else:
        raise TypeError(f"This is not a bone of any kind: {meta_second}, ({type(meta_second)})")

    chain_vector = second_tail - first_head
    x_axis = meta_first.x_axis.normalized()
    z_axis = meta_first.z_axis.normalized()

    # Calculate the distances of the four points to the tail of the last bone.
    # These four points are in the four directions of the bone around the bone's tail.
    x_pos_distance = ((second_head + x_axis) - second_tail).length
    x_neg_distance = ((second_head - x_axis) - second_tail).length

    z_pos_distance = ((second_head + z_axis) - second_tail).length
    z_neg_distance = ((second_head - z_axis) - second_tail).length

    # Store those distances in a dictionary where they are matched with a
    # tuple describing (the main axis of rotation, IK constraint pole_angle),
    # that should be used, when that distance is the lowest.
    axis_dict = {
        x_pos_distance: ("-Z", 180),
        x_neg_distance: ("+Z", 0),
        z_pos_distance: ("+X", -90),
        z_neg_distance: ("-X", 90),
    }

    # Find the tuple to use by picking the one corresponding to the lowest distance.
    lowest_distance = axis_dict[min(list(axis_dict.keys()))]
    pole_angle_deg = lowest_distance[1]

    # On a line that goes from the start to the end of the chain, find the nearest point
    # to the elbow.
    closest = closest_point_on_line(first_head, second_tail, first_tail)
    # Then shoot towards the elbow by the length of that line (that's fairly arbitrary)
    # to find the pole vector position.
    # NOTE: This requires that all the bone rolls are aligned to point towards this point.
    # This can be achieved with the "Flatten IK Chain" operator.
    elbow_vec = (first_tail-closest)
    elbow_direction = elbow_vec.normalized()
    pole_location = closest + elbow_vec + elbow_direction*chain_vector.length

    return pole_angle_deg, elbow_direction, pole_location


def closest_point_on_line(
        line_start: Vector,
        line_end: Vector,
        point: Vector,
        clamp_to_segment: bool = False
    ) -> Vector:
    line_direction = line_end - line_start
    vector_to_point = point - line_start

    line_length_squared = line_direction.dot(line_direction)
    if line_length_squared == 0.0:
        # Degenerate line (start == end)
        return line_start.copy(), 0.0

    factor = vector_to_point.dot(line_direction) / line_length_squared

    if clamp_to_segment:
        factor = max(0.0, min(1.0, factor))

    closest_point = line_start + line_direction * factor
    return closest_point


#######################################
######## Convenience Operators ########
#######################################


class POSE_OT_cloudrig_keyframe_all_settings(Operator):
    """Keyframe all properties shown in the UI below"""

    bl_idname = 'pose.cloudrig_keyframe_all_settings'
    bl_label = "Keyframe CloudRig Settings"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        rig = poll_cloudrig_operator(cls, context, allow_metarigs=False)
        if not rig:
            return False
        if 'ui_data' not in rig.data:
            cls.poll_message_set("CloudRig armature lacks any UI data.")
            return False
        return True

    def execute(self, context):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return

        props_to_key: list[tuple[ID | PoseBone, str]] = []

        def add_props_to_key_recursive(ui_data: OrderedDict | list):
            if hasattr(ui_data, 'items'):
                elem_list = [data for _name, data in ui_data.items()]
            elif type(ui_data) is list:
                elem_list = ui_data

            for elem_data in elem_list:
                if type(elem_data) is str:
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

                    if type(owner) is BoneCollection:
                        # Let's not keyframe bone visibilities.
                        continue

                    prop_name = elem_data['prop_name']
                    props_to_key.append((owner, prop_name))

                add_props_to_key_recursive(elem_data)

        add_props_to_key_recursive(ui_data)

        for prop_owner, prop_name in props_to_key:
            try:
                prop_owner.keyframe_insert(prop_name, group=prop_owner.name, keytype='GENERATED')
            except TypeError:
                # Happens if property is not animatable.
                pass

        return {'FINISHED'}


class POSE_OT_armature_reset(Operator):
    """Reset all bone transforms and custom properties to their default values"""

    bl_idname = 'pose.armature_reset'
    bl_label = "Reset Armature"
    bl_options = {'REGISTER', 'UNDO'}

    reset_action: BoolProperty(
        name="Unassign Action", default=False, description="Un-assign Action"
    )
    reset_viewport_display: BoolProperty(
        name="Viewport Settings", default=False, description="Reset 'Show Name', 'Show Axes', 'In Front' object properties"
    )
    reset_bone_visibility: BoolProperty(
        name="Unhide Bones", default=False, description="Unhide all bones"
    )

    selection_only: BoolProperty(
        name="Selected Only",
        default=False,
        description="Affect selected bones rather than all bones",
    )
    reset_transforms: BoolProperty(
        name="Transforms", default=True, description="Reset bone transforms"
    )
    reset_custom_props: BoolProperty(
        name="Custom Properties", default=True, description="Reset custom properties"
    )

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        rig = find_cloudrig(context)
        layout = self.layout.column(align=True)
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text="Object Properties")
        if rig.animation_data and rig.animation_data.action:
            layout.prop(self, 'reset_action')
        if any((pb.hide or pb.bone.hide for pb in rig.pose.bones)):
            layout.prop(self, 'reset_bone_visibility')
        layout.prop(self, 'reset_viewport_display')
        layout.separator()
        layout.label(text="Bone Properties")
        if context.selected_pose_bones:
            layout.prop(self, 'selection_only')
        layout.prop(self, 'reset_transforms')
        layout.prop(self, 'reset_custom_props')

    def execute(self, context):
        rig = find_cloudrig(context)

        reset_armature(
            rig,
            viewport_display=self.reset_viewport_display,
            bone_visibility=self.reset_bone_visibility,
            action=self.reset_action,
            transforms=self.reset_transforms,
            custom_props=self.reset_custom_props,
            pose_bones=context.selected_pose_bones if self.selection_only else rig.pose.bones,
        )

        return {'FINISHED'}


def reset_armature(rig, *, viewport_display=False, bone_visibility=False, action=False, transforms=True, custom_props=True, pose_bones=[]):
    if viewport_display:
        rig.show_name = False
        rig.show_axis = False
        rig.show_in_front = False

    if not pose_bones:
        pose_bones = rig.pose.bones

    if action:
        if rig.animation_data:
            rig.animation_data.action = None

    for pbone in pose_bones:
        if bone_visibility:
            pbone.hide = False
            pbone.bone.hide = False

        if transforms:
            pbone.location = (0, 0, 0)
            pbone.rotation_euler = (0, 0, 0)
            pbone.rotation_quaternion = (1, 0, 0, 0)
            pbone.scale = (1, 1, 1)

        if not custom_props or len(pbone.keys()) == 0:
            continue

        rna_properties = [
            prop.identifier for prop in pbone.bl_rna.properties if prop.is_runtime
        ]

        # Reset custom property values to their defaults.
        for key in pbone.keys():
            if key.startswith("$"):
                continue
            if key in rna_properties:
                continue  # Addon defined property.

            property_settings = None
            try:
                property_settings = pbone.id_properties_ui(key)
                if not property_settings:
                    continue
                property_settings = property_settings.as_dict()
                if 'default' not in property_settings:
                    continue
            except TypeError:
                # Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
                pass

            if not property_settings:
                continue

            value_type, _is_array = rna_idprop_value_item_type(pbone[key])

            if value_type not in (float, int, bool):
                continue
            pbone[key] = property_settings['default']

@bpy.app.handlers.persistent
def auto_override_rig_data(_=None):
    # On file load, if a CloudRig rig object is overridden, make sure its data is also overridden.
    # Otherwise, Bone Collection visibility changes will not be saved with the file.
    for rig in [ob for ob in bpy.context.scene.objects if is_generated_cloudrig(ob)]:
        if rig.override_library and not rig.data.override_library:
            rig.data.override_create(remap_local_usages=True)


#######################################
########### Dynamic Rig UI ############
#######################################


def should_ui_be_enabled(context) -> bool:
    """Used for disabling UI drawing for performance optimization."""
    rig = find_cloudrig(context)
    if not rig:
        return False
    return not (
        rig.cloudrig_prefs.hide_during_transform and
        is_modal_transform_running(context)
    )


def is_modal_transform_running(context) -> bool:
    """Returns whether any transform operator is running."""
    for m in context.window.modal_operators:
        if m.bl_idname.startswith('TRANSFORM_OT_'):
            return True
    return False

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

        rig = find_cloudrig(context)
        if not rig:
            return

        if not should_ui_be_enabled(context):
            layout.label(text="UI disabled for posing performance.", icon='INFO')
            return

        rig, ui_data = get_rig_and_ui(context)

        layout.operator(
            POSE_OT_cloudrig_keyframe_all_settings.bl_idname,
            text='Keyframe All Settings',
            icon='KEYFRAME_HLT',
        )
        layout.operator(POSE_OT_armature_reset.bl_idname, icon='LOOP_BACK')
        layout.prop(rig.cloudrig_prefs, 'hide_during_transform')
        if hasattr(rig, 'cloudrig') and rig.cloudrig.enabled:
            # If CloudRig add-on is enabled, and this is a metarig.
            layout.separator()
            layout.prop(rig.cloudrig, 'ui_edit_mode', icon='GREASEPENCIL')
            if rig.cloudrig.ui_edit_mode:
                if hasattr(bpy.ops.pose, 'cloudrig_add_property_to_ui'):
                    layout.operator('pose.cloudrig_add_property_to_ui', icon='ADD')

        if ui_data:
            for panel_name, panel_data in ui_data.items():
                if panel_name == "":
                    layout.separator()
                    for label_name, label_data in panel_data.items():
                        if type(label_data) is str:
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
                    full_name = "CLOUDRIG_PT_custom_" + sane_name.lower().replace(
                        " ", ""
                    )
                    header, body = layout.panel(full_name)
                    self.draw_panel_header(context, header, panel_name)
                    if body:
                        self.draw_panel_contents(context, body, panel_name)

    def draw_panel_header(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return
        panel_data = ui_data[panel_name]

        draw_drag_operator(rig, ui_data, panel_data, panel_name, [], layout)

        layout.label(text=panel_name)

    def draw_panel_contents(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return

        panel_data = ui_data.get(panel_name)
        if panel_data:
            """Panel data contains a list of tuples.
            The first entry of each tuple is a string telling us the type of UI element to draw.
            The second entry is the for drawiong the element. Can be str, list, or dict, depending on the type.
            """
            for label_name, label_data in panel_data.items():
                if type(label_data) is str:
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
                if type(value) is dict:
                    # We also want to convert regular dicts to OrderedDict,
                    # especially because they might contain tuple-lists.
                    value = [(k, v) for k, v in value.items()]
                if type(value) is list:
                    value = tuples_to_dict(value)

            ordered_dict[key] = value
        return ordered_dict

    if 'ui_data' not in obj.data:
        return OrderedDict()
    ui_data = obj.data['ui_data'].to_dict()
    if 'panels' not in ui_data:
        return OrderedDict()
    panels = ui_data['panels']
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

    # We need to figure out and pass the parent value string for the edit button.
    parent_value = ""
    if 'children' in ui_path and ui_path[-2] == 'children':
        parent_value = ui_path[-1]

    ui_path += [label_name]

    for row_name, row_data in label_data.items():
        if type(row_data) is str:
            # It's a flag, not a UI element.
            continue
        column = layout
        sub_row = column.row(align=True)
        draw_drag_operator(rig, label_data, row_data, row_name, ui_path, sub_row)
        sub_row.separator()

        for slider_name, slider_data in row_data.items():
            if type(slider_data) is str:
                # It's a flag, not a UI element.
                continue
            if slider_data.get('owner_path') is None:
                # Currently, all UI elements must have a property, and therefore a path to the property owner.
                # Note though that this path is allowed to be an empty string.
                continue
            texts = slider_data.get('texts', [])
            if texts:
                if texts.startswith("["):
                    texts = ast.literal_eval(texts)
                else:
                    texts = [t.strip() for t in texts]
            draw_slider(
                rig=rig,
                column=column,
                sub_row=sub_row,
                ###
                owner_path=slider_data.get('owner_path'),
                prop_name=slider_data.get('prop_name'),
                ###
                ui_path=ui_path + [row_name, slider_name],
                panel_name=panel_name,
                label_name=label_name,
                row_name=row_name,
                slider_name=slider_name,
                ###
                texts=texts,
                icon_true=slider_data.get('icon_true', 'CHECKBOX_HLT'),
                icon_false=slider_data.get('icon_false', 'CHECKBOX_DEHLT'),
                use_expand_enum=bool(slider_data.get('use_expand_enum', False)),
                use_slider=bool(slider_data.get('use_slider', True)),
                operator=slider_data.get('operator'),
                op_icon=slider_data.get('op_icon'),
                op_kwargs=slider_data.get('op_kwargs'),
                children=slider_data.get('children'),
                parent_value=parent_value,
            )


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
    icon_true='CHECKBOX_HLT',
    icon_false='CHECKBOX_DEHLT',
    use_expand_enum=False,
    use_slider=True,
    ###
    texts=[],
    operator="",
    op_icon='BLANK1',
    op_kwargs={},
    ###
    children={},
    parent_value="",
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

    bracketless_prop_name = unquote_custom_prop_name(prop_name)
    prop_value = None
    if not owner:
        sub_row.alert = True
        sub_row.label(
            text="Missing property owner: '{owner_path}' for property '{prop_name}'.".format(owner_path=owner_path, prop_name=prop_name),
            icon='ERROR',
        )
    elif supports_custom_props(owner) and bracketless_prop_name in owner:
        prop_value = owner[bracketless_prop_name]
    else:
        try:
            prop_value = owner.path_resolve(prop_name)
        except ValueError:
            sub_row.alert = True
            sub_row.label(
                text="Missing property '{prop_name}' of owner '{owner_path}'.".format(owner_path=owner_path, prop_name=prop_name),
                icon='ERROR',
            )

    if not sub_row.alert:
        draw_property(
            layout=sub_row,
            prop_owner=owner,
            prop_name=prop_name,
            slider_name=slider_name,
            icon_true=icon_true,
            icon_false=icon_false,
            use_expand_enum=use_expand_enum,
            use_slider=use_slider,
            texts=texts,
        )
        if operator:
            draw_operator(
                rig, sub_row, bl_idname=operator, op_icon=op_icon, op_kwargs=op_kwargs
            )

        prop_value_str = str(prop_value)
        if children:
            box_col = None
            for comma_separated_values, child_data in children.items():
                prop_values_as_str = [
                    v.strip() for v in comma_separated_values.split(",")
                ]
                if prop_value_str in prop_values_as_str:
                    for child_label_name, child_label_data in child_data.items():
                        if not box_col:
                            box_col = column.box().column()
                        draw_rig_settings_per_label(
                            layout=box_col,
                            rig=rig,
                            ui_path=ui_path + ['children', comma_separated_values],
                            panel_name=panel_name,
                            panel_data=child_data,
                            label_name=child_label_name,
                            label_data=child_label_data,
                        )

    if is_ui_edit_mode(rig):
        if not sub_row.alert:
            if type(prop_value) in {int, bool}:
                child_op = sub_row.operator(
                    'pose.cloudrig_add_child_property_to_ui', icon='ADD', text=""
                )
                child_op.parent_value = prop_value_str
                child_op.parent_ui_path = json.dumps(ui_path)
                if type(owner) is PoseBone:
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
                # XXX: This doesn't work when the rig isn't the active object. We would need to pass context to check.
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
            edit_op.parent_value = parent_value or ""
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
        if icon_true != 'CHECKBOX_HLT':
            edit_op.icon_true = icon_true
        if icon_false != 'CHECKBOX_DEHLT':
            edit_op.icon_false = icon_false
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
    use_expand_enum=True,
    use_slider=True,
    texts=[],
):
    if not hasattr(prop_owner, 'path_resolve'):
        print("cloudrig.py: Cannot resolve path from: ", prop_owner)
        return
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
        if value_type is bool:
            icon = (icon_true if prop_value else icon_false) or 'BLANK1'
            layout.prop(prop_owner, prop_name, toggle=True, text=slider_name, icon=icon)
        elif value_type in {int, float}:
            if bracketless_prop_name != prop_name:
                # If this is a custom property.

                # Property is a float/int/color
                # For large ranges, a slider doesn't make sense.
                try:
                    if bracketless_prop_name in prop_owner:
                        prop_owner.id_properties_ui(bracketless_prop_name).as_dict()
                except TypeError:
                    # This happens for Python properties. There's no point drawing them.
                    return
                layout.prop(prop_owner, prop_name, slider=use_slider, text=slider_name)
            else:
                layout.prop(prop_owner, prop_name, text=slider_name)
    elif value_type is str:
        if (
            issubclass(type(prop_owner), bpy.types.Constraint)
            and prop_name == 'subtarget'
            and prop_owner.target
            and prop_owner.target.type == 'ARMATURE'
        ):
            # Special case for nice constraint sub-target selectors.
            layout.prop_search(prop_owner, prop_name, prop_owner.target.pose, 'bones')
        elif isinstance(prop_owner.bl_rna.properties.get(prop_name), bpy.types.EnumProperty):
            enum_layout = layout
            if slider_name.strip() != "" and use_expand_enum:
                split = layout.split(factor=0.4)
                split.label(text=slider_name)
                enum_layout = split.row()
            enum_layout.prop(prop_owner, prop_name, expand=use_expand_enum, text=slider_name.strip() or prop_name)
        else:
            layout.prop(prop_owner, prop_name)
    else:
        layout.prop(prop_owner, prop_name, text=slider_name)


def draw_operator(
    obj: Object,
    layout: UILayout,
    bl_idname: str,
    op_icon='BLANK1',
    op_kwargs={},
    text="",
):
    if not op_icon or op_icon == 'NONE':
        op_icon = 'BLANK1'
    if op_exists(bl_idname):
        op_props = layout.operator(bl_idname, text=text, icon=op_icon)
    elif is_ui_edit_mode(obj):
        layout.alert=True
        layout.label(text="Missing Operator", icon='ERROR')
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
    sub_elements = [elem for key, elem in parent_ui_data.items() if type(elem) is not str]
    if len(sub_elements) > 1 and is_ui_edit_mode(rig):
        is_dragged = ui_data.get('is_dragged', False)
        icon = 'TRACKER'
        icon_value = 0
        if is_dragged:
            icon = 'VIEW_PAN'
            icon_value = 0
        elif cloudrig_installed:
            icon = 'NONE'
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


def op_exists(bl_idname) -> bool:
    """Whether an operator with the given bl_idname is registered."""
    parts = bl_idname.split(".")
    op = bpy.ops
    for part in parts:
        if hasattr(op, part):
            op = getattr(op, part)
        else:
            return False
    return True


def feed_op_props(op_props, op_kwargs: str or dict or list):
    """Set the arguments of an OperatorProperties instance, such as one returned by
    `UILayout.operator()`.
    """

    if type(op_kwargs) is str:
        op_kwargs = ast.literal_eval(op_kwargs)
    if type(op_kwargs) is dict:
        op_kwargs = [(key, value) for key, value in op_kwargs.items()]

    # Pass on any paramteres to the operator that it will accept.
    for key, value in op_kwargs:
        if hasattr(op_props, key):
            desired_type = type(getattr(op_props, key))
            # Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
            if type(value) in {list, dict}:
                value = json.dumps(value)
            if type(value) is not desired_type:
                # Since we store operator kwargs as a string, we need to convert them back to their int/float/bool representation.
                if type(value) is str and desired_type is bool and value == "False":
                    # The case of a False bool needs a bit of special treatment, since bool("False") == True
                    value = False
                else:
                    value = desired_type(value)
            setattr(op_props, key, value)


def unquote_custom_prop_name(prop_name: str) -> str:
    if prop_name.startswith('["') or prop_name.startswith("['"):
        return prop_name[2:-2]
    return prop_name


def supports_custom_props(thing: Any) -> bool:
    try:
        thing.keys()
        return True
    except (TypeError, AttributeError):
        return False

#######################################
########### Rig Preferences ###########
#######################################


class CloudRig_RigPreferences(PropertyGroup):
    hide_during_transform: BoolProperty(
        name="Hide UI During Transformations",
        description="Drawing this UI can be expensive depending on rig complexity. This option can alleviate that by disabling drawing during transformations. However, this can cause the scrollbar to reset to the top due to transformations.",
        default=True,
    )
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
        name="Solo",
        description="Show the Solo operator",
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

    collection_filter: StringProperty(
        name="Collection Filter",
        description="Search collections by name (case-sensitive)",
        update=update_collection_filter,
        options={'LIBRARY_EDITABLE', 'TEXTEDIT_UPDATE'},
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

    @property
    def collection(self) -> BoneCollection:
        armature = self.id_data
        for coll in armature.collections_all:
            if coll.cloudrig_info == self:
                return coll
        assert False

    def update_name(self, context):
        """Runs when trying to change the name of this instance, which should stay in sync
        with the collection it's masking."""

        rig = context.object
        coll = self.collection

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

        def cleanup_garbage_bone_sets(component):
            # Clean up old bone set data.
            for bone_set_name in list(component.params.bone_sets.keys()):
                if not hasattr(component.params.bone_sets, bone_set_name):
                    del component.params.bone_sets[bone_set_name]
            for bone_set_name in list(component.ui_bone_sets.keys()):
                if not hasattr(component.params.bone_sets, bone_set_name):
                    entry_idx = component.ui_bone_sets.find(bone_set_name)
                    component.ui_bone_sets.remove(entry_idx)
            if not component.active_bone_set:
                component.bone_sets_active_index = 0

        # Metarig: Update bone sets with this collection assigned to refer to the new name.
        if is_active_cloud_metarig(context):
            rig = active_rig(context)
            for pb in rig.pose.bones:
                comp = pb.cloudrig_component
                if not comp or not comp.component_type:
                    continue
                cleanup_garbage_bone_sets(comp)
                for bone_set_name in list(comp.params.bone_sets.keys()):
                    bone_set = getattr(comp.params.bone_sets, bone_set_name)
                    for bone_set_coll in bone_set.collections:
                        if bone_set_coll.name == coll.name:
                            bone_set_coll.name = self.name
                            break

        # Fix any references to this collection in the UI data.
        if cloudrig_installed:
            post_gen = importlib.import_module(cr_module_name + ".utils.post_gen")
            post_gen.replace_in_ui_data(rig, f'collections_all["{coll.name}"]', f'collections_all["{self.name}"]')


        # Set the actual collection's name to be in sync.
        coll.name = self.name

    name: StringProperty(
        name="Name",
        description="Name of this Bone Collection",
        update=update_name,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    is_dragged: BoolProperty(
        name="Is Dragged",
        description="Internal. Flag to mark that this collection is currently dragged by the reorder operator. Used to change the icon",
        default=False,
    )

    @property
    def are_parents_visible(self) -> bool:
        parent = self.parent_collection
        if not parent:
            return True

        while parent:
            if not parent.is_visible:
                return False
            parent = parent.cloudrig_info.parent_collection

        return True

    @property
    def parent_collection(self) -> BoneCollection:
        return self.collection.parent

    @parent_collection.setter
    def parent_collection(self, coll: BoneCollection):
        self.collection.parent = coll

    def unfold_parents(self):
        for parent in self.parents_recursive:
            parent.is_expanded = True

    # We need to mask the is_expanded flag so we can set selection state
    # when is_expanded is toggled.
    def update_is_expanded(self, context):
        coll = self.collection
        coll.is_expanded = self.is_expanded
        rig = find_cloudrig(context)
        rig.cloudrig_prefs.active_collection_index = rig.data.collections_all.find(self.name)
        if rig:
            rig.cloudrig_prefs.active_collection_index = coll.index

    is_expanded: BoolProperty(
        name="Is Expanded",
        description="Whether to show the children of this collection",
        default=False,
        update=update_is_expanded,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def siblings(self):
        """Includes self!"""
        if not self.parent_collection:
            all_colls = self.id_data.collections_all
            return [
                coll for coll in all_colls if not coll.cloudrig_info.parent_collection
            ]
        return self.parent_collection.children

    @property
    def children_recursive(self) -> list[BoneCollection]:
        all_children = self.collection.children[:]
        for child in all_children:
            all_children += child.children
        return all_children

    @property
    def parents_recursive(self) -> list[BoneCollection]:
        parents = []
        parent = self.parent_collection
        while parent:
            parents.append(parent)
            parent = parent.cloudrig_info.parent_collection
        return parents

    quick_access: BoolProperty(
        name="Quick Access",
        description="Toggle whether this collection should appear in the quick access list",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def are_parents_unfolded(self) -> bool:
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
        rig = find_cloudrig(context)
        prefs = rig.cloudrig_prefs
        pbones = rig.pose.bones

        main_row = layout.row(align=True)
        if collection.parent:
            split = main_row.split(factor=0.02 * cloudrig_info.hierarchy_depth)
            split.row()
            row = split.row(align=True)
            main_row = row.row(align=True)

        if collection.children:
            icon = 'DOWNARROW_HLT' if collection.is_expanded else 'RIGHTARROW'
            main_row.prop(
                collection.cloudrig_info,
                'is_expanded',
                text="",
                icon=icon,
                emboss=False,
            )
        else:
            main_row.label(text="", icon='BLANK1')

        if prefs.show_local_overrides and collection.is_local_override:
            main_row.prop(
                cloudrig_info,
                'name',
                text="",
                icon='LIBRARY_DATA_OVERRIDE',
                emboss=False,
            )
        else:
            main_row.prop(cloudrig_info, 'name', text="", emboss=False)

        if context.mode != 'EDIT_ARMATURE':
            # Collections.bones is not available in the PyAPI in Edit Mode for some reason.
            direct_selected_bones = [
                bone
                for bone in collection.bones
                if not pbones[bone.name].hide
                and any([c.is_visible for c in bone.collections])
                and pbones[bone.name].select
            ]
            indirect_bones = collection.bones_recursive
            indirect_visible_bones = [
                b
                for b in indirect_bones
                if not pbones[b.name].hide and any([c.is_visible for c in b.collections])
            ]
            indirect_selected_bones = [bone for bone in indirect_visible_bones if pbones[bone.name].select]

            if direct_selected_bones:
                main_row.label(text="", icon='LAYER_ACTIVE')
            elif indirect_selected_bones:
                main_row.label(text="", icon='LAYER_USED')

            if prefs.show_bone_count:
                main_row.label(
                    text=f"{len(indirect_selected_bones)}/{len(indirect_bones)}",
                    icon='BONE_DATA',
                )

        vis_row = main_row.row(align=True)
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
        if prefs.show_solo:
            icon = 'SOLO_ON' if collection.is_solo else 'SOLO_OFF'
            vis_row.prop(collection, 'is_solo', text="", icon=icon)
        if prefs.show_editing:
            vis_row.separator()

            icon = 'RADIOBUT_ON' if cloudrig_info.quick_access else 'RADIOBUT_OFF'
            vis_row.prop(cloudrig_info, 'quick_access', text="", icon=icon)
            metarig = find_metarig_of_rig(context, context.active_object)
            if is_active_cloudrig(context) and metarig:
                icon = (
                    'FAKE_USER_ON'
                    if cloudrig_info.preserve_on_regenerate
                    else 'FAKE_USER_OFF'
                )
                vis_row.prop(cloudrig_info, 'preserve_on_regenerate', text="", icon=icon)

            if collection.is_editable:
                icon = 'TRACKER'
                if collection.cloudrig_info.is_dragged:
                    icon = 'VIEW_PAN'
                vis_row.operator(
                    POSE_OT_cloudrig_reorder_collections.bl_idname, text="", icon=icon
                ).collection_name = collection.name

        return vis_row

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
        rig = find_cloudrig(context)
        layout.prop(rig.cloudrig_prefs, "collection_filter", text="")

    @staticmethod
    def get_visual_collection_order(rig, filtered=False) -> list[BoneCollection]:
        """Return the collections of the rig in the order they are currently to be displayed in the UIList.
        If filtered, only include those collections in the list which aren't being filtered, eg. by collapsing parents, or search.
        """

        # Find collections without any parent
        all_collections = rig.data.collections_all
        root_colls = [coll for coll in all_collections if not coll.parent]
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.children:
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
            filter_map = {coll: flt_flags[i] for i, coll in enumerate(all_collections)}
            # Allow collections that contain any collections that match the filter.
            for i, coll in enumerate(all_collections):
                if any([filter_map[child] for child in get_coll_children_recursive(coll)]):
                    flt_flags[i] = 1073741824

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


def get_coll_children_recursive(coll: BoneCollection) -> list[BoneCollection]:
    children = []
    for child in coll.children:
        children.append(child)
        children += get_coll_children_recursive(child)
    return children

def draw_cloudrig_collections(self, context, rig: Object):
    layout = self.layout
    layout.use_property_split = True
    layout.use_property_decorate = False

    # Figure out property path to the Bone Collection list in this context,
    # considering that this function should work in a number of cases
    # where the rig is not the active object.
    rig_of_mesh, modifier_name = get_cloudrig_of_mesh(context.active_object)
    if context.active_object == rig:
        context_path_to_rig = 'active_object'
    elif modifier_name:
        context_path_to_rig = f'active_object.modifiers["{modifier_name}"].object'
    elif context.active_object.parent == rig:
        context_path_to_rig = 'active_object.parent'
    else:
        layout.label(text="No rig found in context.")
        return

    list_col = draw_ui_list(
        layout,
        context,
        class_name='CLOUDRIG_UL_collections',
        list_path=context_path_to_rig + ".data.collections_all",
        active_index_path=context_path_to_rig + '.cloudrig_prefs.active_collection_index',
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

    row = layout.row()
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
    sel_op.extend_selection = True

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
        if not should_ui_be_enabled(context):
            return False
        return find_cloudrig(context)

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
        row.prop(prefs, 'show_select', text="", icon='MOUSE_LMB')

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
        rig = find_cloudrig(context)
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
        local = "Local " if rig.override_library else ""
        layout.operator(
            POSE_OT_cloudrig_collection_delete.bl_idname,
            text="Delete All {local}Collections".format(local=local),
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


class POSE_OT_cloudrig_collections_reveal_all(Operator):
    """Reveal all collections"""

    bl_idname = "pose.cloudrig_collections_reveal_all"
    bl_label = "Show All Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = find_cloudrig(context)
        for coll in rig.data.collections_all:
            coll.is_visible = True
            coll.is_solo = False

        return {'FINISHED'}


@contextlib.contextmanager
def object_mode(rig, mode='OBJECT'):
    if rig.mode == mode:
        yield

    else:
        mode_bkp = rig.mode
        bpy.ops.object.mode_set(mode=mode)
        yield
        bpy.ops.object.mode_set(mode=mode_bkp)


class POSE_OT_cloudrig_collection_select(Operator):
    "Select all bones in this Bone Collection.\n\n" "Shift: Extend selection.\n" "Ctrl: Mirror selection.\n" "Alt: Deselect"

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
    def description(cls, context, props):
        if not props.select:
            return "Deselect the bones of this collection"

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(
            cls, context, modes={'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}
        )

    def invoke(self, context, event):
        if not self.extend_selection:
            self.extend_selection = event.shift
        if self.select:
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

        with object_mode(rig, mode='POSE'):
            if not self.extend_selection and self.select:
                for pbone in rig.pose.bones:
                    pbone.select = False

            for bone in collection.bones_recursive:
                pbone = rig.pose.bones[bone.name]
                if not self.reveal_bones and (pbone.hide or not any((coll.is_visible_effectively for coll in bone.collections))):
                    continue
                if self.flip:
                    pbone = rig.pose.bones.get(bpy.utils.flip_name(bone.name))
                    if not pbone:
                        continue
                if self.reveal_bones and self.select:
                    pbone.hide = False
                pbone.select = self.select

        return {'FINISHED'}


def poll_cloudrig_operator_collection(operator, context):
    rig = poll_cloudrig_operator(operator, context)
    if not rig:
        return False
    active_coll = rig.data.collections.active
    if not active_coll:
        operator.poll_message_set("No active operator.")
        return False
    if not active_coll.is_editable:
        operator.poll_message_set("Cannot delete linked collection.")
        return False
    return True


class POSE_OT_cloudrig_collection_delete(Operator):
    "Remove the active Bone Collection.\n" "Shift: Delete whole hierarchy" ""

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
        rig = poll_cloudrig_operator_collection(cls, context)
        if not rig:
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
            self.delete_hierarchy(rig)
            self.report(
                {'INFO'}, "Deleted editable bone collections of selected hierarchy."
            )

        self.set_visual_active_index(rig, visual_index)

        return {'FINISHED'}

    @staticmethod
    def get_visual_active_index(rig) -> int:
        """Get the index of the active collection as it is in the current UIList.
        Eg., if the active collection is the 3rd one that is drawn, this will return 2.
        """
        sorted_collections = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        return sorted_collections.index(rig.data.collections.active)

    def set_visual_active_index(self, rig, index):
        """Set the index of the active collection as they appear in the UIList.
        Eg., if index==2, the 3rd collection from the top of the list will become active.
        """
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
        """Try to delete the active Bone Collection, and return success state."""
        coll = rig.data.collections.active
        if not coll:
            self.report({'ERROR'}, "There is no active collection.")
            return False
        if not coll.is_editable:
            self.report({'ERROR'}, "Cannot delete linked collection.")
            return False

        coll_name = coll.name
        rig.data.collections.remove(coll)
        self.report({'INFO'}, "Deleted active collection: '{coll_name}'".format(coll_name=coll_name))
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


class POSE_OT_cloudrig_collection_add(Operator):
    """Add a new Bone Collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Add Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def execute(self, context):
        rig = find_cloudrig(context)
        if rig.data.override_library:
            rig.data.override_library.is_system_override = False
        colls = rig.data.collections
        all_colls = rig.data.collections_all
        active_coll = colls.active
        active_idx = colls.active_index

        coll = colls.new(name="Collection")
        coll.parent = active_coll.parent if active_coll else None
        coll_idx = all_colls.find(coll.name)
        colls.move(coll_idx, active_idx + 1)

        coll.cloudrig_info.unfold_parents()
        rig.cloudrig_prefs.active_collection_index = all_colls.find(coll.name)

        return {'FINISHED'}


class POSE_OT_cloudrig_reorder_collections(Operator):
    "Rearrange and re-parent this collection with the arrow keys, WASD, or by " "moving the mouse.\n\n" "Left-click/Enter: Confirm.\n" "Right-click/Esc: Cancel.\n" "Up/Down: Move Collection up/down.\n" "Left/Right: Unparent/Parent collection to the one above"

    bl_idname = "pose.cloudrig_reorder_collections"
    bl_label = "Reorder Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    collection_name: StringProperty()

    def invoke(self, context, event):
        self.mouse_anchor_y = event.mouse_y
        self.mouse_anchor_x = event.mouse_x
        self.index_offset = 0

        rig = find_cloudrig(context)
        self.collection = rig.data.collections_all.get(self.collection_name)
        if not self.collection:
            return {'CANCELLED'}
        self.initial_parent = self.collection.parent
        self.collection.cloudrig_info.is_dragged = True
        rig.cloudrig_prefs.active_collection_index = self.initial_index = (
            self.collection.index
        )

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rig = find_cloudrig(context)
        self.index_offset = 0
        if (
            event.type in {'W', 'UP_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = -1
        elif (
            event.type in {'S', 'DOWN_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = 1
        elif event.type == 'MOUSEMOVE':
            self.index_offset = int((event.mouse_y - self.mouse_anchor_y) / -20)
            if int((event.mouse_x - self.mouse_anchor_x) / 20) > 0:
                self.parent_active_coll_to_prev_sibling(rig)
                self.mouse_anchor_x = event.mouse_x
            elif int((event.mouse_x - self.mouse_anchor_x) / -20) > 0:
                self.unparent_active_coll_by_one(rig)
                self.mouse_anchor_x = event.mouse_x
        elif event.type in {'LEFTMOUSE', 'NUMPAD_ENTER', 'RET'}:
            self.collection.cloudrig_info.is_dragged = False
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.collection.cloudrig_info.is_dragged = False
            self.collection.parent = self.initial_parent
            rig.data.collections.move(self.collection.index, self.initial_index)
            rig.cloudrig_prefs.active_collection_index = self.collection.index
            return {'CANCELLED'}
        elif (
            event.type in {'RIGHT_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.parent_active_coll_to_prev_sibling(rig)
        elif (
            event.type in {'LEFT_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.unparent_active_coll_by_one(rig)

        if self.index_offset != 0:
            ret = self.move_active_coll_up_down(rig, self.index_offset)
            if ret == {'FINISHED'}:
                self.mouse_anchor_y = event.mouse_y

        return {'RUNNING_MODAL'}

    def unparent_active_coll_by_one(self, rig):
        active_coll = rig.data.collections.active
        if not active_coll.parent:
            return {'CANCELLED'}
        old_parent = active_coll.parent

        old_parent.is_expanded = False
        active_coll.parent = old_parent.parent
        rig.data.collections.move(active_coll.index, old_parent.index + 1)
        rig.cloudrig_prefs.active_collection_index = active_coll.index

        if active_coll.parent:
            self.report({'INFO'}, f"Parented to '{active_coll.parent.name}'.")
        else:
            self.report({'INFO'}, "Set parent to None.")
        return {'FINISHED'}

    def parent_active_coll_to_prev_sibling(self, rig):
        active_coll = rig.data.collections.active
        prev_sibling = self.get_sibling_of_active_coll(
            rig, index_offset=-1, only_editable=True
        )
        if not prev_sibling:
            return {'CANCELLED'}

        prev_sibling.is_expanded = True
        active_coll.parent = prev_sibling

        rig.cloudrig_prefs.active_collection_index = active_coll.index

        if active_coll.parent:
            self.report({'INFO'}, f"Parented to '{active_coll.parent.name}'.")
        else:
            self.report({'INFO'}, "Set parent to None.")
        return {'FINISHED'}

    def get_sibling_of_active_coll(
        self, rig, *, index_offset=-1, only_editable=False
    ) -> BoneCollection | None:
        visual_order = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        visual_index = POSE_OT_cloudrig_collection_delete.get_visual_active_index(rig)

        while True:
            visual_index += index_offset
            if visual_index < 0 or visual_index > len(visual_order) - 1:
                return None

            other_coll = visual_order[visual_index]
            if only_editable and not other_coll.is_editable:
                continue
            if other_coll.parent == self.collection.parent:
                return other_coll

    def move_active_coll_up_down(self, rig, index_offset=-1):
        active_coll = rig.data.collections.active
        sibling_coll = self.get_sibling_of_active_coll(rig, index_offset=index_offset)
        if not sibling_coll:
            return {'CANCELLED'}

        rig.data.collections.move(active_coll.index, sibling_coll.index)
        rig.cloudrig_prefs.active_collection_index = active_coll.index
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_assign(Operator):
    "Assign selected bones to active collection.\n\n" "Alt: Un-assign.\n" "Shift: To active collection & children.\n" "Shift+Ctrl: To all collections"

    bl_idname = "pose.cloudrig_collection_assign"
    bl_label = "(Un)Assign Bones to Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    assign: BoolProperty(default=True)
    all_collections: BoolProperty(default=False)
    assign_to_children: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        rig = poll_cloudrig_operator(
            cls, context, modes={'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}
        )
        if not rig:
            return False
        if not rig.data.collections.active:
            cls.poll_message_set("No active collection.")
            return False
        return True

    @classmethod
    def description(cls, context, props):
        if not props.assign:
            words = ("Assign", "to") if props.assign else ("Unassign", "from")
            colls = "all collections" if props.all_collections else "active collection"
            return f"{words[0]} selected bones {words[1]} {colls}"

    def invoke(self, context, event):
        if self.assign:
            self.assign = not event.alt
        self.assign_to_children = event.shift
        self.all_collections = event.shift and event.ctrl
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        colls = [rig.data.collections.active]
        if self.assign_to_children:
            colls += rig.data.collections.active.cloudrig_info.children_recursive

        if self.all_collections:
            colls = rig.data.collections_all

        with object_mode(rig, mode='POSE'):
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


class POSE_OT_cloudrig_collection_clipboard_copy(Operator):
    """Copy visible collections to Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_copy"
    bl_label = "Copy Visible Collections To Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def execute(self, context):
        rig = find_cloudrig(context)

        json_obj = defaultdict(dict)
        counter = 0
        for coll in rig.data.collections_all:
            if coll.is_visible:
                counter += 1
                json_obj[coll.name]['bone_names'] = [bone.name for bone in coll.bones]
                json_obj[coll.name]['cloudrig_info'] = dict(coll.cloudrig_info.items())
                json_obj[coll.name]['parent_name'] = coll.parent.name if coll.parent else ""

        if counter == 0:
            self.report({'ERROR'}, "No visible collections to copy.")
            return {'CANCELLED'}

        context.window_manager.clipboard = json.dumps(json_obj)

        self.report({'INFO'}, f"Copied {counter} collections to Blender clipboard.")
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_clipboard_paste(Operator):
    """Paste collections from the Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_paste"
    bl_label = "Paste Collections From Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    overwrite_existing: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

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

                if type(coll_data) is list:
                    # Selection Set.
                    bone_names = coll_data
                    coll.cloudrig_info.quick_access = True
                    coll.cloudrig_info.preserve_on_regenerate = True
                elif type(coll_data) is dict:
                    # CloudRig Collection.
                    cloudrig_info = coll_data['cloudrig_info']
                    bone_names = coll_data['bone_names']

                    for key, value in cloudrig_info.items():
                        setattr(coll.cloudrig_info, key, value)

                for bone_name in bone_names:
                    pb = rig.pose.bones.get(bone_name)
                    if not pb:
                        continue
                    coll.assign(pb)
                counter += 1

            # Iterate over everything again to assign the parents,
            # because collections_all is not in hierarchy order.
            for coll_name, coll_data in json_obj.items():
                coll = collections_all.get(coll_name)
                if 'parent_name' not in coll_data:
                    continue
                parent = collections_all.get(coll_data['parent_name'])
                coll.parent = parent

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


class ARMATURE_OT_bone_collections_popup(Operator):
    """Bone Collections pop-up"""

    bl_idname = "armature.bone_collections_popup"
    bl_label = "Bone Collections"
    # Undo step is omitted, since this is just a UI pop-up.
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context)
        return rig and rig.type == 'ARMATURE' and is_cloud_metarig(rig) or is_generated_cloudrig(rig)

    def invoke(self, context, event):
        rig = find_cloudrig(context)
        rig.cloudrig_prefs.active_collection_index *= 1
        wm = context.window_manager
        return wm.invoke_popup(self, width=400)

    def draw(self, context):
        layout = self.layout

        rig = find_cloudrig(context)

        layout.template_list(
            'CLOUDRIG_UL_collections',
            'Bone Collections Popover List',
            rig.data,
            'collections_all',
            rig.cloudrig_prefs,
            'active_collection_index',
            rows=10 if rig.data.collections_all else 1,
        )

    def execute(self, context):
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

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        if not should_ui_be_enabled(context):
            return False
        return True

    def draw(self, context):
        if bpy.app.version < (5, 0, 0) or not cloudrig_installed:
            self.layout.label(text="Available in Blender 5.0 with CloudRig installed.")
            return
        hotkeys.draw_hotkey_list(context, self.layout, sort_mode='BY_OPERATOR', ignore_missing=True)


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
    POSE_OT_cloudrig_switch_parent_bake,
    POSE_OT_cloudrig_snap_bake,
    POSE_OT_cloudrig_toggle_ikfk_bake,
    POSE_OT_cloudrig_keyframe_all_settings,
    POSE_OT_armature_reset,
    POSE_OT_cloudrig_collections_reveal_all,
    POSE_OT_cloudrig_collection_select,
    POSE_OT_cloudrig_collection_delete,
    POSE_OT_cloudrig_collection_add,
    POSE_OT_cloudrig_reorder_collections,
    POSE_OT_cloudrig_collection_assign,
    POSE_OT_cloudrig_collection_clipboard_copy,
    POSE_OT_cloudrig_collection_clipboard_paste,
    ARMATURE_OT_bone_collections_popup,
)


def is_registered(cls):
    """Returns whether a BPy class is registered.
    May not always work, needs more testing..."""
    # NOTE: For Operators, this is tricky!
    # It will work, but ONLY if you adhere perfectly to Blender's operator class
    # naming conventions!
    # If an operator's bl_idname is `pose.my_operator`, its registered bpy.type will be called
    # `POSE_OT_my_operator`, NO MATTER WHAT THE ACTUAL CLASS NAME YOU DEFINED WAS!
    if hasattr(bpy.types, cls.__name__):
        bl_type = getattr(bpy.types, cls.__name__)
        if bl_type and hasattr(bl_type, 'is_registered') and bl_type.is_registered:
            return bl_type
    if issubclass(cls, bpy.types.PropertyGroup):
        existing = bpy.types.PropertyGroup.bl_rna_get_subclass_py(cls.__name__)
        if existing and existing.is_registered:
            return existing
    if issubclass(cls, bpy.types.AddonPreferences):
        subclasses = bpy.types.AddonPreferences.__subclasses__()
        if cls in subclasses and cls.is_registered:
            return cls

    return False


def register():
    """Runs on rig generation, add-on registration, or when this file is executed
    via the text editor.
    Should be able to run without errors even if things are already registered.
    """

    # It's necessary to call unregister() in case a user
    # opens a .blend file where cloudrig.py is registered, then they try to
    # enable the CloudRig add-on.
    # The unregister() function already needs to be safe, so it can be called
    # even when there's nothing to unregister.
    unregister()

    bpy.app.timers.register(auto_override_rig_data, first_interval=2)
    bpy.app.handlers.load_post.append(auto_override_rig_data)

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

    if cloudrig_installed:
        hotkeys.register_hotkey(
            bl_idname='wm.call_menu',
            hotkey_kwargs={
                'type': 'Q',
                'value': 'PRESS',
                'shift': True,
                'alt': True,
            },
            keymap_name='Pose',
            op_kwargs={'name': CLOUDRIG_MT_collections_quick_select.bl_idname},
        )

        for keymap_name in ('Pose', 'Weight Paint', 'Armature'):
            hotkeys.register_hotkey(
                bl_idname='armature.bone_collections_popup',
                hotkey_kwargs={'type': "M", 'value': "PRESS", 'shift': True},
                keymap_name=keymap_name,
            )


def unregister():
    """Runs before register() on generation and when executed from the text editor.
    Should be able to run without errors even before there's anything to unregister.
    """

    try:
        del bpy.types.Object.cloudrig_prefs
        del bpy.types.BoneCollection.cloudrig_info
    except AttributeError:
        pass

    for c in classes:
        reg = is_registered(c)
        if reg:
            try:
                unregister_class(reg)
            except RuntimeError as e:
                print("Failed to unregister ", c.__name__, str(e))
                pass

    try:
        # Un-inject our collection UI override.
        bpy.types.DATA_PT_bone_collections.draw = (
            bpy.types.DATA_PT_bone_collections.draw_bkp
        )
        del bpy.types.DATA_PT_bone_collections.draw_bkp
    except AttributeError:
        pass


if __name__ in ['__main__', 'builtins']:
    # __name__ == `CloudRig.generation.cloudrig` when executed by Blender python import statement.
    # We don't want to run in this case, since register() will be called explicitly by __init__.py.

    # __name__ == `__main__` when executed in Blender's Text Editor.
    # __name__ == `builtins` when executed by cloud_generator.

    register()
