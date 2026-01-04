import bpy

from ..bs_utils.prefs import get_addon_prefs
from ..generation.cloudrig import is_cloud_metarig


def draw_cloudrig_popover(self, context):
    prefs = get_addon_prefs(context)
    if prefs.ui_mode == 'PROPERTIES':
        return
    if not is_cloud_metarig(context.active_object) and prefs.ui_mode != 'HEADER':
        return
    layout = self.layout
    layout.popover(
        panel="POSE_PT_CloudRig_Popover",
        icon='OUTLINER_DATA_ARMATURE',
        text="",
    )


def register():
    bpy.types.VIEW3D_HT_header.append(draw_cloudrig_popover)

def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_cloudrig_popover)
