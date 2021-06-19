from typing import Tuple, List, Dict
import os

import bpy
from mathutils import Vector

from rigify.utils.misc import copy_attributes
from rigify.utils.mechanism import make_property

from ..bone import BoneInfo
from ..utils.naming import slice_name, make_name
from ..utils.maths import flat

class CloudMechanismMixin:
	"""Mixin class for rigging functions, using mostly the BoneInfo class."""

	def get_bone_info(self, name):
		return self.generator.find_bone_info(name)

	@staticmethod
	def find_rig_of_bone(pose_bone):
		return find_rig_of_bone(pose_bone)

	@staticmethod
	def get_rigify_chain(pose_bone):
		return get_rigify_chain(pose_bone)

	def ensure_widget(self, name):
		return self.generator.ensure_widget(name)

	def create_parent_bone(self, child, bone_set=None):
		# TODO: This should be consistent with create_dsp_bone(), probably by implementing that function like this.
		# That is, move the code to a static function that does not require self.
		parent = create_parent_bone(self.generator, child, bone_set)
		return parent

	def create_dsp_bone(self, parent, center=False):
		"""Create a bone to be used as another control's custom_shape_transform."""
		dsp_name = "DSP-" + parent.name
		dsp_bone = self.mch_bones.new(
			name			= dsp_name
			,source			= parent
			,bbone_width	= parent.bbone_width*0.5
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
		return def_bone

	def meta_bone(self, bone_name):
		""" Find and return a bone in the metarig. """
		return self.generator.metarig.pose.bones.get(bone_name)

	def vector_along_bone_chain(self, chain, length=0, index=-1):
		return vector_along_bone_chain(chain, length, index)

	def relink_driver(self, driver_info):
		relink_driver(self.generator.metarig, self.obj, driver_info)

	def transfer_relink_drivers(self, from_thing, to_thing):
		# Transfer and relink bone drivers
		for d in from_thing.drivers[:]:
			to_thing.drivers.append(d)
			from_thing.drivers.remove(d)
			self.relink_driver(d)

	def bendy_parenting(self, bone, parent_name):
		if parent_name=="": return
		parent_bone = self.generator.find_bone_info(parent_name)
		if not parent_bone:
			self.add_log(
				"Parent not found"
				,trouble_bone = bone.name
				,description = f"Target parent bone {parent_name} not found. If this bone does actually exist, you should make sure that this cloud_copy/tweak rig is lower in the parenting hierarchy than the rig that generated the target bone."
			)
			# Still try string-based parenting, which is not ideal but ohwell.
			bone.parent = parent_name
			return
		else:
			bone.parent = parent_bone
			# If parent bone has BBone segments, use Armature constraint for parenting.
			# In this case, we also want to create a parent helper bone to hold that armature constraint.
			if parent_bone.bbone_segments > 1:
				parent_helper = self.create_parent_bone(bone, self.mch_bones)
				parent_helper.custom_shape = None
				parent_helper.add_constraint('ARMATURE', index=-len(bone.constraint_infos)
					,use_deform_preserve_volume = True
					,targets = [
						{
							"subtarget" : parent_bone.name
						}
					]
				)

	@staticmethod
	def flat_vector(vec):
		return flat(vec)

def relink_driver(metarig, rig, driver_info):
	"""Adjust drivers read from the metarig according to some conventions:

	An empty target object or the metarig as the target object will be replaced with the generated rig.
	Variable names with @ in them will be split by the @, and the part after the @ will be the target bone name.
	"""
	for var_info in driver_info['variables']:
		if type(var_info)==tuple: break
		if '@' in var_info['name']:
			splits = var_info['name'].split("@")
			var_info['name'] = splits[0]
			for i, t in enumerate(var_info['targets']):
				var_info['targets'][i]['bone_target'] = splits[i+1]
				if t['id'] == None or t['id'] == metarig:
					t['id'] = rig

def find_rig_of_bone(pose_bone) -> List[bpy.types.PoseBone]:
	if pose_bone.rigify_type != "":
		return get_rigify_chain(pose_bone)
	if pose_bone.parent==None:
		return None

	return find_rig_of_bone(pose_bone.parent)

def get_rigify_chain(pose_bone) -> List[bpy.types.PoseBone]:
	"""Find the chain of bones constituting a rig element that this pose bone belongs to."""

	# We start building a chain with the current bone, prepending bones as we go
	# UP in the hierarchy, until we find a connected bone with a rigify type.
	# If this never happens, this bone does not belong to any rig element.
	cur_pb = pose_bone
	chain = []
	found = False
	while cur_pb:
		chain.insert(0, cur_pb)
		if cur_pb.rigify_type!="":
			found = True
			break
		cur_pb = cur_pb.parent

	if not found:
		return []

	# Go down in the hierarchy from the last bone, appending connected bones to the list.
	# NOTE: If one bone has multiple connected children and neither of them have
	# a rigify type, the chain becomes ambiguous. This case is not supported!
	cur_pb = chain[-1]
	while cur_pb and len(cur_pb.children)>0:
		next_bone = None
		for c in cur_pb.children:
			if c.rigify_type=="" and c.bone.use_connect:
				if next_bone != None:
					print(f"""Warning: Branching connected bone chain for {pose_bone.name}: \n
						\tChain could continue with either {next_bone.name} or {c.name}. \n
						\tPicking the first one arbitrarily! \n
						\tDisconnect the bone or assign a rigify type to make it unambiguous.""")
				else:
					next_bone = c
		if next_bone:
			chain.append(next_bone)
		cur_pb = next_bone
	return chain

def get_bone_chain(rig, start_bone):
	bones = [start_bone]
	if type(start_bone) == bpy.types.PoseBone:
		bones = [start_bone.bone]
	has_connected_children = True
	while has_connected_children:
		# Find first connected child
		has_connected_children = False
		for c in bones[-1].children:
			if c.use_connect:
				bones.append(bones[-1].children[0])
				has_connected_children = True
				break
	return bones

def create_parent_bone(generator, child, bone_set=None):
	"""Copy a bone, prefix it with "P", make the bone shape a bit bigger and parent the bone to this copy."""
	sliced = slice_name(child.name)
	sliced[0].append("P")
	parent_name = make_name(*sliced)
	if bone_set==None:
		bone_set = child.bone_set
	parent_bone = bone_set.new(
		name				= parent_name
		,source				= child
		,custom_shape		= child.custom_shape
		,custom_shape_scale = child.custom_shape_scale * 1.2
		,use_custom_shape_bone_size = child.use_custom_shape_bone_size
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
	data['overridable'] = from_owner.is_property_overridable_library(f'["{prop_name}"]')

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
