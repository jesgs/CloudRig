from typing import List
from bpy.types import PropertyGroup
from ..rig_component_features.bone import BoneInfo

from bpy.props import BoolProperty
from mathutils import Vector

from .cloud_chain import Component_ToonChain
from .cloud_chain_anchor import CloudChainAnchorRig

MERGE_THRESHOLD = 0.000001
# TODO: Center merging probably doesn't work without an anchor, or when Smooth Spline is on. Need tests!

def has_tangent_helpers(rig) -> bool:
	return rig.params.chain.smooth_spline and rig.params.chain.bbone_density > 0

def parent_cluster_to_intersection(cluster: List[BoneInfo], intersection: BoneInfo, have_anchor: bool):
	for str_bone in cluster:
		rig = str_bone.owner_component
		str_bone.parent = intersection
		str_bone.intersection_ctrl = intersection
		if has_tangent_helpers(rig) and not have_anchor:
			str_bone.tangent_helper.constraint_infos[-1].subtarget = intersection.name
			str_bone.tangent_helper.constraint_infos[-1].name = "Copy STR-I Transforms"
			str_bone.tangent_helper.parent = intersection
		str_bone.bone_group = rig.bone_sets['Sub Controls'].bone_group
		str_bone.layers = rig.bone_sets['Sub Controls'].layers[:]

def get_bone_clusters(chain_rigs) -> List[List[BoneInfo]]:
	"""Gather a list of lists of more than one STR bones that are in the same
	location as another STR bone from another face_chain rig with
	params.face_chain.merge==True.
	"""

	clusters = []
	bones_in_a_cluster = []

	all_str_bones = []
	for rig in chain_rigs:
		if not rig.params.face_chain.merge: continue
		all_str_bones.extend(rig.main_str_bones)

	for str_bone in all_str_bones:
		if str_bone in bones_in_a_cluster: continue
		cluster = [str_bone]
		for other_str in all_str_bones:
			if other_str in bones_in_a_cluster: continue
			if str_bone == other_str: continue
			if (str_bone.head - other_str.head).length < MERGE_THRESHOLD:
				cluster.append(other_str)
		if len(cluster) > 1:
			clusters.append(cluster)
		bones_in_a_cluster.extend(cluster)

	return clusters

def do_centered_cluster(cluster: List[BoneInfo], intersection: BoneInfo, is_anchor=False):
	# If bones are in the center, flatten them along the X axis to make sure 
	# they produce a clean curvature. This is important for things like the 
	# teeth or the lips, which are one rig element on each side that meet in 
	# the center, and are expected to make a smooth curve.
	rig = cluster[0].owner_component

	pos_sum = cluster[0].head.copy()
	for c in cluster[1:]:
		pos_sum += c.head
	avg_pos = pos_sum / len(cluster)

	if not is_anchor:
		intersection.vector = Vector((0, 0, intersection.length))
		intersection.roll = 0
		intersection.roll_type = 'VECTOR'
		intersection.roll_vector = avg_pos

	for b in cluster:
		b.flatten(axis='X')
		if has_tangent_helpers(b.owner_component):
			b.tangent_helper.flatten(axis='X')
		if b.owner_component.params.chain.smooth_spline:
			flipped_name = rig.naming.flipped_name(b)
			if flipped_name == b.name:
				continue
			opposite_bone = b.owner_component.generator.find_bone_info(flipped_name)
			if not opposite_bone:
				continue
			if has_tangent_helpers(opposite_bone.owner_component):
				# Make the Damped Track constraint of the opposite TAN- bone aim 
				# at this STR bone's Damped Track target.
				# This gets us a smooth curve across the two chains.
				# (This is also what would happen if it was just one longer smooth chain)
				b.tangent_helper.constraint_infos[1].subtarget = opposite_bone.tangent_helper.constraint_infos[0].subtarget

class CloudFaceChainRig(Component_ToonChain):
	"""Chain with cartoony squash and stretch controls, which supports intersecting bone chains."""

	relinking_behaviour = "Constraints will be moved to the STR bone at the metarig bone's head, or tail if the constraint name is prefixed with \"TAIL-\". If the STR bone is part of an intersection, the constraint is moved to the STR-I intersection control instead."

	def initialize(self):
		super().initialize()

		# Check the generator rig list to see if we are the last chain rig that will be generated.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if isinstance(rig, CloudFaceChainRig):
				self.chain_rigs.append(rig)

		self.is_last_chain_rig = self == self.chain_rigs[-1]

	def prepare_bones(self):
		super().prepare_bones()

		### Following code is only run ONCE by the LAST face_chain_rig.
		if not self.is_last_chain_rig:
			return

		# This is ugly, but any STR controls with the Smooth Spline param need
		# their tangent_helper to be parented to the intersection control's parent.
		for intersection in self.intersection_bones:
			for str_bone in intersection.str_bones:
				if has_tangent_helpers(str_bone.owner_component):
					str_bone.tangent_helper.parent = intersection.parent

		# HACK: We can't ensure that the last chain rig to be executed is a cloud_eyelid,
		# so we just have to make this class aware of its descendant, which is
		# possibly the worst thing I've ever coded.
		for chain_rig in self.chain_rigs:
			if hasattr(chain_rig, 'make_sticky_eyelid'):
				chain_rig.make_sticky_eyelid()

	def create_bone_infos(self, context):
		super().create_bone_infos(context)

		### Following code is only run ONCE by the LAST face_chain_rig.
		if not self.is_last_chain_rig:
			return

		# This is all code that needs to create or interact with intersection controls.

		str_bone_clusters = get_bone_clusters(self.chain_rigs)
		self.intersection_bones = []

		for cluster in str_bone_clusters:
			self.intersection_bones.append(self.create_intersection_for_cluster(cluster))

	def relink(self, last_chain_done=False):
		# Only relink all cloud_face_chain components when the last one is generating.
		if last_chain_done:
			super().relink()
			return
		elif not self.is_last_chain_rig:
			return

		for rig in self.chain_rigs:
			rig.relink(last_chain_done = True)

	def get_relink_target(self, org_i, con):
		"""Overrides cloud_chain. Only work when called by the last chain rig.
		Relink target should become the intersection control if there is one.
		"""

		if con.name.startswith('TAIL-'):
			relink_bone = self.main_str_bones[org_i+1]
		else:
			relink_bone = self.main_str_bones[org_i]

		if hasattr(relink_bone, 'intersection_ctrl'):
			relink_bone = relink_bone.intersection_ctrl

		if con.type == 'ARMATURE':
			if not hasattr(relink_bone, "parent_helper"):
				relink_bone = relink_bone.parent_helper = self.create_parent_bone(relink_bone, self.bones_mch)
			else:
				relink_bone = relink_bone.parent_helper
				print("SKIPPED " + relink_bone.parent_helper.name)

		return relink_bone

	@staticmethod
	def create_intersection_for_cluster(cluster: List[BoneInfo]) -> BoneInfo:
		""" Try to find a CloudChainAnchorRig to parent the cluster to.
			If it doesn't exist, create one.
		"""

		rig = cluster[0].owner_component

		intersection_control = None
		have_anchor = False
		# Search for an anchor rig
		anchor_rigs = [r for r in rig.generator.rig_list if isinstance(r, CloudChainAnchorRig)]
		for anchor_rig in anchor_rigs:
			distance = (anchor_rig.bones_org[0].head - cluster[0].head).length
			if distance < 0.000001:
				intersection_control = anchor_rig.bones_org[0]
				have_anchor = True
				break

		if not intersection_control:
			combined_name = rig.naming.combine_names(cluster)

			slices = rig.naming.slice_name(combined_name)
			# Discard prefixes, put STR-I.
			bone_name = rig.naming.make_name(["STR", "I"], slices[1], slices[2])

			intersection_control = rig.bone_sets['Intersection Controls'].new(
				name = bone_name
				,source = cluster[0]
				,custom_shape = rig.ensure_widget('Cube')
				,custom_shape_scale = 0.5
			)

		if abs(intersection_control.head.x) < 0.001:
			do_centered_cluster(cluster, intersection_control, have_anchor)

		# Parent the bones
		parent_cluster_to_intersection(cluster, intersection_control, have_anchor)

		intersection_control.str_bones = cluster
		return intersection_control

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		# The sub_controls set is special in that its .new() function should never be
		# called, and therefore it never creates any bones. However, pre-existing
		# STR bones who then had a merged control created for them will be assigned
		# the bone group and layer of this BoneSet.
		cls.define_bone_set(params, 'Sub Controls', 	preset=1,	default_layers=[cls.DEFAULT_LAYERS.MCH])#, is_advanced=True)
		cls.define_bone_set(params, 'Intersection Controls',	preset=8,	default_layers=[cls.DEFAULT_LAYERS.STRETCH])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)


	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)
		cls.draw_prop(context, layout, params.face_chain, 'merge')

class Params(PropertyGroup):
	merge: BoolProperty(
		name		 = "Merge Controls"
		,description = "If any controls of this rig intersect with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer"
		,default	 = True
	)

class RigComponent(CloudFaceChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)