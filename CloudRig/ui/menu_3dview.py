# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Context, Menu

from ..generation.cloudrig import is_cloud_metarig, is_generated_cloudrig


class VIEW3D_MT_cloudrig(Menu):
    bl_label = "CloudRig"
    bl_idname = "VIEW3D_MT_cloudrig"

    def draw(self, context: Context):
        layout = self.layout
        active_obj = context.active_object
        is_active_generated = is_generated_cloudrig(active_obj)
        target_rig = active_obj.cloudrig.generator.target_rig

        text = "Re-Generate Rig" if target_rig or is_active_generated else "Generate Rig"
        layout.operator('pose.cloudrig_generate', text=text, icon='FILE_REFRESH')
        layout.operator('object.cloudrig_metarig_toggle', icon='EVENT_TAB')

        if is_active_generated:
            layout.operator('object.cloudrig_push_to_metarig', icon='IMPORT')
        elif context.mode in {'POSE', 'EDIT_ARMATURE'}:
            layout.separator()
            layout.operator('pose.cloudrig_copy_component', icon='DUPLICATE', text="Copy Component")
            layout.operator(
                'pose.cloudrig_symmetrize_components',
                icon='MOD_MIRROR',
                text="Symmetrize Components",
            )


def draw_cloudrig_menu(self, context: Context):
    obj = context.active_object
    if is_cloud_metarig(obj) or is_generated_cloudrig(obj):
        self.layout.menu(VIEW3D_MT_cloudrig.bl_idname)


registry = [VIEW3D_MT_cloudrig]


def register():
    bpy.types.VIEW3D_MT_editor_menus.append(draw_cloudrig_menu)


def unregister():
    bpy.types.VIEW3D_MT_editor_menus.remove(draw_cloudrig_menu)
