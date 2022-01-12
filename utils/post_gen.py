"""
This file contains a list of utility functions that can be useful to call from
post-generation scripts.
"""

import bpy
from rna_prop_ui import rna_idprop_ui_prop_update

sides = {'.L' : 'Left', '.R' : 'Right'}
suffixes = list(sides.keys())

def set_custom_property_value(rig, bone_name, prop, value):
	"""Assign the value of a custom property."""
	bone = rig.pose.bones.get(bone_name)
	if not bone: return
	if not prop in bone: return	# We don't want to create properties here!
	bone[prop] = value
	rna_idprop_ui_prop_update(bone, prop)

def set_custom_property_default(rig, bone_name, prop, value):
	"""Assign the value of a custom property as the default and current values."""
	bone = rig.pose.bones.get(bone_name)
	if not bone: return
	if not prop in bone: return	# We don't want to create properties here!
	ui_props = bone.id_properties_ui(prop)
	ui_props.update(default=value)
	set_custom_property_value(rig, bone_name, prop, value)

def link_script(rig, prop_name: str, filepath: str, script_name: str):
	"""Load a text datablock by linking from a blend file, and attach it to the rig."""
	if script_name in bpy.data.texts:	# If already loaded, don't reload it.
		text = bpy.data.texts[script_name]
		if text.filepath == "":	# If the text file is internal, nuke it.
			bpy.data.texts.remove(text)

	rel_path = bpy.path.relpath(filepath)
	if script_name not in bpy.data.texts:
		with bpy.data.libraries.load(rel_path, link=True) as (data_from, data_to):
			data_to.texts = [script_name]
		text = bpy.data.texts[script_name]
	rig.data[prop_name] = text
	exec(text.as_string(), {})

def rename_bone(rig, name_from, name_to):
	"""Rename a bone and account for all the things that could break when doing so.
	This means also replacing the bone's name in the rig's UI data and in driver
	data paths.
	"""
	bone = rig.pose.bones.get(name_from)
	if not bone:
		return
	bone.name = name_to
	replace_in_ui_data(rig, name_from, name_to)
	replace_driver_var_path(rig, name_from, name_to)

def rename_custom_property(rig, bone_name, name_from, name_to):
	"""Rename a bone custom property, and account for all the things that could 
	break when doing so. This means also replacing the bone's name in the rig's 
	UI data and in driver data paths."""
	pb = rig.pose.bones.get(bone_name)
	if name_from not in pb:
		return
	from_ui_data = pb.id_properties_ui(name_from)
	pb[name_to] = pb[name_from]
	pb.id_properties_ui(name_to).update_from(from_ui_data)
	pb.property_overridable_library_set(f'["{name_to}"]', True)
	replace_driver_var_path(rig, name_from, name_to)
	replace_in_ui_data(rig, name_from, name_to)
	del pb[name_from]

def replace_in_ui_data(rig, from_str, to_str):
	"""Replace occurrences of a string in the rig's UI Data"""
	def replace_data(prop_owner, prop_name):
		if prop_name not in prop_owner:
			return
		data_str = str(prop_owner[prop_name].to_dict())
		data_str = data_str.replace(from_str, to_str)
		prop_owner[prop_name] = eval(data_str)
	
	replace_data(rig.data, 'ui_data')
	replace_data(rig.data, 'gizmo_interactions')

def replace_driver_var_path(rig, from_str, to_str):
	"""Replace a string in all driver data paths of a rig."""
	datablocks = [rig, rig.data]
	for db in datablocks:
		if not db.animation_data:
			continue
		for fc in db.animation_data.drivers:
			for var in fc.driver.variables:
				if var.type == 'SINGLE_PROP':
					for t in var.targets:
						t.data_path = t.data_path.replace(from_str, to_str)

def clean_properties(rig):
	"""Remove useless custom props; 
	These were causing crashes when trying to open anim files with Ellie re-generated with 
	latest CloudRig on 2021 Nov 4.
	"""

	bad_prop_names = ['bone_gizmo', 'enable_bone_gizmo', 'pizmo_vis_mesh', 'BoolToolRoot', 'active_islands_index', 'als', 'hops', 'island_groups', 'tissue_tessellate', 'vs', 'matrix_world', 'BBN_info']
	rigify = ['rigify_type', 'rigify_parameters']
	def clean_prop_owner(prop_owner, bad_keys):
		for key, value in list(prop_owner.items()):
			if key in bad_keys:
				del prop_owner[key]

	for ob in bpy.data.objects:
		clean_prop_owner(ob, bad_prop_names)
		if ob.data:
			clean_prop_owner(ob.data, bad_prop_names)
		if ob.type == 'ARMATURE':
			if ob.data.rigify_target_rig:
				for pb in ob.pose.bones:
					clean_prop_owner(pb, bad_prop_names)
			else:
				for pb in ob.pose.bones:
					clean_prop_owner(pb, bad_prop_names + rigify)

def check_wrong_drivers(rig):
	# Check for metarig driver vars that target the metarig.
	for o in bpy.data.objects:
		if o.type == 'ARMATURE' and o.data.rigify_target_rig:
			for fc in o.animation_data.drivers:
				for var in fc.driver.variables:
					if var.type == 'TRANSFORMS':
						for t in var.targets:
							if t.id == o:
								print("Probably broken: Driver targets metarig bone transform: " + fc.data_path)
								t.id = rig
								print("Fixed now, but you gotta re-generate.")

def GLOBAL_rename_obdatas():
	# Ensure object data names are correct
	for o in bpy.data.objects:
		if not o.data: continue
		data_name = "Data_"+o.name
		if o.data.name != data_name:
			o.data.name = data_name
