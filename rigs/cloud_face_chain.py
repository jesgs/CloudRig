from typing import List
from ..bone import BoneInfo

from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

from .cloud_chain import CloudChainRig, CUSTOM_SPACE

class CloudFaceChainRig(CloudChainRig):
	"""Chain with cartoony squash and stretch controls, with modifications and extra features for face rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_face_chain rigs from the generator, including self.
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

	def create_bone_infos(self):
		super().create_bone_infos()

		### Following code is only run ONCE by the LAST face_chain_rig.
		# This is all code that needs to create or interact with intersection controls.
		if not self.is_last_chain_rig:
			return

		all_str_bones = self.group_str_bones(self.chain_rigs)
		all_intersection_bones = self.ensure_intersection_controls(all_str_bones)

		self.create_armature_parents(all_intersection_bones)
		self.create_armature_parents(all_str_bones)
		if not CUSTOM_SPACE:
			for str_bone in all_str_bones:
				if hasattr(str_bone, 'merged_control'):
					if str_bone.owner_rig.params.CR_chain_smooth_spline:
						str_bone.parent = str_bone.merged_control.parent
					else:
						str_bone.parent = str_bone.merged_control
					if hasattr(str_bone, 'local_helper'):
						str_bone.local_helper.parent = str_bone.parent

	def relink(self):
		"""Overrides cloud_base."""
		if not self.is_last_chain_rig:
			return

		for rig in self.chain_rigs:
			rig.move_and_relink_constraints()

	def move_and_relink_constraints(self):
		"""Overrides cloud_chain.
		"""
		for i, org in enumerate(self.org_chain):
			for c in org.constraint_infos[:]:
				to_bone = self.main_str_bones[i]
				if 'TAIL' in c.name:
					if len(self.main_str_bones) <= i+1:
						self.raise_error(f"Cannot move constraint {c.name} from {org.name} to final STR bone since it doesn't exist! Make sure Final Control param is enabled!")
					to_bone = self.main_str_bones[i+1]

				# TODO: This is currently a pretty big copy paste from cloud_chain's relink(), except for the below two lines. Not great!
				# Probably split off this middle bit into a def get_relink_target(self, index) or so.
				if hasattr(to_bone, 'merged_control'):
					to_bone = to_bone.merged_control

				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	@staticmethod
	def group_str_bones(chain_rigs):
		"""Gather a list of lists of more than one STR bones that are in the same 
		location as another STR bone from another face_chain rig with
		CR_face_chain_merge==True.
		"""
		merge_threshold = 0.000001
		sets_to_merge = {}

		all_str_bones = []
		for rig in chain_rigs:
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

	@staticmethod
	def ensure_intersection_controls(all_str_bones):
		# For each main STR control in this rig
		#   For each main STR control in every other rig
		#	   If the two are in the same position
		#		   Ensure a parent control
		#		   Move both to the layers of the Sub Controls bone set.

		intersection_controls = []
		for str_bone in all_str_bones:
			if hasattr(str_bone, 'group'):
				rig = str_bone.owner_rig
				intersection_control = rig.ensure_intersection_control(str_bone.group)
				if intersection_control not in intersection_controls:
					intersection_controls.append(intersection_control)

		return intersection_controls

	@staticmethod
	def ensure_intersection_control(bones):
		""" Ensure that all bones share the same parent control.
			If this is not the case, create it and parent them.
		"""

		rig = bones[0].owner_rig

		# Check the bones' parents to see if the desired control was already created.
		intersection_control = None
		for b in bones:
			b.layers = b.owner_rig.sub_controls.layers[:]
			if b.parent.name.startswith("STR-I"):
				# print(f"{b.name} - This should never happen because every STR bone should only be passed to ensure_intersection_control() once!")
				# TODO: I thought this should never happen, but it dooo
				intersection_control = b.parent
				break

		if not intersection_control:
			combined_name = rig.naming.combine_names(bones)
			# TODO: This does something funky for combining bones with Cheek and Chin.
			# Eg., STR-TIP-Chin.L + STR-TIP-Cheek1.L + STR-TIP-Cheek3_2.L = STR-I-Cheek1+eek3_2+in.L

			# If the combined name is too long for a bone name (63 chars), ignore bones until the name is short enough.
			for i in range(1, len(bones)-1):
				if len(combined_name) < 60:
					break
				combined_name = rig.naming.combine_names(bones[:-i])

			slices = rig.naming.slice_name(combined_name)
			# Discard prefixes, put STR-I.
			bone_name = rig.naming.make_name(["STR", "I"], slices[1], slices[2])

			# Check again if it exists - TODO this shouldn't be necessary, it should be caught above with the parent check. Although checking doesn't hurt. But if it already existed, add a bug log.
			intersection_control = rig.generator.find_bone_info(bone_name)

			if not intersection_control:
				intersection_control = rig.merged_controls.new(
					name = bone_name
					,source = bones[0]
					,custom_shape = rig.ensure_widget('Cube')
					,custom_shape_scale = bones[0].custom_shape_scale
				)

		# If bones are in the center, flatten them to make sure they produce a clean curvature.
		if abs(intersection_control.head.x) < 0.001:
			intersection_control.vector = Vector((0, 0, intersection_control.length))	# TODO: be nicer to make it aligned with whatever axis the rest of the bones are closest to, instead of arbitrarily the up axis.
			intersection_control.roll = 0
			for b in bones:
				flipped = rig.naming.flipped_name(b)
				if flipped!=b.name:
					b.vector = rig.flat_vector(b.vector)
					if hasattr(b, 'tangent_helper'):
						b.tangent_helper.vector = rig.flat_vector(b.tangent_helper.vector)

		for str_bone in bones:
			if hasattr(str_bone, 'merged_control'):
				continue

			str_bone.parent = intersection_control

			str_bone.merged_control = intersection_control

			if not str_bone.owner_rig.params.CR_chain_smooth_spline:
				continue

			if not CUSTOM_SPACE:
				# Add old-style helpers to propagate rotation from Intersection(STR-I) to STR bones.
				rig = str_bone.owner_rig
				intersection_helper = rig.face_mch.new(
					name = rig.naming.add_prefix(str_bone, "I-H")
					,source = str_bone
					,parent = intersection_control
				)
				
				local_helper = str_bone.local_helper = rig.face_mch.new(
					name = rig.naming.add_prefix(str_bone, "I-H-L")
					,source = str_bone
					,parent = intersection_control.parent
				)
				local_helper.add_constraint('COPY_ROTATION'
					,subtarget = intersection_helper.name
					,mix_mode = 'REPLACE'
					,space = 'WORLD'
				)
				local_helper.add_constraint('COPY_LOCATION'
					,subtarget = intersection_helper.name
					,space = 'WORLD'
				)

				str_bone.add_constraint('COPY_ROTATION'
					,subtarget = local_helper.name
				)
				str_bone.add_constraint('COPY_LOCATION'
					,subtarget = local_helper.name
				)
				str_bone.add_constraint('COPY_SCALE'
					,subtarget = intersection_control.name
					,space = 'LOCAL'
				)

				return intersection_control
			str_bone.tangent_helper.add_constraint('COPY_ROTATION'
				,subtarget = intersection_control.name
				,index = 1
				,owner_space = 'CUSTOM'
				,space_object = rig.obj
				,space_subtarget = intersection_control.name
			)

			str_bone.tangent_clone.add_constraint('COPY_ROTATION'
				,index = 1
				,subtarget = intersection_control.name
				,owner_space = 'CUSTOM'
				,space_object = rig.obj
				,space_subtarget = intersection_control.name
			)
		
		return intersection_control

	@staticmethod
	def create_armature_parents(all_str_bones):
		"""For Main STR Controls and Intersection controls that now have an Armature
		constraint, create a parent bone and move the armature constraint to that.
		"""

		# Armature constraints turn parenting into local matrix, which 
		# messes up DT helper bones that rely on that local rotation.
		# So if Smooth Spline param is enabled and we are relinking an 
		# armature constraint, make a separate bone for it.
		for str_bone in all_str_bones:
			for c in str_bone.constraint_infos:
				bone = str_bone
				rig = bone.owner_rig
				# bone = str_bone.parent # TODO: If cloud_chain.CUSTOM_SPACE = True, maybe this needs to be uncommented??
				if c.type=='ARMATURE' and not hasattr(bone, 'arm_parent'):
					bone.arm_parent = rig.create_parent_bone(bone, rig.face_mch)
					bone.arm_parent.constraint_infos.append(c)
				else:
					bone.constraint_infos.append(c)
				str_bone.constraint_infos.remove(c)

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Sub Controls", 	preset=1,	default_layers=[cls.default_layers('MCH')])#, override='MCH')
		cls.define_bone_set(params, "Merged Controls",	preset=8,	default_layers=[cls.default_layers('STRETCH')])
		cls.define_bone_set(params, "Face Helpers", 				default_layers=[cls.default_layers('MCH')], override='MCH')

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

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_face_chain_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_face_chain_merge")

		return layout

class Rig(CloudFaceChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)