from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty
import bpy
from . import rigs

def refresh_rig_type_list(context=None):
    if not context:
        context = bpy.context
    prefs = context.preferences.addons[__package__].preferences
    prefs.rig_type_list.clear()
    for rig_type_name, rig_module in rigs.rig_types.items():
        entry = prefs.rig_type_list.add()
        entry.name = rig_type_name

class CloudRigElementType(PropertyGroup):
	"""Purely for UI purposes, so we can store a list of strings in the RNA that
	represent the list of available rig types. We need that in the RNA so we can use
	prop_search() to draw a nice list that the user can type into to filter and search."""
	name: StringProperty()

class CloudRigPreferences(AddonPreferences):
	# this must match the addon name, use '__package__'
	# when defining this in a submodule of a python package.
	bl_idname = __package__

	rig_type_list: CollectionProperty(type=CloudRigElementType)

registry = [
    CloudRigElementType,
    CloudRigPreferences
]

def register():
    refresh_rig_type_list()