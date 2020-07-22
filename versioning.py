import bpy
from bpy.app.handlers import persistent
from datetime import datetime as dt
from .ui import is_cloud_metarig

blender_version = float(str(bpy.app.version[0]) + "." + str(bpy.app.version[1]) + str(bpy.app.version[2]))

date_format = "%Y-%m-%d"
build_date = dt.strptime(bpy.app.build_commit_date.decode(), date_format)

def is_before_register_commit():
	# https://developer.blender.org/rBAc20728941cf32e9cbe2f0bcd6ebae27bb6d01238
	register_commit_date = dt.strptime("2020-06-24", date_format)
	return build_date < register_commit_date

def do_blender_versioning():
	"""Code that needs to run only for specific versions of Blender."""
	pass

def rename_parameters(metarig, dictionary):
	for pb in metarig.pose.bones:
		if pb.rigify_type!='':
			for old_key in pb.rigify_parameters.keys():
				if old_key in dictionary:
					new_key = dictionary[old_key]
					value = pb.rigify_parameters[old_key]
					try:
						setattr(pb.rigify_parameters, new_key, value)
					except:
						# We assume this fails because we're trying to assign an int to a string enum... The solution couldn't be simpler...!
						rna_class = bpy.types.PropertyGroup.bl_rna_get_subclass_py('RigifyParameters')
						enum_prop = rna_class.bl_rna.properties.get(new_key)
						if enum_prop:
							# This will only work for the current version
							enum_string_value = enum_prop.enum_items[value].name
							print(f"Updated enum property {old_key}->{new_key}, value: {enum_string_value}")
							setattr(pb.rigify_parameters, new_key, enum_string_value)
						else:
							# For other versions, just back it up.
							pb.rigify_parameters[new_key] = value

def version_cloud_metarig(metarig):
	"""Convert older CloudRig metarigs to work with the current version of the addon as well as possible."""
	data = metarig.data
	# Beginning of metarig versioning: 2020-07-22.
	# I should've started this sooner. Metarigs older than this are not guaranteed backwards compatibility.
	if data.cloudrig_parameters.version == 0.0:
		dictionary = {
			"CR_constraints_additive" : "CR_bone_constraints_additive"
			,"CR_copy_type" : "CR_bone_copy_type"
			,"CR_show_spline_ik_settings" : "CR_spline_ik_show_settings"
			,"CR_match_hooks_to_bones" : "CR_spline_ik_match_hooks"
			,"CR_curve_handle_length" : "CR_spline_ik_handle_length"
			,"CR_num_hooks" : "CR_spline_ik_hooks"
			,"CR_subdivide_deform" : "CR_spline_ik_subdivide"
			,"CR_create_ik_spine" : "CR_spine_use_ik"
			,"CR_double_controls" : "CR_spine_double"
			,"CR_double_ik_control" : "CR_limb_double_ik"
			,"CR_use_foot_roll" : "CR_limb_use_foot_roll"
			,"CR_limb_heel_bone" : "CR_limb_heel_bone"
			,"CR_ik_at_tail" : "CR_ik_chain_at_tip"
			,"CR_world_aligned_controls" : "CR_ik_chain_world_aligned"
			,"CR_use_pole_target" : "CR_ik_chain_use_pole"
			,"CR_center_all_fk" : "CR_fk_chain_display_center"
			,"CR_double_first_control" : "CR_fk_chain_double_first"
			,"CR_use_fk_hinge" : "CR_fk_chain_hinge"
			,"CR_use_custom_limb_name" : "CR_fk_chain_use_limb_name"
			,"CR_custom_limb_name" : "CR_fk_chain_limb_name"
			,"CR_use_custom_category_name" : "CR_fk_chain_use_category_name"
			,"CR_custom_category_name" : "CR_fk_chain_category_name"
			,"CR_hook_name" : "CR_curve_hook_name"
			,"CR_controls_for_handles" : "CR_curve_controls_for_handles"
			,"CR_rotatable_handles" : "CR_curve_rotatable_handles"
			,"CR_separate_radius" : "CR_curve_separate_radius"
			,"CR_target_curve" : "CR_curve_target"
			,"CR_deform_segments" : "CR_chain_segments"
			,"CR_bbone_density" : "CR_chain_bbone_density"
			,"CR_shape_key_helpers" : "CR_chain_shape_key_helpers"
			,"CR_sharp_sections" : "CR_chain_sharp"
			,"CR_smooth_spline" : "CR_chain_smooth_spline"
			,"CR_cap_control" : "CR_chain_tip_control"
			,"" : ""
		}
		rename_parameters(metarig, dictionary)
		data.cloudrig_parameters.version = 0.1
		# TODO: Assume that version 0.0 is the metarigs in CoffeeRun crowd.blend, and try to make them work with current CloudRig.

def do_metarig_versioning():
	cloud_metarigs = [o for o in bpy.data.objects if o.type=='ARMATURE' and is_cloud_metarig(o)]
	for metarig in cloud_metarigs:
		version_cloud_metarig(metarig)

@persistent
def do_versioning(dummy):
	do_blender_versioning()
	do_metarig_versioning()

def register():
	bpy.app.handlers.load_post.append(do_versioning)

def unregister():
	bpy.app.handlers.load_post.remove(do_versioning)
