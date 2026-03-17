# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import Operator
from bpy.utils import flip_name

from ..bs_utils.properties import copy_property_group


class POSE_OT_cloudrig_symmetrize_components(Operator):
    """Mirror rig component type and parameters of selected bones to the opposite side. Names should end in L/R"""

    bl_idname = "pose.cloudrig_symmetrize_components"
    bl_label = "Symmetrize Components"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            cls.poll_message_set("Active armature must be in pose mode.")
            return False
        sel_bones = context.selected_pose_bones
        if not sel_bones:
            cls.poll_message_set("At least one bone must be selected.")
            return False
        for pb in sel_bones:
            mirrored_name = flip_name(pb.name)
            if mirrored_name != pb.name and mirrored_name in obj.pose.bones:
                return True
        cls.poll_message_set("No selected bones have a CloudRig Component assigned. Nothing to symmetrize.")
        return False

    def execute(self, context):
        rig = context.active_object

        num_mirrored = 0

        # First make sure that all selected bones can be mirrored unambiguously.
        for from_pbone in context.selected_pose_bones:
            to_pbone = rig.pose.bones.get(flip_name(from_pbone.name))
            if not to_pbone:
                # Bones without an opposite will just be ignored.
                continue
            if to_pbone != from_pbone and to_pbone.select:
                self.report(
                    {'ERROR'},
                    "Bone {bone} selected on both sides, mirroring would be ambiguous, "
                    "aborting. Only select the left or right side, not both!"
                    .format(bone=from_pbone.name),
                )
                return {'CANCELLED'}

        # Then mirror the parameters.
        for from_pbone in context.selected_pose_bones:
            to_pbone = rig.pose.bones.get(flip_name(from_pbone.name))
            if to_pbone == from_pbone or not to_pbone:
                # Bones without an opposite will just be ignored.
                continue

            copy_property_group(from_pbone.cloudrig_component, to_pbone.cloudrig_component, x_mirror=True)
            num_mirrored += 1

        self.report({'INFO'}, "Mirrored parameters of {num_mirrored} bones.".format(num_mirrored=num_mirrored))

        return {'FINISHED'}


class POSE_OT_cloudrig_copy_component(Operator):
    """Copy rig component type and parameters from active to selected bones"""

    bl_idname = "pose.cloudrig_copy_component"
    bl_label = "Copy Component to Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            cls.poll_message_set("Active armature must be in pose mode.")
            return False

        active = context.active_pose_bone
        if not active or not active.cloudrig_component.component_type:
            cls.poll_message_set("Active bone has no CloudRig Component assigned.")
            return False

        select = context.selected_pose_bones
        if len(select) < 2:
            cls.poll_message_set("At least two bones must be selected.")
            return False

        if active not in select:
            cls.poll_message_set("Make sure the active bone is also selected.")
            return False

        return True

    def execute(self, context):
        from_bone = context.active_pose_bone

        num_copied = 0
        for to_bone in context.selected_pose_bones:
            if to_bone == from_bone:
                continue
            num_copied += 1
            copy_property_group(from_bone.cloudrig_component, to_bone.cloudrig_component, x_mirror=False)

        self.report(
            {'INFO'},
            "Copied {component_type} parameters to {num_copied} bones."
            .format(component_type=from_bone.cloudrig_component.component_type, num_copied=num_copied),
        )

        return {'FINISHED'}



def draw_copy_mirror_ops(self, context):
    layout = self.layout
    if context.mode == 'POSE':
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_copy_component.bl_idname,
            icon='DUPLICATE',
            text="Copy Rig Component",
        )
        layout.operator(
            POSE_OT_cloudrig_symmetrize_components.bl_idname,
            icon='MOD_MIRROR',
            text="Symmetrize Rig Component",
        )


# =============================================
# Registration

registry = [POSE_OT_cloudrig_symmetrize_components, POSE_OT_cloudrig_copy_component]
