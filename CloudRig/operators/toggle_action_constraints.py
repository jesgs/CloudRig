# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty
from bpy.types import Action, ActionSlot, Constraint, Context, Object, Operator


class CLOUDRIG_OT_toggle_action_constraints(Operator):
    """Toggle Action Constraints of the active Action on all bones of this Armature object"""

    bl_idname = "armature.toggle_action_constraints"
    bl_label = "Toggle Action Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    enable: BoolProperty(name="Enable", default=True)

    @staticmethod
    def get_first_referencing_constraint(
        rig: Object,
        action: Action,
        action_slot: ActionSlot,
    ) -> Constraint | None:
        """Return the first Action constraint on any bone that targets the given action and slot."""
        for pb in rig.pose.bones:
            for con in pb.constraints:
                if con.type == 'ACTION' and con.action == action and con.action_slot == action_slot:
                    return con

    @classmethod
    def poll(cls, context: Context):
        rig = context.active_object
        if not rig or rig.type != 'ARMATURE' or rig.mode not in ['POSE', 'OBJECT']:
            cls.poll_message_set("There must be an active armature in pose or object mode.")
            return False
        if not (rig.animation_data and rig.animation_data.action):
            cls.poll_message_set("Armature must have an action assigned.")
            return False
        action = rig.animation_data.action
        action_slot = rig.animation_data.action_slot
        con = cls.get_first_referencing_constraint(rig, action, action_slot)
        if not con:
            cls.poll_message_set("No constraints in this armature are referencing the active Action.")
            return False
        return True

    def execute(self, context: Context):
        rig = context.active_object
        action = rig.animation_data.action
        action_slot = rig.animation_data.action_slot

        con_count = 0
        for pb in rig.pose.bones:
            for con in pb.constraints:
                if con.type == 'ACTION' and con.action == action and con.action_slot == action_slot:
                    con.mute = not self.enable
                    con_count += 1

        self.report({'INFO'}, rpt_('Affected constraints: {count}').format(count=con_count))

        return {'FINISHED'}


def draw_toggle_but(self, context: Context):
    layout = self.layout
    st = context.space_data
    if st.mode != 'ACTION':
        return
    if not CLOUDRIG_OT_toggle_action_constraints.poll(context):
        return
    rig = context.active_object
    first_con = CLOUDRIG_OT_toggle_action_constraints.get_first_referencing_constraint(
        rig, rig.animation_data.action, rig.animation_data.action_slot
    )
    op = layout.operator(
        CLOUDRIG_OT_toggle_action_constraints.bl_idname,
        text="Action Constraints",
        icon='CONSTRAINT_BONE',
        depress=first_con.enabled,
    )
    op.enable = not first_con.enabled


registry = [CLOUDRIG_OT_toggle_action_constraints]


def register():
    bpy.types.DOPESHEET_HT_header.append(draw_toggle_but)


def unregister():
    bpy.types.DOPESHEET_HT_header.remove(draw_toggle_but)
