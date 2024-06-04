import os
import bpy

# We can store multiple preview collections here,
# however in this example we only store "main"
cloudrig_icons = {}

class PreviewsExamplePanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Previews Example Panel"
    bl_idname = "OBJECT_PT_previews"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.operator("render.render", icon_value=get_cloudrig_icon_id("vertical_twoway_arrows"))

def get_cloudrig_icon_id(icon_name) -> int:
    pcoll = cloudrig_icons["main"]
    icon_id = -1
    icon = pcoll.get(icon_name)
    if icon:
        icon_id = icon.icon_id
    return icon_id

def load_icon(icon_name):
    icons_dir = os.path.dirname(__file__)

    pcoll = cloudrig_icons["main"]
    pcoll.load(icon_name, os.path.join(icons_dir, f"{icon_name}.svg"), 'IMAGE')

    return pcoll

def register():
    pcoll = bpy.utils.previews.new()
    cloudrig_icons["main"] = pcoll
    load_icon("vertical_twoway_arrows")

    bpy.utils.register_class(PreviewsExamplePanel)


def unregister():
    for pcoll in cloudrig_icons.values():
        bpy.utils.previews.remove(pcoll)
    cloudrig_icons.clear()

    bpy.utils.unregister_class(PreviewsExamplePanel)