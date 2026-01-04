import bpy

from ..generation.cloudrig import is_cloud_metarig


def draw_cloudrig_popover(self, context):
    if not is_cloud_metarig(context.active_object):
        return
    layout = self.layout
    # layout.separator_spacer()
    layout.popover(
        panel="POSE_PT_CloudRig",
        icon='OUTLINER_DATA_ARMATURE',
        text="",
    )


def register():
    bpy.types.VIEW3D_HT_header.append(draw_cloudrig_popover)

def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_cloudrig_popover)
