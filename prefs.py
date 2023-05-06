from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty
import bpy
from . import rigs

def refresh_rig_type_list(context=None):
    if not context:
        context = bpy.context
    prefs = context.preferences.addons[__package__].preferences
    prefs.rig_type_list.clear()
    for rig_file_name, rig_module in rigs.rig_types.items():
        pretty_name = rig_file_name.replace("cloud_", "").replace("_", " ").title().replace("Fk", "FK").replace("Ik", "IK")

        type_info = prefs.rig_type_list.add()
        type_info.name = pretty_name
        type_info.file_name = rig_file_name

class CloudRigElementTypeInfo(PropertyGroup):
    """Purely for UI purposes, so we can store a list of strings in the RNA that
    represent the list of available rig types. We need that in the RNA so we can use
    prop_search() to draw a nice list that the user can type into to filter and search."""
    name: StringProperty(
        name = "UI Name", 
        description = "Pretty, title-case name that will be displayed in the UI"
    )
    file_name: StringProperty(
        name = "File Name", 
        description = "Name used under the hood for matching the element type to its implementation python file"
    )

class CloudRigPreferences(AddonPreferences):
    bl_idname = __package__

    rig_type_list: CollectionProperty(type=CloudRigElementTypeInfo)

registry = [
    CloudRigElementTypeInfo,
    CloudRigPreferences
]

def register():
    refresh_rig_type_list()