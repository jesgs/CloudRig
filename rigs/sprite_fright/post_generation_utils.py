import bpy
from rna_prop_ui import rna_idprop_ui_prop_update
import sys
from ...cloudrig import area_names

sides = {'.L' : 'Left', '.R' : 'Right'}
suffixes = list(sides.keys())

def set_custom_property_value(rig, bone_name, prop, value):
	"Assign the value of a custom property."
	bone = rig.pose.bones.get(bone_name)
	if not bone: return
	if not prop in bone: return	# We don't want to create properties here!
	bone[prop] = value
	rna_idprop_ui_prop_update(bone, prop)

def link_script(rig, prop_name:str, filepath:str, script_name:str):
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

def create_selection_sets(context, selset_text: bpy.types.Text):
	"""Create selection sets."""
	selection_set_dict = eval(selset_text.as_string())
	from bone_selection_sets import from_json
	import json
	from_json(context, json.dumps(selection_set_dict))

def add_ui_data(rig, 
	area_identifier="misc_properties", row_name="row", col_name="", 
	info={'prop_bone' : "Properties", 'prop_id' : "prop"}
):
	assert area_identifier in area_names, f"Area identifier {area_identifier} must be one of {area_names}"
	assert 'prop_bone' in info and 'prop_id' in info, "UI data entry must have a property bone and property name."

	if info['prop_bone'] not in rig.pose.bones:
		print(f"Property bone not found: {info['prop_bone']}, skipping")
		return
	if info['prop_id'] not in rig.pose.bones[info['prop_bone']]:
		print(f"Property {info['prop_id']} not in bone: {info['prop_bone']}")
		return

	if area_identifier not in rig.data:
		rig.data[area_identifier] = {}
	area_dict = rig.data[area_identifier]
	if row_name not in area_dict:
		area_dict[row_name] = {}
	row = area_dict[row_name]
	if col_name=="":
		col_name = row_name
	row[col_name] = info
	print(f"    Added {col_name}")

def face_rig_tweaks(rig):
	"""Automate some tweaks on the face rig."""

	# Implement "Face Squash" property if it exists.
	prp_head = rig.pose.bones.get("PRP-Head")
	if prp_head and 'Face Squash' in prp_head:
		print("Implement 'Face Squash'...")
		for bn in ['DEF-Head_Top', 'DEF-Head', 'MSTR-H-Head_Bottom']:
			pb = rig.pose.bones.get(bn)
			if not pb: continue
			print("    " + pb.name)
			for prop_name in ['use_bulge_min', 'use_bulge_max']:
				pb.constraints[0].driver_remove(prop_name)
				d = pb.constraints[0].driver_add(prop_name).driver
				d.type = 'SCRIPTED'
				d.expression = '1-var'
				var = d.variables.new()
				var.targets[0].id = rig
				var.targets[0].data_path = f'pose.bones["PRP-Head"]["Face Squash"]'

	for suf in suffixes:
		# Add lip corner parent shifting to the UI
		ui_data = {
			'prop_bone' : f'CTR-LipCorner{suf}',
			'prop_id' : 'HeadJaw',
			'operator' : 'pose.cloudrig_snap_bake',
			'bones' : [f'CTR-LipCorner{suf}'],
		}
		add_ui_data(rig, 'face_settings', 'LipHeadJaw', f'{sides[suf]} Corner Top/Bot', ui_data)

		print("Disable Action constraints on lip corners when they are pinching...")
		for bn in ['P-STR-TIP-Lip_Top2', 'P-STR-Lip_Bottom2']:
			bone_name = bn + suf
			pb = rig.pose.bones.get(bone_name)
			if not pb: continue
			print("    " + pb.name)
			for c in pb.constraints:
				if c.type!='ACTION':
					continue
				driver = c.driver_remove('influence')
				driver = c.driver_add('influence').driver
				driver.expression = "1-var"
				var = driver.variables.new()
				var.targets[0].id = rig
				var.targets[0].data_path = f'pose.bones["CTR-LipCorner{suf}"]["Sharp"]'

		print("Move Copy Transforms constraints on the lips to the top of the constraint stack...")
		for bn in ['STR-Lip_Top2', 'STR-TIP-Lip_Top2', 'STR-Lip_Bottom2', 'STR-Lip_Bottom1']:
			bone_name = bn + suf
			pb = rig.pose.bones.get(bone_name)
			if not pb: continue
			print("    " + pb.name)
			for i, c in enumerate(pb.constraints):
				if c.type=='COPY_TRANSFORMS':
					pb.constraints.move(i, 0)

	# Parent top of head STR to a custom control
	bpy.ops.object.mode_set(mode='EDIT')
	master_control = rig.data.edit_bones.get('MSTR-Head_Top')
	if master_control:
		for head_end_name in ['STR-TIP-Head_Top', 'STR-TIP-Head']:
			head_bone = rig.data.edit_bones.get(head_end_name)
			if not head_bone: continue
			print("Parenting head tip to upper head master....")
			head_bone.parent = master_control
			break

	bpy.ops.object.mode_set(mode='OBJECT')

def sprite_post_gen_chores(context, charname:str, shared_script=True):
	"""Automate post-generation chores as much as possible, relying on naming conventions when possible."""

	rig = context.object

	# If any object in the file has a particle system, load and attach the hair script.
	for o in bpy.data.objects:
		if o.type!='MESH': continue
		if len(o.particle_systems)>0:
			print("Loading hair particle script for object: " + o.name)
			link_script(rig, "hair_script", '//../../scripts/rigged_particle_hair.blend', 'rigged_particle_hair.py')
			break

	# If there is a text datablock named "charname_selection_sets.py", load selection sets from it.
	selset_text = bpy.data.texts.get(charname.lower()+"_selection_sets.py")
	if selset_text:
		print("Creating selection sets: " + selset_text.name)
		create_selection_sets(context, selset_text)

	# If there is a text datablock named "charname_rename_curves.py", attach it to the rig.
	rename_text = bpy.data.texts.get(charname.lower()+"_rename_curves.py")
	if rename_text:
		print("Attaching curve renaming script: " + rename_text.name)
		rig.data['rename_script'] = rename_text

	# Head Squash
	face_rig_tweaks(rig)

	# Set arms to FK
	print("Set arms to FK...")
	set_custom_property_value(rig, 'PRP-UpperArm.L', 'ik_left_arm', 0.0)
	set_custom_property_value(rig, 'PRP-UpperArm.R', 'ik_right_arm', 0.0)

	print("Adding face settings...")
	add_ui_data(rig, 'face_settings', 'Chin Resists Jaw', info={
		'prop_bone' : 'PRP-Head',
		'prop_id' : 'Chin Resists Jaw',
		'operator' : 'pose.cloudrig_snap_bake',
		'bones' : ['Chin_Main'],
	})
	add_ui_data(rig, 'face_settings', 'BrowsDetach', 'Left Brow Detach', info={
		'prop_bone' : 'MSTR-Eyebrow_Detached.L',
		'prop_id' : 'detach',
		'operator' : 'pose.cloudrig_snap_bake',
		'bones' : ['Eyebrow1.L', 'Eyebrow3.L', 'Eyebrow4.L', 'Eyebrow5.L'],
	})
	add_ui_data(rig, 'face_settings', 'BrowsDetach', 'Right Brow Detach', info={
		'prop_bone' : 'MSTR-Eyebrow_Detached.R',
		'prop_id' : 'detach',
		'operator' : 'pose.cloudrig_snap_bake',
		'bones' : ['Eyebrow1.R', 'Eyebrow3.R', 'Eyebrow4.R', 'Eyebrow5.R'],
	})
	add_ui_data(rig, 'face_settings', 'FaceSquash', info={
		'prop_bone' : 'PRP-Head',
		'prop_id' : 'Face Squash',
	})
	add_ui_data(rig, 'face_settings', 'TeethFollowMouth', info={
		'prop_bone' : 'PRP-Head',
		'prop_id' : 'Teeth Follow Mouth',
	})

	# Update cloudrig.py on the SpriteFright SVN...
	# This cannot be done with file linking in a nice way, so we just copy the file each time any of the rigs are generated.
	# Yes, this is pretty nasty.
	if shared_script:
		print("Update and load shared cloudrig.py")
		from pathlib import Path
		cloudrig_path = Path(__file__).parent / "../../cloudrig.py"
		with open(cloudrig_path) as cloudrig_file:
			lines = cloudrig_file.readlines()

		script_id = "sprite_fright"
		with open('/home/guest/SVN/SpriteFright/pro/lib/scripts/cloudrig.py', 'w') as svn_file:
			for l in lines:
				svn_file.write(l.replace('"SCRIPT_ID"', f'"{script_id}"'))

		rig.data['cloudrig'] = script_id
		abs_path = '/home/guest/SVN/SpriteFright/pro/lib/scripts/cloudrig.blend'
		rel_path = bpy.path.relpath(abs_path)
		link_script(rig, 'script', rel_path, 'cloudrig.py')
	
	# Ensure object data names are correct
	for o in bpy.data.objects:
		if not o.data: continue
		data_name = "Data_"+o.name
		if o.data.name != data_name:
			print(f"Renaming obdata: {o.data.name} -> {data_name}")
			o.data.name = data_name