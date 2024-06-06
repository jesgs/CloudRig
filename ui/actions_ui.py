# SPDX-License-Identifier: GPL-2.0-or-later

import bpy

from bl_math import clamp

from ..utils.external.naming import Side, get_name_side
from ..generation.cloudrig import CloudRigOperator

from bpy.types import (
    PropertyGroup,
    Action,
    UIList,
    UILayout,
    Context,
    Panel,
    Armature,
)
from bpy.props import (
    EnumProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    FloatProperty,
    PointerProperty,
)

from bl_ui.generic_ui_list import draw_ui_list

from bpy.utils import flip_name


class ActionSlot(PropertyGroup):
    action: PointerProperty(
        name="Action",
        type=Action,
        description="Action to apply to the rig via constraints",
    )

    enabled: BoolProperty(
        name="Enabled",
        description="Create constraints for this action on the generated rig",
        default=True,
    )

    symmetrical: BoolProperty(
        name="Symmetrical",
        description="Apply the same setup but mirrored to the opposite side control, shown in "
        "parentheses. Bones will only be affected by the control with the same side "
        "(eg., .L bones will only be affected by the .L control). Bones without a "
        "side in their name (so no .L or .R) will be affected by both controls "
        "with 0.5 influence each",
        default=True,
    )

    subtarget: StringProperty(
        name="Control Bone",
        description="Select a bone on the generated rig which will drive this action",
    )

    transform_channel: EnumProperty(
        name="Transform Channel",
        items=[
            ("LOCATION_X", "X Location", "X Location"),
            ("LOCATION_Y", "Y Location", "Y Location"),
            ("LOCATION_Z", "Z Location", "Z Location"),
            ("ROTATION_X", "X Rotation", "X Rotation"),
            ("ROTATION_Y", "Y Rotation", "Y Rotation"),
            ("ROTATION_Z", "Z Rotation", "Z Rotation"),
            ("SCALE_X", "X Scale", "X Scale"),
            ("SCALE_Y", "Y Scale", "Y Scale"),
            ("SCALE_Z", "Z Scale", "Z Scale"),
        ],
        description="Transform channel",
        default="LOCATION_X",
    )

    target_space: EnumProperty(
        name="Transform Space",
        items=[
            ("WORLD", "World Space", "World Space"),
            ("POSE", "Pose Space", "Pose Space"),
            ("LOCAL_WITH_PARENT", "Local With Parent", "Local With Parent"),
            ("LOCAL", "Local Space", "Local Space"),
        ],
        default="LOCAL",
    )

    def update_frame_start(self, _context):
        if self.frame_start > self.frame_end:
            self.frame_end = self.frame_start

    frame_start: IntProperty(
        name="Start Frame",
        description="First frame of the action's timeline",
        update=update_frame_start,
    )

    def update_frame_end(self, _context):
        if self.frame_end < self.frame_start:
            self.frame_start = self.frame_end

    frame_end: IntProperty(
        name="End Frame",
        default=2,
        description="Last frame of the action's timeline",
        update=update_frame_end,
    )

    trans_min: FloatProperty(
        name="Min",
        default=-0.05,
        description="Value that the transformation value must reach to put the action's timeline "
        "to the first frame. Rotations are in degrees",
    )

    trans_max: FloatProperty(
        name="Max",
        default=0.05,
        description="Value that the transformation value must reach to put the action's timeline "
        "to the last frame. Rotations are in degrees",
    )

    def update_is_corrective(self, context):
        if not self.is_corrective:
            self.trigger_action_a = None
            self.trigger_action_b = None

    is_corrective: BoolProperty(
        name="Corrective",
        description="Indicate that this is a corrective action. Corrective actions will activate "
        "based on the activation of two other actions (using End Frame if both inputs "
        "are at their End Frame, and Start Frame if either is at Start Frame)",
        update=update_is_corrective,
    )

    def poll_trigger_action(self, action):
        """Whether an action can be used as a corrective action's trigger or not."""
        armature_obj = self.id_data

        slots = armature_obj.cloudrig.generator.action_slots
        active_slot = armature_obj.cloudrig.generator.active_action_slot

        # If this action is the same as the active slot's action, don't show it.
        if active_slot and action == active_slot.action:
            return False

        # If this action is used by any other action slot, show it.
        for slot in slots:
            if slot.action == action and not slot.is_corrective:
                return True

        return False

    trigger_action_a: PointerProperty(
        name="Trigger A",
        type=Action,
        description="Action whose activation will trigger the corrective action",
        poll=poll_trigger_action,
    )

    trigger_action_b: PointerProperty(
        name="Trigger B",
        description="Action whose activation will trigger the corrective action",
        type=Action,
        poll=poll_trigger_action,
    )

    @property
    def generator(self):
        return self.id_data.cloudrig.generator

    def next_slot_with_action(self, action, reversed=False):
        """Return next or previous slot in the list with the given action."""
        generator = self.generator
        found_self = False
        found_slot = None
        slots = generator.action_slots
        if reversed:
            slots = reversed(slots)
        for slot in slots:
            if slot == self:
                found_self = True
            if slot.action == action:
                found_slot = slot
                if found_self:
                    break
        return found_slot

    @property
    def trigger_slot_a(self) -> "ActionSlot":
        """Return the next Action Slot after this one, that has the "A" trigger Action."""
        return self.next_slot_with_action(self.trigger_action_a)

    @property
    def trigger_slot_b(self) -> "ActionSlot":
        """Return the next Action Slot after this one, that has the "B" trigger Action."""
        return self.next_slot_with_action(self.trigger_action_b)

    @property
    def corrective_slots(self) -> list["ActionSlot"]:
        """Return all corrective action slots targetting this slot."""
        for slot in self.generator.action_slots:
            if slot.trigger_slot_a == self:
                yield slot
            if slot.trigger_slot_b == self:
                yield slot

    show_action_a: BoolProperty(name="Show Settings")
    show_action_b: BoolProperty(name="Show Settings")

    @property
    def keyed_bone_names(self) -> list[str]:
        """Return a list of bone names that have keyframes in the Action of this Slot."""
        keyed_bones = []

        for fc in self.action.fcurves:
            # Extracting bone name from fcurve data path
            if fc.data_path.startswith('pose.bones["'):
                bone_name = fc.data_path[12:].split('"]')[0]

                if bone_name not in keyed_bones:
                    keyed_bones.append(bone_name)

        return keyed_bones

    @property
    def do_symmetry(self) -> bool:
        return self.symmetrical and get_name_side(self.subtarget) != Side.MIDDLE

    @property
    def default_side(self):
        return get_name_side(self.subtarget)

    def get_min_max(self, side=Side.MIDDLE) -> tuple[float, float]:
        if side == -self.default_side:
            # Flip min/max in some cases - based on code of Paste Pose Flipped
            if self.transform_channel in ['LOCATION_X', 'ROTATION_Z', 'ROTATION_Y']:
                return -self.trans_min, -self.trans_max
        return self.trans_min, self.trans_max

    def get_factor_expression(self, var, side=Side.MIDDLE):
        assert not self.is_corrective

        trans_min, trans_max = self.get_min_max(side)

        if 'ROTATION' in self.transform_channel:
            var = f'({var}*180/pi)'

        return f'clamp(({var} - {trans_min:.4}) / {trans_max - trans_min:.4})'

    def get_trigger_expression(self, var_a, var_b):
        assert self.is_corrective

        return f'clamp({var_a} * {var_b})'

    ##################################
    # Default Frame

    def get_default_channel_value(self) -> float:
        # The default transformation value for rotation and location is 0, but for scale it's 1.
        return 1.0 if 'SCALE' in self.transform_channel else 0.0

    def get_default_factor(self, side=Side.MIDDLE, *, triggers=None) -> float:
        """Based on the transform channel, and transform range,
        calculate the evaluation factor in the default pose.
        """
        if self.is_corrective:
            if not triggers or None in triggers:
                return 0

            val_a, val_b = [trigger.get_default_factor(side) for trigger in triggers]

            return clamp(val_a * val_b)

        else:
            trans_min, trans_max = self.get_min_max(side)

            if trans_min == trans_max:
                # Avoid division by zero
                return 0

            def_val = self.get_default_channel_value()
            factor = (def_val - trans_min) / (trans_max - trans_min)

            return clamp(factor)

    def get_default_frame(self, side=Side.MIDDLE, *, triggers=None) -> float:
        """Based on the transform channel, frame range and transform range,
        we can calculate which frame within the action should have the keyframe
        which has the default pose.
        This is the frame which will be read when the transformation is at its default
        (so 1.0 for scale and 0.0 for loc/rot)
        """
        factor = self.get_default_factor(side, triggers=triggers)

        return self.frame_start * (1 - factor) + self.frame_end * factor

    def is_default_frame_integer(self) -> bool:
        default_frame = self.get_default_frame()

        return abs(default_frame - round(default_frame)) < 0.001


class CLOUDRIG_OT_action_new(CloudRigOperator):
    """Create new Action"""

    # This is needed because bpy.ops.action.new() has a poll function that blocks
    # the operator unless it's drawn in an animation UI panel.

    bl_idname = "action.cloudrig_new"
    bl_label = "New"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        generator = context.object.cloudrig.generator
        action_slots = generator.action_slots
        active_slot = generator.active_action_slot
        action = bpy.data.actions.new(name="Action")
        active_slot.action = action
        return {'FINISHED'}


class CLOUDRIG_OT_jump_to_action_slot(CloudRigOperator):
    """Set Active Action Slot Index"""

    bl_idname = "object.cloudrig_jump_to_action_slot"
    bl_label = "Jump to Action Slot"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    to_index: IntProperty()

    def execute(self, context):
        context.object.cloudrig.generator.active_action_index = self.to_index
        return {'FINISHED'}


class CLOUDRIG_UL_action_slots(UIList):
    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data: Armature,
        action_slot: ActionSlot,
        icon_value: int,
        active_data,
        active_propname: str,
        slot_index: int = 0,
        flt_flag: int = 0,
    ):
        assert (
            self.layout_type == 'DEFAULT'
        ), "Other layouts not implemented for the Action Slot list."

        if not action_slot.action:
            layout.label(text="", translate=False, icon='ACTION')
            return

        armature_obj = action_slot.id_data
        generator = armature_obj.cloudrig.generator
        active_slot = generator.active_action_slot

        row = layout.row()
        icon = 'ACTION'

        # Check if this action is a trigger for the active corrective action
        if action_slot in {
            active_slot.trigger_slot_a,
            active_slot.trigger_slot_b,
            *active_slot.corrective_slots,
        }:
            icon = 'RESTRICT_INSTANCED_OFF'

        row.prop(action_slot.action, 'name', text="", emboss=False, icon=icon)

        if action_slot.is_corrective:
            text = "Corrective"
            icon = 'RESTRICT_INSTANCED_OFF'

            for trigger in [
                action_slot.trigger_action_a,
                action_slot.trigger_action_b,
            ]:
                trigger_slot, trigger_idx = generator.find_slot_by_action(trigger)

                # No trigger action set, no slot or invalid slot
                if not trigger_slot or trigger_slot.is_corrective:
                    row.alert = True
                    text = "No Trigger Action"
                    icon = 'ERROR'
                    break

            row.label(text=text, icon=icon)
        else:
            text = action_slot.subtarget
            icon = 'BONE_DATA'

            if not action_slot.subtarget:
                row.alert = True
                text = 'No Control Bone'
                icon = 'ERROR'

            elif generator.target_rig:
                # Check for bones not actually present in the generated rig
                bones = generator.target_rig.pose.bones

                if action_slot.subtarget not in bones:
                    row.alert = True
                    text = 'Bad Control Bone'
                    icon = 'ERROR'
                elif (
                    action_slot.symmetrical
                    and flip_name(action_slot.subtarget) not in bones
                ):
                    row.alert = True
                    text = 'Bad Control Bone'
                    icon = 'ERROR'

            row.label(text=text, icon=icon)

        icon = 'CHECKBOX_HLT' if action_slot.enabled else 'CHECKBOX_DEHLT'
        row.enabled = action_slot.enabled

        layout.prop(action_slot, 'enabled', text="", icon=icon, emboss=False)


class DATA_PT_cloudrig_actions(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = "Actions"
    bl_parent_id = "POSE_PT_CloudRig"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: Context):
        generator = context.object.cloudrig.generator
        action_slots = generator.action_slots

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_ui_list(
            layout,
            context,
            class_name='CLOUDRIG_UL_action_slots',
            unique_id='CloudRig Action Slots',
            list_path='object.cloudrig.generator.action_slots',
            active_index_path='object.cloudrig.generator.active_action_index',
        )

        active_slot = generator.active_action_slot

        if len(action_slots) == 0 or not active_slot:
            return

        layout.template_ID(active_slot, 'action', new=CLOUDRIG_OT_action_new.bl_idname)

        if not active_slot.action:
            return

        layout = layout.column()
        layout.prop(active_slot, 'is_corrective')

        if active_slot.is_corrective:
            self.draw_ui_corrective(context, active_slot)
        else:
            self.draw_slot_ui(layout, active_slot, generator.target_rig)
            self.draw_status(active_slot)

    def draw_ui_corrective(self, context: Context, slot):
        layout = self.layout

        layout.prop(slot, 'frame_start', text="Frame Start")
        layout.prop(slot, 'frame_end', text="End")
        layout.separator()

        for trigger_prop in ['trigger_action_a', 'trigger_action_b']:
            self.draw_ui_trigger(context, slot, trigger_prop)

    def draw_ui_trigger(self, context: Context, slot, trigger_prop: str):
        layout = self.layout
        metarig = context.object
        generator = metarig.cloudrig.generator
        assert isinstance(metarig.data, Armature)

        trigger = getattr(slot, trigger_prop)
        icon = 'ACTION' if trigger else 'ERROR'

        row = layout.row()
        row.prop(slot, trigger_prop, icon=icon)

        if not trigger:
            return

        trigger_slot, slot_index = generator.find_slot_by_action(trigger)

        if not trigger_slot:
            row = layout.split(factor=0.4)
            row.separator()
            row.alert = True
            row.label(text="Action not in list", icon='ERROR')
            return

        show_prop_name = 'show_action_' + trigger_prop[-1]
        show = getattr(slot, show_prop_name)
        icon = 'HIDE_OFF' if show else 'HIDE_ON'

        row.prop(slot, show_prop_name, icon=icon, text="")

        op = row.operator(
            CLOUDRIG_OT_jump_to_action_slot.bl_idname, text="", icon='LOOP_FORWARDS'
        )
        op.to_index = slot_index

        if show:
            col = layout.column(align=True)
            col.enabled = False
            self.draw_slot_ui(col, trigger_slot, generator.target_rig)
            col.separator()

    @staticmethod
    def draw_slot_ui(layout, slot, target_rig):
        if not target_rig:
            row = layout.row()
            row.alert = True
            row.label(
                text="Cannot verify bone name without a generated rig", icon='ERROR'
            )

        row = layout.row()

        bone_icon = 'BONE_DATA' if slot.subtarget else 'ERROR'

        if target_rig:
            subtarget_exists = slot.subtarget in target_rig.pose.bones
            row.prop_search(slot, 'subtarget', target_rig.pose, 'bones', icon=bone_icon)
            row.alert = not subtarget_exists

            if slot.subtarget and not subtarget_exists:
                row = layout.split(factor=0.4)
                row.column()
                row.alert = True
                row.label(text=f"Bone not found: {slot.subtarget}", icon='ERROR')
        else:
            row.prop(slot, 'subtarget', icon=bone_icon)

        flipped_subtarget = flip_name(slot.subtarget)

        if flipped_subtarget != slot.subtarget:
            flipped_subtarget_exists = (
                not target_rig or flipped_subtarget in target_rig.pose.bones
            )

            row = layout.row()
            row.use_property_split = True
            row.prop(slot, 'symmetrical', text=f"Symmetrical ({flipped_subtarget})")

            if slot.symmetrical and not flipped_subtarget_exists:
                row.alert = True

                row = layout.split(factor=0.4)
                row.column()
                row.alert = True
                row.label(text=f"Bone not found: {flipped_subtarget}", icon='ERROR')

        layout.prop(slot, 'frame_start', text="Frame Start")
        layout.prop(slot, 'frame_end', text="End")

        layout.prop(slot, 'target_space', text="Target Space")
        layout.prop(slot, 'transform_channel', text="Transform Channel")

        layout.prop(slot, 'trans_min')
        layout.prop(slot, 'trans_max')

    def draw_status(self, slot):
        """
        There are a lot of ways to create incorrect Action setups, so give
        the user a warning in those cases.
        """
        layout = self.layout

        split = layout.split(factor=0.4)
        heading = split.row()
        heading.alignment = 'RIGHT'
        heading.label(text="Status:")

        if slot.trans_min == slot.trans_max:
            col = split.column(align=True)
            col.alert = True
            col.label(text="Min and max value are the same!")
            col.label(text=f"Will be stuck reading frame {slot.frame_start}!")
            return

        if slot.frame_start == slot.frame_end:
            col = split.column(align=True)
            col.alert = True
            col.label(text="Start and end frame cannot be the same!")

        default_frame = slot.get_default_frame()

        if slot.is_default_frame_integer():
            split.label(text=f"Default Frame: {round(default_frame)}")
        else:
            split.alert = True
            split.label(
                text=f"Default Frame: {round(default_frame, 2)} "
                "(Should be a whole number!)"
            )


registry = (
    ActionSlot,
    CLOUDRIG_OT_action_new,
    CLOUDRIG_OT_jump_to_action_slot,
    CLOUDRIG_UL_action_slots,
    DATA_PT_cloudrig_actions,
)
