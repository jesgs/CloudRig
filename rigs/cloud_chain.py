from typing import Tuple, List
from ..bone import BoneInfo, BoneSet

from bpy.props import BoolProperty, IntProperty
from mathutils.geometry import intersect_point_line

from .cloud_base import CloudBaseRig

"""
Ideas to improve this:
Spline IK like controls(the other two types) for bendy bones' handles.
Recursive generation of layers of STR controls... Little use case and lots of headache.
"""

CUSTOM_SPACE = True	# TODO: This is now in master but smooth chains are apparently glitching again, whether this is True or False, when the character's root is rotated. What!?

class CloudChainRig(CloudBaseRig):
	"""Chain with cartoony squash and stretch controls."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.chain_length = 0
		if self.params.CR_chain_bbone_density > 0:
			self.params.CR_chain_unlock_deform = False

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.str_chain = self.ensure_bone_set("Stretch Controls")
		self.str_mch = self.ensure_bone_set("Stretch Helpers")
		self.skh_bones = self.ensure_bone_set("Shape Key Helpers")
		if self.params.CR_chain_unlock_deform:
			self.def_ctr = self.ensure_bone_set("Deform Controls")
			self.def_mch = self.ensure_bone_set("Deform Helpers")

	def create_bone_infos(self):
		super().create_bone_infos()

		self.cyclic = (self.org_chain[-1].tail - self.org_chain[0].head).length < 0.001

		for org in self.org_chain:
			self.chain_length += org.length
		self.average_org_length = self.chain_length / len(self.org_chain)

		str_sections = self.make_str_chain(self.org_chain)
		if self.params.CR_chain_segments > 1:
			self.make_str_helpers(str_sections)

		if self.params.CR_chain_smooth_spline:
			for str_bone in self.str_chain:
				self.set_up_smooth_spline(str_bone)
		else:
			for str_bone in self.str_chain:
				str_bone.tangent_helper = self.make_tangent_helper(str_bone)

		self.make_def_chain(self.str_chain)

		self.connect_parent_chain_rig()

	def reparent_bone(self, child: BoneInfo):
		"""Override.

		Children of this rig's ORG bones should be re-parented to the appropriate
		DEF bone using Armature constraint, if that DEF bone's bbone_segments > 1.
		"""

		parent = super().reparent_bone(child)

		if child.parent not in self.org_chain:
			return
		if len(parent.def_bones)==0:
			return
		for c in child.constraint_infos:
			if c.type=='ARMATURE':
				return

		# Also note that this function is expected to be called by child rigs,
		# which means this rig already finished executing, which means we know that
		# make_def_chain() has run, and ORG bones are aware of their DEF bones.

		# Get ratio of how far along the child bone is on the ORG bone.
		intersect = intersect_point_line(child.head, parent.head, parent.tail)
		ratio = intersect[1]
		def_index = ratio * self.params.CR_chain_segments
		def_index = int(def_index)
		def_index = max(0, min(def_index, len(parent.def_bones)-1) )	# Clamp it.

		def_bone = parent.def_bones[def_index]

		if def_bone.bbone_segments == 1:
			return

		child.parent = def_bone
		child.add_constraint('ARMATURE'
			,use_deform_preserve_volume = True
			,targets = [
				{
					"subtarget" : child.parent.name
				}
			],
		)

		return parent

	def relink(self):
		"""Overrides cloud_base"""
		self.move_and_relink_constraints()

	def move_and_relink_constraints(self):
		"""Move constraints from ORG bones to main STR bones and relink them.

		If the constraint name contains 'TAIL', we assume the constraint is meant
		for the STR bone at the tip or the ORG bone rather than at the head.
		"""
		for i, org in enumerate(self.org_chain):
			for c in org.constraint_infos[:]:
				to_bone = self.main_str_bones[i]
				if 'TAIL' in c.name:
					if len(self.main_str_bones) <= i+1:
						# TODO: Add a log, don't totally cancel the generation!
						self.raise_error(f"Cannot move constraint {c.name} from {org.name} to final STR bone since it doesn't exist! Make sure Final Control param is enabled!")
					to_bone = self.main_str_bones[i+1]

				if c.type=='ARMATURE':
					to_bone = self.create_parent_bone(to_bone, self.parent_switch_bones)

				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	def determine_segments(self, org_bone: BoneInfo) -> Tuple[int, int]:
		"""Determine how many deform and b-bone segments should be in a section of the chain."""
		segments = self.params.CR_chain_segments

		bbone_density = round(org_bone.length/self.average_org_length *
			self.params.CR_chain_bbone_density * self.params.CR_chain_segments)

		# No segments for last bone of the chain if there is no control for its tail.
		if org_bone == self.org_chain[-1] and not self.params.CR_chain_tip_control:
			return 1, 1

		return segments, bbone_density

	def make_str_chain(self, org_chain: BoneSet) -> List[List[BoneInfo]]:
		"""Create all STR controls for this chain."""
		self.main_str_bones: List[BoneInfo] = []
		str_sections = []
		for org_i, org_bone in enumerate(org_chain):
			segments, bbone_density = self.determine_segments(org_bone)

			str_section = []
			for i in range(segments):
				str_bone = self.make_str_bone(org_bone, i, segments)
				str_section.append(str_bone)
				if i==0:
					str_bone.custom_shape_scale *= 1.3
					self.main_str_bones.append(str_bone)
					if org_i == 0 and self.cyclic:
						direction = (org_bone.tail - self.org_chain[-1].head).normalized()
						str_bone.tail = str_bone.head + direction*str_bone.length

			str_sections.append(str_section)

			# Create STR-TIP control at the end of the chain.
			if org_i==len(org_chain)-1 and self.params.CR_chain_tip_control:
				if self.cyclic:
					self.str_chain[-1].next = self.str_chain[0]
					self.str_chain[0].prev = self.str_chain[-1]
				else:
					str_bone = self.make_str_bone(org_bone, i, 1, name=self.naming.add_prefix(str_bone, "TIP"))
					str_bone.put(org_bone.tail)
					str_bone.vector = org_bone.vector
					str_bone.length = str_bone.prev.length
					str_bone.custom_shape_scale *= 1.3
					str_sections.append([str_bone])
					self.main_str_bones.append(str_bone)

		# Set first and last control's shapes
		if not self.cyclic:
			self.str_chain[0].custom_shape = self.ensure_widget("Hemisphere_Flip")
			self.str_chain[-1].custom_shape = self.ensure_widget("Hemisphere")

		return str_sections

	def make_str_bone(self, org_bone: BoneInfo, seg_i: int, segments: int, name="") -> BoneInfo:
		"""Create an STR control."""
		direction = org_bone.vector
		if seg_i==0 and org_bone.prev:
			direction = org_bone.tail - org_bone.prev.head
		unit = org_bone.vector / segments
		if name=="":
			name = org_bone.name.replace("ORG", "STR")
		str_bone = self.str_chain.new(
			name = name
			,source = org_bone
			,head = org_bone.head + (unit * seg_i)
			,vector = direction
			,length = org_bone.length / segments / 2
			,roll = org_bone.roll
			,custom_shape = self.ensure_widget("Sphere")
			,custom_shape_scale = 0.3
			,parent = org_bone
		)

		str_bone.org_parent = org_bone

		if segments>1:
			sliced = self.naming.slice_name(str_bone.name)
			str_bone.name = self.naming.make_name(sliced[0], f"{sliced[1]}{seg_i+1}", sliced[2])
		str_bone.bbone_width *= 1.2
		return str_bone

	def make_str_helpers(self, str_sections: List[List[BoneInfo]]):
		"""Create STR-H bones that keep STR controls between two main STR controls."""
		main_str_bone = None
		for sec_i, section in enumerate(str_sections):
			if self.params.CR_chain_tip_control and section==str_sections[-1]:
				# If there is a tip control, the last section will be just that tip control, so do nothing.
				continue
			for i, str_bone in enumerate(section):
				# If this STR bone is not the first in its section
				# Create an STR-H parent helper for it, which will hold some constraints
				# that keep this bone between the first and last STR bone of the section.
				if i==0:
					main_str_bone = str_bone
					main_str_bone.sub_bones = []
					continue
				main_str_bone.sub_bones.append(str_bone)

				str_h_bone = self.str_mch.new(
					name 		 = self.naming.add_prefix(str_bone, "H")
					,source 	 = str_bone
					,bbone_width = str_bone.bbone_width
					,parent		 = str_bone.parent
					,hide_select = self.mch_disable_select
				)
				# if self.rigify_parent:
				# 	self.rigify_parent.reparent_bone(str_h_bone.parent)
				str_bone.parent = str_h_bone

				first_str = section[0].name
				last_str = str_sections[sec_i+1][0].name
				influence_unit = 1 / len(section)
				influence = i * influence_unit
				str_h_bone.add_constraint('COPY_LOCATION'
					,space		= 'WORLD'
					,subtarget	= first_str
				)
				str_h_bone.add_constraint('COPY_LOCATION'
					,space		= 'WORLD'
					,subtarget	= last_str
					,influence	= influence)

				str_h_bone.add_constraint('COPY_ROTATION'
					,space		= 'WORLD'
					,subtarget	= first_str
				)
				str_h_bone.add_constraint('COPY_ROTATION'
					,space		= 'WORLD'
					,subtarget	= last_str
					,influence	= influence
				)
				str_h_bone.add_constraint('DAMPED_TRACK', subtarget=last_str)

	def set_up_smooth_spline(self, str_bone, prev=None, nxt=None):
		str_bone.dt_bone = self.make_dt_helper(str_bone, prev, nxt)
		str_bone.tangent_helper = self.make_tangent_helper(str_bone)

	def make_dt_helper(self, str_bone: BoneInfo,
						prev: BoneInfo = None, nxt: BoneInfo = None) -> BoneInfo:
		"""Create a child bone for an STR bone with Damped Track constraints
		to aim at the previous and next STR bones."""
		dt_bone = self.str_mch.new(
			name = self.naming.add_prefix(str_bone, "DT")
			,source = str_bone
			,parent = str_bone
			,overwrite = True
		)
		if not nxt:
			nxt = str_bone.next
		if not prev:
			prev = str_bone.prev

		if nxt:
			pos_con = dt_bone.add_constraint('DAMPED_TRACK'
				,name = "Damped Track +Y"
				,subtarget = nxt.name
				,track_axis='TRACK_Y'
			)
		if prev:
			neg_con = dt_bone.add_constraint('DAMPED_TRACK'
				,name = "Damped Track -Y"
				,subtarget = prev.name
				,track_axis='TRACK_NEGATIVE_Y'
			)
			if nxt:
				neg_con.influence = 0.5
		dt_bone.inherit_scale = 'AVERAGE'	# No real purpose, just for viewport display

		return dt_bone

	def make_tangent_helper(self, str_bone):
		tangent_helper = self.str_mch.new(
			name = self.naming.add_prefix(str_bone, "TAN")
			,source = str_bone
			,parent = str_bone
			,inherit_scale = 'NONE'
			,overwrite = True
		)
		tangent_helper.add_constraint('COPY_SCALE'
			,subtarget = str_bone.name
			,space = 'WORLD'
		)

		if not self.params.CR_chain_smooth_spline:
			return tangent_helper

		assert hasattr(str_bone, 'dt_bone'), f"make_tangent_helper() called for str_bone {str_bone} without calling make_dt_helper() first, while Smooth Chain param is True."

		dt = str_bone.dt_bone
		tangent_helper.add_constraint('COPY_ROTATION'
			,name = "Copy Rotation (Damped Track Helper)"
			,subtarget = dt.name
		)
		if CUSTOM_SPACE:
			tangent_helper.add_constraint('COPY_ROTATION'
				,name = "Copy Rotation (User Rotation Reader)"
				,subtarget = str_bone.name
				,owner_space = 'CUSTOM'
				,space_object = self.obj
				,space_subtarget = str_bone.name
			)
		else:
			tangent_helper.add_constraint('COPY_ROTATION'
				,name = "Copy Rotation (User Rotation)"
				,subtarget = str_bone.name
			)
			tangent_helper.add_constraint('COPY_ROTATION'
				,name = "Copy Rotation (Remove Y)"
				,use_xyz = [False, True, False]
				,invert_xyz = [False, True, False]
				,subtarget = str_bone.name
			)

		if not CUSTOM_SPACE:
			return tangent_helper
		# TODO: Had to copy paste this code, would be nice to have a proper
		# utility for copying a bone with its constraints and drivers and whatnot.
		tangent_clone = self.str_mch.new(
			name = self.naming.add_prefix(tangent_helper, "CLONE")
			,source = str_bone
			,parent = str_bone
			,inherit_scale = 'NONE'
		)
		tangent_clone.add_constraint('COPY_ROTATION'
			,name = "Copy Rotation (Damped Track Helper)"
			,subtarget = dt.name
		)
		tangent_clone.add_constraint('COPY_ROTATION'
			,name = "Copy Rotation (User Rotation Reader)"
			,subtarget = str_bone.name
			,owner_space = 'CUSTOM'
			,space_object = self.obj
			,space_subtarget = str_bone.name
		)

		tangent_helper.add_constraint('COPY_ROTATION'
			,subtarget = tangent_clone.name
			,use_xyz = [False, True, False]
			,invert_xyz = [False, True, False]
			,owner_space = 'CUSTOM'
			,space_object = self.obj
			,space_subtarget = tangent_clone.name
		)

		str_bone.tangent_clone = tangent_clone

		return tangent_helper

	def make_def_chain(self, str_chain: List[BoneInfo]) -> List[BoneInfo]:
		"""Create a deform chain stretching from one STR bone to the next"""
		for str_i, str_bone in enumerate(str_chain):
			# Skip the tip control
			if str_bone == str_chain[-1] and self.params.CR_chain_tip_control and not self.cyclic:
				continue

			org_bone = str_bone.org_parent
			if not hasattr(org_bone, 'def_bones'):
				org_bone.def_bones = []

			tail = org_bone.tail
			if str_bone.next:
				tail = str_bone.next.head

			def_name = str_bone.name.replace("STR", "DEF")
			def_bone = self.def_chain.new(
				name					 = def_name
				,source					 = org_bone
				,parent					 = str_bone
				,head					 = str_bone.head
				,tail					 = tail
				,bbone_handle_type_start = 'TANGENT'
				,bbone_handle_type_end	 = 'TANGENT'
				,bbone_custom_handle_start = str_bone.tangent_helper
				,hide_select			 = self.mch_disable_select
				,use_deform				 = True
			)
			org_bone.def_bones.append(def_bone)

			if self.params.CR_chain_unlock_deform:
				def_bone_control = self.create_parent_bone(def_bone, bone_set=self.def_ctr)
				def_bone_control.name = def_bone_control.name.replace("DEF-P-", "DEF_CTR-")
				def_bone_control.inherit_scale = 'ALIGNED'
				def_bone_parent = self.create_parent_bone(def_bone_control, bone_set=self.def_mch)
				def_bone_control.head = def_bone_control.center
				def_bone_control.custom_shape_scale *= 0.5
				self.setup_def_bone(def_bone_parent, org_bone, str_bone, str_bone.next)
				def_bone_control.custom_shape = self.ensure_widget('Cube_Flat')
			else:
				self.setup_def_bone(def_bone, org_bone, str_bone, str_bone.next)

		return self.def_chain

	def setup_def_bone(self, def_bone, org_bone, str_bone, next_str_bone=None):
		"""Configure BBone setup for def_bone."""

		segments, bbone_density = self.determine_segments(org_bone)

		# If def_bone is the first bone of the segment, but not the first bone of the chain.
		if str_bone in self.main_str_bones:
			def_bone.bbone_easein = 1 - self.params.CR_chain_sharp

		def_bone.bbone_segments = bbone_density/(org_bone.length/def_bone.length)
		# If bbone_density is >0, force at least 2 bbone_segments.
		# Otherwise it's not a bendy bone.
		if self.params.CR_chain_bbone_density > 0 and def_bone.bbone_segments < 2:
			def_bone.bbone_segments = 2

		if not next_str_bone:
			next_str_bone = str_bone.next
		if next_str_bone:
			def_bone.bbone_custom_handle_end = next_str_bone.tangent_helper
			def_bone.add_constraint('STRETCH_TO'
				,subtarget = next_str_bone.name
				,use_bulge_min = not self.params.CR_chain_preserve_volume
				,use_bulge_max = not self.params.CR_chain_preserve_volume
			)

			is_last_of_segment = next_str_bone in self.main_str_bones

			# Last bone of the segment, but not the last bone of the chain.
			if is_last_of_segment and next_str_bone != self.str_chain[-1] or \
				next_str_bone not in self.str_chain:	# Catch case of connecting parent chain
				def_bone.bbone_easeout = 1 - self.params.CR_chain_sharp

		else:
			# This only happens if this is the last deform bone and CR_chain_tip_control==False.
			# In this case it shouldn't be a bendy bone, so set deform segments to 1.
			def_bone.bbone_segments = 1

		# B-Bone scale drivers
		if def_bone.bbone_segments > 1:
			def_bone.inherit_scale = 'NONE'
			self.make_bbone_scale_drivers(def_bone)

		if self.params.CR_chain_shape_key_helpers and def_bone.prev:
			self.make_shape_key_helper(def_bone.prev, def_bone)

	def make_shape_key_helper(self, def_bone_1: BoneInfo, def_bone_2: BoneInfo) -> BoneInfo:
		"""Create SKP and SKH helper bones.

		Reading the local rotation of SKH
		should give us the rotation which we can use to activate corrective
		shape keys, since it will always represent the true rotational
		difference between the end of def_bone_1 and the start of def_bone_2.
		"""

		# SKP (Shape Key Helper Parent): Copy Transforms of the b-bone tail
		# of def_bone_1.
		skp_bone = self.skh_bones.new(
			name		 = def_bone_1.name.replace("DEF", "SKP")
			,source		 = def_bone_1
			,head		 = def_bone_1.tail.copy()
			,tail		 = def_bone_1.tail + def_bone_1.vector
			,parent		 = def_bone_1
			,hide_select = self.mch_disable_select
		)
		skp_bone.scale_length(0.3)
		skp_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_1.name
			,use_bbone_shape = True
			,head_tail		 = 1
		)

		# SKH (Shape Key Helper): This is parented to SKP and Copy Transforms
		# of the b-bone head of def_bone_2.
		skh_bone = self.skh_bones.new(
			name		 = def_bone_1.name.replace("DEF", "SKH")
			,source		 = def_bone_1
			,head		 = def_bone_2.head.copy()
			,tail		 = def_bone_2.tail.copy()
			,parent		 = skp_bone
			,hide_select = self.mch_disable_select
		)
		skh_bone.scale_width(2)
		skh_bone.scale_length(0.4)
		skh_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_2.name
			,use_bbone_shape = True
			,head_tail		 = 0
		)
		return skh_bone

	def connect_parent_chain_rig(self):
		"""Connect two separate but connected cloud_chain rigs.

		If the parent rig is a connected chain rig with cap_control=False,
		make the last DEF bone of that rig stretch to this rig's first STR.
		"""

		parent_rig = self.rigify_parent
		if not isinstance(parent_rig, CloudChainRig): return
		if parent_rig.params.CR_chain_tip_control: return

		meta_org_bone = self.meta_bone(self.naming.strip_org(self.org_chain[0]))
		if not meta_org_bone.bone.use_connect: return

		parent_rig.params.CR_chain_tip_control = True
		def_bone = parent_rig.def_chain[-1]
		str_bone = parent_rig.str_chain[-1]
		if parent_rig.params.CR_chain_unlock_deform:
			def_bone = parent_rig.def_mch[-1]
		parent_rig.setup_def_bone(def_bone, parent_rig.org_chain[-1], str_bone, self.str_chain[0])
		def_bone.parent = str_bone
		self.str_chain[0].custom_shape = self.ensure_widget('Sphere')
		if self.params.CR_chain_shape_key_helpers or parent_rig.params.CR_chain_shape_key_helpers:
			self.make_shape_key_helper(def_bone, self.def_chain[0])
		if self.params.CR_chain_smooth_spline or parent_rig.params.CR_chain_smooth_spline:
			self.set_up_smooth_spline(str_bone, nxt=self.str_chain[0])

	##############################
	# Parameters

	@classmethod
	def draw_bone_set_params(cls, layout, params, set_info):
		# We only want to draw this bone set UI if the option for it is enabled.
		if set_info['name'] in ["Deform Controls", "Deform Helpers"] and not params.CR_chain_unlock_deform:
			return
		super().draw_bone_set_params(layout, params, set_info)

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Stretch Controls", preset=8,	default_layers=[cls.default_layers('STRETCH')])
		cls.define_bone_set(params, "Deform Controls", preset=5,	default_layers=[cls.default_layers('STRETCH')])
		cls.define_bone_set(params, "Deform Helpers", 				default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Stretch Helpers",				default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Shape Key Helpers",			default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_chain_show_settings = BoolProperty(
			name		 = "Chain Settings"
			,description = "Reveal settings for the cloud_chain rig type"
		)
		params.CR_chain_segments = IntProperty(
			 name		 = "Deform Segments"
			,description = "Number of deform bones per section"
			,default	 = 2
			,min		 = 1
			,max		 = 9
		)
		params.CR_chain_bbone_density = IntProperty(
			 name		 = "B-Bone Density"
			,description = "Average number of B-Bone Segments per deform bone. Longer bones will have more, shorter ones fewer, to get an even distribution. There will be a minimum of 2 B-Bone Segments unless this parameter is 0"
			,default	 = 10
			,min		 = 0
			,max		 = 32
		)
		params.CR_chain_unlock_deform = BoolProperty(
			 name		 = "Unlock Deform"
			,description = "Allow Deform bones to be controlled directly, by moving their constraints to a parent helper bone. This requires that B-Bone Density is set to 0"
			,default	 = False
		)
		params.CR_chain_shape_key_helpers = BoolProperty(
			 name		 = "Shape Key Helpers"
			,description = "Create SKH bones that read the rotation between two deform bones, which can be used to drive corrective shape keys"
		)
		params.CR_chain_sharp = BoolProperty(
			 name		 = "Sharp Sections"
			,description = "B-Bone EaseIn/Out is set to 0 for bones connecting two sections"
			,default	 = False
		)
		params.CR_chain_smooth_spline = BoolProperty(
			 name		 = "Smooth Spline"
			,description = "B-Bone Splines affect their neighbours for smoother curves. Works best when Deform Segments is 1, but that is not a requirement"
			,default	 = False
		)
		params.CR_chain_tip_control = BoolProperty(
			 name		 = "Final Control"
			,description = "Add the final control at the end of the chain. Disabling this allows you to connect another chain to this one"
			,default	 = True
		)
		params.CR_chain_preserve_volume = BoolProperty(
			 name		 = "Preserve Volume"
			,description = "Squash and stretch will preserve volume"
			,default	 = False
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_chain_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_chain_segments")
		cls.draw_prop(layout, params, "CR_chain_bbone_density")
		row = cls.draw_prop(layout, params, "CR_chain_unlock_deform")
		row.enabled = params.CR_chain_bbone_density==0

		cls.draw_prop(layout, params, "CR_chain_shape_key_helpers")
		cls.draw_prop(layout, params, "CR_chain_sharp")
		cls.draw_prop(layout, params, "CR_chain_smooth_spline")
		cls.draw_prop(layout, params, "CR_chain_tip_control")
		cls.draw_prop(layout, params, "CR_chain_preserve_volume")

		return layout

class Rig(CloudChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)