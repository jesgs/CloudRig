# SPDX-FileCopyrightText: 2021-2022 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import PoseBone
from bpy.utils import flip_name

from ..utils.external.misc import property_to_python
from ..generation.cloudrig import CloudRigOperator


class POSE_OT_cloudrig_symmetrize_components(CloudRigOperator):
    """Mirror rig component type and parameters of selected bones to the opposite side. Names should end in L/R"""

    bl_idname = "pose.cloudrig_symmetrize_components"
    bl_label = "Symmetrize Components"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            cls.poll_message_set("An active armature must be in pose mode.")
            return False
        sel_bones = context.selected_pose_bones
        if not sel_bones:
            cls.poll_message_set("At least one bone must be selected.")
            return False
        for pb in sel_bones:
            mirrored_name = flip_name(pb.name)
            if mirrored_name != pb.name and mirrored_name in obj.pose.bones:
                return True
        return False

    def execute(self, context):
        rig = context.object

        num_mirrored = 0

        # First make sure that all selected bones can be mirrored unambiguously.
        for pb in context.selected_pose_bones:
            flip_bone = rig.pose.bones.get(flip_name(pb.name))
            if not flip_bone:
                # Bones without an opposite will just be ignored.
                continue
            if flip_bone != pb and flip_bone.bone.select:
                self.report(
                    {'ERROR'},
                    f"Bone {pb.name} selected on both sides, mirroring would be ambiguous, "
                    f"aborting. Only select the left or right side, not both!",
                )
                return {'CANCELLED'}

        # Then mirror the parameters.
        for pb in context.selected_pose_bones:
            flip_bone = rig.pose.bones.get(flip_name(pb.name))
            if flip_bone == pb or not flip_bone:
                # Bones without an opposite will just be ignored.
                continue

            num_mirrored += copy_cloudrig_component(
                pb, flip_bone, match_type=False, x_mirror=True
            )

        self.report({'INFO'}, f"Mirrored parameters of {num_mirrored} bones.")

        return {'FINISHED'}


class POSE_OT_cloudrig_copy_component(CloudRigOperator):
    """Copy rig component type parameters from active to selected bones"""

    bl_idname = "pose.cloudrig_copy_component"
    bl_label = "Copy Component to Selected"
    bl_options = {'REGISTER', 'UNDO'}

    match_type: bpy.props.BoolProperty(
        name="Match Type",
        description="Only mirror components to selected bones which have the same component "
        "type as the active bone",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            return False

        active = context.active_pose_bone
        if not active or not active.cloudrig_component.component_type:
            return False

        select = context.selected_pose_bones
        if len(select) < 2 or active not in select:
            return False

        return True

    def execute(self, context):
        active_bone = context.active_pose_bone

        num_copied = 0
        for pb in context.selected_pose_bones:
            if pb == active_bone:
                continue
            num_copied += copy_cloudrig_component(
                active_bone, pb, match_type=self.match_type
            )

        self.report(
            {'INFO'},
            f"Copied {active_bone.cloudrig_component.component_type} parameters to {num_copied} bones.",
        )

        return {'FINISHED'}


def copy_cloudrig_component(
    from_bone: PoseBone,
    to_bone: PoseBone,
    *,
    match_type=False,
    x_mirror=False,
) -> bool:
    tgt_component_type = to_bone.cloudrig_component.component_type
    src_component_type = from_bone.cloudrig_component.component_type

    if match_type and tgt_component_type != src_component_type:
        return False
    else:
        tgt_component_type = to_bone.cloudrig_component.component_type = (
            src_component_type
        )


    if 'cloudrig_component' in from_bone:
        param_dict = from_bone['cloudrig_component'].to_dict()#.get('cloudrig_component')
        if x_mirror:
            to_bone['cloudrig_component'] = recursive_mirror(param_dict)
        else:
            to_bone['cloudrig_component'] = param_dict
    else:
        try:
            del to_bone['cloudrig_component']
        except KeyError:
            pass
    return True


def recursive_mirror(value):
    """Mirror strings(.L/.R) in any mixed structure of dictionaries/lists."""

    if isinstance(value, dict):
        return {key: recursive_mirror(val) for key, val in value.items()}

    elif isinstance(value, list):
        return [recursive_mirror(elem) for elem in value]

    elif isinstance(value, str):
        return flip_name(value)

    else:
        return value


def draw_copy_mirror_ops(self, context):
    layout = self.layout
    if context.mode == 'POSE':
        layout.separator()
        op = layout.operator(
            POSE_OT_cloudrig_copy_component.bl_idname,
            icon='DUPLICATE',
            text="Copy Only Parameters",
        )
        op.match_type = True
        op = layout.operator(
            POSE_OT_cloudrig_copy_component.bl_idname,
            icon='DUPLICATE',
            text="Copy Type & Parameters",
        )
        op.match_type = False
        layout.operator(
            POSE_OT_cloudrig_symmetrize_components.bl_idname,
            icon='MOD_MIRROR',
            text="Mirror Type & Parameters",
        )


# =============================================
# Registration

registry = [POSE_OT_cloudrig_symmetrize_components, POSE_OT_cloudrig_copy_component]
