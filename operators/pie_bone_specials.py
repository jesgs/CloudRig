# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from .pie_bone_parenting import GenericBoneOperator
from bpy.types import Menu, EditBone, PoseBone, Object, Operator
from ..bs_utils.hotkeys import register_hotkey
from ..utils.rig import get_current_rigs


class POSE_OT_delete_bones(GenericBoneOperator, Operator):
    """Delete selected bones"""

    bl_idname = "pose.delete_selected"
    bl_label = "Delete Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        eb.hide = False
        remove_drivers_of_bone(rig, eb.name)
        eb.id_data.edit_bones.remove(eb)
        return True

    def execute(self, context):
        rigs = get_current_rigs(context)
        mirror_states = {}
        for rig in rigs:
            mirror_states[rig] = rig.data.use_mirror_x
        affected = self.affect_bones(context)
        for rig in rigs:
            rig.use_mirror_x = mirror_states[rig]
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Deleted {len(affected)} bone{plural}.")
        return {'FINISHED'}


class POSE_OT_dissolve_bones(Operator):
    """Dissolve selected bones"""

    bl_idname = "pose.dissolve_selected"
    bl_label = "Dissolve Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != 'ARMATURE':
            cls.poll_message_set("Select an Armature.")
            return False
        if context.active_object.mode not in ('POSE', 'EDIT'):
            cls.poll_message_set("Must be in Edit/Pose mode.")
            return False
        if context.active_object.mode == 'EDIT':
            bones = [eb for eb in context.active_object.data.edit_bones if eb.select_head or eb.select_tail]
        else:
            bones = [pb.bone for pb in context.selected_pose_bones]
        if not can_dissolve_any(bones):
            cls.poll_message_set("No selected bone has connected children or parents")
            return False

        return True

    def execute(self, context):
        rig = context.active_object
        org_mode = rig.mode
        if rig.mode == 'POSE':
            bone_names = [b.name for b in context.selected_pose_bones]
            bpy.ops.object.mode_set(mode='EDIT')
            for bone_name in bone_names:
                rig.data.edit_bones[bone_name].hide = False
                rig.data.edit_bones[bone_name].select = True
        
        bpy.ops.armature.dissolve()
        if org_mode != 'EDIT':
            bpy.ops.object.mode_set(mode=org_mode)
        return {'FINISHED'}

def can_dissolve_any(bones: list[EditBone or PoseBone]) -> bool:
    any_connected_children = lambda bone: any((child.use_connect for child in bone.children))
    has_connected_parent = lambda bone: bone.parent and bone.use_connect
    return any((has_connected_parent(bone) or any_connected_children(bone) for bone in bones))

def remove_drivers_of_bone(
    rig: Object,
    bone_name: str,
):
    datablocks = []

    if rig.animation_data:
        datablocks.append(rig)
    if rig.data.animation_data:
        datablocks.append(rig.data)

    for db in datablocks:
        for fc in db.animation_data.drivers[:]:
            if f'.bones["{bone_name}"]' in fc.data_path:
                db.animation_data.drivers.remove(fc)


class CLOUDRIG_MT_PIE_bone_specials(Menu):
    bl_label = "Bone Specials"

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object
        pie = layout.menu_pie()

        # 1) < Symmetrize Rigging
        pie.operator(
            'pose.symmetrize_rigging',
            text="Symmetrize",
            icon='MOD_MIRROR',
        )

        # 2) > Delete Bones (With Symmetry)
        text_del = "Delete"
        if rig.data.use_mirror_x:
            text_del = "Delete (Symmetrized)"
        pie.operator(
            'pose.delete_selected',
            text=text_del,
            icon='X',
        )

        # 3) V Leave empty.
        pie.separator()

        # 4) ^ Leave empty.
        pie.separator()

        # 5) <^ Toggle Armature Symmetry.
        pie.prop(
            rig.data,
            'use_mirror_x',
            toggle=True,
            icon='MOD_MIRROR',
            text="Armature X-Mirror",
        )

        # 6) ^> Dissolve Bones.
        text_dissolve = "Dissolve"
        if rig.data.use_mirror_x:
            text_dissolve = "Dissolve (Symmetrized)"
        pie.operator(
            'pose.dissolve_selected',
            text=text_dissolve,
            icon='X',
        )

        # 7) <v Toggle Pose Symmetry.
        if rig.pose:
            pie.prop(
                rig.pose,
                'use_mirror_x',
                toggle=True,
                icon='MOD_MIRROR',
                text="Pose X-Mirror",
            )
        else:
            pie.separator()

        # 8) v> Leave empty.
        pie.separator()


registry = [
    POSE_OT_delete_bones,
    POSE_OT_dissolve_bones,
    CLOUDRIG_MT_PIE_bone_specials,
]


def register():
    for keymap_name in ('Pose', 'Weight Paint', 'Armature'):
        register_hotkey(
            'wm.call_menu_pie',
            hotkey_kwargs={'type': "X", 'value': "PRESS"},
            keymap_name=keymap_name,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_bone_specials'},
        )
