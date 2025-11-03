# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, StringProperty

from ..rig_component_features.mechanism import get_component_pbone_chain
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
        description="Use a specific bone as the beginning of the chain, rather than the active bone"
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

        # Enter edit mode
        org_mode = rig.mode
        pb_chain = get_component_pbone_chain(context.active_pose_bone)

        bpy.ops.object.mode_set(mode='EDIT')

        eb_chain = [rig.data.edit_bones[pb.name] for pb in pb_chain]
        did_anything = False
        counter = 0
        while not is_ideal_ik_chain(eb_chain) or counter > 10:
            did_anything = ik_chain_flatten_single_iter(eb_chain)
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
