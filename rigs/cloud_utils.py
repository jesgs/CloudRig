from typing import Tuple, List
from mathutils import Vector

import bpy
from rna_prop_ui import rna_idprop_ui_create
import os

from copy import deepcopy
from rigify.utils.misc import copy_attributes
from rigify.utils.mechanism import make_property

from ..bone import BoneInfo
from ..utils.naming import slice_name, make_name
from ..utils.maths import flat
from ..ui import add_ui_data

class CloudUtilities:
	# Utility functions that probably won't be overriden by a sub-class because they perform a very specific task.
	# If a class inherits this class, it's also expected to inherit CloudBaseRig - These are only split up for organizational purposes.

	def get_bone_info(self, name):
		for bi in self.all_bones:
			if bi.name==name:
				return bi

	def add_ui_data(self, ui_area, row_name, col_name, info, default=0.0, _min=0.0, _max=1.0):
		add_ui_data(self.obj, ui_area, row_name, col_name.replace("_", " "), info, default, _min, _max)

	# TODO: Move this to cloud_fk_chain.py?
	# This would require splitting off the neck and head from the spine rig.
	def hinge_setup(self, bone, category, *,
		prop_bone, prop_name, default_value=0.0,
		parent_bone=None, head_tail=0,
		hng_name=None, limb_name=None, bone_set=None
	):
		""" Create a hinge toggle for a bone. Bone is usually the first bone in an FK chain.
		When hinge is turned on, the bone doesn't inherit rotation from its parents, but still inherits rotation from the rig's root bone."""

		# Defaults for optional parameters
		if not hng_name:
			sliced = self.naming.slice_name(bone.name)
			sliced[0].insert(0, "HNG")
			hng_name = self.naming.make_name(*sliced)
		if not parent_bone:
			parent_bone = bone.parent
		if not limb_name:
			limb_name = "Hinge: " + self.side_suffix + " " + self.naming.slice_name(bone.name)[1]
		if bone_set==None:
			bone_set = bone.container

		info = {
			"prop_bone"			: prop_bone,
			"prop_id" 			: prop_name,

			"operator" : "pose.snap_simple",
			"bones" : [bone.name]
		}

		# Store UI info
		self.add_ui_data("fk_hinges", category, limb_name, info, default=default_value)

		# Create Hinge helper bone
		BODY_MECH = 8
		hng_bone = bone_set.new(
			name			= hng_name
			,source			= bone
			,hide_select	= self.mch_disable_select
		)

		# Hinge Armature constraint
		hng_con = hng_bone.add_constraint('ARMATURE',
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
		hng_bone.add_constraint('COPY_LOCATION'
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

	def rig_child(self, child_bone, parent_names, prop_bone, prop_name, bone_set=None):
		""" Rig a child with multiple switchable parents, using Armature constraint and drivers.
		child_bone: The child bone.
		parent_names: Parent identifiers(NOT BONE NAMES!) to search for among registered parent identifiers (These are hard-coded identifiers such as 'Hips', 'Torso', etc.)
		prop_bone: Bone which stores the property that controls the parent switching.
		prop_name: Name of said property on the prop_bone.
		bone_set: BoneSet to create this bone in. If not provided, use "Parent Switch Helpers" from cloud_base.
		Return list of parent names for which a registered parent candidate was found and rigged.
		"""
		if bone_set==None:
			bone_set = self.parent_switch_bones

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
		arm_con_bone = self.create_parent_bone(child_bone, bone_set)
		arm_con_bone.hide_select = self.mch_disable_select
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
		arm_con = arm_con_bone.add_constraint('ARMATURE',
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

	def create_parent_bone(self, child, bone_set=None):
		return create_parent_bone(child, bone_set)

	def create_dsp_bone(self, parent, center=False):
		"""Create a bone to be used as another control's custom_shape_transform."""
		dsp_name = "DSP-" + parent.name
		dsp_bone = self.dsp_bones.new(
			name			= dsp_name
			,source			= parent
			,bbone_width	= parent.bbone_width*0.5
			,only_transform = True
			,custom_shape	= None
			,parent			= parent
			,hide_select	= self.mch_disable_select
		)
		parent.dsp_bone = dsp_bone
		if center:
			dsp_bone.put(parent.center, scale_length=0.3, scale_width=1.5)
		parent.custom_shape_transform = dsp_bone
		return dsp_bone

	def make_def_bone(self, bone, bone_set):
		"""Make a DEF- bone parented to bone."""
		def_bone = bone_set.new(
			name = self.naming.make_name(["DEF"], *self.naming.slice_name(bone.name)[1:])
			,source = bone
			,use_deform = True
			,parent = bone
		)
		return

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
				'bone_target' : bi.bbone_custom_handle_start.name,
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
		if (bi.bbone_handle_type_end == 'TANGENT' and bi.bbone_custom_handle_start):
			bi.drivers.append(scaleinx_driver)

			scaleiny_driver = deepcopy(scaleinx_driver)
			scaleiny_driver['prop'] = "bbone_scaleiny"
			scaleiny_var = deepcopy(scaleinx_var)
			scaleiny_var['targets'][0]['transform_type'] = 'SCALE_Z'
			scaleiny_driver['variables']['var'] = scaleiny_var
			bi.drivers.append(scaleiny_driver)

		# Scale Out X/Y
		if (bi.bbone_handle_type_end == 'TANGENT' and bi.bbone_custom_handle_end):
			scaleoutx_driver = deepcopy(scaleinx_driver)
			scaleoutx_driver['prop'] = "bbone_scaleoutx"
			scaleoutx_driver['variables']['var']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end.name
			bi.drivers.append(scaleoutx_driver)

			scaleouty_driver = deepcopy(scaleoutx_driver)
			scaleouty_driver['prop'] = "bbone_scaleouty"
			scaleouty_driver['variables']['var']['targets'][0]['transform_type'] = 'SCALE_Z'
			bi.drivers.append(scaleouty_driver)

		### Ease In/Out
		easein_var = {
			'type' : 'TRANSFORMS',
			'targets' : [{
				'bone_target' : bi.bbone_custom_handle_start.name,
				'transform_type' : 'SCALE_Y',
				'transform_space' : 'LOCAL_SPACE',
			}]
		}
		easein_driver = {
			'expression' : "(var-scale)",
			'prop' : "bbone_easein",
			'variables' : {
				'var' : easein_var,
				'scale' : {
					'type' : 'TRANSFORMS',
					'targets' : [{
						'bone_target' : bi.bbone_custom_handle_start.name,
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
			easeout_driver['variables']['var']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end.name
			easeout_driver['variables']['scale']['targets'][0]['bone_target'] = bi.bbone_custom_handle_end.name
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
	def flat_vector(vec):
		return flat(vec)

def create_parent_bone(child, bone_set=None):
	"""Copy a bone, prefix it with "P", make the bone shape a bit bigger and parent the bone to this copy."""
	sliced = slice_name(child.name)
	sliced[0].append("P")
	parent_name = make_name(*sliced)
	if bone_set==None:
		bone_set = child.container
	parent_bone = bone_set.new(
		name				= parent_name
		,source				= child
		,custom_shape		= child.custom_shape
		,custom_shape_scale = child.custom_shape_scale * 1.1
		,parent 			= child.parent
	)

	child.parent = parent_bone
	return parent_bone

def copy_custom_property(from_owner, to_owner, prop_name):
	rna_ui = from_owner['_RNA_UI'].to_dict()

	if prop_name not in rna_ui:
		print(f"Warning: Custom property {prop_name} not found on {from_owner}, failed to copy.")
		return

	data = rna_ui[prop_name]
	data['overridable'] = from_owner.is_property_library_overridable(f'["{prop_name}]"')

	if not 'default' in data:
		data['default'] = 1.0
	if not 'description' in data:
		data['description'] = ""

	make_property(to_owner, prop_name, **data)

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

def vector_along_bone_chain(chain: List[BoneInfo], length=0, index=-1) -> Tuple[Vector, Vector]:
	"""On a bone chain, find the point a given length down the chain. Return its position and direction."""
	if index > -1:
		# Instead of using bone length, simply return the location and direction of a bone at a given index.

		# If the index is too high, return the tail of the bone.
		if index >= len(chain):
			b = chain[-1]
			return (b.tail.copy(), b.vector.normalized())

		b = chain[index]
		direction = b.vector.normalized()

		if index > 0:
			prev_bone = chain[index-1]
			direction = (b.vector + prev_bone.vector).normalized()
		return (b.head.copy(), direction)


	length_cumultative = 0
	for b in chain:
		if length_cumultative + b.length > length:
			length_remaining = length - length_cumultative
			direction = b.vector.normalized()
			loc = b.head + direction * length_remaining
			return (loc, direction)
		else:
			length_cumultative += b.length

	length_remaining = length - length_cumultative
	direction = chain[-1].vector.normalized()
	loc = chain[-1].tail + direction * length_remaining
	return (loc, direction)
