import bpy
from bpy.app.handlers import persistent
from .utils.ui import is_cloud_metarig
from .utils.object import set_enum_property_by_integer

# This should get a version bump whenever there is a change that affects metarigs.
# For example, changing names of rig types, splitting an old rig type into multiple,
# changing names of parameters, etc.
cloud_metarig_version = 11

def update_enum_property(owner, old_key, new_key, int_value):
	enum_string_value = set_enum_property_by_integer(owner, new_key, int_value)
	if enum_string_value:
		print(f"Updated enum property {old_key}->{new_key}, value: {enum_string_value}")
	else:
		# If an enum property's definition is lost, their string value is lost 
		# and is left with an int. In this case, just back up that int.
		owner[new_key] = int_value

def rename_parameters(metarig, dictionary):
	"""When we change the python name of a parameter, this can be used to find the old data
	and put it on the property with the new name."""
	for pb in metarig.pose.bones:
		if pb.rigify_type == '': continue
		for old_key in list(pb.rigify_parameters.keys()):
			if old_key in dictionary:
				new_key = dictionary[old_key]
				value = pb.rigify_parameters[old_key]
				try:
					print(f"Rename param {pb.name}: {old_key}->{new_key}")
					setattr(pb.rigify_parameters, new_key, value)
				except:
					update_enum_property(pb.rigify_parameters, old_key, new_key, value)

def version_cloud_metarig(metarig):
	"""Convert older CloudRig metarigs to work with the current version of
	CloudRig as well as possible. They will still need some manual cleanup!!!"""
	data = metarig.data
	target_rig = data.rigify_target_rig

	# NOTE on limitations:
	# The old value is not stored in the file at all if it was left as default, so
	# there's no way to guarantee correct versioning when changing the default value of a parameter.
	# So, make really damn sure that default values are correct when first implementing them!

	# Beginning of metarig versioning: 2020-07-22.
	print(f"CloudRig Versioning: {metarig.name} bumping version {data.cloudrig_parameters.version} -> {cloud_metarig_version}")
	if data.cloudrig_parameters.version < 1:
		pass
		# TODO: Assume that version 0.0 is the metarigs in CoffeeRun crowd.blend, and try to make them work with current CloudRig.
	if data.cloudrig_parameters.version < 2:
		print("2:")
		dictionary = {
			"CR_constraints_additive" : "CR_copy_constraints_additive"
			,"CR_bone_type" : "CR_bone_copy_type"
			,"CR_show_spline_ik_settings" : "CR_spline_ik_show_settings"
			,"CR_match_hooks_to_bones" : "CR_spline_ik_match_hooks"
			,"CR_curve_handle_length" : "CR_spline_ik_handle_length"
			,"CR_num_hooks" : "CR_spline_ik_hooks"
			,"CR_subdivide_deform" : "CR_spline_ik_subdivide"
			,"CR_create_ik_spine" : "CR_spine_use_ik"
			,"CR_double_controls" : "CR_spine_double"
			,"CR_double_ik_control" : "CR_limb_double_ik"
			,"CR_use_foot_roll" : "CR_leg_use_foot_roll"
			,"CR_leg_heel_bone" : "CR_leg_heel_bone"
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
			,"CR_custom_bone_parent" : "CR_copy_parent"
			,"CR_transform_locks" : "CR_copy_locks"
			,"CR_layers" : "CR_copy_layers"
			,"CR_custom_props" : "CR_copy_props"
			,"CR_ik_settings" : "CR_copy_ik_settings"
			,"CR_tweak_bbone_props" : "CR_copy_bbone_props"
			,"CR_ankle_pivot_bone" : "CR_leg_heel_bone"
		}
		rename_parameters(metarig, dictionary)
	if data.cloudrig_parameters.version < 3:
		print("3:")
		for pb in metarig.pose.bones:
			if 'CR_create_deform_bone' in pb.rigify_parameters.keys():
				pb.bone.use_deform = pb.rigify_parameters['CR_create_deform_bone']
	if data.cloudrig_parameters.version < 4:
		print("4:")
		for pb in metarig.pose.bones:
			# Spine rig no longer includes a neck and head.
			if 'CR_spine_length' in pb.rigify_parameters.keys():
				spine_length = pb.rigify_parameters['CR_spine_length']
				spine_bone = pb
				for i in range(spine_length):
					if len(spine_bone.children)==0: break
					spine_bone = spine_bone.children[0]
				if spine_bone.rigify_type=='':
					neck_bone = spine_bone
					for i in range(2):
						if not neck_bone.bone.use_connect: continue
						neck_bone.rigify_type = 'cloud_fk_chain'
						neck_bone.rigify_parameters['CR_chain_segments'] = 1
						neck_bone.rigify_parameters['CR_chain_sharp'] = True
						neck_bone.rigify_parameters['CR_fk_chain_double_first'] = False
						neck_bone.rigify_parameters['CR_fk_chain_hinge'] = True

						if 'CR_BG_LAYERS_stretch_controls' in spine_bone.rigify_parameters.keys():
							neck_bone.rigify_parameters['CR_BG_LAYERS_stretch_controls'] = spine_bone.rigify_parameters['CR_BG_LAYERS_stretch_controls']
						if 'CR_BG_stretch_controls' in spine_bone.rigify_parameters.keys():
							neck_bone.rigify_parameters['CR_BG_stretch_controls'] = spine_bone.rigify_parameters['CR_BG_stretch_controls']

						if len(neck_bone.children) == 0:
							break
						neck_bone = neck_bone.children[0] # Head bone

			# Curve target selection is now a PointerProperty instead of StringProperty.
			if 'CR_target_curve_name' in pb.rigify_parameters.keys():
				curve_name = pb.rigify_parameters['CR_target_curve_name']
				while curve_name.startswith(" "):
					curve_name = curve_name[1:]

				pb.rigify_parameters['CR_curve_target'] = bpy.data.objects.get(curve_name)
	if data.cloudrig_parameters.version < 5:
		print("5:")
		for pb in metarig.pose.bones:
			# cloud_limb is now only for arms, leg is split off into cloud_leg.
			if pb.rigify_type=='cloud_limbs':
				if 'CR_limb_type' in pb.rigify_parameters.keys() and pb.rigify_parameters['CR_limb_type']==1:
					pb.rigify_type = 'cloud_leg'
				else:
					pb.rigify_type = 'cloud_limb'

		dictionary = {
			"CR_leg_use_foot_roll" : "CR_leg_use_foot_roll"
			,"CR_leg_heel_bone" : "CR_leg_heel_bone"
		}
		rename_parameters(metarig, dictionary)
	if data.cloudrig_parameters.version < 6:
		print("6:")
		# Renamed actions to action_slots
		if 'actions' in data.cloudrig_parameters:
			for old_slot in data.cloudrig_parameters['actions']:
				slot_data = old_slot.to_dict()
				new_slot = data.cloudrig_parameters.action_slots.add()
				for key in slot_data.keys():
					try:
						setattr(new_slot, key, old_slot[key])
					except:
						update_enum_property(new_slot, key, key, old_slot[key])
	if data.cloudrig_parameters.version < 7:
		print("7:")
		# Split up cloud_bone into cloud_copy and cloud_tweak
		dictionary = {
			'CR_bone_parent' : 'CR_copy_parent',
			'CR_bone_constraints_additive' : 'CR_tweak_constraints_additive',
			'CR_bone_transforms' : 'CR_tweak_transforms',
			'CR_bone_locks' : 'CR_tweak_locks',
			'CR_bone_rot_mode' : 'CR_tweak_rot_mode',
			'CR_bone_shape' : 'CR_tweak_shape',
			'CR_bone_group' : 'CR_tweak_group',
			'CR_bone_layers' : 'CR_tweak_layers',
			'CR_bone_ik_settings' : 'CR_tweak_ik_settings',
			'CR_bone_bbone_props' : 'CR_tweak_bbone_props',
		}
		rename_parameters(metarig, dictionary)
		for pb in metarig.pose.bones:
			if pb.rigify_type=='cloud_bone':
				if 'CR_bone_copy_type' in pb.rigify_parameters and pb.rigify_parameters['CR_bone_copy_type']==1:
					pb.rigify_type = 'cloud_tweak'
				else:
					pb.rigify_type = 'cloud_copy'
				print(f"{pb.name} rigify_type: cloud_bone -> {pb.rigify_type}")

			# Demote uses of cloud_eye to cloud_aim
			# (This was done in a previous version but I forgot to add versioning code)
			if pb.rigify_type=='cloud_eye':
				pb.rigify_type = 'cloud_aim'
				print(f"{pb.name} rigify_type: cloud_eye -> {pb.rigify_type}")
	if data.cloudrig_parameters.version < 8:
		print("8:")
		# Move various parameters and functionality to cloud_base.
		dictionary = {
			'CR_copy_parent' : 'CR_base_parent',
			'CR_face_chain_relink' : 'CR_base_relink'
		}
		rename_parameters(metarig, dictionary)
		# CR_fk_chain_def_parenting turns from a checkbox to a string input, tricky.
		if target_rig:
			for pb in metarig.pose.bones:
				if 'CR_fk_chain_def_parenting' in pb.rigify_parameters and pb.rigify_parameters['CR_fk_chain_def_parenting']:
					org_bone = target_rig.data.bones.get("ORG-"+pb.name)
					parent = org_bone.parent
					def_name = parent.name.replace("ORG", "DEF")
					pb.rigify_parameters['CR_base_parent'] = def_name
					print(f"Convert param {pb.name}: CR_fk_chain_def_parenting -> CR_base_parent ({def_name})")
	if data.cloudrig_parameters.version < 9:
		print("9:")
		# Rigify now supports CollectionProperty parameters, so we no longer need to store
		# the parent switching list on bpy.types.Bone.
		for pb in metarig.pose.bones:
			b = pb.bone
			if 'parent_slots' in b.keys():
				for i, old_slot in enumerate(b['parent_slots']):
					new_slot = pb.rigify_parameters.CR_base_parent_slots.add()
					new_slot.name = old_slot['name']
					new_slot.bone = old_slot['bone']
				del b['parent_slots']
				pb.rigify_parameters.CR_base_active_parent_slot_index = b['active_parent_slot_index']
				del b['active_parent_slot_index']
	if data.cloudrig_parameters.version < 10:
		print("10:")
		# Change the experimental Sprite Fright eye rig back to the standard aim rig
		for pb in metarig.pose.bones:
			if pb.rigify_type=='sprite_fright.eye':
				pb.rigify_type = 'cloud_aim'
				rename_parameters(metarig, {'CR_sprite_eye_highlight' : 'CR_aim_highlight'})
	if data.cloudrig_parameters.version < 11:
		print("11:")
		# Rename eye highlight parameter to be more generic
		rename_parameters(metarig, {'CR_aim_highlight' : 'CR_aim_eye_highlight'})
		rename_parameters(metarig, {'CR_aim_eye_highlight' : 'CR_aim_create_sub_control'})
		# Changed the default of CR_fk_chain_double_first from True to False.

@persistent
def update_all_metarigs(dummy):
	cloud_metarigs = [o for o in bpy.data.objects if o.type=='ARMATURE' and is_cloud_metarig(o)]
	for metarig in cloud_metarigs:
		if metarig.data.cloudrig_parameters.version == cloud_metarig_version:
			continue
		if metarig.data.cloudrig_parameters.version > cloud_metarig_version:
			print(f"\tFound a metarig with a higher metarig version than the current: {metarig.name}")
			print("\tIt must have been created with a newer version of CloudRig, and won't behave as expected.")
			print("\tYou should update CloudRig!")
			continue
		version_cloud_metarig(metarig)
		metarig.data.cloudrig_parameters.version = cloud_metarig_version

def register():
	bpy.app.handlers.load_post.append(update_all_metarigs)

def unregister():
	bpy.app.handlers.load_post.remove(update_all_metarigs)
