import os
import bpy

# We can store multiple preview collections here,
# however in this example we only store "main"
cloudrig_icons = {}

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

def unregister():
    for pcoll in cloudrig_icons.values():
        bpy.utils.previews.remove(pcoll)
    cloudrig_icons.clear()