import bpy
from bpy.props import BoolProperty, StringProperty, FloatProperty, IntProperty
from mathutils import Vector
from math import radians as rad

from rigify.base_rig import stage

from .cloud_fk_chain import CloudFKChainRig

BODY_MECH = 8

IK_MAIN = 0
IK_SECOND = 16
#TODO: There's some code in limb that makes the last def- bone has bbone_easeout=0. That should be in here, under a parameter, that's greyed out when ik_tail or whatever it will be called, would be enabled. Maybe.
class CloudIKChainRig(CloudFKChainRig):
	"""CloudRig IK chain."""

	description = "IK chain with stretchy IK and IK/FK snapping. Pole control optional."

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		assert self.params.CR_ik_length <= len(self.bones.org.main), f"IK Length parameter ({self.params.CR_ik_length}) higher than number of bones in the connected chain ({len(self.bones.org.main)}) on rig: {self.meta_base_bone.name}"

		# UI Strings and Custom Property names
		self.category = self.slice_name(self.base_bone)[1]
		if self.params.CR_use_custom_category_name:
			self.category = self.params.CR_custom_category_name

		self.limb_name = self.category						# Name used for naming bones. Should not contain a side identifier like .L/.R.
		if self.params.CR_use_custom_limb_name:
			self.limb_name = self.params.CR_custom_limb_name
		
		self.limb_ui_name = self.side_prefix + " " + self.limb_name	# Name used for UI related things. Should contain the side identifier.

		self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
		self.ikfk_name = "ik_" + self.limb_name_props
		self.ik_stretch_name = "ik_stretch_" + self.limb_name_props
		self.fk_hinge_name = "fk_hinge_" + self.limb_name_props

		self.pole_side = 1
		self.ik_pole_offset = 3		# Scalar on distance from the body.
		
		# List of parent candidate identifiers that this rig is looking for among its registered parent candidates
		self.ik_parents = ['Root', 'Torso', 'Hips', 'Chest', self.limb_ui_name]

	def ensure_bone_sets(self, bone_set_defs):
		bone_sets = super().ensure_bone_sets(bone_set_defs)
		self.ik_ctrls = self.ensure_bone_set(bone_set_defs["IK Controls"])
		self.ik_parent_ctrls = self.ensure_bone_set(bone_set_defs["IK Parent Controls"])
		self.ik_mch = self.ensure_bone_set(bone_set_defs["IK Mechanism"])
		self.fk_mch = self.ensure_bone_set(bone_set_defs["FK Helpers"])
		bone_sets.append(self.ik_ctrls)
		bone_sets.append(self.ik_parent_ctrls)
		bone_sets.append(self.ik_mch)
		bone_sets.append(self.fk_mch)
		return bone_sets

	def prepare_root_bone(self):
		# Socket/Root bone to parent IK and FK to.
		root_name = self.base_bone.replace("ORG", "ROOT")
		base_bone = self.get_bone(self.base_bone)
		self.limb_root_bone = self.ik_mch.new(
			name 					= root_name
			,source 				= base_bone
			,parent 				= self.bones.parent
			,custom_shape 			= self.load_widget("Cube")
			,custom_shape_scale 	= 0.5
		)
		self.register_parent(self.limb_root_bone, self.limb_ui_name)

	def calculate_ik_info(self):
		""" Calculate pole angle, pole control direction and distance. """
		meta_first_name = self.org_chain[0].name.replace("ORG-", "")
		meta_first = self.meta_bone(meta_first_name, pose=True)

		meta_last_name = self.org_chain[1].name.replace("ORG-", "")
		meta_last = self.meta_bone(meta_last_name, pose=True)

		chain_vector = meta_last.bone.tail_local - meta_first.bone.head_local

		first_tail = meta_first.bone.tail_local
		last_tail = meta_last.bone.tail_local

		# Calculate the distances of the four points to the tail of the last bone.
		# These four points are in the four directions of the bone around the bone's tail.
		x_pos_distance = ((first_tail+meta_first.x_axis) - last_tail).length
		x_neg_distance = ((first_tail-meta_first.x_axis) - last_tail).length

		z_pos_distance = ((first_tail+meta_first.z_axis) - last_tail).length
		z_neg_distance = ((first_tail-meta_first.z_axis) - last_tail).length

		# Store those distances in a dictionary where they are matched with a tuple describing (the main axis of rotation, IK constraint pole_angle), that should be used, when that distance is the lowest.
		axis_dict = {
			x_pos_distance : ("-Z", 180),
			x_neg_distance : ("+Z", 0),
			z_pos_distance : ("+X", -90),
			z_neg_distance : ("-X", 90)
		}

		lowest_distance = axis_dict[min(list(axis_dict.keys()))]	# Find the tuple to use by picking the one corresponding to the lowest distance.
		rotation_axis = lowest_distance[0]
		self.pole_angle = rad(lowest_distance[1])

		vector_flipper = 1
		perpendicular_axis = meta_first.x_axis
		if rotation_axis[0] == "-":
			vector_flipper = -1
		if rotation_axis[1] == "Z":
			perpendicular_axis = meta_first.z_axis

		# Find the vector that is perpendicular to a plane defined by the chain vector and the main rotation axis.
		self.pole_vector = chain_vector.cross(perpendicular_axis).normalized() * vector_flipper * chain_vector.length

		# We want the pole control to be offset from the first bone's tail by that vector.
		self.pole_location = first_tail + self.pole_vector

	def create_pole_control(self):
		# Create IK Pole Control
		pole_ctrl = self.pole_ctrl = self.ik_ctrls.new(
			name				= self.make_name(["IK", "POLE"], self.limb_name, [self.side_suffix])
			,bbone_width		= 0.1
			,head				= self.pole_location
			,tail				= self.pole_location + self.flat_vector(self.pole_vector) * 0.2
			,roll				= 0
			,custom_shape		= self.load_widget('ArrowHead')
			,custom_shape_scale	= 0.5
			,use_custom_shape_bone_size = True
		)

		pole_line = self.ik_ctrls.new(
			name		  = self.make_name(["IK", "POLE", "LINE"], self.limb_name, [self.side_suffix])
			,source		  = pole_ctrl
			,tail		  = self.org_chain[0].tail.copy()
			,parent		  = pole_ctrl
			,hide_select  = True
			,custom_shape = self.load_widget('Pole_Line')
			,use_custom_shape_bone_size	= True
		)
		pole_line.add_constraint(self.obj, 'STRETCH_TO'
			,subtarget = self.org_chain[0].name
			,head_tail = 1
		)
		# Add a driver to the Line's hide property so it's hidden exactly when the pole target is hidden.
		pole_line.drivers.append({
			'prop' : 'hide',
			'variables' : [{
				'type' : 'SINGLE_PROP',
				'targets' : [{
					'id' : self.obj,
					'data_path' : f'data.bones["{pole_ctrl.name}"].hide'
				}]
			}]
		})

		self.create_dsp_bone(pole_ctrl)
		return pole_ctrl

	def add_ui_data_ik_fk(self, fk_chain, ik_chain, ik_pole):
		""" Prepare the data needed to be stored on the armature object for IK/FK snapping. """
		fk_chain = fk_chain[:self.params.CR_ik_length]
		ik_chain = ik_chain[:self.params.CR_ik_length]

		info = {	# These parameter names must be kept in sync with Snap_IK2FK in cloudrig.py
			"operator"				: "armature.ikfk_toggle",
			"prop_bone"				: self.prop_bone.name,
			"prop_id"				: self.ikfk_name,
			"fk_chain"				: [b.name for b in fk_chain],
			"ik_chain"				: [b.name for b in ik_chain],
			"str_chain"				: [b.name for b in self.main_str_bones],
			"double_first_control"	: self.params.CR_double_first_control,
			"double_ik_control"		: self.params.CR_double_ik_control,
			"ik_pole"				: self.pole_ctrl.name if self.pole_ctrl else "",
			"ik_control"			: self.ik_mstr.name
		}
		self.add_ui_data("ik_switches", self.category, self.limb_ui_name, info, default=1.0)

	def make_ik_chain(self, org_chain, ik_mstr, pole_target, ik_pole_direction=0):
		""" Based on a chain of ORG bones, create an IK chain, optionally with a pole target."""
		ik_chain = []
		for i, org_bone in enumerate(org_chain):
			ik_bone = self.ik_mch.new(
				name		 = org_bone.name.replace("ORG", "IK")
				,source		 = org_bone
				,hide_select = self.mch_disable_select
			)
			ik_chain.append(ik_bone)

			if i == 0:
				# First IK bone special treatment
				ik_bone.parent = self.limb_root_bone.name
				ik_bone.custom_shape = self.load_widget("IK_Base")
				ik_bone.use_custom_shape_bone_size = True
				ik_bone.bone_group	  = self.bone_groups["IK Controls"]
				ik_bone.layers		  = self.bone_layers["IK Controls"]

			else:
				ik_bone.parent = ik_chain[-2]
			
			if i == self.params.CR_ik_length-1:
				# Add the IK constraint to the previous bone, targetting this one.
				pole_target_name = pole_target.name if pole_target else ""
				ik_chain[self.params.CR_ik_length-2].add_constraint(self.obj, 'IK', 
					pole_target		= self.obj if pole_target_name!="" else None,
					pole_subtarget	= pole_target_name,
					pole_angle		= self.pole_angle,
					subtarget		= ik_bone.name,
					chain_count		= self.params.CR_ik_length-1
				)
				# Parent this one to the IK master.
				ik_bone.parent = ik_mstr

				if self.params.CR_world_aligned_controls:
					fk_bone = self.fk_chain[i]
					fk_name = fk_bone.name
					fk_bone.name = fk_bone.name.replace("FK-", "FK-W-")	# W for World.
					# Make child control for the world-aligned control, that will have the original transforms and name.
					# This is currently just the target of a Copy Transforms constraint on the ORG bone.
					fk_child_bone = self.fk_mch.new(
						name		= fk_name
						,source		= fk_bone
						,parent		= fk_bone
					)

					fk_bone.flatten()

					ik_mstr.flatten()
		
		# Add IK/FK Snapping to the UI.
		self.add_ui_data_ik_fk(self.fk_chain, ik_chain, pole_target)
		return ik_chain

	def setup_ik_stretch(self):
		ik_org_bone = self.org_chain[self.params.CR_ik_length-1]
		str_name = self.org_chain[0].name.replace("ORG", "IK-STR")
		stretch_bone = self.ik_mch.new(
			name		 = str_name
			,source		 = self.org_chain[0]
			,tail		 = self.ik_mstr.head.copy()
			,parent		 = self.limb_root_bone.name
			,hide_select = self.mch_disable_select
		)
		stretch_bone.scale_width(0.4)

		# Bone responsible for giving stretch_bone the target position to stretch to.
		self.stretch_target_bone = self.ik_mch.new(
			name		 = ik_org_bone.name.replace("ORG", "IK-STR-TGT")
			,source		 = ik_org_bone
			,parent		 = self.ik_mstr
			,hide_select = self.mch_disable_select
		)

		chain_length = 0
		for ikb in self.ik_chain[:self.params.CR_ik_length-1]:	# TODO: Support IK at tail of chain.
			chain_length += ikb.length

		length_factor = chain_length / stretch_bone.length
		stretch_bone.add_constraint(self.obj, 'STRETCH_TO', subtarget=self.stretch_target_bone.name)
		limit_scale = stretch_bone.add_constraint(self.obj, 'LIMIT_SCALE', 
			use_max_y = True,
			max_y = length_factor,
			influence = 0
		)

		limit_scale.drivers.append({
			'prop' : 'influence',
			'expression' : "1-stretch",
			'variables' : {
				'stretch' : {
					'type' : 'SINGLE_PROP',
					'targets' : [
						{
							'id' : self.obj,
							'id_type' : 'OBJECT',
							'data_path' : f'pose.bones["{self.prop_bone.name}"]["{self.ik_stretch_name}"]'
						}
					]
				}
			}
		})

		# Store info for UI
		info = {
			"prop_bone"			: self.prop_bone.name,
			"prop_id" 			: self.ik_stretch_name,
		}
		self.add_ui_data("ik_stretches", self.category, self.limb_ui_name, info, default=1.0)

		# Last IK bone should copy location of the tail of the stretchy bone.
		self.ik_tgt_bone = self.ik_chain[self.params.CR_ik_length-1]
		self.ik_tgt_bone.add_constraint(self.obj, 'COPY_LOCATION'
			,space		   = 'WORLD'
			,subtarget	   = stretch_bone.name
			,head_tail	   = 1
		)

		# Create Helpers for main STR bones so they will stick to the stretchy bone.
		self.main_str_transform_setup(stretch_bone, chain_length)

		return stretch_bone

	def main_str_transform_setup(self, stretch_bone, chain_length):
		""" Set up transformation constraint to mid-limb STR bone that ensures that it stays in between the root of the limb and the IK master control during IK stretching. """

		cum_length = self.org_chain[0].length
		for i, main_str_bone in enumerate(self.main_str_bones):
			if i == 0: continue
			if i == len(self.main_str_bones)-1: continue
			main_str_helper = self.ik_mch.new(
				name		 = main_str_bone.name.replace("STR-", "STR-S-")
				,source		 = main_str_bone
				,bbone_width = 1/10
				,parent		 = main_str_bone.parent
				,hide_select = self.mch_disable_select
			)
			main_str_bone.parent = main_str_helper

			con_name = 'CopyLoc_IK_Stretch'
			main_str_helper.add_constraint(self.obj, 'COPY_LOCATION'
				,space			= 'WORLD'
				,subtarget		= stretch_bone.name
				,name			= con_name
				,head_tail		= cum_length/chain_length	# How far this bone is along the total chain length
			)
			cum_length += self.org_chain[i].length

			main_str_helper.drivers.append({
				'prop' : f'constraints["{con_name}"].influence',
				'expression' : f"ik * stretch * (distance > {chain_length} * scale)",
				'variables' : {
					'stretch' : {
						'type' : 'SINGLE_PROP',
						'targets' : [{
							'data_path' : f'pose.bones["{self.prop_bone.name}"]["{self.ik_stretch_name}"]'
						}]
					},
					'ik' : {
						'type' : 'SINGLE_PROP',
						'targets' : [{
							'data_path' : f'pose.bones["{self.prop_bone.name}"]["{self.ikfk_name}"]'
						}]
					},
					'distance' : {
						'type' : 'LOC_DIFF',
						'targets' : [{
							'bone_target' : self.ik_tgt_bone.name,
							'transform_space' : 'WORLD_SPACE'
						},
						{
							'bone_target' : self.ik_chain[0].name,
							'transform_space' : 'WORLD_SPACE'
						}]
					},
					'scale' : {
						'type' : 'TRANSFORMS',
						'targets' : [{
							'bone_target' : self.ik_chain[0].name,
							'transform_type' : 'SCALE_Y',
							'transform_space' : 'WORLD_SPACE'
						}]
					}
				}
			})

	def prepare_ik_chain(self):
		# Create IK Master control
		ik_org_bone = self.org_chain[self.params.CR_ik_length-1]
		mstr_name = ik_org_bone.name.replace("ORG", "IK-MSTR")
		self.ik_mstr = self.ik_ctrls.new(
			name		  = mstr_name
			,source		  = self.org_chain[self.params.CR_ik_length-1]
			,custom_shape = self.load_widget("Sphere")
			,parent		  = None
		)

		self.calculate_ik_info()
		# Create Pole control
		self.pole_ctrl = None
		if self.params.CR_use_pole_target:
			self.pole_ctrl = self.create_pole_control()

		# Create IK Chain
		self.ik_chain = self.make_ik_chain(self.org_chain, self.ik_mstr, self.pole_ctrl, self.ik_pole_direction)

		# Set up IK Stretch
		stretch_bone = self.setup_ik_stretch()

		if self.pole_ctrl:
			# Add aim constraint to pole display bone
			self.pole_ctrl.dsp_bone.add_constraint(self.obj, 'DAMPED_TRACK', 
				subtarget  = stretch_bone.name,
				head_tail  = 0.5,
				track_axis = 'TRACK_NEGATIVE_Y'
			)

	def prepare_org_limb(self):
		# Note: Runs after prepare_org_chain().

		# Add Copy Transforms constraints to the ORG bones to copy the IK bones.
		# Put driver on the influence to be able to disable IK.

		for org_bone in self.org_chain:
			ik_bone = self.get_bone_info(org_bone.name.replace("ORG", "IK"))
			copy_trans = org_bone.add_constraint(self.obj, 'COPY_TRANSFORMS'
				,space		  = 'WORLD'
				,subtarget	  = ik_bone.name
				,name		  = "Copy Transforms IK"
			)

			copy_trans.drivers.append({
				'prop' : 'influence',
				'variables' : [{
					'type' : 'SINGLE_PROP',
					'targets' : [{
						'data_path' : f'pose.bones["{self.prop_bone.name}"]["{self.ikfk_name}"]'
					}]
				}]
			})

	def prepare_bones(self):
		super().prepare_bones()
		self.prepare_root_bone()
		self.prepare_ik_chain()
		self.prepare_org_limb()
		self.prepare_parent_switch()

	def prepare_parent_switch(self, ik_ctrl=None):
		if not ik_ctrl:
			ik_ctrl = self.ik_mstr

		if len(self.get_parent_candidates()) == 0:
			# If this rig has no parent candidates, there's nothing to be done here.
			return

		ik_parents_prop_name = "ik_parents_" + self.limb_name_props
		# Try to rig the IK control's parent switcher, searching for these parent candidates.
		parent_names = self.rig_child(ik_ctrl, self.ik_parents, self.prop_bone, ik_parents_prop_name)
		if len(parent_names) > 0:
			bones = [ik_ctrl.name]
			if self.params.CR_use_pole_target:
				bones.append(self.pole_ctrl.name)
			else:
				bones.append(self.ik_chain[0].name)
			info = {
				"prop_bone" : self.prop_bone.name,
				"prop_id" : ik_parents_prop_name,
				"texts" : parent_names,
				
				"operator" : "pose.rigify_switch_parent",
				"icon" : "COLLAPSEMENU",
				"parent_names" : parent_names,	# TODO: I think this is unused now.
				"bones" : bones,
				}
			self.add_ui_data("parents", self.category, self.limb_ui_name, info, default=0, _max=len(parent_names)-1)

		### IK Pole Follow
		if self.params.CR_use_pole_target:
			# Rig the IK Pole control's parent switcher.
			self.rig_child(self.pole_ctrl, self.ik_parents, self.prop_bone, ik_parents_prop_name)

			# Add option to the UI.
			ik_pole_follow_name = "ik_pole_follow_" + self.limb_name_props
			info = {
				"prop_bone" : self.prop_bone.name,
				"prop_id"	: ik_pole_follow_name,

				"operator" : "pose.snap_simple",
				"bones" : [self.pole_ctrl.name],
				"select_bones" : True
			}
			default = 1.0 if self.limb_type=='LEG' else 0.0
			self.add_ui_data("ik_pole_follows", self.category, self.limb_ui_name, info, default=default)

			# Get the armature constraint from the IK pole's parent, and add the IK master as a new target.
			arm_con_bone = self.pole_ctrl.parent
			arm_con = arm_con_bone.constraint_infos[0]
			arm_con.targets.append({
				"subtarget" : self.ik_mstr.name
			})

			# Add driver to the new constraint target
			target_idx = len(arm_con.targets)-1
			arm_con.drivers.append({
				'prop' : f'targets[{target_idx}].weight',
				'expression' : 'follow',
				'variables' : {}	# Variable is created in the for loop below.
			})
			
			# Tweak each driver on the IK pole parent
			# NOTE: These were originally created by calling self.rig_child(self.pole_ctrl...
			for i, d in enumerate(arm_con.drivers):
				if i != len(arm_con.drivers)-1:
					d['expression'] = f"({d['expression']}) - follow"
				
				# Add "follow" variable.
				d['variables']['follow'] = {
					'type' : 'SINGLE_PROP',
					'targets' : [{
						'data_path' : f'pose.bones["{self.prop_bone.name}"]["{ik_pole_follow_name}"]'
					}]
				}

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		super().define_bone_sets(params)
		""" Create parameters for this rig's bone sets. """
		cls.define_bone_set(params, "IK Controls", preset=2, default_layers=[cls.default_layers('IK_MAIN')])
		cls.define_bone_set(params, "IK Parent Controls", preset=8, default_layers=[cls.default_layers('IK_MAIN')])
		cls.define_bone_set(params, "IK Mechanism", default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "FK Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""

		params.CR_show_ik_settings = BoolProperty(name="IK Rig")
		# TODO: Parameter to let the IK control be at the tip of the last bone instead of at the last bone itself. Would be useful for fingers.
		params.CR_use_custom_limb_name = BoolProperty(
			 name		 = "Custom Limb Name"
			,description = "Specify a name for this limb. Settings for limbs with the same name will be displayed on the same row in the rig UI. If not enabled, use the name of the base bone, without pre and suffixes"
			,default 	 = False
		)
		params.CR_custom_limb_name = StringProperty(
			name		 = "Custom Limb"
			,default	 = "Arm"
			,description = """This name should NOT include a side indicator such as ".L" or ".R", as that will be determined by the bone's name. There can be exactly two limbs with the same name(a left and a right one)."""
		)
		params.CR_use_custom_category_name = BoolProperty(
			 name		 = "Custom Category Name"
			,description = "Specify a category for this limb. If not enabled, use the name of the base bone, without pre and suffixes"
			,default	 = False,
		)
		params.CR_custom_category_name = StringProperty(
			name		 = "Custom Category"
			,default	 = "arms"
			,description = "Limbs in the same category will have their settings displayed in the same column"
			)
		params.CR_ik_length = IntProperty(
			name	 	 = "IK Length"
			,description = "Length of the IK chain. Cannot be higher than the number of bones in the chain"
			,default	 = 3
			,min		 = 1
			,max		 = 255
		)
		params.CR_world_aligned_controls = BoolProperty(
			 name		 = "World Aligned Control"
			,description = "Ankle/Wrist IK/FK controls are aligned with world axes"
			,default	 = True
		)
		params.CR_use_pole_target = BoolProperty(
			name 		 = "Use Pole Target"
			,description = "If disabled, you can control the rotation of the IK chain by simply rotating its first bone, rather than with an IK pole control"
			,default	 = True
		)

		super().add_parameters(params)

	@classmethod
	def bone_set_ui(cls, params, layout, set_info, ui_rows):
		if set_info['name'] != "FK Helpers" or params.CR_world_aligned_controls:
			super().bone_set_ui(params, layout, set_info, ui_rows)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		ui_rows = super().cloud_params_ui(layout, params)

		icon = 'TRIA_DOWN' if params.CR_show_ik_settings else 'TRIA_RIGHT'
		layout.prop(params, "CR_show_ik_settings", toggle=True, icon=icon)
		if not params.CR_show_ik_settings: return ui_rows

		name_row = layout.row()
		limb_column = name_row.column()
		limb_column.prop(params, "CR_use_custom_limb_name")
		if params.CR_use_custom_limb_name:
			limb_column.prop(params, "CR_custom_limb_name", text="")
		category_column = name_row.column()
		category_column.prop(params, "CR_use_custom_category_name")
		if params.CR_use_custom_category_name:
			category_column.prop(params, "CR_custom_category_name", text="")

		pole_row = layout.row()
		pole_row.prop(params, "CR_use_pole_target")
		layout.prop(params, "CR_ik_length")
		layout.prop(params, "CR_world_aligned_controls")

		return ui_rows

class Rig(CloudIKChainRig):
	pass