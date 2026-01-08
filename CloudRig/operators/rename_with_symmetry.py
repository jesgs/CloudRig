# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import EditBone, Object, Operator, PoseBone, UILayout
from bpy.utils import flip_name

from ..bs_utils.hotkeys import register_hotkey
from ..generation.cloudrig import is_cloud_metarig
from ..generation.naming import uniqify


class OBJECT_OT_rename_with_symmetry(Operator):
    """Rename active object or bone while accounting for symmetry when possible."""

    bl_idname = "object.rename_with_symmetry"
    bl_label = "Smart Rename"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'new_name'

    def update_new_name(self, context):
        for item, (op_prop_name, _desired_name, new_name) in get_future_names(self, context).items():
            setattr(self, op_prop_name, new_name)
    new_name: StringProperty(
        name="Name",
        description="Value to set the name of the active element to.",
        update=update_new_name,
    )
    use_symmetry: BoolProperty(
        name="Use Symmetry",
        description="Rename the symmetrical object/bone, not just the active one",
        default=True,
    )

    name_display: StringProperty(
        name="Final Name",
        description="Actual name that will be given to the active item, which may be different from the input if the desired name was already taken.",
    )
    name_display_flipped: StringProperty(
        name="Final Name",
        description="Actual name that will be given to the opposite item, which may be different from the input if the desired name was already taken.",
    )

    @property
    def new_name_opposite(self):
        return flip_name(self.new_name)

    @classmethod
    def poll(cls, context):
        if get_active_item(context) is None:
            cls.poll_message_set("Nothing to rename.")
            return False
        return True

    def invoke(self, context, _event):
        self.rename_map = {}
        item = get_active_item(context)
        self.new_name = item.name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        name_row = layout.row(align=True)
        item = get_active_item(context)
        icon_id = UILayout.icon(item)
        name_row.prop(self, 'new_name', text="", icon_value=icon_id)
        opposite_item = get_opposite_item(item)
        if opposite_item and opposite_item != item:
            toggle_row = name_row.row(align=True)
            toggle_row.enabled = opposite_item is not None
            toggle_row.prop(self, 'use_symmetry', text="", icon='MOD_MIRROR')

        if self.new_name == item.name:
            layout.label(text="Name unchanged.")
            return

        box = layout.box()
        box.label(text="Rename:")

        warn = 0
        for item, (op_prop_name, desired_name, new_name), in get_future_names(self, context).items():
            icon_id = UILayout.icon(item)
            self.draw_rename_preview(box, item, op_prop_name, icon_value=icon_id)
            if new_name != desired_name:
                warn += 1
        if warn:
            row = box.row()
            row.alert = True
            s = "s" if warn > 1 else ""
            row.label(text=f"Name{s} will be incremented.", icon='ERROR')

    def draw_rename_preview(self, layout, item, op_prop_name: str, icon_value: int):
        split = layout.row().split(align=True, factor=0.45)
        split.enabled = False
        row = split.row()
        row.prop(item, 'name', text="", icon_value=icon_value)
        split = split.row().split(factor=0.1)
        split.row().label(text="\u279C")
        split.row().prop(self, op_prop_name, text="", icon_value=icon_value)

    def execute(self, context):
        counter = 0
        for item, (_prop_name, _desired_name, new_name) in get_future_names(self, context).items():
            if item.name != new_name:
                counter += 1
            item.name = new_name

        msg = "Did nothing"
        if counter > 0:
            msg = "Renamed"
        if counter > 1:
            msg += " (Symmetrized)"

        if context.mode == 'EDIT_ARMATURE' and is_cloud_metarig(context.active_object):
            # Refresh pose bone data...
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, msg+"!")
        return {'FINISHED'}


def get_collprop(item):
    if isinstance(item, Object):
        return bpy.data.objects
    elif isinstance(item, PoseBone):
        return item.id_data.pose.bones
    elif isinstance(item, EditBone):
        return item.id_data.edit_bones
    else:
        raise NotImplementedError(f"Data type not yet supported: {type(item)}")

def get_future_names(self, context) -> dict[Any, tuple[str, str, str]]:
    rename_dict = {}
    item = get_active_item(context)
    collprop = get_collprop(item)
    rename_dict[item] = (
        'name_display',
        self.new_name,
        uniqify(self.new_name, collprop, id=item)
    )

    if not self.use_symmetry:
        return rename_dict

    opposite_item = collprop.get(flip_name(item.name))
    if opposite_item:
        rename_dict[opposite_item] = (
            'name_display_flipped',
            flip_name(self.new_name),
            uniqify(flip_name(self.new_name), collprop, id=opposite_item)
        )

    return rename_dict

def get_active_item(context) -> Any | None:
    if context.mode == 'OBJECT' and context.object:
        return context.object
    elif context.mode in ('POSE', 'WEIGHT_PAINT') and context.active_pose_bone:
        return context.active_pose_bone
    elif context.mode == 'EDIT_ARMATURE':
        return context.active_bone

def get_opposite_item(item) -> Any | None:
    collprop = get_collprop(item)
    return collprop.get(flip_name(item.name))

registry = [OBJECT_OT_rename_with_symmetry]

def register():
    register_hotkey(
        OBJECT_OT_rename_with_symmetry.bl_idname,
        hotkey_kwargs={'type': "F2", 'value': "PRESS"},
        keymap_name='3D View',
    )
