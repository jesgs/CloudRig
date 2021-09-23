from rigify import rig_lists

def find_rig_class(rig_type):
	if rig_type == "":
		return None
	rig_type_sanitized = rig_type.replace(" ", "")
	if rig_type_sanitized not in rig_lists.rigs:
		return None
	rig_module = rig_lists.rigs[rig_type_sanitized]["module"]

	return rig_module.Rig
