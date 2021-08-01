from bpy.types import PoseBone
from typing import Tuple

from bpy.props import BoolProperty
from mathutils import Vector
from math import radians as rad

from ..rig_features.mechanism import get_bone_chain
from ..utils.maths import flat
from .cloud_fk_chain import CloudFKChainRig

"""Ideas to improve this:
Allow disabling IK stretch functionality.
"""

class CloudIKChainRig(CloudFKChainRig):
	"""IK chain with stretchy IK, IK/FK snapping, squash and stretch controls, and optional IK pole control."""

	# Strings to try to communicate obscure behaviours of this rig type in the params UI.
	parent_switch_behaviour = 'The active parent will own the IK-MSTR and IK-POLE controls.'
	parent_switch_overwrites_root_parent = False
	always_use_custom_props = True

	forced_params = {
		'CR_fk_chain_root' : True,
	}

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		# UI Strings and Custom Property names
		self.ikfk_name = "ik_" + self.limb_name_props
		self.ik_stretch_name = "ik_stretch_" + self.limb_name_props

		self.pole_side = 1
		self.ik_pole_offset = 3		# Scalar on distance from the body. Could become a parameter but it's unimportant.

		# Will be passed to the IK constraint's chain_count.
		# Elements of the rig can use this to avoid having to make assumptions about correlations
		# between the length of the ORG chain vs how long the IK chain is.
		self.chain_count = self.bone_count-1
		if self.params.CR_ik_chain_at_tip:
			self.chain_count += 1

	def create_bone_infos(self):
		super().create_bone_infos()
		if not len(self.bones_org) > 1:
			self.raise_error(f"ERROR on {self.base_bone}: cloud_ik_chain requires a chain of at least 2 bones!")
		self.last_org = self.bones_org[-1]
		if self.params.CR_ik_chain_at_tip:
			self.bones_org.new(
				name = "TIP-"+self.last_org.name
				,source = self.last_org
				,head = self.last_org.tail.copy()
				,vector = self.last_org.vector
			)
		if self.params.CR_ik_chain_world_aligned:
			self.world_align_last_fk()
		self.make_ik_setup()
		# Add IK/FK Snapping to the UI.
		ui_data = self.create_ui_data(self.bone_sets['FK Controls'], self.ik_chain, self.ik_mstr, self.pole_ctrl)
		self.add_ui_data("ik_switches", self.limb_name, self.limb_ui_name, ui_data, default=1.0)
		self.attach_org_to_ik()

	def world_align_last_fk(self):
		# Make last FK bone world-aligned.
		self.make_world_aligned_control(self.last_org.fk_bone)

	def make_world_aligned_control(self, bone):
		# Make a world-aligned parent control for a bone.
		old_name = bone.name
		bone.name = self.naming.add_prefix(bone.name, "W")	# W for World.

		# Make child control for the world-aligned control, that will have the original transforms and name.
		# This is currently just the target of a Copy Transforms constraint on the ORG bone.
		fk_child_bone = self.bone_sets['FK Helpers'].new(
			name		= old_name
			,source		= bone
			,parent		= bone
		)

		bone.flatten()

	def make_ik_setup(self):
		# Create IK Master control
		self.ik_mstr = self.create_ik_master(
			self.bone_sets['IK Controls'],
			self.bones_org[self.chain_count],
		)

		self.calculate_ik_info()
		# Create Pole control
		self.pole_ctrl = None
		if self.params.CR_ik_chain_use_pole:
			self.pole_ctrl = self.make_pole_control()

		# Create IK Chain
		self.ik_chain = self.make_ik_chain(self.bones_org, self.ik_mstr, self.pole_ctrl)

		if self.pole_ctrl:
			# Create a display helper that aims the pole target at the IK chain
			dsp_bone = self.create_dsp_bone(self.pole_ctrl)
			dsp_bone.add_constraint('DAMPED_TRACK',
				subtarget  = self.ik_chain[1].name,
				track_axis = 'TRACK_NEGATIVE_Y'
			)

		# Set up IK Stretch
		self.stretch_bone = self.make_ik_stretch()

	def create_ik_master(self, bone_set, source_bone, bone_name="", shape_name="Sphere"):
		if bone_name=="":
			bone_name = source_bone.name.replace("ORG", "IK-MSTR")

		ik_master = bone_set.new(
			name		  = bone_name
			,source		  = source_bone
			,custom_shape = self.ensure_widget(shape_name)
			,parent		  = None
		)

		return ik_master

	@staticmethod
	def calculate_ik_info_static(
			meta_first: PoseBone,
			meta_second: PoseBone
		) -> Tuple[float, Vector, Vector]:

		chain_vector = meta_second.tail - meta_first.head

		first_tail = meta_first.tail
		last_tail = meta_second.tail

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
		pole_angle = rad(lowest_distance[1])

		vector_flipper = 1
		perpendicular_axis = meta_first.x_axis
		if rotation_axis[0] == "-":
			vector_flipper = -1
		if rotation_axis[1] == "Z":
			perpendicular_axis = meta_first.z_axis

		# Find the vector that is perpendicular to a plane defined by the chain vector and the main rotation axis.
		pole_vector = chain_vector.cross(perpendicular_axis).normalized() * vector_flipper * chain_vector.length

		# We want the pole control to be offset from the first bone's tail by that vector.
		pole_location = first_tail + pole_vector

		return pole_angle, pole_vector, pole_location

	def calculate_ik_info(self):
		""" Calculate pole angle, pole control direction and distance. """
		meta_first_name = self.bones_org[0].name.replace("ORG-", "")
		meta_first = self.meta_bone(meta_first_name)

		meta_second_name = self.bones_org[1].name.replace("ORG-", "")
		meta_second = self.meta_bone(meta_second_name)

		pole_angle, pole_vector, pole_location = self.calculate_ik_info_static(meta_first, meta_second)
		self.pole_angle = pole_angle
		self.pole_vector = pole_vector
		self.pole_location = pole_location

	def make_pole_control(self):
		# Create IK Pole Control
		pole_ctrl = self.pole_ctrl = self.bone_sets['IK Controls'].new(
			name				= self.naming.make_name(["IK", "POLE"], self.limb_name, [self.side_suffix])
			,bbone_width		= 0.1
			,head				= self.pole_location
			,tail				= self.pole_location + flat(self.pole_vector) * 0.2
			,roll				= 0
			,custom_shape		= self.ensure_widget('Arrow_Head')
			,custom_shape_scale	= 0.5
			,use_custom_shape_bone_size = True
			,parent = self.ik_mstr
		)
		self.lock_transforms(pole_ctrl, loc=False)

		pole_line = self.bone_sets['IK Controls'].new(
			name		  = self.naming.make_name(["IK", "POLE", "LINE"], self.limb_name, [self.side_suffix])
			,source		  = pole_ctrl
			,tail		  = self.bones_org[0].tail.copy()
			,parent		  = pole_ctrl
			,hide_select  = True
			,custom_shape = self.ensure_widget('Line')
			,use_custom_shape_bone_size	= True
		)
		pole_line.add_constraint('STRETCH_TO'
			,subtarget = self.bones_org[0].name
			,head_tail = 1
		)
		# Add a driver to the Line's hide property so it's hidden exactly when the pole target is hidden.
		pole_line.drivers_data.append({
			'prop' : 'hide',
			'variables' : [{
				'type' : 'SINGLE_PROP',
				'targets' : [{
					'data_path' : f'data.bones["{pole_ctrl.name}"].hide'
				}]
			}]
		})

		return pole_ctrl

	def make_ik_chain(self, org_chain, ik_mstr, pole_target=None, ik_pole_direction=0):
		""" Based on a chain of ORG bones, create an IK chain, optionally with a pole target."""
		ik_chain = []
		for i, org_bone in enumerate(org_chain):
			ik_bone = self.bone_sets['IK Mechanism'].new(
				name		 = org_bone.name.replace("ORG", "IK")
				,source		 = org_bone
			)
			ik_chain.append(ik_bone)

			if i == 0:
				# First IK bone special treatment
				ik_bone.parent 						= self.root_bone
				ik_bone.custom_shape 				= self.ensure_widget("Squares_2")
				ik_bone.custom_shape_scale_xyz		= Vector((0.8, 1, 0.8))
				ik_bone.bone_group	  				= self.bone_sets['IK Controls'].bone_group
				ik_bone.layers		  				= self.bone_sets['IK Controls'].layers[:]

			else:
				ik_bone.parent = ik_chain[-2]

			if i == self.chain_count:
				# Add the IK constraint to the previous bone, targetting this one.
				ik_chain[-2].add_constraint('IK',
					pole_target		= self.obj if pole_target else None,
					pole_subtarget	= pole_target.name if pole_target else "",
					pole_angle		= self.pole_angle,
					subtarget		= ik_bone.name,
					chain_count		= i
				)
				# Parent this one to the IK master.
				ik_bone.parent = ik_mstr
				if self.params.CR_ik_chain_world_aligned:
					ik_mstr.flatten()

		ik_chain[0].custom_shape_scale_xyz = ik_chain[0].custom_shape_scale_xyz.copy()	# TODO: This shouldn't be needed! Otherwise it seems all bones in this rig use a single vector.
		ik_chain[0].custom_shape_scale_xyz.y = ik_chain[0].length / (ik_chain[0].bbone_width * 10 * self.scale)	# This is awkward, but it's a drawback of the BBone Display Size==widget size system: We basically want a single value to not use the system here, so we un-multiply it.
		return ik_chain

	def create_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
		# List of bone tuples to snap (from, to).
		map_on = []									# Which bone will be snapped to which when the custom property is set to 1.
		map_off = [] 								# Which bone will be snapped to which when the custom property is set to 0.

		hide_on = [b.name for b in fk_chain]		# Which bones will be hidden when the custom property is set to 1.
		hide_off = [ik_mstr.name]	# Which bones will be hidden when the custom property is set to 0.
		if ik_pole:
			hide_off.append(ik_pole.name)

		map_on.append( (ik_mstr.name, fk_chain[-1].name) )
		map_on.append( (ik_chain[0].name, fk_chain[0].name) )

		if self.params.CR_fk_chain_double_first:
			hide_on.append( (fk_chain[0].parent.name) )
			map_off.append( (fk_chain[0].parent.name, ik_chain[0].name) )

		for i in range(len(fk_chain)):
			map_off.append( (fk_chain[i].name, ik_chain[i].name))

		ui_data = {
			'operator'				: 'pose.cloudrig_toggle_ikfk_bake'
			,'prop_bone'			: self.properties_bone
			,'prop_id'				: self.ikfk_name
			,'map_on'				: map_on
			,'map_off'				: map_off
			,'hide_on'				: hide_on
			,'hide_off'				: hide_off
			,'ik_pole'				: ik_pole.name if ik_pole else ''
			,'fk_first'				: self.bone_sets['FK Controls'][0].name
			,'fk_last'				: self.bone_sets['FK Controls'][1].name
		}
		return ui_data

	def make_ik_stretch(self):
		"""Primary function that starts the entire Stretchy IK set-up.
		Some extra stuff is in attach_org_to_ik. # TODO: Put these things under a parameter, so IK Stretch can be disabled when not needed.
		"""

		ik_org_bone = self.bones_org[self.chain_count]
		stretch_bone = self.bone_sets['IK Mechanism'].new(
			name		 = self.bones_org[0].name.replace("ORG", "IK-STR")
			,source		 = self.bones_org[0]
			,tail		 = self.ik_mstr.head.copy()
			,parent		 = self.root_bone
		)
		stretch_bone.scale_width(0.4)

		# Bone responsible for giving stretch_bone the target position to stretch to.
		self.stretch_target_bone = self.bone_sets['IK Mechanism'].new(
			name		 = ik_org_bone.name.replace("ORG", "IK-STR-TGT")
			,source		 = ik_org_bone
			,parent		 = self.ik_mstr
		)

		chain_length = 0
		for ikb in self.ik_chain[:self.chain_count]:
			chain_length += ikb.length

		length_factor = chain_length / stretch_bone.length
		stretch_bone.add_constraint('STRETCH_TO', subtarget=self.stretch_target_bone.name)
		limit_scale = stretch_bone.add_constraint('LIMIT_SCALE',
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
							'data_path' : f'pose.bones["{self.properties_bone.name}"]["{self.ik_stretch_name}"]'
						}
					]
				}
			}
		})

		# Store info for UI
		info = {
			"prop_bone"			: self.properties_bone,
			"prop_id" 			: self.ik_stretch_name,
		}
		self.add_ui_data("ik_stretches", self.limb_name, self.limb_ui_name, info, default=1.0)

		# Last IK bone should copy location of the tail of the stretchy bone.
		self.ik_tgt_bone = self.ik_chain[self.chain_count]
		self.ik_tgt_bone.add_constraint('COPY_LOCATION'
			,space		   = 'WORLD'
			,subtarget	   = stretch_bone.name
			,head_tail	   = 1
		)

		# Create Helpers for main STR bones so they will stick to the stretchy bone during IK stretching.
		self.make_ik_stretch_helpers(stretch_bone, chain_length)

		return stretch_bone

	def make_ik_stretch_helpers(self, stretch_bone, chain_length):
		""" Set up transformation constraint to mid-limb STR bone that ensures
			that it stays in between the root of the limb and the IK master
			control during IK stretching.
		"""

		# This driver will cause the Copy Location constraint to activate exactly
		# when the stretch bone's current length exceeds its original length.
		ik_stretch_engaged_driver = {
			'prop' : 'influence',
			'expression' : f"ik * stretch * (distance > {chain_length} * scale)",
			'variables' : {
				'stretch' : {
					'type' : 'SINGLE_PROP',
					'targets' : [{
						'data_path' : f'pose.bones["{self.properties_bone.name}"]["{self.ik_stretch_name}"]'
					}]
				},
				'ik' : {
					'type' : 'SINGLE_PROP',
					'targets' : [{
						'data_path' : f'pose.bones["{self.properties_bone.name}"]["{self.ikfk_name}"]'
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
		}

		cum_length = self.bones_org[0].length
		for i, main_str_bone in enumerate(self.main_str_bones):
			# How far this bone is along the total chain length
			head_tail = cum_length/chain_length
			if head_tail > 1.0: break
			if i == 0: continue
			if i == len(self.main_str_bones)-1 and not self.params.CR_ik_chain_at_tip: continue
			# Create STR-S helper
			main_str_helper = self.bone_sets['IK Mechanism'].new(
				name		 = self.naming.add_prefix(main_str_bone, "S")
				,source		 = main_str_bone
				,bbone_width = 1/10
				,parent		 = main_str_bone.parent
			)
			main_str_bone.stretch_helper = main_str_helper
			main_str_bone.parent = main_str_helper

			con_name = 'CopyLoc_IK_Stretch'
			copyloc = main_str_helper.add_constraint('COPY_LOCATION'
				,space			= 'WORLD'
				,subtarget		= stretch_bone.name
				,name			= con_name
				,head_tail		= head_tail
			)
			org_bone = self.bones_org[i]
			cum_length += org_bone.length

			copyloc.drivers.append(dict(ik_stretch_engaged_driver))

		# Attach ORG chain to IK Stretch	- This works but provides no benefit, and can result in snapping if the IK Base control is translated.
		# cum_length = 0
		# for i, org_bone in enumerate(self.bones_org):
		# 	head_tail = cum_length/chain_length
		# 	cum_length += org_bone.length
		# 	# ORG Copy Transforms to IK Stretch bone
		# 	ct_ik_str = org_bone.add_constraint('COPY_TRANSFORMS'
		# 		,name	   = "Copy Transforms IK Stretch"
		# 		,space	   = 'WORLD'
		# 		,subtarget = stretch_bone.name
		# 		,head_tail = head_tail

		# 	)

		# 	ct_ik_str.drivers.append(dict(ik_stretch_engaged_driver))

	def attach_org_to_ik(self):
		# Note: Runs after attach_org_to_fk().

		# Add Copy Transforms constraints to the ORG bones to copy the IK bones.
		# Put driver on the influence to be able to disable IK.

		for org_bone in self.bones_org:
			# Copy Transforms to IK bone
			ik_bone = self.get_bone_info(org_bone.name.replace("ORG", "IK"))
			ct_ik = org_bone.add_constraint('COPY_TRANSFORMS'
				,space		  = 'WORLD'
				,subtarget	  = ik_bone.name
				,name		  = "Copy Transforms IK"
				# ,index		  = 1 # In case IK Stretch is enabled, this constraint needs to be inserted before the Copy Transforms IK Stretch constraint!
			)

			ct_ik.drivers.append({
				'prop' : 'influence'
				,'variables' : [
					(self.properties_bone.name, self.ikfk_name)
				]
			})

	def apply_parent_switching(self, parent_slots, 
			child_bone=None,
			prop_bone=None, prop_name="",
			ui_area="", row_name="", col_name=""
		):
		"""Overrides cloud_base."""
		if not child_bone:
			child_bone = self.ik_mstr

		ik_parents_prop_name = "ik_parents_" + self.limb_name_props
		super().apply_parent_switching(parent_slots
			,child_bone = child_bone
			,prop_bone = prop_bone or self.properties_bone
			,prop_name = prop_name or ik_parents_prop_name
			,ui_area = ui_area or 'ik_parents'
			,row_name = row_name or self.limb_name
			,col_name = col_name or self.limb_ui_name
		)

		if self.params.CR_ik_chain_use_pole:
			self.setup_ik_pole_parent_switch(self.ik_mstr)

	def setup_ik_pole_parent_switch(self, ik_mstr):
		"""Rig the IK Pole control's parent switcher, with an additional "IK Pole Follows" slider."""
		# Create parent helper bone
		parent_helper = self.create_parent_bone(self.pole_ctrl, bone_set=self.bones_mch)
		parent_helper.custom_shape = None

		# Copy the constraint and drivers from the IK master
		arm_con_info = parent_helper.add_constraint('ARMATURE', use_deform_preserve_volume=True)
		arm_con_info.targets = [dict(d) for d in ik_mstr.parent.constraint_infos[0].targets]
		arm_con_info.drivers = [dict(d) for d in ik_mstr.parent.constraint_infos[0].drivers]

		# Add IK Pole Follows option to the UI.
		ik_pole_follow_name = "ik_pole_follow_" + self.limb_name_props
		info = {
			"prop_bone" : self.properties_bone,
			"prop_id"	: ik_pole_follow_name,

			"operator" : "pose.cloudrig_snap_bake",
			"bones" : [self.pole_ctrl.name],
			"select_bones" : True
		}
		self.add_ui_data("ik_pole_follows", self.limb_name, self.limb_ui_name, info, default=0.0)

		if not self.params.CR_base_parent_switching:
			return
		# Get the armature constraint from the IK pole's parent, and add the IK master as a new target.
		arm_con_info.targets.append({
			"subtarget" : self.ik_mstr.name
		})

		# Add driver to the new constraint target.
		target_idx = len(arm_con_info.targets)-1
		arm_con_info.drivers.append({
			'prop' : f'targets[{target_idx}].weight',
			'expression' : 'follow',
			'variables' : {}	# Variable is created in the for loop below.
		})

		# Tweak each driver on the IK pole parent.
		for i, d in enumerate(arm_con_info.drivers):
			if i != len(arm_con_info.drivers)-1:
				d['expression'] = f"({d['expression']}) - follow"

			# Add "follow" variable.
			d['variables']['follow'] = {
				'type' : 'SINGLE_PROP',
				'targets' : [{
					'data_path' : f'pose.bones["{self.properties_bone.name}"]["{ik_pole_follow_name}"]'
				}]
			}

	def add_test_animation(self, action, start_frame=1, flip_xyz=[False, False, False]) -> int:
		"""Add animation curves to the action to test this rig.

		Return the frame at which animation is finished.
		"""
		last_frame = super().add_test_animation(action, start_frame, flip_xyz)
		self.disable_property_until_frame(action, last_frame, self.ikfk_name)
		return last_frame

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'IK Controls', 		preset=2, default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])
		cls.define_bone_set(params, 'IK Extra Controls',preset=2, default_layers=[cls.DEFAULT_LAYERS.IK_SECOND])
		cls.define_bone_set(params, 'IK Mechanism', 			  default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_ik_chain_at_tip = BoolProperty(
			name		 = "IK At Tail"
			,description = "Put the IK control at the tail of the chain, rather than the head of the last bone"
			,default	 = False
		)
		params.CR_ik_chain_world_aligned = BoolProperty(
			 name		 = "World Aligned IK Master"
			,description = "Ankle/Wrist IK/FK controls are aligned with world axes"
			,default	 = False
		)
		params.CR_ik_chain_use_pole = BoolProperty(
			name 		 = "Create IK Pole"
			,description = "If disabled, you can control the rotation of the IK chain by simply rotating its first bone, rather than with an IK pole control"
			,default	 = True
		)

		super().add_parameters(params)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)

		layout.separator()
		cls.draw_control_label(layout, "IK")

		cls.draw_prop(layout, params, "CR_ik_chain_use_pole")
		cls.draw_prop(layout, params, "CR_ik_chain_at_tip")
		
		if not cls.is_advanced_mode(context):
			return
		cls.draw_prop(layout, params, "CR_ik_chain_world_aligned")

		# TODO: This operator should work by picking 3 points on the bone chain, 
		# then aligning all points of the bone chain to that plane.

		# op = layout.operator('object.cloudrig_flatten_bones')
		# op.use_selected = False
		# op.start_bone = context.active_pose_bone.name
		# op.chain_length = len(get_bone_chain(context.active_pose_bone) ) - 1
		# op.skip_popup = True

	##############################
	# Overlay
	@classmethod
	def draw_overlay(cls, context, buffer) -> list((Vector, Vector)):
		active_pb = context.active_pose_bone
		chain = cls.get_rigify_chain(active_pb)

		pole_angle, pole_vector, pole_location = cls.calculate_ik_info_static(chain[0], chain[1])

		buffer.draw_line_3d(chain[1].head, pole_location)

class Rig(CloudIKChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)