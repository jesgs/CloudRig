from typing import List

import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty
from mathutils import Vector
from math import radians as rad
from math import pi
from copy import deepcopy

from rigify.base_rig import stage

from .cloud_ik_chain import CloudIKChainRig
from ..bone import BoneInfo

"""TODO
feet control shouldn't be forced onto the floor, maybe based on an option, or use anklepivot bone, or whatever.
ROLL-Foot.L shouldn't have its tail be offset in a flat forward direction. Instead, make it perpendicular to the knee, pointing towards the toe. (cross product of knee and toe bones' vectors?)
Some smartypants way of ensuring that the IK pole, when IK Pole Follow is enabled, follows the IK control on its roll axis, but not the other axes?
Scissor limb rig possible? (limb with an extra bone to help elbow/knee deformation) - Can it work in FK?
	I guess this would have to manifest more like an "arbitrary length limb" idea. IK chains can already be arbitrary length, but to allow that for limbs... might be super tricky. Especially when it comes to IK->FK snapping!
"""

class CloudLimbRig(CloudIKChainRig):
	"""IK chain with extra features for specific limbs, such as foot roll."""

	forced_params = {
		'CR_chain_sharp' : True
	}

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""

		self.limb_type = self.params.CR_limb_type

		# UI Strings and Custom Property names
		self.category = ""

		self.limb_name = self.limb_type.capitalize()
		if self.params.CR_fk_chain_use_limb_name:
			self.limb_name = self.params.CR_fk_chain_limb_name

		self.limb_ui_name = self.side_prefix + " " + self.limb_name

		# IK values
		self.ik_pole_direction = 1 if self.limb_type=='ARM' else -1				#TODO: self.limb_type doesn't exist in cloud_ik_chain...

		# List of parent candidate identifiers that this rig is looking for among its registered parent candidates
		self.ik_parents = ['Root', 'Torso', self.limb_ui_name]
	
		if self.limb_type=='LEG':
			if len(self.bones.org.main) != 4:
				self.raise_error("Leg chain must be exactly 4 connected bones.")
			self.ik_parents.append('Hips')

			self.ik_pole_offset = 5
			self.pole_side = -1
			self.chain_count -= 1

			self.category = "legs"
		elif self.limb_type=='ARM':
			if len(self.bones.org.main) != 3:
				self.raise_error("Arm chain must be exactly 3 connected bones.")
			self.ik_parents.append('Chest')

			self.category = "arms"

		if self.params.CR_fk_chain_use_category_name:
			self.category = self.params.CR_fk_chain_category_name

	def determine_segments(self, org_bone):
		segments, bbone_density = super().determine_segments(org_bone)

		if self.limb_type=='LEG' and org_bone in self.org_chain[-2:]:
			# Force strictly 1 segment on the foot and the toe.
			return 1, bbone_density
		elif self.limb_type=='ARM' and org_bone == self.org_chain[-1]:
			# Force strictly 1 segment on the wrist.
			return 1, bbone_density
		elif org_bone == self.org_chain[-1] and not self.params.CR_chain_tip_control:
			return 1, 1

		return segments, bbone_density

	def prepare_bones(self):
		super().prepare_bones()
		self.tweak_str_limb()
		self.make_ik_limb()
		self.tweak_org_foot()
		segments = self.params.CR_chain_segments
		if self.params.CR_limb_auto_hose and segments > 1:
			upper = self.str_chain[1:segments]
			lower = self.str_chain[segments+1:segments*2]
			self.setup_rubber_hose(self.org_chain[1], upper, lower)

	def make_fk_chain(self):
		"""Override."""
		super().make_fk_chain()

		if self.limb_type=='LEG':
			self.fk_toe = self.org_chain[3].fk_bone

		elbow_knee = self.org_chain[1].fk_bone
		elbow_knee.lock_rotation[1] = elbow_knee.lock_rotation[2] = self.params.CR_limb_lock_yz

	def world_align_last_fk(self):
		"""Override. Make last FK bone world-aligned."""
		if self.params.CR_limb_type=='LEG':
			self.make_world_aligned_control(self.org_chain[-2].fk_bone)
		else:
			super().world_align_last_fk()

	def make_parent_switch(self):
		"""Override."""
		ik_ctrl = self.ik_mstr
		if self.params.CR_limb_double_ik:
			ik_ctrl = ik_ctrl.parent

		super().make_parent_switch(ik_ctrl)

	def tweak_str_limb(self):
		# We want to make some changes to the STR chain to make it behave more limb-like.

		# Disable first Copy Rotation constraint on the upperarm
		# TODO: Why did we do this?
		for b in self.main_str_bones[0].sub_bones:
			str_h_bone = b.parent
			str_h_bone.constraint_infos[2].mute = True

	def make_ik_limb(self):
		# NOTE: This runs after super().make_ik_setup()

		def foot_dsp(bone):
			# Create foot DSP helpers
			if self.limb_type=='LEG':
				dsp_bone = self.create_dsp_bone(bone)
				direction = 1 if self.side_suffix=='L' else -1
				projected_head = Vector((bone.head[0], bone.head[1], 0))
				projected_tail = Vector((bone.tail[0], bone.tail[1], 0))
				projected_center = projected_head + (projected_tail-projected_head) / 2
				dsp_bone.head = projected_center
				dsp_bone.tail = projected_center + Vector((0, -self.scale/10, 0))
				dsp_bone.roll = rad(90) * direction

		# Configure IK Master
		wgt_name = 'Hand_IK' if self.limb_type=='ARM' else 'Foot_IK'
		self.ik_mstr.custom_shape = self.ensure_widget(wgt_name)
		self.ik_mstr.custom_shape_scale = 0.8 if self.limb_type=='ARM' else 2.8

		foot_dsp(self.ik_mstr)
		# Parent control
		if self.params.CR_limb_double_ik:
			double_control = self.create_parent_bone(self.ik_mstr, self.ik_parent_ctrls)
			double_control.bone_group = "IK Parent Controls"
			foot_dsp(double_control)

		# IK Foot setup, including Foot Roll
		if self.limb_type == 'LEG':
			if self.params.CR_limb_use_foot_roll:
				self.make_footroll(self.ik_tgt_bone, self.ik_chain[-2:], self.org_chain[-2:])
			self.make_ik_toe()

		# Counter-Rotate setup for the first section of STR bones.
		for i in range(0, self.params.CR_chain_segments):
			factor_unit = 0.9 / self.params.CR_chain_segments
			factor = 0.9 - factor_unit * i
			self.add_counterrotate_constraint(self.str_chain[i], self.org_chain[0], factor)

	def make_footroll(self, ik_tgt, ik_chain, org_chain):
		ik_foot = ik_chain[0]

		# Create ROLL control behind the foot (Limit Rotation, lock other transforms)
		rolly_stretchy = self.new_bonei(self.ik_mch
			,name		 = self.org_chain[0].name.replace("ORG", "IK-STR-ROLL")
			,source		 = self.org_chain[0]
			,tail		 = self.ik_mstr.head.copy()
			,parent		 = self.limb_root_bone.name
			,hide_select = self.mch_disable_select
		)
		rolly_stretchy.scale_width(0.4)
		rolly_stretchy.add_constraint('STRETCH_TO', subtarget=self.ik_chain[-2].name)

		sliced_name = self.naming.slice_name(ik_foot.name)
		master_name = self.naming.make_name(["ROLL", "MSTR"], sliced_name[1], sliced_name[2])
		roll_master = self.new_bonei(self.ik_mch
			,name		 = master_name
			,source		 = self.ik_mstr
			,parent		 = self.ik_mstr
		)
		roll_master.constraint_infos.append(self.ik_tgt_bone.constraint_infos[0])
		self.ik_tgt_bone.clear_constraints()

		roll_name = self.naming.make_name(["ROLL"], sliced_name[1], sliced_name[2])
		roll_ctrl = self.new_bonei(self.ik_ctrls
			,name		  = roll_name
			,bbone_width  = 1/18
			,head		  = ik_foot.head + Vector((0, self.scale, self.scale/4))
			,tail		  = ik_foot.head + Vector((0, self.scale/2, self.scale/4))
			,roll		  = rad(180)
			,parent		  = roll_master
			,custom_shape = self.ensure_widget('FootRoll')
			,use_custom_shape_bone_size = True
		)

		roll_ctrl.add_constraint('LIMIT_ROTATION'
			,use_limit_x=True
			,min_x = rad(-90)
			,max_x = rad(130)
			,use_limit_y=True
			,use_limit_z=True
			,min_z = rad(-90)
			,max_z = rad(90)
		)

		# Create bone to use as pivot point when rolling back. This is read from the metarig and should be placed at the heel of the shoe, pointing forward.
		heel_pivot_name = self.params.CR_limb_heel_bone
		if heel_pivot_name=="":
			heel_pivot_name = self.org_chain[-2].name.replace("ORG-", "")
		heel_pivot_bone = self.generator.metarig.data.bones.get(heel_pivot_name)
		assert heel_pivot_bone, f"ERROR: Could not find HeelPivot bone in the metarig: {heel_pivot_name}."

		# Take the bone shape size of the foot controls from the heel pivot bone b-bone scale.
		self.ik_mstr._bbone_x = heel_pivot_bone.bbone_x
		self.ik_mstr._bbone_z = heel_pivot_bone.bbone_z
		if self.params.CR_limb_double_ik:
			self.ik_mstr.parent._bbone_x = heel_pivot_bone.bbone_x
			self.ik_mstr.parent._bbone_z = heel_pivot_bone.bbone_z

		heel_pivot = self.new_bonei(self.ik_mch
			,name		  = "IK-RollBack" + self.naming.suffix_separator + self.side_suffix
			,bbone_width  = self.org_chain[-1].bbone_width
			,head		  = heel_pivot_bone.head_local
			,tail		  = heel_pivot_bone.head_local + Vector((0, -self.scale*0.1, 0))
			,roll		  = 0
			,parent		  = roll_master
			,hide_select  = self.mch_disable_select
		)

		heel_pivot.add_constraint('TRANSFORM',
			subtarget = roll_ctrl.name,
			map_from = 'ROTATION',
			map_to = 'ROTATION',
			from_min_x_rot = rad(-90),
			to_min_x_rot = rad(60),
		)

		# Create reverse bones
		rik_chain = []
		for i, b in reversed(list(enumerate(org_chain))):
			rik_bone = self.new_bonei(self.ik_mch
				,name		 = b.name.replace("ORG", "RIK")
				,source		 = b
				,head		 = b.tail.copy()
				,tail		 = b.head.copy()
				,roll		 = 0
				,parent		 = heel_pivot
				,hide_select = self.mch_disable_select
			)
			rik_chain.append(rik_bone)
			ik_chain[i].parent = rik_bone

			if i == 1:
				rik_bone.add_constraint('TRANSFORM'
					,subtarget		= roll_ctrl.name
					,map_from		= 'ROTATION'
					,map_to			= 'ROTATION'
					,from_min_x_rot	= rad(90)
					,from_max_x_rot	= rad(166)
					,to_min_x_rot   = rad(0)
					,to_max_x_rot   = rad(169)
					,from_min_z_rot	= rad(-60)
					,from_max_z_rot	= rad(60)
					,to_min_z_rot   = rad(10)
					,to_max_z_rot   = rad(-10)
				)

			if i == 0:
				rik_bone.add_constraint('COPY_LOCATION'
					,space			= 'WORLD'
					,target			= self.obj
					,subtarget		= rik_chain[-2].name
					,head_tail		= 1
				)

				rik_bone.add_constraint('TRANSFORM'
					,name = "Transformation Roll"
					,subtarget = roll_ctrl.name
					,map_from = 'ROTATION'
					,map_to = 'ROTATION'
					,from_min_x_rot = rad(0)
					,from_max_x_rot = rad(135)
					,to_min_x_rot   = rad(0)
					,to_max_x_rot   = rad(118)
					,from_min_z_rot = rad(-45)
					,from_max_z_rot = rad(45)
					,to_min_z_rot   = rad(25)
					,to_max_z_rot   = rad(-25)
				)
				rik_bone.add_constraint('TRANSFORM'
					,name = "Transformation CounterRoll"
					,subtarget = roll_ctrl.name
					,map_from = 'ROTATION'
					,map_to = 'ROTATION'
					,from_min_x_rot = rad(90)
					,from_max_x_rot = rad(135)
					,to_min_x_rot   = rad(0)
					,to_max_x_rot   = rad(-31.8)
				)

		# Change the subtarget of the constraints on main_str_bones from the old stretchy bone to the new one, that accounts for footroll.
		for main_str_bone in self.main_str_bones:
			ci = main_str_bone.parent.get_constraint('CopyLoc_IK_Stretch')
			if ci:
				ci.subtarget = rolly_stretchy.name

	def make_ik_toe(self):
		# FK Toe bone should be parented between FK Foot and IK Toe.
		fk_toe = self.fk_toe
		fk_toe.parent = None
		toe_con = fk_toe.add_constraint('ARMATURE',
			targets = [
				{
					"subtarget" : self.org_chain[-2].fk_bone.name	# FK Foot
				},
				{
					"subtarget" : self.ik_chain[-1].name	# IK Toe
				}
			],
		)

		ik_driver = {
			'prop' : 'targets[1].weight',
			'variables' : [
				(self.properties_bone.name, self.ikfk_name)
			]
		}
		toe_con.drivers.append(ik_driver)

		fk_driver = deepcopy(ik_driver)
		fk_driver['expression'] = "1-var"
		fk_driver['prop'] = 'targets[0].weight'
		toe_con.drivers.append(fk_driver)

	def add_counterrotate_constraint(self, str_bone, org_bone, factor):
		str_bone.add_constraint('TRANSFORM',
			name = "Transformation (Counter-Rotate)",
			subtarget = org_bone.name,
			map_from = 'ROTATION', map_to = 'ROTATION',
			use_motion_extrapolate = True,
			from_min_y_rot =   -1,
			from_max_y_rot =	1,
			to_min_y_rot   =  factor,
			to_max_y_rot   = -factor,
			from_rotation_mode = 'SWING_TWIST_Y'
		)

	def tweak_org_foot(self):
		# Delete IK constraint and driver from toe bone. It should always use FK.
		if self.limb_type == 'LEG':
			org_toe = self.org_chain[-1]
			org_toe.constraint_infos.pop()
			org_toe.drivers = {}

	def setup_rubber_hose(self, org_elbow: BoneInfo, str_upper: List[BoneInfo], str_lower: List[BoneInfo]):
		""" Add translating Transformation constraints to str_upper and 
			str_lower controls, driven by org_elbow. (Also meant for legs)
		"""

		for str_list in [str_upper, str_lower]:
			for str_bone in str_list:
				distance = org_elbow.length / 2.5
				str_bone.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose)"
					,subtarget = org_elbow.name
					,map_from = 'ROTATION'
					,from_min_x_rot = -pi
					,from_max_x_rot = pi
					,from_min_z_rot = -pi
					,from_max_z_rot = pi
					,to_min_x = -distance
					,to_max_x = distance
					,to_min_z = distance
					,to_max_z = -distance
					,map_to_x_from = 'Z'
					,map_to_z_from = 'X'
				)
		# TODO: influence based on center-ness, hooked up to a UI property with a driver
		# middle bone should have transf constraints for counter-rotate and scale, same influence drivers. 

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_limb_show_settings = BoolProperty(
			name		 = "Limb Settings"
			,description = "Reveal settings for the cloud_limbs rig type"
		)
		params.CR_limb_auto_hose = BoolProperty(
			name		 = "Auto Rubber Hose"
			,description = "Set up an Auto Rubber Hose setting which when enabled will attempt to automatically add curvature to limbs as they are bent. Works best when Chain Segments parameter is an even number, and it must be greater than 1"
			,default	 = False
		)

		params.CR_limb_type = EnumProperty(
			 name 		 = "Type"
			,items 		 = (
				("ARM", "Arm", "Arm (Chain of 3)"),
				("LEG", "Leg", "Leg (Chain of 4, includes foot rig)"),
			)
			,default	 = 'ARM'
		)
		params.CR_limb_double_ik = BoolProperty(
			 name		 = "Double IK Master"
			,description = "The IK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose"
			,default	 = True
		)

		params.CR_limb_lock_yz = BoolProperty(
			 name		 = "Lock Elbow/Shin YZ"
			,description = "Lock Y and Z rotation of the elbow/shin"
			,default 	 = False
		)
		params.CR_limb_use_foot_roll = BoolProperty(
			 name 		 = "Foot Roll"
			,description = "Create Foot roll controls"
			,default 	 = True
		)
		params.CR_limb_heel_bone = StringProperty(
			 name		 = "Heel Pivot Bone"
			,description = "Bone to use as the heel pivot. This bone should be placed at the heel of the shoe, pointing forward. If unspecified, fall back to the foot bone"
			,default	 = ""
		)

	@classmethod
	def draw_cloud_params(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_limb_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_limb_type")
		if params.CR_limb_type=='LEG':
			cls.draw_prop(layout, params, "CR_limb_use_foot_roll")
			if params.CR_limb_use_foot_roll:
				cls.draw_prop_search(layout, params, "CR_limb_heel_bone", bpy.context.object.data, "bones", text="Heel Pivot")

		cls.draw_prop(layout, params, "CR_limb_double_ik")

		word = "Elbow" if params.CR_limb_type == 'ARM' else "Shin"
		cls.draw_prop(layout, params, "CR_limb_lock_yz", text=f"Lock {word} Y/Z")
		row = cls.draw_prop(layout, params, 'CR_limb_auto_hose')
		row.enabled = params.CR_chain_segments > 1

		return layout

class Rig(CloudLimbRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_limbs")