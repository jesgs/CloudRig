from typing import Tuple, List

import bpy
from mathutils import Vector

from rigify.utils.misc import copy_attributes

from ..rig_component_features.bone import BoneInfo
from ..generation.naming import slice_name, make_name

class CloudMechanismMixin:
	"""Mixin class for rigging functions, using mostly the BoneInfo class."""

	def find_bone_info(self, name):
		return self.generator.find_bone_info(name)

	@staticmethod
	def find_chain_of_pbone(pose_bone):
		return find_chain_of_pbone(pose_bone)

	def get_component_bone_chain(self):
		# TODO 4.0: This could be moved to the RigComponent RNA class.
		connected = type(self).chain_must_be_connected
		pose_bone = self.metarig.pose.bones.get(self.base_bone_name)
		return get_component_bone_chain(pose_bone, connected)

	def ensure_widget(self, name):
		return self.generator.ensure_widget(name)

	def create_parent_bone(self, child, bone_set=None):
		return create_parent_bone(child, bone_set)

	def create_dsp_bone(self, parent):
		return create_dsp_bone(parent, self.bones_mch)

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

	@property
	def meta_base_bone(self):
		"""Return pose bone in the metarig that has this rig type assigned."""
		return self.meta_bone(self.base_bone_name)

	def vector_along_bone_chain(self, chain, length=0, index=-1):
		return vector_along_bone_chain(chain, length, index)

	def relink_driver(self, driver_info):
		relink_driver(self.metarig, self.target_rig, driver_info)

	def transfer_relink_drivers(self, from_bone: BoneInfo, to_bone: BoneInfo):
		"""Transfer and relink drivers from one bone to another."""
		for d in from_bone.drivers[:]:
			to_bone.drivers.append(d)
			from_bone.drivers.remove(d)
			self.relink_driver(d)

def relink_driver(metarig, rig, driver_info):
	"""Adjust drivers read from the metarig according to some conventions:

	An empty target object or the metarig as the target object will be replaced
	with the generated rig.
	Variable names with @ in them will be split by the @, and the part after the
	@ will be the target bone name.
	"""
	for var_info in driver_info['variables']:
		if type(var_info)==tuple: break
		if '@' in var_info['name']:
			splits = var_info['name'].split("@")
			var_info['name'] = splits[0]
			for i, t in enumerate(var_info['targets']):
				var_info['targets'][i]['bone_target'] = splits[i+1]
		for i, t in enumerate(var_info['targets']):
			if t['id'] == None or t['id'] == metarig:
				t['id'] = rig

def find_chain_of_pbone(pose_bone) -> List[bpy.types.PoseBone]:
	if pose_bone.cloudrig_component.component_type:
		return get_component_bone_chain(pose_bone)
	if not pose_bone:
		return None

	return find_chain_of_pbone(pose_bone.parent)

def get_component_bone_chain(pose_bone, connected=True) -> List[bpy.types.Bone]:
	"""Find the chain of bones constituting a rig component that this pose bone belongs to."""

	# We start building a chain with the current bone, prepending bones as we go
	# UP in the hierarchy, until we find a connected bone with a rigify type.
	# If this never happens, this bone does not belong to any rig component.
	cur_pb = pose_bone
	chain = []
	found = False
	while cur_pb:
		chain.insert(0, cur_pb)
		if cur_pb.cloudrig_component.component_type != "":
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
			if c.cloudrig_component.component_type == "":
				if connected and not c.bone.use_connect:
					continue
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

def get_bone_chain(start_bone):
	bones = [start_bone]
	if type(start_bone) == bpy.types.PoseBone:
		bones = [start_bone.bone]
	has_connected_children = True
	while has_connected_children:
		# Find first connected child
		has_connected_children = False
		for c in bones[-1].children:
			if c.use_connect:
				bones.append(c)
				has_connected_children = True
				break
	return bones

def create_parent_bone(child, bone_set=None):
	"""Copy a bone, prefix it with "P", make the bone shape a bit bigger and parent the bone to this copy."""
	sliced = slice_name(child.name)
	sliced[0].append("P")
	parent_name = make_name(*sliced)
	if bone_set==None:
		bone_set = child.bone_set
	parent_bone = bone_set.new(
		name						 = parent_name
		,source						 = child
		,parent						 = child.parent
		,custom_shape				 = child.custom_shape
		,custom_shape_scale_xyz		 = Vector(child.custom_shape_scale_xyz) * 1.2
		,custom_shape_translation	 = Vector(child.custom_shape_translation)
		,use_custom_shape_bone_size  = child.use_custom_shape_bone_size
		,custom_shape_rotation_euler = child.custom_shape_rotation_euler
	)

	child.parent = parent_bone
	child.parent_helper = parent_bone
	return parent_bone

def create_dsp_bone(parent, bone_set):
	"""Create a bone to be used as another control's custom_shape_transform."""
	dsp_name = "DSP-" + parent.name
	dsp_bone = bone_set.new(
		name			= dsp_name
		,source			= parent
		,bbone_width	= parent.bbone_width*0.5
		,custom_shape	= None
		,parent			= parent
	)
	parent.custom_shape_transform = dsp_bone
	return dsp_bone

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
