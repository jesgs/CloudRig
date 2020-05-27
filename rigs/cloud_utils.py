import bpy
import os

from copy import deepcopy
from rigify.utils.misc import copy_attributes

class CloudUtilities:
	# Utility functions that probably won't be overriden by a sub-class because they perform a very specific task.
	# If a class inherits this class, it's also expected to inherit CloudBaseRig - These are only split up for organizational purposes.

	def add_ui_data(self, ui_area, row_name, col_name, info, default=0.0, _min=0.0, _max=1.0):
		""" Store a dict in the rig data, which is used by cloudrig.py to draw the CloudRig UI. 
		ui_area: One of a list of pre-defined strings that the UI script recognizes, that describes a panel or area in the UI. Eg, "fk_hinges", "ik_switches".
		row_name: A row in the UI area.
		col_name: A column within the row.
		info: The dictionary to store in the rig data.
		"""

		assert ('prop_bone' in info) and ('prop_id' in info), 'Error: Expected an info dict with at least "prop_bone" and "prop_id" keys.'

		if ui_area not in self.obj.data:
			self.obj.data[ui_area] = {}

		if row_name not in self.obj.data[ui_area]:
			self.obj.data[ui_area][row_name] = {}

		self.obj.data[ui_area][row_name][col_name] = info
		
		# Create custom property.
		prop_bone = self.bone_infos.find(info['prop_bone'])
		prop_id = info['prop_id']
		prop_bone.custom_props[prop_id] = {
			"default" : default, 
			"min" : _min,
			"max" : _max
		}

	# TODO: Move this to cloud_fk_chain.py?
	def hinge_setup(self, bone, category, *, 
		prop_bone, prop_name, default_value=0.0, 
		parent_bone=None, head_tail=0, 
		hng_name=None, limb_name=None
	):
		# Initialize some defaults
		if not hng_name:
			sliced = slice_name(bone.name)
			sliced[0].insert(0, "HNG")
			hng_name = make_name(*sliced)
		if not parent_bone:
			parent_bone = bone.parent
		if not limb_name:
			limb_name = "Hinge: " + self.side_suffix + " " + slice_name(bone.name)[1]
		
		info = {
			"prop_bone"			: prop_bone.name,
			"prop_id" 			: prop_name,

			"operator" : "pose.snap_simple",
			"bones" : [bone.name]
		}

		# Store UI info
		self.add_ui_data("fk_hinges", category, limb_name, info, default=default_value)

		# Create Hinge helper bone
		BODY_MECH = 8
		hng_bone = self.bone_infos.bone(
			name			= hng_name
			,source			= bone
			,bone_group 	= bone.bone_group
			,layers			= bone.layers
			,hide_select	= self.mch_disable_select
		)

		# Hinge Armature constraint
		hng_con = hng_bone.add_constraint(self.obj, 'ARMATURE', 
			targets = [
				{
					"subtarget" : 'root'
				},
				{
					"subtarget" : str(parent_bone)
				}
			],
		)

		hng_con.drivers.append({
			'prop' : 'targets[0].weight',
			'variables' : [
				(prop_bone.name, prop_name)
			]
		})

		hng_con.drivers.append({
			'prop' : 'targets[1].weight',
			'expression' : '1-var',
			'variables' : [
				(prop_bone.name, prop_name)
			]
		})

		# Hinge Copy Location constraint
		hng_bone.add_constraint(self.obj, 'COPY_LOCATION'
			,space = 'WORLD'
			,subtarget	   = str(parent_bone)
			,head_tail	   = head_tail
		)

		# Parenting
		bone.parent = hng_bone
		return hng_bone

	def register_parent(self, bone, name):
		if name in self.parent_candidates:
			print(f"Warning: Overwriting registered parent: {bone.name}, {name}")
		self.parent_candidates[name] = bone

	def get_parent_candidates(self, candidates={}):
		""" Go recursively up the rig element hierarchy. Collect and return a list of the registered parent bones from each rig."""
		
		for parent_name in self.parent_candidates.keys():
			candidates[parent_name] = self.parent_candidates[parent_name]

		if self.rigify_parent and hasattr(self.rigify_parent, "get_parent_candidates"):
			return self.rigify_parent.get_parent_candidates(candidates)
		
		return candidates

	def load_widget(self, name):
		return self.generator.load_widget(name)

	def rig_child(self, child_bone, parent_names, prop_bone, prop_name):
		""" Rig a child with multiple switchable parents, using Armature constraint and drivers.
		This requires:
			child_bone: The child bone.
			parent_names: Parent identifiers(NOT BONE NAMES!) to search for among registered parent identifiers (These are hard-coded identifiers such as 'Hips', 'Torso', etc.)
			prop_bone: Bone which stores the property that controls the parent switching.
			prop_name: Name of said property on the prop_bone.
		Return list of parent names for which a registered parent candidate was found and rigged.
		"""

		# Test that at least one of the parents exists.
		parent_candidates = self.get_parent_candidates()
		found_parents = []
		for pn in parent_names:
			if pn in list(parent_candidates.keys()):
				found_parents.append(pn)
		if len(found_parents) == 0: 
			print(f"Warning: No parents to be rigged for {child_bone.name}.")
			return found_parents

		# Create parent bone for the bone that stores the Armature constraint.
		# NOTE: Bones with Armature constraints should never be exposed to the animator directly because it breaks snapping functionality!
		arm_con_bone = self.create_parent_bone(child_bone)
		arm_con_bone.bone_group = self.bone_groups["Parent Switch Helpers"]
		arm_con_bone.layers = self.bone_layers["Parent Switch Helpers"]
		arm_con_bone.name = "Parents_" + child_bone.name
		arm_con_bone.custom_shape = None

		targets = []
		for pn in parent_names:
			if pn not in parent_candidates.keys():
				continue
			pb = parent_candidates[pn]
			targets.append({
				"subtarget" : pb.name
			})

		# Add armature constraint
		arm_con = arm_con_bone.add_constraint(self.obj, 'ARMATURE', 
			targets = targets
		)

		# Add weight drivers
		for i, t in enumerate(arm_con.targets):
			arm_con.drivers.append({
				'prop' : f'targets[{i}].weight',
				'expression' : f'parent=={i}',
				'variables' : {
					'parent' : {
						'type' : 'SINGLE_PROP',
						'targets' : [{
							'data_path' : f'pose.bones["{prop_bone.name}"]["{prop_name}"]'
						}]
					}
				}
			})

		return found_parents

	def create_parent_bone(self, child):
		"""Copy a bone, prefix it with "P", make the bone shape a bit bigger and parent the bone to this copy."""
		sliced = slice_name(child.name)
		sliced[0].append("P")
		parent_name = make_name(*sliced)
		parent_bone = self.bone_infos.bone(
			name				= parent_name 
			,source				= child
			,custom_shape		= child.custom_shape
			,custom_shape_scale = child.custom_shape_scale * 1.1
			,bone_group			= child.bone_group
			,layers				= child.layers
			,parent 			= child.parent
			,hide_select		= self.mch_disable_select
		)

		child.parent = parent_bone
		return parent_bone

	def create_dsp_bone(self, parent, center=False):
		"""Create a bone to be used as another control's custom_shape_transform."""
		dsp_name = "DSP-" + parent.name
		dsp_bone = self.bone_infos.bone(
			name			= dsp_name
			,source			= parent
			,bbone_width	= parent.bbone_width*0.5
			,only_transform = True
			,custom_shape	= None
			,parent			= parent
			,bone_group		= self.bone_groups["Display Transform Helpers"]
			,layers			= self.bone_layers["Display Transform Helpers"]
			,hide_select	= self.mch_disable_select
		)
		parent.dsp_bone = dsp_bone
		if center:
			dsp_bone.put(parent.center, scale_length=0.3, scale_width=1.5)
		parent.custom_shape_transform = dsp_bone
		return dsp_bone

	def meta_bone(self, bone_name, pose=False):
		""" Find and return a bone in the metarig. """
		if self.obj.mode=='EDIT' and not pose:
			return self.generator.metarig.data.edit_bones.get(bone_name)
		else:
			return self.generator.metarig.pose.bones.get(bone_name)

	def make_bbone_scale_drivers(self, boneinfo):
		bi = boneinfo
		armature = self.obj

		scaleinx_var = {
			'type' : 'TRANSFORMS',
			'targets' : [{
				'bone_target' : bi.bbone_custom_handle_start,
				'transform_type' : 'SCALE_X',
				'transform_space' : 'WORLD_SPACE'
			}]
		}

		scaleinx_driver = {
			'expression' : "var/scale",
			'prop' : "bbone_scaleinx",
			'variables' : {
				'var' : scaleinx_var,
				'scale' : {
					'type' : 'TRANSFORMS',
					'targets' : [{
						'transform_space' : 'WORLD_SPACE',
						'transform_type' : 'SCALE_Y',
					}]
				}
			}
		}

		# Scale In X/Y
		if (bi.bbone_handle_type_end == 'TANGENT' and bi.bbone_custom_handle_start!=""):
			bi.drivers.append(scaleinx_driver)

			scaleiny_driver = deepcopy(scaleinx_driver)
			scaleiny_driver['prop'] = "bbone_scaleiny"
			scaleiny_var = deepcopy(scaleinx_var)
			scaleiny_var['targets'][0]['transform_type'] = 'SCALE_Z'
			scaleiny_driver['variables']['var'] = scaleiny_var
			bi.drivers.append(scaleiny_driver)

		# Scale Out X/Y
		if (bi.bbone_handle_type_end == 'TANGENT' and bi.bbone_custom_handle_end!=""):
			scaleoutx_driver = deepcopy(scaleinx_driver)
			scaleoutx_driver['prop'] = "bbone_scaleoutx"
			scaleoutx_driver['variables']['var']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end
			bi.drivers.append(scaleoutx_driver)

			scaleouty_driver = deepcopy(scaleoutx_driver)
			scaleouty_driver['prop'] = "bbone_scaleouty"
			scaleouty_driver['variables']['var']['targets'][0]['transform_type'] = 'SCALE_Z'
			bi.drivers.append(scaleouty_driver)

		### Ease In/Out
		easein_var = {
			'type' : 'TRANSFORMS',
			'targets' : [{
				'bone_target' : bi.bbone_custom_handle_start,
				'transform_type' : 'SCALE_Y',
				'transform_space' : 'LOCAL_SPACE',
			}]
		}
		easein_driver = {
			'expression' : "var-scale",
			'prop' : "bbone_easein",
			'variables' : {
				'var' : easein_var,
				'scale' : {
					'type' : 'TRANSFORMS',
					'targets' : [{
						'bone_target' : bi.bbone_custom_handle_start,
						'transform_space' : 'LOCAL_SPACE',
						'transform_type' : 'SCALE_AVG',
					}]
				}
			}
		}

		# Ease In
		if (bi.bbone_handle_type_start == 'TANGENT' and bi.bbone_custom_handle_start):
			bi.drivers.append(easein_driver)

		# Ease Out
		if (bi.bbone_handle_type_end == 'TANGENT' and bi.bbone_custom_handle_end):
			easeout_driver = deepcopy(easein_driver)
			easeout_driver['prop'] = "bbone_easeout"
			easeout_driver['variables']['var']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end
			easeout_driver['variables']['scale']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end
			bi.drivers.append(easeout_driver)

	def vector_along_bone_chain(self, chain, length=0, index=-1):
		return vector_along_bone_chain(chain, length, index)

	def copy_and_relink_driver(self, fcurve, obj, data_path, index=None):
		"""Copy a driver to some other data path, while accounting for any constraint relinking."""

		data_path = fcurve.data_path
		if 'constraints' in data_path:
			org_con_name = data_path.split('constraints["')[-1].split('"]')[0]
			new_con_name = org_con_name.split("@")[0]
			data_path = data_path.replace(org_con_name, new_con_name)

		new_fc = copy_driver(fcurve, self.obj, data_path, index)
		new_fc.data_path = data_path

		# Switch targets from metarig or None to generated rig.
		for var in new_fc.driver.variables:
			for t in var.targets:
				if t.id in [None, self.generator.metarig]:
					t.id = self.obj

	@staticmethod
	def datablock_from_str(collprop, string):
		return datablock_from_str(collprop, string)

	@staticmethod
	def set_layers(obj, layerlist, additive=False):
		return set_layers(obj, layerlist, additive)

	@staticmethod
	def lock_transforms(obj, loc=True, rot=True, scale=True):
		return lock_transforms(obj, loc, rot, scale)

	def add_prefix_to_name(self, name, new_prefix):
		""" The most common case of making a bone name based on another one is to add a prefix to it. """
		sliced_name = self.slice_name(name)
		sliced_name[0].append(new_prefix)
		return self.make_name(*sliced_name)

	def make_name(self, prefixes=[], base="", suffixes=[]):
		return make_name(prefixes, base, suffixes, self.generator.prefix_separator, self.generator.suffix_separator)
	
	def slice_name(self, name):
		return slice_name(name, self.generator.prefix_separator, self.generator.suffix_separator)
	
	@staticmethod
	def ensure_visible(obj):
		return EnsureVisible(obj)
	
	@staticmethod
	def flip_name(from_name, only=True, must_change=False):
		return flip_name(from_name, only, must_change)
	
	@staticmethod
	def flat_vector(vec):
		return flat(vec)

def copy_driver(from_fcurve, obj, data_path=None, index=None):
	if not data_path:
		data_path = from_fcurve.data_path
	
	new_fc = None
	if index:
		new_fc = obj.driver_add(data_path, index)
	else:
		new_fc = obj.driver_add(data_path)

	copy_attributes(from_fcurve, new_fc)
	copy_attributes(from_fcurve.driver, new_fc.driver)

	# Remove default modifiers, variables, etc.
	for m in new_fc.modifiers:
		new_fc.modifiers.remove(m)
	for v in new_fc.driver.variables:
		new_fc.driver.variables.remove(v)

	# Copy modifiers
	for m1 in from_fcurve.modifiers:
		m2 = new_fc.modifiers.new(type=m1.type)
		copy_attributes(m1, m2)

	# Copy variables
	for v1 in from_fcurve.driver.variables:
		v2 = new_fc.driver.variables.new()
		copy_attributes(v1, v2)
		for i in range(len(v1.targets)):
			copy_attributes(v1.targets[i], v2.targets[i])
	
	return new_fc

def datablock_from_str(collprop, string):
	""" Workaround to T59106. Using PointerProperty causes error spam in console. """
	found = collprop.get(string)
	if found: return found

	while string.startswith(" "):
		string = string[1:]
	
	found = collprop.get(string)
	if found: return found

def make_name(prefixes=[], base="", suffixes=[], prefix_separator="-", suffix_separator="."):
	# In our naming convention, prefixes are separated by dashes and suffixes by periods, eg: DSP-FK-UpperArm_Parent.L.001
	# Trailing zeroes should be avoided though, but that's not done by this function(for now?)
	name = ""
	for pre in prefixes:
		name += pre + prefix_separator
	name += base
	for suf in suffixes:
		name += suffix_separator + suf
	return name

def slice_name(name, prefix_separator="-", suffix_separator="."):
	prefixes = name.split(prefix_separator)[:-1]
	suffixes = name.split(suffix_separator)[1:]
	base = name.split(prefix_separator)[-1].split(suffix_separator)[0]
	return [prefixes, base, suffixes]

def lock_transforms(obj, loc=True, rot=True, scale=True):
	if type(loc) in (list, tuple):
		obj.lock_location = loc
	else:
		obj.lock_location = [loc, loc, loc]

	if type(rot) in (list, tuple):
		obj.lock_rotation = rot[:3]
		if len(rot)==4:
			obj.lock_rotation_w = rot[-1]
	else:
		obj.lock_rotation = [rot, rot, rot]
		obj.lock_rotation_w = rot

	if type(scale) in (list, tuple):
		obj.lock_scale = scale
	else:
		obj.lock_scale = [scale, scale, scale]

def vector_along_bone_chain(chain, length=0, index=-1):
	"""On a bone chain, find the point a given length down the chain. Return its position and direction."""
	if index > -1:
		# Instead of using bone length, simply return the location and direction of a bone at a given index.
		
		# If the index is too high, return the tail of the bone.
		if index >= len(chain):
			b = chain[-1]
			return (b.tail.copy(), b.vec.normalized())
		
		b = chain[index]
		direction = b.vec.normalized()

		if index > 0:
			prev_bone = chain[index-1]
			direction = (b.vec + prev_bone.vec).normalized()
		return (b.head.copy(), direction)

	
	length_cumultative = 0
	for b in chain:
		if length_cumultative + b.length > length:
			length_remaining = length - length_cumultative
			direction = b.vec.normalized()
			loc = b.head + direction * length_remaining
			return (loc, direction)
		else:
			length_cumultative += b.length
	
	length_remaining = length - length_cumultative
	direction = chain[-1].vec.normalized()
	loc = chain[-1].tail + direction * length_remaining
	return (loc, direction)

def set_layers(obj, layerlist, additive=False):
	"""Layer setting function that can take either a list of booleans or a list of ints.
	In case of booleans, it must be a 32 length list, and we set the bone's layer list to the passed list.
	In case of ints, enable the layers with the indicies in the passed list.
	
	obj can either be a bone or an armature.
	"""
	layers = obj.layers[:]

	if not additive:
		layers = [False]*32
	
	for i, e in enumerate(layerlist):
		if type(e)==bool:
			assert len(layerlist)==32, f"ERROR: Layer assignment expected a list of 32 booleans, got {len(layerlist)}."
			layers[i] = e
		elif type(e)==int:
			layers[e] = True
	
	obj.layers = layers[:]

def recursive_search_layer_collection(collName, layerColl=None):
	# Recursivly transverse layer_collection for a particular name
	# This is the only way to set active collection as of 14-04-2020.
	if not layerColl:
		layerColl = bpy.context.view_layer.layer_collection
	
	found = None
	if (layerColl.name == collName):
		return layerColl
	for layer in layerColl.children:
		found = recursive_search_layer_collection(collName, layer)
		if found:
			return found

def set_active_collection(collection):
	layer_collection = recursive_search_layer_collection(collection.name)
	bpy.context.view_layer.active_layer_collection = layer_collection

def flip_name(from_name, only=True, must_change=False):
	# based on BLI_string_flip_side_name in https://developer.blender.org/diffusion/B/browse/master/source/blender/blenlib/intern/string_utils.c
	# If only==True, only replace the first occurrence of a side identifier in the string, eg. "Left_Eyelid.L" would become "Right_Eyelid.L". With only==False, it would instead return "Right_Eyelid.R"
	# if must_change==True, raise an error if the string couldn't be flipped.

	l = len(from_name)	# Number of characters from left to right, that we still care about. At first we care about all of them.
	
	# Handling .### cases
	if("." in from_name):
		# Make sure there are only digits after the last period
		after_last_period = from_name.split(".")[-1]
		before_last_period = from_name.replace("."+after_last_period, "")
		all_digits = True
		for c in after_last_period:
			if( c not in "0123456789" ):
				all_digits = False
				break
		# If that is so, then we don't care about the characters after this last period.
		if(all_digits):
			l = len(before_last_period)
	
	new_name = from_name[:l]
	
	left = 				['left',  'Left',  'LEFT', 	'.l', 	  '.L', 		'_l', 				'_L',				'-l',	   '-L', 	'l.', 	   'L.',	'l_', 			 'L_', 			  'l-', 	'L-']
	right_placehold = 	['*rgt*', '*Rgt*', '*RGT*', '*dotl*', '*dotL*', 	'*underscorel*', 	'*underscoreL*', 	'*dashl*', '*dashL', '*ldot*', '*Ldot', '*lunderscore*', '*Lunderscore*', '*ldash*','*Ldash*']
	right = 			['right', 'Right', 'RIGHT', '.r', 	  '.R', 		'_r', 				'_R',				'-r',	   '-R', 	'r.', 	   'R.',	'r_', 			 'R_', 			  'r-', 	'R-']
	
	def flip_sides(list_from, list_to, new_name):
		for side_idx, side in enumerate(list_from):
			opp_side = list_to[side_idx]
			if(only):
				# Only look at prefix/suffix.
				if(new_name.startswith(side)):
					new_name = new_name[len(side):]+opp_side
					break
				elif(new_name.endswith(side)):
					new_name = new_name[:-len(side)]+opp_side
					break
			else:
				if("-" not in side and "_" not in side):	# When it comes to searching the middle of a string, sides must Strictly a full word or separated with . otherwise we would catch stuff like "_leg" and turn it into "_reg".
					# Replace all occurences and continue checking for keywords.
					new_name = new_name.replace(side, opp_side)
					continue
		return new_name
	
	new_name = flip_sides(left, right_placehold, new_name)
	new_name = flip_sides(right, left, new_name)
	new_name = flip_sides(right_placehold, right, new_name)
	
	# Re-add trailing digits (.###)
	new_name = new_name + from_name[l:]

	if(must_change):
		assert new_name != from_name, "Failed to flip string: " + from_name
	
	return new_name

def flat(vec):
	""" Return a copy of a vector with its two absolute lowest values set to 0. Useful for making vectors world-aligned. """
	new_vec = vec.copy()

	maxabs = 0
	max_index = 0
	for i, val in enumerate(vec):
		if abs(val) > maxabs:
			maxabs = abs(val)
			max_index = i

	for i in range(0, len(vec)):
		if i != max_index:
			new_vec[i] = 0

	return new_vec

class EnsureVisible:
	""" Ensure an object is visible, then reset it to how it was before. """

	def __init__(self, obj):
		""" Ensure an object is visible, and create this small object to manage that object's visibility-ensured-ness. """
		self.obj_name = obj.name
		self.obj_hide = obj.hide_get()
		self.obj_hide_viewport = obj.hide_viewport
		self.temp_coll = None
		
		if not obj.visible_get():
			obj.hide_set(False)
			obj.hide_viewport = False

		if not obj.visible_get():
			# If the object is still not visible, we need to move it to a visible collection. To not break other scripts though, we should restore the active collection afterwards.
			active_coll = bpy.context.collection

			coll_name = "temp_visible"
			temp_coll = bpy.data.collections.get(coll_name)
			if not temp_coll:
				temp_coll = bpy.data.collections.new(coll_name)
			if coll_name not in bpy.context.scene.collection.children:
				bpy.context.scene.collection.children.link(temp_coll)
		
			if obj.name not in temp_coll.objects:
				temp_coll.objects.link(obj)
			
			self.temp_coll = temp_coll

			set_active_collection(active_coll)
	
	def restore(self):
		""" Restore visibility settings to their original state. """
		obj = bpy.data.objects.get(self.obj_name)
		if not obj: return

		obj.hide_set(self.obj_hide)
		obj.hide_viewport = self.obj_hide_viewport

		# Remove object from temp collection
		if self.temp_coll and obj.name in self.temp_coll.objects:
			self.temp_coll.objects.unlink(obj)

			# Delete temp collection if it's empty now.
			if len(self.temp_coll.objects) == 0:
				bpy.data.collections.remove(self.temp_coll)
				self.temp_coll = None