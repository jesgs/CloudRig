from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty
import bpy
from . import rigs

def init_element_module_list(context=None):
    if not context:
        context = bpy.context
    prefs = context.preferences.addons[__package__].preferences
    prefs.rig_type_list.clear()
    for rig_file_name, rig_module in rigs.rig_modules.items():
        if not hasattr(rig_module, 'Rig'):
            continue
        rig_class = rig_module.Rig

        type_info = prefs.rig_type_list.add()
        type_info.name = rig_class.ui_name
        type_info.module_name = rig_file_name

class CloudRigElementTypeInfo(PropertyGroup):
    """Purely for UI purposes, so we can store a list of strings in the RNA that
    represent the list of available rig types. We need that in the RNA so we can use
    prop_search() to draw a nice list that the user can type into to filter and search."""
    name: StringProperty(
        name = "UI Name", 
        description = "Pretty, title-case name that will be displayed in the UI"
    )
    module_name: StringProperty(
        name = "Rig Module Name", 
        description = "Name used under the hood for matching the element type to its implementation module (ie. Python file)"
    )

class CloudRigPreferences(AddonPreferences):
    bl_idname = __package__

    rig_type_list: CollectionProperty(type=CloudRigElementTypeInfo)

registry = [
    CloudRigElementTypeInfo,
    CloudRigPreferences
]

def register():
    init_element_module_list()