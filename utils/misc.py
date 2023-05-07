# Not a fan of a file called utils/misc.py but man, these functions
# really don't fit anywhere.

from rigify import rig_lists
import addon_utils
import bpy

def get_active_pose_bone(context):
	"""Return the PoseBone of the active bone. Can be None."""
	return context.object.pose.bones.get(context.active_bone.name)

def find_rig_class(rig_type):
	# TODO: This was a Rigify function that should now be deprecated!
	if rig_type == "":
		return None
	rig_type_sanitized = rig_type.replace(" ", "")
	if rig_type_sanitized not in rig_lists.rigs:
		return None
	rig_module = rig_lists.rigs[rig_type_sanitized]["module"]

	return rig_module.Rig

def check_addon(context, addon_name) -> bool:
	"""Same as addon_utils.check() but account for workspace-specific disabling.
	Return whether an addon is enabled in this context.
	"""
	addon_enabled_in_userprefs = addon_utils.check(addon_name)[1]
	if addon_enabled_in_userprefs and context.workspace.use_filter_by_owner:
		# Not sure why it's called owner_ids, but it contains a list of enabled addons in this workspace.
		addon_enabled_in_workspace = addon_name in context.workspace.owner_ids
		return addon_enabled_in_workspace

	return addon_enabled_in_userprefs

def get_addon_prefs(context=None):
	if not context:
		context = bpy.context
	return context.preferences.addons[__package__.split(".")[0]].preferences
