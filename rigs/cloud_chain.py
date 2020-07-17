from bpy.props import BoolProperty, IntProperty

from .cloud_utils import make_name, slice_name
from .cloud_base import CloudBaseRig

"""
TODO: Allow for circular chains, if the first bone's head is the same location as the last bone's tail, and final control is enabled. Doesn't have to be a parameter.

Ideas:
Spline IK like controls(the other two types) for bendy bones' handles.
Recursive generation of STR layers as per Pablo's request, so we don't just have main and sub STR controls, but any number of nested layers(although we would probably never use more than 3, but then again, I thought we would never use more than 2, so)
"""

class CloudChainRig(CloudBaseRig):
	"""Chain with cartoony squash and stretch controls."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.chain_length = 0

	def ensure_bone_sets(self):
		# TODO: We should introduce a convention that bone sets ending in _chain are ones where the order is expected to be meaningful. If our STR bones could be ordered, our code could be a bit cleaner. And they are ordered, it's just not clear.
		super().ensure_bone_sets()
		self.str_bones = self.ensure_bone_set("Stretch Controls")
		self.str_mch = self.ensure_bone_set("Stretch Helpers")
		self.skh_bones = self.ensure_bone_set("Shape Key Helpers")
		self.def_bones = self.ensure_bone_set("Deform Bones")

	def prepare_bones(self):
		super().prepare_bones()

		for org in self.org_chain:
			self.chain_length += org.length
		self.average_org_length = self.chain_length / len(self.org_chain)

		str_sections = self.make_str_chain(self.org_chain)
		self.make_str_helpers(str_sections)
		if self.params.CR_smooth_spline:
			self.make_dt_helpers(self.str_bones)

		self.make_def_chain(self.str_bones)

		self.connect_parent_chain_rig()

	def determine_segments(self, org_bone):
		"""Determine how many deform and b-bone segments should be in a section of the chain."""
		segments = self.params.CR_deform_segments

		bbone_density = round(org_bone.length/self.average_org_length * self.params.CR_bbone_density * self.params.CR_deform_segments)

		# No segments for last bone of the chain if there is no control for its tail.
		if org_bone == self.org_chain[-1] and not self.params.CR_cap_control:
			return 1, 1
		
		return segments, bbone_density

	def make_str_chain(self, org_chain):
		self.main_str_bones = []
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
					if org_i==0:
						str_bone.custom_shape = self.load_widget("Hemisphere_Flip")
			str_sections.append(str_section)

			# Tip control at the end of the chain.
			if org_i==len(org_chain)-1 and self.params.CR_cap_control:
				str_bone = self.make_str_bone(org_bone, i, 1)
				str_bone.put(org_bone.tail)
				str_bone.length = str_bone.prev.length
				str_bone.name = str_bone.name.replace("STR", "STR-TIP")
				str_bone.custom_shape_scale *= 1.3
				str_sections.append([str_bone])
				str_bone.custom_shape = self.load_widget("Hemisphere")
				self.main_str_bones.append(str_bone)
		
		return str_sections

	def make_str_bone(self, org_bone, seg_i, segments):
		direction = org_bone.vector
		if seg_i==0 and org_bone.prev:
			direction = org_bone.tail - org_bone.prev.head
		unit = org_bone.vector / segments
		str_bone = self.str_bones.new(
			name = org_bone.name.replace("ORG", "STR")
			,source = org_bone
			,head = org_bone.head + (unit * seg_i)
			,vector = direction
			,length = org_bone.length / segments / 2
			,roll = org_bone.roll
			,custom_shape = self.load_widget("Sphere")
			,custom_shape_scale = 0.3
			,parent = org_bone
		)
		str_bone.org_parent = org_bone
		if segments>1 and seg_i>0:
			sliced = self.slice_name(str_bone.name)
			str_bone.name = make_name(sliced[0], f"{sliced[1]}_{seg_i}", sliced[2])
		str_bone.bbone_width *= 1.2
		return str_bone

	def make_str_helpers(self, str_sections):
		"""STR-H are mechanism bones that keep STR controls between two main STR controls."""
		main_str_bone = None
		for sec_i, section in enumerate(str_sections):
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
					name 		 = self.add_prefix_to_name(str_bone.name, "H")
					,source 	 = str_bone
					,bbone_width = 1/10
					,parent		 = str_bone.parent
					,hide_select = self.mch_disable_select
				)
				str_bone.parent = str_h_bone

				first_str = section[0].name
				last_str = str_sections[sec_i+1][0].name
				influence_unit = 1 / len(section)
				influence = i * influence_unit
				str_h_bone.add_constraint('COPY_LOCATION', space='WORLD', subtarget=first_str)
				str_h_bone.add_constraint('COPY_LOCATION', space='WORLD', subtarget=last_str, influence=influence)

				str_h_bone.add_constraint('COPY_ROTATION', space='WORLD', subtarget=first_str)
				str_h_bone.add_constraint('COPY_ROTATION', space='WORLD', subtarget=last_str, influence=influence)
				str_h_bone.add_constraint('DAMPED_TRACK', subtarget=last_str)

	def make_dt_helpers(self, str_chain):
		""" Create a child bone for each STR bone with Damped Track constraints to aim at the previous and next STR bones. """

		for str_bone in str_chain:
			dt_bone = self.str_mch.new(
				name = str_bone.name.replace("STR", "DT-STR")
				,source = str_bone
				,parent = str_bone
			)
			str_bone.dt_bone = dt_bone
			if str_bone.next:
				pos_con = dt_bone.add_constraint('DAMPED_TRACK', subtarget = str_bone.next.name, track_axis='TRACK_Y')
			if str_bone.prev:
				neg_con = dt_bone.add_constraint('DAMPED_TRACK', subtarget = str_bone.prev.name, track_axis='TRACK_NEGATIVE_Y')
				if str_bone.next:
					neg_con.influence = 0.5
			dt_bone.add_constraint('COPY_ROTATION', subtarget = str_bone.name, mix_mode='BEFORE')
			dt_bone.inherit_scale = 'NONE'
			dt_bone.add_constraint('COPY_SCALE', subtarget=str_bone.name)

	def make_def_chain(self, str_chain):
		"""Create a deform chain stretching from one STR bone to the next"""
		for str_i, str_bone in enumerate(str_chain):
			# Skip the tip control
			if str_i == len(str_chain)-1 and self.params.CR_cap_control:
				continue

			org_bone = str_bone.org_parent
			org_bone.def_bones = []	# TODO: deprecate this? It's currently only used by the spine neck, which is also to be deprecated.
			def_section = []

			segments, bbone_density = self.determine_segments(org_bone)
			tail = org_bone.tail

			def_name = str_bone.name.replace("STR", "DEF")
			def_bone = self.def_bones.new(
				name					 = def_name
				,source					 = org_bone
				,parent					 = str_bone
				,head					 = str_bone.head
				,tail					 = tail
				,bbone_handle_type_start = 'TANGENT'
				,bbone_handle_type_end	 = 'TANGENT'
				,bbone_custom_handle_start = str_bone
				,hide_select			 = self.mch_disable_select
				,use_deform				 = True
			)

			### Configure BBone setup
			# First bone of the segment, but not the first bone of the chain.
			if str_bone in self.main_str_bones and str_i!=0:
				def_bone.bbone_easein = not self.params.CR_sharp_sections

			if hasattr(def_bone.bbone_custom_handle_start, 'dt_bone'):
				def_bone.bbone_custom_handle_start = def_bone.bbone_custom_handle_start.dt_bone

			if str_bone.next:
				def_bone.tail = str_bone.next.head
				def_bone.bbone_custom_handle_end = str_bone.next
				# Last bone of the segment, but not the last bone of the chain.
				if str_bone.next in self.main_str_bones and str_bone.next != str_chain[-1]:
					def_bone.bbone_easeout = not self.params.CR_sharp_sections
				if hasattr(def_bone.bbone_custom_handle_end, 'dt_bone'):
					def_bone.bbone_custom_handle_end = def_bone.bbone_custom_handle_end.dt_bone
				def_bone.add_constraint('STRETCH_TO', subtarget = str_bone.next.name)

			def_bone.bbone_segments = bbone_density/(org_bone.length/def_bone.length)
			# Force B-Bone segments to be a minimum of 2, unless bbone_density is 0.
			if def_bone.bbone_segments < 2 and self.params.CR_bbone_density > 0:
				def_bone.bbone_segments = 2

			# B-Bone scale drivers
			if def_bone.bbone_segments > 1:
				def_bone.inherit_scale = 'NONE'
				self.make_bbone_scale_drivers(def_bone)

			if def_bone.prev:
				self.make_shape_key_helper(def_bone.prev, def_bone)

			org_bone.def_bones.append(def_bone)

		return self.def_bones

	def make_shape_key_helper(self, def_bone_1, def_bone_2):
		"""The goal is to accurately read the rotational difference between def_bone_1 and def_bone_2, each of which can be a bendy bone.
		SKP (Shape Key Helper Parent): Copy Transforms of the b-bone tail of of def_bone_1.
		SKH (Shape Key Helper): This is parented to SKP and Copy Transforms of the b-bone head of def_bone_2.
		Reading the local rotation of SKH should now give us the rotation which we can use to activate corrective shape keys.
		"""

		skp_bone = self.skh_bones.new(
			name		 = def_bone_2.name.replace("DEF", "SKP")
			,head		 = def_bone_1.tail.copy()
			,tail		 = def_bone_1.tail + def_bone_1.vector
			,parent		 = def_bone_1
			,bbone_width = 0.05
			,hide_select = self.mch_disable_select
		)
		skp_bone.scale_length(0.3)
		skp_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_1.name
			,use_bbone_shape = True
			,head_tail		 = 1
		)

		skh_bone = self.skh_bones.new(
			name		 = def_bone_2.name.replace("DEF", "SKH")
			,head		 = def_bone_2.head.copy()
			,tail		 = def_bone_2.tail.copy()
			,parent		 = skp_bone
			,bbone_width = 0.03
			,hide_select = self.mch_disable_select
		)
		skh_bone.scale_length(0.4)
		skh_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_2.name
			,use_bbone_shape = True
			,head_tail		 = 0
		)

	def connect_parent_chain_rig(self):
		# If the parent rig is a connected chain rig with cap_control=False, make the last DEF bone of that rig stretch to this rig's first STR.
		parent_rig = self.rigify_parent
		if isinstance(parent_rig, CloudChainRig):
			if not parent_rig.params.CR_cap_control:
				meta_org_bone = self.generator.metarig.data.bones.get(self.org_chain[0].name.replace("ORG-", ""))
				if meta_org_bone.use_connect:
					def_bone = parent_rig.def_bones[-1]
					str_bone = self.str_bones[0]
					str_bone.custom_shape = self.load_widget('Sphere')
					def_bone.bbone_custom_handle_end = str_bone
					def_bone.add_constraint('STRETCH_TO', subtarget = str_bone.name)
					self.make_bbone_scale_drivers(def_bone)
					if self.params.CR_shape_key_helpers:
						self.make_shape_key_helper(def_bone, self.def_bones[0])

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Stretch Controls", preset=8,	default_layers=[cls.default_layers('STRETCH')])
		cls.define_bone_set(params, "Stretch Helpers",				default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Shape Key Helpers",			default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Deform Bones",					default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_show_chain_settings = BoolProperty(
			name		 = "Chain Settings"
			,description = "Reveal settings for the cloud_chain rig type"
		)
		params.CR_deform_segments = IntProperty(
			 name		 = "Deform Segments"
			,description = "Number of deform bones per section"
			,default	 = 2
			,min		 = 1
			,max		 = 9
		)
		params.CR_bbone_density = IntProperty(
			 name="B-Bone Density"
			,description="Average number of B-Bone Segments per deform bone. Longer bones will have more, shorter ones fewer, to get an even distribution. There will be a minimum of 2 B-Bone Segments unless this parameter is 0"
			,default=10
			,min=0
			,max=32
		)
		params.CR_shape_key_helpers = BoolProperty(
			 name="Shape Key Helpers"
			,description="Create SKH- bones that reliably read the rotation between two deform bones, and can therefore be used to drive shape keys"
		)
		params.CR_sharp_sections = BoolProperty(
			 name="Sharp Sections"
			,description="B-Bone EaseIn/Out is set to 0 for bones connectiong two sections"
			,default=False
		)

		params.CR_smooth_spline = BoolProperty(
			 name="Smooth Spline"
			,description="BBone Splines affect their neighbours to make smoother curves easier"
			,default=False
		)

		params.CR_cap_control = BoolProperty(
			 name		 = "Final Control"
			,description = "Add the final control at the end of the chain (Turn off if you connect another chain to this one)"
			,default	 = True
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_chain_settings"): return layout

		layout.prop(params, "CR_deform_segments")
		layout.prop(params, "CR_bbone_density")

		layout.prop(params, "CR_shape_key_helpers")
		sharp_sections = layout.row()
		sharp_sections.prop(params, "CR_sharp_sections")
		layout.prop(params, "CR_smooth_spline")
		cls.ui_rows['CR_sharp_sections'] = sharp_sections
		layout.prop(params, "CR_cap_control")

		return layout

class Rig(CloudChainRig):
	pass

import bpy

def create_sample(obj):
    # generated by rigify.utils.write_metarig
    bpy.ops.object.mode_set(mode='EDIT')
    arm = obj.data

    bones = {}

    bone = arm.edit_bones.new('Chain_1')
    bone.head = 0.0000, 0.0000, 0.0000
    bone.tail = 0.0000, -0.5649, 0.0000
    bone.roll = -3.1416
    bone.use_connect = False
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0282
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bones['Chain_1'] = bone.name
    bone = arm.edit_bones.new('Chain_2')
    bone.head = 0.0000, -0.5649, 0.0000
    bone.tail = 0.0000, -1.1299, 0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0282
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Chain_1']]
    bones['Chain_2'] = bone.name
    bone = arm.edit_bones.new('Chain_3')
    bone.head = 0.0000, -1.1299, 0.0000
    bone.tail = 0.0000, -1.6948, -0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Chain_2']]
    bones['Chain_3'] = bone.name
    bone = arm.edit_bones.new('Chain_4')
    bone.head = 0.0000, -1.6948, -0.0000
    bone.tail = 0.0000, -2.2598, 0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Chain_3']]
    bones['Chain_4'] = bone.name

    bpy.ops.object.mode_set(mode='OBJECT')
    pbone = obj.pose.bones[bones['Chain_1']]
    pbone.rigify_type = 'cloud_chain'
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    try:
        pbone.rigify_parameters.CR_subdivide_deform = 10
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_controls_for_handles = True
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_show_spline_ik_settings = True
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_show_display_settings = False
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_rotatable_handles = False
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_hook_name = "Cable"
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_show_chain_settings = True
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_sharp_sections = False
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_bbone_density = 6
    except AttributeError:
        pass
    pbone = obj.pose.bones[bones['Chain_2']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    pbone = obj.pose.bones[bones['Chain_3']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    pbone = obj.pose.bones[bones['Chain_4']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'

    bpy.ops.object.mode_set(mode='EDIT')
    for bone in arm.edit_bones:
        bone.select = False
        bone.select_head = False
        bone.select_tail = False
    for b in bones:
        bone = arm.edit_bones[bones[b]]
        bone.select = True
        bone.select_head = True
        bone.select_tail = True
        arm.edit_bones.active = bone

    return bones