# Not a fan of a file called utils/misc.py but man, these functions
# really don't fit anywhere.

from rigify import rig_lists
import addon_utils

def find_rig_class(rig_type):
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
	if addon_name in context.workspace.owner_ids:	# Not sure why this is called owner_ids, but it seems to contain a list of enabled addons in this workspace.
		return addon_utils.check(addon_name)[1]
	return False