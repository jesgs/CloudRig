import bpy
from rna_prop_ui import rna_idprop_ui_prop_update
from ...rig_features.ui import add_ui_data
import sys, os

sides = {'.L' : 'Left', '.R' : 'Right'}
suffixes = list(sides.keys())

sprites_svn = "/home/guest/SVN/SpriteFright" if sys.platform.startswith("linux") else "E:/Sprites"

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

def face_rig_tweaks(rig):
	"""Automate some tweaks on the face rig."""

	# I didn't set the correct rotation order on these Transformation constraints,
	# on every character, so I'd rather just fix it here.
	for bonename in ['P-STR-Lip_Bottom1', 'P-STR-TIP-Lip_Top2', 'P-STR-Lip_Bottom2', 'P-STR-Lip_Top2']:
		for suf in suffixes:
			bone = rig.pose.bones.get(bonename+suf)
			if not bone or len(bone.constraints) == 0: continue
			trans_con = bone.constraints[-1]
			if trans_con.type != 'TRANSFORM': continue
			trans_con.to_euler_order = 'ZYX'

	# Implement "Face Squash" property if it exists.
	prp_head = rig.pose.bones.get("PRP-Head")
	if prp_head and 'Face Squash' in prp_head:
		# print("Implement 'Face Squash'...")
		for bn in ['DEF-Head_Top', 'DEF-Head', 'MSTR-H-Head_Bottom']:
			pb = rig.pose.bones.get(bn)
			if not pb: continue
			# print("    " + pb.name)
			for prop_name in ['use_bulge_min', 'use_bulge_max']:
				con = pb.constraints[0]
				if con.type != 'STRETCH_TO':
					continue
				con.driver_remove(prop_name)
				d = con.driver_add(prop_name).driver
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
		if ui_data['prop_bone'] not in rig.pose.bones: continue
		add_ui_data(rig, "Face", 'LipHeadJaw'
			,info = ui_data
			,label_name = "Mouth"
			,entry_name = f'{sides[suf]} Corner Top/Bot'
		)

		# print("Disable Action constraints on lip corners when they are pinching...")
		for bn in ['P-STR-TIP-Lip_Top2', 'P-STR-Lip_Bottom2']:
			bone_name = bn + suf
			pb = rig.pose.bones.get(bone_name)
			if not pb: continue
			# print("    " + pb.name)
			for c in pb.constraints:
				if c.type!='ACTION':
					continue
				driver = c.driver_remove('influence')
				driver = c.driver_add('influence').driver
				driver.expression = "1-var"
				var = driver.variables.new()
				var.targets[0].id = rig
				var.targets[0].data_path = f'pose.bones["CTR-LipCorner{suf}"]["Sharp"]'

		# print("Move Copy Transforms constraints on the lips to the top of the constraint stack...")
		for bn in ['STR-Lip_Top2', 'STR-TIP-Lip_Top2', 'STR-Lip_Bottom2', 'STR-Lip_Bottom1']:
			bone_name = bn + suf
			pb = rig.pose.bones.get(bone_name)
			if not pb: continue
			# print("    " + pb.name)
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
			# print("Parenting head tip to upper head master....")
			head_bone.parent = master_control
			break

	bpy.ops.object.mode_set(mode='OBJECT')

def sprite_post_gen_chores(context, charname="", shared_script=False):
	"""Automate post-generation chores as much as possible, relying on naming conventions when possible."""

	rig = context.object

	# If any object in the file has a particle system, load and attach the hair script.
	for o in bpy.data.objects:
		if o.type!='MESH': continue
		if len(o.particle_systems) > 0:
			hair_blend = '//../../scripts/rigged_particle_hair.blend'
			if os.path.isfile(bpy.path.abspath(hair_blend)):
				link_script(rig, "hair_script", hair_blend, 'rigged_particle_hair.py')
			break

	# If there is a text datablock ending in "_rename_curves.py", attach it to the rig.
	for text in bpy.data.texts:
		if text.name.endswith("_rename_curves.py"):
			rig.data['rename_script'] = text

	# Head Squash
	face_rig_tweaks(rig)

	# Set arms to FK
	set_custom_property_value(rig, 'PRP-UpperArm.L', 'ik_left_arm', 0.0)
	set_custom_property_value(rig, 'PRP-UpperArm.R', 'ik_right_arm', 0.0)

	# Set face property defaults
	set_custom_property_value(rig, 'PRP-Head', 'Teeth Follow Mouth', 1.0)
	set_custom_property_value(rig, 'PRP-Head', 'Chin Resists Jaw', 0.5)

	if 'PRP-Head' in rig.pose.bones:
		add_ui_data(rig, "Face", 'FaceSquash'
			,info = {
				'prop_bone' : 'PRP-Head',
				'prop_id' : 'Face Squash',
			}
		)
		add_ui_data(rig, "Face", 'Chin Resists Jaw'
			,info = {
				'prop_bone' : 'PRP-Head',
				'prop_id' : 'Chin Resists Jaw',
				'operator' : 'pose.cloudrig_snap_bake',
				'bones' : ['Chin_Main'],
			}
			,label_name = "Mouth"
		)
		add_ui_data(rig, "Face", 'TeethFollowMouth'
			,info = {
				'prop_bone' : 'PRP-Head',
				'prop_id' : 'Teeth Follow Mouth',
			}
			,label_name = "Mouth"
		)
		add_ui_data(rig, "Face", 'Teeth'
			,info = {
				'prop_bone' : 'PRP-Head',
				'prop_id' : 'Teeth',
				'texts' : '["Round", "Square", "Sharp"]'
			}
			,label_name = "Mouth"
		)
	for side, suf in sides.items():
		bone_name = f'MSTR-Eyebrow_Detached{suf}'
		if bone_name not in rig.pose.bones: continue
		add_ui_data(rig, "Face", 'BrowsDetach'
			,info = {
				'prop_bone' : bone_name,
				'prop_id' : 'detach',
				'operator' : 'pose.cloudrig_snap_bake',
				'bones' : [f'Eyebrow1{suf}', f'Eyebrow3{suf}', f'Eyebrow4{suf}', f'Eyebrow5{suf}'],
			}
			,label_name = "Eyebrows"
			,entry_name = f'{side} Brow Detach'
		)

	# Populate face DEF layer
	for pb in rig.pose.bones:
		if pb.name.startswith('DEF'):
			face_pb = pb.parent
			if not face_pb: continue
			if not face_pb.bone.layers[19] and not face_pb.bone.layers[3] and 'Lip' not in pb.name: continue
			if 'DEF-Eye.' in pb.name: continue
			if 'DEF-Eye_Highlight.' in pb.name: continue
			if 'DEF-Eyebrow' in pb.name: continue
			# if 'Eye' in pb.name and 'brow' not in pb.name: continue
			pb.bone.layers[13] = True

	# Update cloudrig.py on the SpriteFright SVN...
	# This cannot be done with file linking in a nice way, so we just copy the file each time any of the rigs are generated.
	# Yes, this is pretty nasty.
	if shared_script:
		from pathlib import Path
		cloudrig_path = Path(__file__).parent / "../../generation/cloudrig.py"
		with open(cloudrig_path) as cloudrig_file:
			lines = cloudrig_file.readlines()

		with open(sprites_svn + '/pro/lib/scripts/cloudrig.py', 'w') as svn_file:
			for l in lines:
				svn_file.write(l)

		abs_path = sprites_svn + '/pro/lib/scripts/cloudrig.blend'
		rel_path = bpy.path.relpath(abs_path)
		link_script(rig, 'script', rel_path, 'cloudrig.py')

		# Also attach the library absolute path warning script
		link_script(rig, 'warn_abs_lib', rel_path, 'warn_absolute_library.py')

	# Ensure object data names are correct
	for o in bpy.data.objects:
		if not o.data: continue
		data_name = "Data_"+o.name
		if o.data.name != data_name:
			o.data.name = data_name