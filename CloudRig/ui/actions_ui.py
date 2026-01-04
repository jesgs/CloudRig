# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import random

import bpy
from bl_math import clamp
from bl_ui.generic_ui_list import draw_ui_list
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import (
    Action,
    ActionChannelbag,
    ActionSlot,
    Armature,
    Operator,
    PropertyGroup,
    UILayout,
    UIList,
)
from bpy.utils import flip_name
from bpy_extras import anim_utils

from ..bs_utils.ui import aligned_label, label_split
from ..utils.external.naming import Side, get_name_side


class ActionConstraintSetup(PropertyGroup):
    def update_ui(self, context):
        if not self.action:
            return
        # Initialize the unique ID the first time an Action is set.
        self.unique_id
        # Set the first slot if none are set.
        if self.action and self.action.slots and not self.action_slot:
            self.action_slot = self.action.slots[0]
        self['name'] = self.get_name_transform()

    action: PointerProperty(
        name="Action",
        type=Action,
        description="Action to apply to the rig via constraints",
        update=update_ui,
    )

    def slot_name_from_handle(self, curr_value, _is_set) -> str:
        try:
            curr_value = int(curr_value)
        except ValueError:
            return ""
        action_slot = next((s for s in self.action.slots if s.handle==curr_value), None)
        if not action_slot:
            return ""
        return action_slot.name_display

    def slot_name_to_handle(self, new_value, curr_value, _is_set)  -> str:
        action_slot = next((s for s in self.action.slots if s.name_display==new_value and s.identifier.startswith("OB")), None)
        if not action_slot:
            return ""
        return str(action_slot.handle)

    action_slot_ui: StringProperty(
        name="Acion Slot",
        description="Slot of the Action to use for the Action Constraints",
        get_transform=slot_name_from_handle,
        set_transform=slot_name_to_handle,
        update=update_ui,
    )

    @property
    def unique_id(self) -> int:
        if not self.action and 'unique_id' not in self:
            return 0
        if 'unique_id' in self and self['unique_id'] != 0:
            return self.get('unique_id')
        else:
            self['unique_id'] = random.randint(0, 100_000_000)
        return self['unique_id']

    @property
    def action_slot(self) -> ActionSlot | None:
        return self.action.slots.get("OB"+self.action_slot_ui)

    @action_slot.setter
    def action_slot(self, slot):
        if slot:
            self.action_slot_ui = slot.name_display

    def get_name_transform(self):
        if self.action:
            name = self.action.name
            if self.action_slot and len(self.action.slots) > 1:
                name += " ➔ " + self.action_slot.name_display
        else:
            name = str(self.unique_id)
        return name

    name: StringProperty(get=get_name_transform)

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

    is_corrective: BoolProperty(
        name="Corrective",
        description="Indicate that this is a corrective action. Corrective actions will activate "
        "based on the activation of two other actions"
        "are at their End Frame, and Start Frame if either is at Start Frame)",
    )

    def setup_id_to_str(self, curr_value, _is_set):
        try:
            curr_value = int(curr_value)
        except ValueError:
            return ""
        action_setups = self.id_data.cloudrig.generator.action_setups
        action_setup = next((setup for setup in action_setups if setup.unique_id==curr_value), None)
        if not action_setup:
            return ""
        return action_setup.name
    def setup_name_to_id(self, new_value, curr_value, _is_set):
        action_setups = self.id_data.cloudrig.generator.action_setups
        action_setup = next((setup for setup in action_setups if setup.name==new_value), None)
        if not action_setup:
            return ""
        return str(action_setup.unique_id)

    trigger_select_a: StringProperty(
        name="Trigger A",
        description="Action Set-up whose activation will trigger this set-up as a corrective",
        get_transform=setup_id_to_str,
        set_transform=setup_name_to_id,
    )
    trigger_select_b: StringProperty(
        name="Trigger B",
        description="Action Set-up whose activation will trigger this set-up as a corrective",
        get_transform=setup_id_to_str,
        set_transform=setup_name_to_id,
    )
    @property
    def trigger_a(self) -> ActionConstraintSetup | None:
        action_setups = self.id_data.cloudrig.generator.action_setups
        return next((setup for setup in action_setups if setup.name == self.trigger_select_a), None)

    @trigger_a.setter
    def trigger_a(self, action_setup: ActionConstraintSetup | None):
        self.trigger_select_a = action_setup.name if action_setup else ""

    @property
    def trigger_b(self) -> ActionConstraintSetup | None:
        action_setups = self.id_data.cloudrig.generator.action_setups
        return next((setup for setup in action_setups if setup.name == self.trigger_select_b), None)

    @trigger_b.setter
    def trigger_b(self, action_setup: ActionConstraintSetup | None):
        self.trigger_select_b = action_setup.name if action_setup else ""

    @property
    def generator(self):
        return self.id_data.cloudrig.generator

    @property
    def corrective_slots(self) -> list[ActionConstraintSetup]:
        """Return all corrective action setups targetting this setup."""
        for action_setup in self.generator.action_setups:
            if action_setup.trigger_a == self:
                yield action_setup
            if action_setup.trigger_b == self:
                yield action_setup

    show_action_a: BoolProperty(name="Show Settings")
    show_action_b: BoolProperty(name="Show Settings")

    @property
    def channelbag(self) -> ActionChannelbag | None:
        return anim_utils.action_get_channelbag_for_slot(self.action, self.action_slot)

    @property
    def keyed_bone_names(self) -> list[str]:
        """Return a list of bone names that have keyframes in the Action of this Setup."""
        keyed_bones = []

        channelbag = self.channelbag
        if not channelbag:
            return []
        keyed_bones = []
        for fc in channelbag.fcurves:
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
    def default_side(self) -> Side:
        return get_name_side(self.subtarget)

    def get_min_max(self, side=Side.MIDDLE) -> tuple[float, float]:
        if side == -self.default_side and side != Side.MIDDLE:
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


class CLOUDRIG_OT_action_new(Operator):
    """Create new Action"""

    # This is needed because bpy.ops.action.new() has a poll function that blocks
    # the operator unless it's drawn in an animation UI panel.

    bl_idname = "action.cloudrig_new"
    bl_label = "New"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        generator = context.object.cloudrig.generator
        active_setup = generator.active_action_setup
        action = bpy.data.actions.new(name="Action")
        active_setup.action = action
        return {'FINISHED'}


class CLOUDRIG_OT_jump_to_action_setup(Operator):
    """Set Active Action Setup Index"""

    bl_idname = "object.cloudrig_jump_to_action_setup"
    bl_label = "Jump to Action Setup"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    setup_id: IntProperty()

    def execute(self, context):
        for i, action_setup in enumerate(context.object.cloudrig.generator.action_setups):
            if action_setup.unique_id == self.setup_id:
                context.object.cloudrig.generator.active_action_index = i
                break
        self.report({'INFO'}, f'Set active action set-up index to {i}.')
        return {'FINISHED'}


class CLOUDRIG_UL_action_setups(UIList):
    def draw_item(
        self,
        context,
        layout: UILayout,
        data: Armature,
        action_setup: ActionConstraintSetup,
        icon_value: int,
        active_data,
        active_propname: str,
        setup_index: int = 0,
        flt_flag: int = 0,
    ):
        assert (
            self.layout_type == 'DEFAULT'
        ), "Other layouts not implemented for the Action Setup list."

        if not action_setup.action:
            layout.label(text="", translate=False, icon='ACTION')
            return

        armature_obj = action_setup.id_data
        generator = armature_obj.cloudrig.generator
        active_setup = generator.active_action_setup

        row = layout.row()
        icon = 'ACTION'

        # Check if this action is a trigger for the active corrective action
        if action_setup in {
            active_setup.trigger_a,
            active_setup.trigger_b,
            *active_setup.corrective_slots,
        }:
            icon = 'RESTRICT_INSTANCED_OFF'

        row.label(text=action_setup.name, icon=icon)

        if action_setup.is_corrective:
            text = "Corrective"
            icon = 'RESTRICT_INSTANCED_OFF'

            for trigger_setup in [
                action_setup.trigger_a,
                action_setup.trigger_b,
            ]:
                # No trigger set -> no setup or invalid setup
                if not trigger_setup or trigger_setup.is_corrective:
                    row.alert = True
                    text = "Missing Trigger" if not trigger_setup else "Corrective Trigger (Unsupported)"
                    icon = 'ERROR'
                    break

            row.label(text=text, icon=icon)
        else:
            text = action_setup.subtarget
            icon = 'BONE_DATA'

            if not action_setup.subtarget:
                row.alert = True
                text = 'Missing Control Bone'
                icon = 'ERROR'

            elif generator.target_rig:
                # Check for bones not actually present in the generated rig
                bones = generator.target_rig.pose.bones
                flipped_name = flip_name(action_setup.subtarget)

                if action_setup.subtarget not in bones:
                    row.alert = True
                    text = f'Missing: "{action_setup.subtarget}"'
                elif (
                    action_setup.symmetrical
                    and flipped_name not in bones
                ):
                    row.alert = True
                    text = f'Missing: "{flipped_name}"'

            row.label(text=text, icon=icon)

        icon = 'CHECKBOX_HLT' if action_setup.enabled else 'CHECKBOX_DEHLT'
        row.enabled = action_setup.enabled

        layout.prop(action_setup, 'enabled', text="", icon=icon, emboss=False)


def draw_action_setup_list(context, layout):
    header, panel = layout.panel("CloudRig Actions", default_closed=True)
    header.label(text="Actions")
    if not panel:
        return

    rig = context.object
    generator = rig.cloudrig.generator
    action_setups = generator.action_setups

    layout = panel
    layout.use_property_split = True
    layout.use_property_decorate = False

    draw_ui_list(
        layout,
        context,
        class_name='CLOUDRIG_UL_action_setups',
        unique_id='CloudRig Action Setups',
        list_path='object.cloudrig.generator.action_setups',
        active_index_path='object.cloudrig.generator.active_action_index',
    )

    active_setup = generator.active_action_setup

    if len(action_setups) == 0 or not active_setup:
        return

    col = layout.column(align=True)
    col.use_property_split=False
    col.template_ID(active_setup, 'action', new=CLOUDRIG_OT_action_new.bl_idname)
    if not active_setup.action:
        return
    if not active_setup.action.slots:
        layout.alert = True
        layout.label(text="No slots in this Action.")
        return

    col.prop_search(active_setup, "action_slot_ui", active_setup.action, 'slots', text="")

    layout = layout.column()
    layout.prop(active_setup, 'is_corrective')

    if active_setup.is_corrective:
        draw_ui_corrective(context, layout.column(align=True), active_setup)
    else:
        draw_action_setup_ui(layout, active_setup, generator.target_rig)
    draw_status(layout, active_setup)

def draw_ui_corrective(context, layout, action_setup):
    layout.prop(action_setup, 'frame_start', text="Frame Start")
    layout.prop(action_setup, 'frame_end', text="End")
    layout.separator()

    for trigger_prop in ['trigger_select_a', 'trigger_select_b']:
        draw_ui_trigger(context, layout, action_setup, trigger_prop)

def draw_ui_trigger(context, layout: UILayout, action_setup: ActionConstraintSetup, trigger_prop: str):
    metarig = context.object
    generator = metarig.cloudrig.generator
    assert isinstance(metarig.data, Armature)

    trigger_setup = getattr(action_setup, trigger_prop.replace("select_", ""))
    icon = 'ACTION' if trigger_setup else 'ERROR'

    row = layout.row(align=True)
    row.prop_search(generator.active_action_setup, trigger_prop, generator, 'action_setups', icon=icon)

    if not trigger_setup:
        return

    if not trigger_setup:
        aligned_label(layout, text="Trigger Missing", icon='ERROR', alert=True)
        return

    show_prop_name = 'show_action_' + trigger_prop[-1]
    show = getattr(action_setup, show_prop_name)
    icon = 'HIDE_OFF' if show else 'HIDE_ON'

    row.prop(action_setup, show_prop_name, icon=icon, text="")

    op = row.operator(
        CLOUDRIG_OT_jump_to_action_setup.bl_idname, text="", icon='LOOP_FORWARDS'
    )
    op.setup_id = trigger_setup.unique_id

    if show:
        col = layout.column(align=True)
        col.enabled = False
        draw_action_setup_ui(col, trigger_setup, generator.target_rig)
        col.separator()

def draw_action_setup_ui(layout, action_setup, target_rig):
    if not target_rig:
        row = layout.row()
        row.alert = True
        row.label(
            text="Cannot verify bone name without a generated rig", icon='ERROR'
        )

    row = layout.row()

    bone_icon = 'BONE_DATA' if action_setup.subtarget else 'ERROR'

    if target_rig:
        subtarget_exists = action_setup.subtarget in target_rig.pose.bones
        row.alert = not subtarget_exists
        row.prop_search(action_setup, 'subtarget', target_rig.pose, 'bones', icon=bone_icon)

        if not subtarget_exists:
            if action_setup.subtarget:
                aligned_label(layout, text=f"Bone not found: {action_setup.subtarget}", icon='ERROR', alert=True)
            return
    else:
        row.prop(action_setup, 'subtarget', icon=bone_icon)

    flipped_subtarget = flip_name(action_setup.subtarget)

    if flipped_subtarget != action_setup.subtarget:
        flipped_subtarget_exists = (
            not target_rig or flipped_subtarget in target_rig.pose.bones
        )

        row = layout.row()
        row.use_property_split = True
        row.prop(action_setup, 'symmetrical', text=f"Symmetrical ({flipped_subtarget})")

        if action_setup.symmetrical and not flipped_subtarget_exists:
            row.alert = True
            aligned_label(layout, text=f"Bone not found: {flipped_subtarget}", icon='ERROR', alert=True)

    layout.prop(action_setup, 'frame_start', text="Frame Start")
    layout.prop(action_setup, 'frame_end', text="End")

    layout.prop(action_setup, 'target_space', text="Target Space")
    layout.prop(action_setup, 'transform_channel', text="Transform Channel")

    layout.prop(action_setup, 'trans_min')
    layout.prop(action_setup, 'trans_max')

def draw_status(layout, action_setup):
    """
    There are a lot of ways to create incorrect Action setups, so give
    the user a warning in those cases.
    """
    split = label_split(layout, text="Status:")

    if action_setup.trans_min == action_setup.trans_max:
        col = split.column(align=True)
        col.alert = True
        col.label(text="Min and max value are the same!")
        col.label(text=f"Will be stuck reading frame {action_setup.frame_start}!")
        return

    if action_setup.frame_start == action_setup.frame_end:
        col = split.column(align=True)
        col.alert = True
        col.label(text="Start and end frame cannot be the same!")

    default_frame = action_setup.get_default_frame()

    if action_setup.is_default_frame_integer():
        split.label(text=f"Default Frame: {round(default_frame)}")
    else:
        split.alert = True
        split.label(
            text=f"Default Frame: {round(default_frame, 2)} "
            "(Should be a whole number!)"
        )


registry = (
    ActionConstraintSetup,
    CLOUDRIG_OT_action_new,
    CLOUDRIG_OT_jump_to_action_setup,
    CLOUDRIG_UL_action_setups,
)
