import bpy
from typing import List
from ..bone import BoneInfo

from bpy.props import BoolProperty
from mathutils import Vector
from math import radians as rad

from ..utils.maths import flat
from ..utils.mechanism import get_bone_chain
from .cloud_fk_chain import CloudFKChainRig

"""Ideas to improve this:
Allow disabling IK stretch functionality.
"""

class CloudIKChainRig(CloudFKChainRig):
	"""IK chain with stretchy IK, IK/FK snapping, squash and stretch controls, and optional IK pole control."""

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
		self.chain_count = len(self.bones.org.main)-1
		if self.params.CR_ik_chain_at_tip:
			self.chain_count += 1

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.ik_ctrls = self.ensure_bone_set("IK Controls")
		self.ik_ctrls_secondary = self.ensure_bone_set("IK Extra Controls")
		self.ik_mch = self.ensure_bone_set("IK Mechanism")

	def prepare_bones(self):
		super().prepare_bones()
		if self.params.CR_ik_chain_world_aligned:
			self.world_align_last_fk()
		self.make_ik_setup()
		# Add IK/FK Snapping to the UI.
		ui_data = self.create_ui_data(self.fk_chain, self.ik_chain, self.ik_mstr, self.pole_ctrl)
		self.add_ui_data("ik_switches", self.category, self.limb_ui_name, ui_data, default=1.0)
		self.attach_org_to_ik()

		# List of parent candidate identifiers that this rig is looking for among its registered parent candidates
		self.setup_ik_parent_switches()

	def world_align_last_fk(self):
		# Make last FK bone world-aligned.
		self.make_world_aligned_control(self.org_chain[-1].fk_bone)

	def make_world_aligned_control(self, bone):
		# Make a world-aligned parent control for a bone.
		old_name = bone.name
		bone.name = self.naming.add_prefix(bone.name, "W")	# W for World.

		# Make child control for the world-aligned control, that will have the original transforms and name.
		# This is currently just the target of a Copy Transforms constraint on the ORG bone.
		fk_child_bone = self.new_bonei(self.fk_mch
			,name		= old_name
			,source		= bone
			,parent		= bone
		)

		bone.flatten()

	def make_ik_setup(self):
		# Create IK Master control
		ik_org_bone = self.org_chain[self.chain_count]
		mstr_name = ik_org_bone.name.replace("ORG", "IK-MSTR")
		self.ik_mstr = self.create_ik_master(
			self.ik_ctrls, 
			ik_org_bone, 
		)

		self.calculate_ik_info()
		# Create Pole control
		self.pole_ctrl = None
		if self.params.CR_ik_chain_use_pole:
			self.pole_ctrl = self.make_pole_control()

		# Create IK Chain
		self.ik_chain = self.make_ik_chain(self.org_chain, self.ik_mstr, self.pole_ctrl)

		if self.pole_ctrl:
			# Add aim constraint to pole display bone
			self.pole_ctrl.dsp_bone.add_constraint('DAMPED_TRACK',
				subtarget  = self.ik_chain[1].name,
				track_axis = 'TRACK_NEGATIVE_Y'
			)

		# Set up IK Stretch
		stretch_bone = self.make_ik_stretch()

	def create_ik_master(self, bone_set, source_bone, bone_name="", shape_name="Sphere"):
		if bone_name=="":
			bone_name = "IK-MSTR-" + source_bone.name.replace("ORG-", "")

		ik_master = self.new_bonei(self.ik_ctrls
			,name		  = bone_name
			,source		  = source_bone
			,custom_shape = self.ensure_widget(shape_name)
			,parent		  = None
		)

		return ik_master

	@staticmethod
	def calculate_ik_info_static(
			meta_first: bpy.types.PoseBone, 
			meta_last: bpy.types.PoseBone
		) -> (float, Vector, Vector):
		
		chain_vector = meta_last.tail - meta_first.head

		first_tail = meta_first.tail
		last_tail = meta_last.tail

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
		meta_first_name = self.org_chain[0].name.replace("ORG-", "")
		meta_first = self.meta_bone(meta_first_name)

		meta_last_name = self.org_chain[1].name.replace("ORG-", "")
		meta_last = self.meta_bone(meta_last_name)

		pole_angle, pole_vector, pole_location = self.calculate_ik_info_static(meta_first, meta_last)
		self.pole_angle = pole_angle
		self.pole_vector = pole_vector
		self.pole_location = pole_location

	def make_pole_control(self):
		# Create IK Pole Control
		pole_ctrl = self.pole_ctrl = self.new_bonei(self.ik_ctrls
			,name				= self.naming.make_name(["IK", "POLE"], self.limb_name, [self.side_suffix])
			,bbone_width		= 0.1
			,head				= self.pole_location
			,tail				= self.pole_location + self.flat_vector(self.pole_vector) * 0.2
			,roll				= 0
			,custom_shape		= self.ensure_widget('ArrowHead')
			,custom_shape_scale	= 0.5
			,use_custom_shape_bone_size = True
		)

		pole_line = self.new_bonei(self.ik_ctrls
			,name		  = self.naming.make_name(["IK", "POLE", "LINE"], self.limb_name, [self.side_suffix])
			,source		  = pole_ctrl
			,tail		  = self.org_chain[0].tail.copy()
			,parent		  = pole_ctrl
			,hide_select  = True
			,custom_shape = self.ensure_widget('Pole_Line')
			,use_custom_shape_bone_size	= True
		)
		pole_line.add_constraint('STRETCH_TO'
			,subtarget = self.org_chain[0].name
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

		self.create_dsp_bone(pole_ctrl)
		return pole_ctrl

	def make_ik_chain(self, org_chain, ik_mstr, pole_target=None, ik_pole_direction=0):
		""" Based on a chain of ORG bones, create an IK chain, optionally with a pole target."""
		ik_chain = []
		for i, org_bone in enumerate(org_chain):
			ik_bone = self.new_bonei(self.ik_mch
				,name		 = org_bone.name.replace("ORG", "IK")
				,source		 = org_bone
				,hide_select = self.mch_disable_select
			)
			ik_chain.append(ik_bone)

			if i == 0:
				# First IK bone special treatment
				ik_bone.parent = self.limb_root_bone
				ik_bone.custom_shape = self.ensure_widget("Rectangles")
				ik_bone.bone_group	  = self.ik_ctrls.bone_group
				ik_bone.use_custom_shape_bone_size = True
				ik_bone.layers		  = self.ik_ctrls.layers[:]
				dsp = self.create_dsp_bone(ik_bone)
				dsp.length = self.scale
				ik_bone.custom_shape_scale = dsp.length / ik_bone.length
				dsp.add_constraint('STRETCH_TO', subtarget=ik_bone.name, head_tail=1, rest_length=dsp.length)

			else:
				ik_bone.parent = ik_chain[-2]

			if i == self.chain_count:
				# Add the IK constraint to the previous bone, targetting this one.
				pole_target_name = pole_target.name if pole_target else ""
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

		for i, fk_bone in enumerate(fk_chain):
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
			,'fk_first'				: self.fk_chain[0].name
			,'fk_last'				: self.fk_chain[1].name
		}
		return ui_data

	def make_ik_stretch(self):
		ik_org_bone = self.org_chain[self.chain_count]
		stretch_bone = self.new_bonei(self.ik_mch
			,name		 = self.org_chain[0].name.replace("ORG", "IK-STR")
			,source		 = self.org_chain[0]
			,tail		 = self.ik_mstr.head.copy()
			,parent		 = self.limb_root_bone.name
			,hide_select = self.mch_disable_select
		)
		stretch_bone.scale_width(0.4)

		# Bone responsible for giving stretch_bone the target position to stretch to.
		self.stretch_target_bone = self.new_bonei(self.ik_mch
			,name		 = ik_org_bone.name.replace("ORG", "IK-STR-TGT")
			,source		 = ik_org_bone
			,parent		 = self.ik_mstr
			,hide_select = self.mch_disable_select
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
		self.add_ui_data("ik_stretches", self.category, self.limb_ui_name, info, default=1.0)

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

		cum_length = self.org_chain[0].length
		for i, main_str_bone in enumerate(self.main_str_bones):
			# How far this bone is along the total chain length
			head_tail = cum_length/chain_length
			if head_tail > 1.0: break
			if i == 0: continue
			if i == len(self.main_str_bones)-1: continue
			main_str_helper = self.new_bonei(self.ik_mch
				,name		 = self.naming.add_prefix(main_str_bone, "S")
				,source		 = main_str_bone
				,bbone_width = 1/10
				,parent		 = main_str_bone.parent
				,hide_select = self.mch_disable_select
			)
			main_str_bone.parent = main_str_helper

			con_name = 'CopyLoc_IK_Stretch'
			main_str_helper.add_constraint('COPY_LOCATION'
				,space			= 'WORLD'
				,subtarget		= stretch_bone.name
				,name			= con_name
				,head_tail		= head_tail
			)
			cum_length += self.org_chain[i].length

			main_str_helper.drivers.append({
				'prop' : f'constraints["{con_name}"].influence',
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
			})

	def attach_org_to_ik(self):
		# Note: Runs after attach_org_to_fk().

		# Add Copy Transforms constraints to the ORG bones to copy the IK bones.
		# Put driver on the influence to be able to disable IK.

		for org_bone in self.org_chain:
			ik_bone = self.get_bone_info(org_bone.name.replace("ORG", "IK"))
			copy_trans = org_bone.add_constraint('COPY_TRANSFORMS'
				,space		  = 'WORLD'
				,subtarget	  = ik_bone.name
				,name		  = "Copy Transforms IK"
			)

			copy_trans.drivers.append({
				'prop' : 'influence',
				'variables' : [
					(self.properties_bone.name, self.ikfk_name)
				]
			})

	def setup_ik_parent_switches(self, ik_ctrl: BoneInfo = None):
		if not ik_ctrl:
			ik_ctrl = self.ik_mstr

		if len(self.get_parent_candidates({}, exclude_self=True)) == 0:
			# If this rig has no parent candidates, there's nothing to be done here.
			return

		ik_parents_prop_name = "ik_parents_" + self.limb_name_props
		# Rig the IK control's parent switcher.
		parent_names = self.rig_child(ik_ctrl, self.properties_bone, ik_parents_prop_name)
		if len(parent_names) > 1:
			bones = [ik_ctrl.name]
			if self.params.CR_ik_chain_use_pole:
				bones.append(self.pole_ctrl.name)
			else:
				bones.append(self.ik_chain[0].name)
			info = {
				"prop_bone" : self.properties_bone,
				"prop_id" : ik_parents_prop_name,
				"texts" : parent_names,

				"operator" : "pose.cloudrig_switch_parent_bake",
				"icon" : "COLLAPSEMENU",
				"parent_names" : parent_names,	# TODO: I think this is unused now.
				"bones" : bones,
				}
			self.add_ui_data("ik_parents", self.category, self.limb_ui_name, info, default=0, max=len(parent_names)-1)

		### IK Pole Follow
		if self.params.CR_ik_chain_use_pole:
			self.setup_ik_pole_parent_switch(ik_parents_prop_name)

	def setup_ik_pole_parent_switch(self, ik_parents_prop_name: str):
		# Rig the IK Pole control's parent switcher.
		self.rig_child(self.pole_ctrl, self.properties_bone, ik_parents_prop_name, force_setup=True)

		# Add option to the UI.
		ik_pole_follow_name = "ik_pole_follow_" + self.limb_name_props
		info = {
			"prop_bone" : self.properties_bone,
			"prop_id"	: ik_pole_follow_name,

			"operator" : "pose.cloudrig_snap_bake",
			"bones" : [self.pole_ctrl.name],
			"select_bones" : True
		}
		self.add_ui_data("ik_pole_follows", self.category, self.limb_ui_name, info, default=0.0)

		# TODO This will fail when the IK chain is at the rig's root and therefore only has one parent and no parent switching setup and no armature constraint!
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
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "IK Controls", preset=2, default_layers=[cls.default_layers('IK_MAIN')])
		cls.define_bone_set(params, "IK Extra Controls", preset=2, default_layers=[cls.default_layers('IK_SECOND')])
		cls.define_bone_set(params, "IK Mechanism", default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_ik_chain_show_settings = BoolProperty(
			name		 = "IK Settings"
			,description = "Reveal settings for the cloud_ik_chain rig type"
		)
		params.CR_ik_chain_at_tip = BoolProperty(	# TODO: implement this.
			name		 = "At Tail"
			,description = "Put the IK control at the tail of the chain, rather than the head of the last bone"
			,default	 = False
		)
		params.CR_ik_chain_world_aligned = BoolProperty(
			 name		 = "World Aligned Control"
			,description = "Ankle/Wrist IK/FK controls are aligned with world axes"
			,default	 = True
		)
		params.CR_ik_chain_use_pole = BoolProperty(
			name 		 = "Use Pole Target"
			,description = "If disabled, you can control the rotation of the IK chain by simply rotating its first bone, rather than with an IK pole control"
			,default	 = True
		)

		super().add_parameters(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_ik_chain_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_ik_chain_use_pole")
		# cls.draw_prop(layout, params, "CR_ik_chain_at_tip")
		cls.draw_prop(layout, params, "CR_ik_chain_world_aligned")

		op = layout.operator('object.cloudrig_flatten_bones')
		op.use_selected = False
		op.start_bone = context.active_pose_bone.name
		op.chain_length = len(get_bone_chain(context.object, context.active_pose_bone) ) - 1
		op.skip_popup = True

		return layout

	##############################
	# Overlay
	@classmethod
	def draw_overlay(cls, context, buffer) -> list((Vector, Vector)):
		active_pb = context.active_pose_bone
		last_pb = cls.get_rigify_chain(active_pb)[-1]

		pole_angle, pole_vector, pole_location = cls.calculate_ik_info_static(active_pb, last_pb)

		buffer.draw_line_3d(active_pb.tail, pole_location)

class Rig(CloudIKChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)