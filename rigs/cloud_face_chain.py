from typing import List
from ..rig_features.bone import BoneInfo

from bpy.props import BoolProperty
from mathutils import Vector

from .cloud_chain import CloudChainRig
from .cloud_chain_anchor import CloudChainAnchorRig

MERGE_THRESHOLD = 0.000001

def has_tangent_helpers(rig) -> bool:
	return rig.params.CR_chain_smooth_spline and rig.params.CR_chain_bbone_density > 0

def parent_cluster_to_intersection(cluster: List[BoneInfo], intersection: BoneInfo):
	for str_bone in cluster:
		rig = str_bone.owner_rig
		str_bone.parent = intersection
		str_bone.intersection_ctrl = intersection
		if has_tangent_helpers(rig):
			str_bone.tangent_helper.constraint_infos[-1].subtarget = intersection.name
			str_bone.tangent_helper.constraint_infos[-1].name = "Copy STR-I Transforms"
			str_bone.tangent_helper.parent = intersection
		str_bone.bone_group = rig.bone_sets['Sub Controls'].bone_group
		str_bone.layers = rig.bone_sets['Sub Controls'].layers[:]

def get_bone_clusters(chain_rigs) -> List[List[BoneInfo]]:
	"""Gather a list of lists of more than one STR bones that are in the same
	location as another STR bone from another face_chain rig with
	CR_face_chain_merge==True.
	"""

	clusters = []
	bones_in_a_cluster = []

	all_str_bones = []
	for rig in chain_rigs:
		if not rig.params.CR_face_chain_merge: continue
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
	# If bones are in the center, flatten them to make sure they produce a clean curvature.
	# This is important for things like the teeth or the lips, which are one rig
	# element on each side that meet in the center, and are expected to make a smooth curve.

	rig = cluster[0].owner_rig

	if not is_anchor:
		intersection.vector = Vector((0, 0, intersection.length))
		intersection.roll = 0

	for b in cluster:
		b.flatten()
		if has_tangent_helpers(b.owner_rig):
			b.tangent_helper.flatten()
		if b.owner_rig.params.CR_chain_smooth_spline:
			flipped_name = rig.naming.flipped_name(b)
			if flipped_name == b.name:
				continue
			opposite_bone = b.owner_rig.generator.find_bone_info(flipped_name)
			if not opposite_bone:
				continue
			if has_tangent_helpers(opposite_bone.owner_rig):
				# Make the Damped Track constraint of the opposite TAN- bone aim 
				# at this STR bone's Damped Track target.
				# This gets us a smooth curve across the two chains.
				# (This is also what would happen if it was just one longer smooth chain)
				b.tangent_helper.constraint_infos[1].subtarget = opposite_bone.tangent_helper.constraint_infos[0].subtarget

class CloudFaceChainRig(CloudChainRig):
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
				if has_tangent_helpers(str_bone.owner_rig):
					str_bone.tangent_helper.parent = intersection.parent

		# HACK: We can't ensure that the last chain rig to be executed is a cloud_eyelid,
		# so we just have to make this class aware of its descendant, which is
		# possibly the worst thing I've ever coded.
		for chain_rig in self.chain_rigs:
			if type(chain_rig) != type(self):
				chain_rig.make_sticky_eyelid()

	def create_bone_infos(self):
		super().create_bone_infos()

		### Following code is only run ONCE by the LAST face_chain_rig.
		if not self.is_last_chain_rig:
			return

		# This is all code that needs to create or interact with intersection controls.

		str_bone_clusters = get_bone_clusters(self.chain_rigs)
		self.intersection_bones = []

		for cluster in str_bone_clusters:
			self.intersection_bones.append(self.create_intersection_for_cluster(cluster))

	def relink(self, last_chain_done=False):
		# Only relink all cloud_face_chain rigs when the last one is generating.
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

		if con.type == 'ARMATURE' and not hasattr(relink_bone, "parent_helper"):
			relink_bone = relink_bone.parent_helper = self.create_parent_bone(relink_bone, self.bones_mch)

		return relink_bone

	@staticmethod
	def create_intersection_for_cluster(cluster: List[BoneInfo]) -> BoneInfo:
		""" Try to find a CloudChainAnchorRig to parent the cluster to.
			If it doesn't exist, create one.
		"""

		rig = cluster[0].owner_rig

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
		parent_cluster_to_intersection(cluster, intersection_control)

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

		params.CR_face_chain_merge = BoolProperty(
			name		 = "Merge Controls"
			,description = "If any controls of this rig intersect with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer"
			,default	 = True
		)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)
		cls.draw_prop(layout, params, "CR_face_chain_merge")

class Rig(CloudFaceChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)