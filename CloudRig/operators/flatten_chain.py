# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..utils.rig import ik_chain_flatten_single_iter, is_ideal_ik_chain


class CLOUDRIG_OT_flatten_ik_chain(Operator):
    """Flatten a chain of bones on a plane, and align rolls with a potential IK pole vector. Useful for perfect IK chains"""

    bl_idname = "armature.flatten_ik_chain"
    bl_label = "Flatten IK Chain"
    bl_options = {'REGISTER', 'UNDO'}

    remove_active_log: BoolProperty(
        description="For calling this operator from the Generation Log", default=False
    )
    start_bone: StringProperty(
        description="Use a specific bone as the beginning of the chain, rather than the active bone",
        options={'SKIP_SAVE'}
    )
    pole_axis: EnumProperty(
        name="Pole Axis",
        description="Which bone axis should point toward the IK pole target",
        items=[
            ("-Z", "-Z", "-Z"),
            ("+Z", "+Z", "+Z"),
            ("+X", "+X", "+X"),
            ("-X", "-X", "-X"),
        ]
    )
    limit_count: IntProperty(
        name="Limit To First",
        default=2,
        description="If >0, only flatten the first X bones rather than the whole connected chain",
    )

    @classmethod
    def poll(cls, context):
        rig = context.active_object
        if not rig or rig.type != 'ARMATURE' or rig.mode != 'POSE':
            cls.poll_message_set("Active armature must be in pose mode.")
            return False
        return True

    def execute(self, context):
        rig = context.active_object
        start_pb = context.active_pose_bone
        if self.start_bone:
            start_pb = rig.pose.bones.get(self.start_bone)
        if not start_pb:
            self.report({'ERROR'}, "Bone not found: {bone}".format(bone=self.start_bone))
            return {'CANCELLED'}

        # Enter edit mode
        org_mode = rig.mode
        comp = start_pb.cloudrig_component.inherited_component
        pb_chain = comp.component_pbone_chain
        if self.limit_count > 0:
            pb_chain = pb_chain[:self.limit_count]

        bpy.ops.object.mode_set(mode='EDIT')

        eb_chain = [rig.data.edit_bones[pb.name] for pb in pb_chain]
        if comp.component_type == 'Chain: Leg':
            # Drop the toe.
            eb_chain = eb_chain[:-1]
        did_anything = False
        counter = 0
        max_iter = 100
        while not is_ideal_ik_chain(eb_chain) or counter > max_iter:
            did_anything = ik_chain_flatten_single_iter(eb_chain, axis=self.pole_axis)
            counter += 1

        bpy.ops.object.mode_set(mode=org_mode)

        if self.remove_active_log:
            rig.cloudrig.generator.remove_active_log()

        if did_anything or counter > 1:
            self.report({'INFO'}, "Bone chain now perfect for IK.")
        else:
            self.report({'INFO'}, "Bone chain was already perfect for IK.")

        return {'FINISHED'}


registry = [CLOUDRIG_OT_flatten_ik_chain]
