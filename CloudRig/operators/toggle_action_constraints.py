# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty
from bpy.types import Action, ActionSlot, Constraint, Operator


class CLOUDRIG_OT_Toggle_Action_Constraints(Operator):
    """Toggle Action constraints of the active action on all bones of the armature"""

    bl_idname = "armature.toggle_action_constraints"
    bl_label = "Toggle Action Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    enable: BoolProperty(name="Enable", default=True)

    @staticmethod
    def get_first_referencing_constraint(
        rig,
        action: Action,
        action_slot: ActionSlot
    ) -> Constraint | None:
        for pb in rig.pose.bones:
            for c in pb.constraints:
                if c.type == 'ACTION' and c.action == action and c.action_slot==action_slot:
                    return c

    @classmethod
    def poll(cls, context):
        rig = context.active_object
        if not rig or rig.type != 'ARMATURE' or rig.mode not in ['POSE', 'OBJECT']:
            cls.poll_message_set("There must be an active armature in pose or object mode.")
            return
        if not (rig.animation_data and rig.animation_data.action):
            cls.poll_message_set("Armature must have an action assigned.")
            return
        action = rig.animation_data.action
        action_slot = rig.animation_data.action_slot
        con = cls.get_first_referencing_constraint(rig, action, action_slot)
        if not con:
            cls.poll_message_set("No constraints in this armature are referencing the active Action.")
            return False
        return True

    def execute(self, context):
        rig = context.active_object
        action = rig.animation_data.action
        action_slot = rig.animation_data.action_slot

        con_count = 0
        for pb in rig.pose.bones:
            for c in pb.constraints:
                if c.type == 'ACTION' and c.action == action and c.action_slot == action_slot:
                    c.mute = not self.enable
                    con_count += 1

        word = "Enabled" if self.enable else "Disabled"
        self.report(
            {'INFO'}, f'{word} {con_count} constraints referencing "{action.name}".'
        )

        return {'FINISHED'}


def draw_toggle_but(self, context):
    layout = self.layout
    st = context.space_data
    if st.mode != 'ACTION':
        return
    if not CLOUDRIG_OT_Toggle_Action_Constraints.poll(context):
        return
    rig = context.active_object
    first_con = CLOUDRIG_OT_Toggle_Action_Constraints.get_first_referencing_constraint(
        rig, rig.animation_data.action, rig.animation_data.action_slot
    )
    op = layout.operator(
        CLOUDRIG_OT_Toggle_Action_Constraints.bl_idname,
        text="Action Constraints",
        icon='CONSTRAINT_BONE',
        depress=first_con.enabled,
    )
    op.enable = not first_con.enabled


registry = [CLOUDRIG_OT_Toggle_Action_Constraints]


def register():
    bpy.types.DOPESHEET_HT_header.append(draw_toggle_but)


def unregister():
    bpy.types.DOPESHEET_HT_header.remove(draw_toggle_but)
