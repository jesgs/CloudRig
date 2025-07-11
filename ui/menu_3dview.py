# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Menu


class VIEW3D_MT_cloudrig(Menu):
    bl_label = "CloudRig"
    bl_idname = "VIEW3D_MT_cloudrig"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        target_rig = obj.cloudrig.generator.target_rig

        text = "Re-Generate Rig" if target_rig else "Generate Rig"
        layout.operator('pose.cloudrig_generate', text=text)

        if context.mode in {'POSE', 'EDIT_ARMATURE'}:
            layout.separator()
            layout.operator(
                'pose.cloudrig_copy_component', icon='DUPLICATE', text="Copy Component"
            )
            layout.operator(
                'pose.cloudrig_symmetrize_components',
                icon='MOD_MIRROR',
                text="Symmetrize Components",
            )


def draw_cloudrig_menu(self, context):
    if (
        context.object
        and context.object.type == 'ARMATURE'
        and context.object.cloudrig.enabled
    ):
        self.layout.menu(VIEW3D_MT_cloudrig.bl_idname)


registry = [VIEW3D_MT_cloudrig]


def register():
    bpy.types.VIEW3D_MT_editor_menus.append(draw_cloudrig_menu)


def unregister():
    bpy.types.VIEW3D_MT_editor_menus.remove(draw_cloudrig_menu)
