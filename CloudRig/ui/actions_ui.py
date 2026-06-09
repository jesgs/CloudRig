# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..generation.cloud_generator import GeneratorProperties


import bpy
from bl_ui.generic_ui_list import draw_ui_list
from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import (
    IntProperty,
)
from bpy.types import (
    Armature,
    Context,
    Object,
    Operator,
    UILayout,
    UIList,
)
from bpy.utils import flip_name

from ..bs_utils.ui import aligned_label, label_split
from ..generation.actions_component import ActionConstraintSetup


class CLOUDRIG_OT_action_new(Operator):
    """Create new Action"""

    # This is needed because bpy.ops.action.new() has a poll function that blocks
    # the operator unless it's drawn in an animation UI panel.

    bl_idname = "action.cloudrig_new"
    bl_label = "New"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context: Context):
        generator = context.object.cloudrig.generator
        active_setup = generator.active_action_setup
        action = bpy.data.actions.new(name="Action")
        active_setup.action = action
        return {'FINISHED'}


class CLOUDRIG_OT_jump_to_action_setup(Operator):
    """Set the active Action Setup"""

    bl_idname = "object.cloudrig_jump_to_action_setup"
    bl_label = "Jump to Action Setup"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    setup_id: IntProperty()

    def execute(self, context: Context):
        for i, action_setup in enumerate(context.object.cloudrig.generator.action_setups):
            if action_setup.unique_id == self.setup_id:
                context.object.cloudrig.generator.active_action_index = i
                break
        self.report({'INFO'}, rpt_('Set active action setup index to {index}.').format(index=i))
        return {'FINISHED'}


class CLOUDRIG_UL_action_setups(UIList):
    def draw_item(
        self,
        _context: Context,
        layout: UILayout,
        _list_owner: GeneratorProperties,
        list_element: ActionConstraintSetup,
        _icon_value: int,
        _active_prop_owner: GeneratorProperties,
        _active_prop_name: str,
    ):
        assert self.layout_type == 'DEFAULT', "Other layouts not implemented for the Action Setup list."
        action_setup = list_element
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
                    text = (
                        iface_("Missing Trigger") if not trigger_setup else iface_("Corrective Trigger (Unsupported)")
                    )
                    icon = 'ERROR'
                    break

            row.label(text=text, icon=icon)
        else:
            text = action_setup.subtarget
            icon = 'BONE_DATA'

            if not action_setup.subtarget:
                row.alert = True
                text = rpt_('Missing Control Bone')
                icon = 'ERROR'

            elif generator.target_rig:
                # Check for bones not actually present in the Target Rig.
                bones = generator.target_rig.pose.bones
                flipped_name = flip_name(action_setup.subtarget)

                if action_setup.subtarget not in bones:
                    row.alert = True
                    text = rpt_('Missing: "{bone}"').format(bone=action_setup.subtarget)
                elif action_setup.symmetrical and flipped_name not in bones:
                    row.alert = True
                    text = rpt_('Missing: "{bone}"').format(bone=flipped_name)

            row.label(text=text, icon=icon, translate=False)

        icon = 'CHECKBOX_HLT' if action_setup.enabled else 'CHECKBOX_DEHLT'
        row.enabled = action_setup.enabled

        layout.prop(action_setup, 'enabled', text="", icon=icon, emboss=False)


def draw_action_setup_list(context: Context, layout: UILayout):
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

    if not action_setups or not active_setup:
        return

    col = layout.column(align=True)
    col.use_property_split = False
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


def draw_ui_corrective(context: Context, layout: UILayout, action_setup: ActionConstraintSetup):
    layout.prop(action_setup, 'frame_start', text="Frame Start")
    layout.prop(action_setup, 'frame_end', text="End")
    layout.separator()

    for trigger_prop in ['trigger_select_a', 'trigger_select_b']:
        draw_ui_trigger(context, layout, action_setup, trigger_prop)


def draw_ui_trigger(context: Context, layout: UILayout, action_setup: ActionConstraintSetup, trigger_prop: str):
    metarig = context.object
    generator = metarig.cloudrig.generator
    assert isinstance(metarig.data, Armature)

    trigger_setup = getattr(action_setup, trigger_prop.replace("select_", ""))
    icon = 'ACTION' if trigger_setup else 'ERROR'

    row = layout.row(align=True)
    row.prop_search(generator.active_action_setup, trigger_prop, generator, 'action_setups', icon=icon)

    if not trigger_setup:
        return

    show_prop_name = 'show_action_' + trigger_prop[-1]
    show = getattr(action_setup, show_prop_name)
    icon = 'HIDE_OFF' if show else 'HIDE_ON'

    row.prop(action_setup, show_prop_name, icon=icon, text="")

    op = row.operator(CLOUDRIG_OT_jump_to_action_setup.bl_idname, text="", icon='LOOP_FORWARDS')
    op.setup_id = trigger_setup.unique_id

    if show:
        col = layout.column(align=True)
        col.enabled = False
        draw_action_setup_ui(col, trigger_setup, generator.target_rig)
        col.separator()


def draw_action_setup_ui(layout: UILayout, action_setup: ActionConstraintSetup, target_rig: Object):
    if not target_rig:
        row = layout.row()
        row.alert = True
        row.label(text="Cannot verify bone name without a Target Rig", icon='ERROR')

    row = layout.row()

    bone_icon = 'BONE_DATA' if action_setup.subtarget else 'ERROR'

    if target_rig:
        subtarget_exists = action_setup.subtarget in target_rig.pose.bones
        row.alert = not subtarget_exists
        row.prop_search(action_setup, 'subtarget', target_rig.pose, 'bones', icon=bone_icon)

        if not subtarget_exists:
            if action_setup.subtarget:
                aligned_label(
                    layout,
                    text=iface_("Bone not found: {bone}").format(bone=action_setup.subtarget),
                    icon='ERROR',
                    alert=True,
                )
            return
    else:
        row.prop(action_setup, 'subtarget', icon=bone_icon)

    flipped_subtarget = flip_name(action_setup.subtarget)

    if flipped_subtarget != action_setup.subtarget:
        flipped_subtarget_exists = not target_rig or flipped_subtarget in target_rig.pose.bones

        row = layout.row()
        row.use_property_split = True
        row.prop(action_setup, 'symmetrical', text=iface_("Symmetrical ({bone})").format(bone=flipped_subtarget))

        if action_setup.symmetrical and not flipped_subtarget_exists:
            row.alert = True
            aligned_label(
                layout,
                text=iface_("Bone not found: {bone}").format(bone=flipped_subtarget),
                icon='ERROR',
                alert=True,
            )

    layout.prop(action_setup, 'frame_start', text="Frame Start")
    layout.prop(action_setup, 'frame_end', text="End")

    layout.prop(action_setup, 'target_space', text="Target Space")
    layout.prop(action_setup, 'transform_channel', text="Transform Channel")

    layout.prop(action_setup, 'trans_min')
    layout.prop(action_setup, 'trans_max')


def draw_status(layout: UILayout, action_setup: ActionConstraintSetup):
    """
    There are a lot of ways to create incorrect Action setups, so give
    the user a warning in those cases.
    """
    split = label_split(layout, text="Status:")

    if action_setup.trans_min == action_setup.trans_max:
        col = split.column(align=True)
        col.alert = True
        col.label(text="Min and max value are the same!")
        col.label(text=iface_("Will be stuck reading frame {frame}!").format(frame=action_setup.frame_start))
        return

    if action_setup.frame_start == action_setup.frame_end:
        col = split.column(align=True)
        col.alert = True
        col.label(text="Start and end frame cannot be the same!")
        return

    default_frame = action_setup.get_default_frame()

    if abs(default_frame - round(default_frame)) < 0.001:
        split.label(text=iface_("Default Frame: {frame}").format(frame=round(default_frame, 2)))
    else:
        split.alert = True
        split.label(
            text=iface_("Default Frame: {frame} (Should be a whole number!)").format(frame=round(default_frame, 2))
        )


registry = (
    CLOUDRIG_OT_action_new,
    CLOUDRIG_OT_jump_to_action_setup,
    CLOUDRIG_UL_action_setups,
)
