from typing import List
from ..bone import BoneInfo

from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

from .cloud_chain import CloudChainRig

class CloudFaceChainRig(CloudChainRig):
	"""Chain with cartoony squash and stretch controls, with modifications and extra features for face rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_face_chain rigs from the generator, excluding self.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if isinstance(rig, type(self)):
				self.chain_rigs.append(rig)
		
		self.is_last_chain_rig = self == self.chain_rigs[-1]

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		# This bone set is special in that its .new() function should never be 
		# called, and therefore it never creates any bones. However, pre-existing 
		# STR bones who then had a merged control created for them will be assigned 
		# the bone group and layer of this BoneSet.
		self.sub_controls = self.ensure_bone_set("Sub Controls")
		self.merged_controls = self.ensure_bone_set("Merged Controls")
		self.face_mch = self.ensure_bone_set("Face Helpers")

	def prepare_bones(self):
		super().prepare_bones()
		
		if self.params.CR_face_chain_relink:
			self.move_and_relink_constraints()

		### Following code is only run ONCE by the LAST face_chain_rig.
		if not self.is_last_chain_rig:
			return

		all_str_bones = self.group_str_bones()
		self.ensure_intersection_controls(all_str_bones)
		self.create_armature_parents(all_str_bones)

	def move_and_relink_constraints(self):
		"""Move constraints from ORG bones to main STR bones and relink them.

		If the constraint name contains 'TAIL', we assume the constraint is meant
		for the STR bone at the tip or the ORG bone rather than at the head.
		"""
		for i, org in enumerate(self.org_chain):
			for c in org.constraint_infos[:]:
				to_bone = self.main_str_bones[i]
				if 'TAIL' in c.name:
					to_bone = self.main_str_bones[i+1]

				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				c.relink()

	def group_str_bones(self):
		"""Gather a list of lists of more than one STR bones that are in the same 
		location as another STR bone from another face_chain rig with
		CR_face_chain_merge==True.
		"""
		merge_threshold = 0.000001
		sets_to_merge = {}

		all_str_bones = []
		for rig in self.chain_rigs:
			if not rig.params.CR_face_chain_merge: continue
			all_str_bones.extend(rig.main_str_bones)

		for str_bone in all_str_bones:
			for other_str in all_str_bones:
				if str_bone == other_str: continue
				if (str_bone.head - other_str.head).length < merge_threshold:
					if hasattr(str_bone, 'group') and other_str not in str_bone.group:
						str_bone.group.append(other_str)
						other_str.group = str_bone.group
					elif hasattr(other_str, 'group') and str_bone not in other_str.group:
						other_str.group.append(str_bone)
						str_bone.group = other_str.group
					else:
						str_bone.group = other_str.group = [str_bone, other_str]
		
		return all_str_bones

	def ensure_intersection_controls(self, all_str_bones):
		# For each main STR control in this rig
		#   For each main STR control in every other rig
		#	   If the two are in the same position
		#		   Ensure a parent control
		#		   Move both to the layers of the Sub Controls bone set.

		for str_bone in all_str_bones:
			if hasattr(str_bone, 'group'):
				self.ensure_intersection_control(str_bone.group)

	def ensure_intersection_control(self, bones):
		""" Ensure that all bones share the same parent control.
			If this is not the case, create it and parent them.
		"""

		# Check the bones' parents to see if the desired control was already created.
		intersection_control = None
		for b in bones:
			b.layers = b.owner_rig.sub_controls.layers[:]
			if b.parent.name.startswith("STR-I"):
				# TODO: I thought this should never happen, but it dooo
				intersection_control = b.parent
				break

		if not intersection_control:
			combined_name = self.naming.combine_names(bones)
			slices = self.naming.slice_name(combined_name)
			# Discard prefixes, put STR-I.
			bone_name = self.naming.make_name(["STR", "I"], slices[1], slices[2])
			intersection_control = bones[0].owner_rig.new_bonei(bones[0].owner_rig.merged_controls
				,name = bone_name
				,source = bones[0]
				,custom_shape = self.ensure_widget('Cube')
				,custom_shape_scale = bones[0].custom_shape_scale
			)

		# If bones are in the center, flatten them to make sure they produce a clean curvature.
		if abs(intersection_control.head.x) < 0.001:
			intersection_control.vector = Vector((0, 0, intersection_control.length))	# TODO: be nicer to make it aligned with whatever axis the rest of the bones are closest to, instead of arbitrarily the up axis.
			intersection_control.roll = 0
			for b in bones:
				b.vector = self.flat_vector(b.vector)

		for str_bone in bones:
			if hasattr(str_bone, 'merged_control'):
				continue

			str_bone.parent = intersection_control # This will be set to None later by the generator when it sees the Armature constraint, just using it for easy access here.

			str_bone.merged_control = intersection_control

			if not str_bone.owner_rig.params.CR_chain_smooth_spline:
				continue

			str_bone.tangent_helper.add_constraint('COPY_ROTATION'
				,subtarget = intersection_control.name
				,index = 1
				,owner_space = 'CUSTOM'
				,space_object = self.obj
				,space_subtarget = intersection_control.name
			)

			str_bone.tangent_clone.add_constraint('COPY_ROTATION'
				,index = 1
				,subtarget = intersection_control.name
				,owner_space = 'CUSTOM'
				,space_object = self.obj
				,space_subtarget = intersection_control.name
			)

	def create_armature_parents(self, all_str_bones):
		"""For Main STR Controls and Intersection controls that now have an Armature
		constraint, create a parent bone and move the armature constraint to that.
		"""

		# Armature constraints turn parenting into local matrix, which 
		# messes up DT helper bones that rely on that local rotation.
		# So if Smooth Spline param is enabled and we are relinking an 
		# armature constraint, make a separate bone for it.
		for str_bone in all_str_bones:
			for c in str_bone.constraint_infos:

				if c.type=='ARMATURE' and not hasattr(str_bone.parent, 'arm_parent'):
					str_bone.parent.arm_parent = self.create_parent_bone(str_bone.parent, self.face_mch)
					str_bone.parent.arm_parent.constraint_infos.append(c)
				else:
					str_bone.parent.constraint_infos.append(c)
				str_bone.constraint_infos.remove(c)

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Sub Controls", 	preset=1,	default_layers=[cls.default_layers('MCH')])
		cls.define_bone_set(params, "Merged Controls",	preset=8,	default_layers=[cls.default_layers('STRETCH')])
		cls.define_bone_set(params, "Face Helpers", 				default_layers=[cls.default_layers('MCH')])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_face_chain_show_settings = BoolProperty(
			name		 = "Face Chain Settings"
			,description = "Reveal settings for the cloud_face_chain rig type"
		)
		params.CR_face_chain_merge = BoolProperty(
			name		 = "Merge Controls"
			,description = "If any controls of this rig overlap with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer"
			,default	 = True
		)
		params.CR_face_chain_relink = BoolProperty(
			name		 = "Relink Constraints"
			,description = "Constraints on this chain will be relinked to the corresponding STR controls that are created for them. For the final bone of the chain, constraints intended for the final control should be prefixed with \"TAIL-\""
			,default	 = True
		)

	@classmethod
	def draw_cloud_params(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_face_chain_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_face_chain_merge")
		cls.draw_prop(layout, params, "CR_face_chain_relink")

		return layout

class Rig(CloudFaceChainRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_face_chain")