from typing import List

import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty
from mathutils import Vector
from mathutils.geometry import intersect_point_line
from math import radians as rad
from math import pi, pow
from copy import deepcopy

from rigify.base_rig import stage

from .cloud_ik_chain import CloudIKChainRig
from ..bone import BoneInfo
from ..utils.maths import flat

class CloudLimbRig(CloudIKChainRig):
	"""IK chain with extra features such as Auto-Rubberhose for a simple limb like an arm."""

	forced_params = {
		'CR_fk_chain_root' : True
		,'CR_chain_sharp' : True
	}

	required_chain_length = 3

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""

		if not self.params.CR_chain_smooth_spline:
			self.params.CR_limb_auto_hose = False

		# UI Strings and Custom Property names
		self.limb_name = "Arm"
		if self.params.CR_fk_chain_use_limb_name:
			self.limb_name = self.params.CR_fk_chain_limb_name

		self.limb_ui_name = self.side_prefix + " " + self.limb_name

		# IK values
		self.ik_pole_direction = 1
	
		self.check_correct_chain_length()

		self.category = "arms"
		if self.params.CR_fk_chain_use_category_name:
			self.category = self.params.CR_fk_chain_category_name

	def check_correct_chain_length(self):
		req_len = type(self).required_chain_length
		if len(self.bones.org.main) != req_len:
			self.raise_error(f"Chain must be exactly {req_len} connected bones.")

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.ik_double_ctrls = self.ensure_bone_set("IK Child Controls")

	def prepare_bones(self):
		super().prepare_bones()
		self.tweak_str_limb()
		segments = self.params.CR_chain_segments
		if self.params.CR_limb_auto_hose and segments > 1:
			upper = self.str_chain[1:segments]
			lower = self.str_chain[segments+1:segments*2]
			self.setup_rubber_hose(self.org_chain[1], upper, lower)

	##############################
	# Override some inherited functionality

	def determine_segments(self, org_bone):
		"""Overrides function from cloud_chain."""
		segments, bbone_density = super().determine_segments(org_bone)

		if org_bone == self.org_chain[-1]:
			# Force strictly 1 segment on the wrist.
			return 1, bbone_density
		elif org_bone == self.org_chain[-1] and not self.params.CR_chain_tip_control:
			return 1, 1
		else:
			return segments, bbone_density

	def make_ik_setup(self):
		"""Override."""
		super().make_ik_setup()

		# Parent control
		if self.params.CR_limb_double_ik:
			old_name = self.ik_mstr.name
			self.ik_mstr.name = self.naming.add_prefix(self.ik_mstr, "C")
			double_control = self.create_parent_bone(self.ik_mstr, self.ik_double_ctrls)
			double_control.name = old_name
			double_control.bone_group = "IK Child Controls"
			double_control.set_layers(self.ik_ctrls_secondary.layers, additive=True)

		# Counter-Rotate setup for the first section of STR bones.
		for i in range(0, self.params.CR_chain_segments):
			factor_unit = 0.9 / self.params.CR_chain_segments
			factor = 0.9 - factor_unit * i
			self.add_counterrotate_constraint(self.str_chain[i], self.org_chain[0], factor)

	def create_ik_master(self, bone_set, source_bone, bone_name="", shape_name=""):
		"""Override."""
		if shape_name=="":
			shape_name="Hand_IK"
		ik_master = super().create_ik_master(bone_set, source_bone, bone_name, shape_name)
		ik_master.custom_shape_scale = 0.8
		
		return ik_master

	def make_fk_chain(self):
		"""Override."""
		super().make_fk_chain()

		elbow_knee = self.org_chain[1].fk_bone
		elbow_knee.lock_rotation[1] = elbow_knee.lock_rotation[2] = self.params.CR_limb_lock_yz

	def setup_ik_parent_switches(self, 
			ik_parents_identifiers: List[str], 
			ik_ctrl: BoneInfo=None
		):
		"""Override."""
		ik_ctrl = self.ik_mstr
		if self.params.CR_limb_double_ik:
			ik_ctrl = ik_ctrl.parent

		super().setup_ik_parent_switches(ik_parents_identifiers, ik_ctrl)


	def create_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
		"""Override."""
		ui_data = super().create_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

		if self.params.CR_limb_double_ik:
			ui_data['hide_off'].append(ik_mstr.parent.name)
			map_on = {}
			# Need to awkwardly insert IK master parent->last FK bone switching BEFORE IK master parent, 
			# because in this dictionary order matters.
			for mapping in ui_data['map_on']:
				if mapping[0] == ik_mstr.name:
					map_on.append( (ik_mstr.parent.name, fk_chain[-1].name) )
				map_on.append( mapping )
			ui_data['map_on'] = map_on
		return ui_data

	##############################
	# End of overrides

	def tweak_str_limb(self):
		# We want to make some changes to the STR chain to make it behave more limb-like.

		# Disable first Copy Rotation constraint on the upperarm
		# TODO: Why did we do this?
		for b in self.main_str_bones[0].sub_bones:
			str_h_bone = b.parent
			str_h_bone.constraint_infos[2].mute = True

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

	def setup_rubber_hose(self, org_elbow: BoneInfo, str_upper: List[BoneInfo], str_lower: List[BoneInfo]):
		""" Add translating Transformation constraints to str_upper and 
			str_lower controls, driven by org_elbow. (Also meant for legs)
		"""

		# Create UI property
		prop_name = "auto_rubber_hose_" + self.limb_name_props
		info = {
			"prop_bone"			: self.properties_bone,
			"prop_id" 			: prop_name,
		}

		control_bone = None
		if self.params.CR_limb_auto_hose_control:
			# Create control bone
			control_bone = self.make_rubber_hose_control()
			self.properties_bone.custom_props[prop_name] = {'default' : 0.0}
			self.properties_bone.drivers.append({
				'prop' : f'["{prop_name}"]'
				,'expression' : "var-1"
				,'variables' : [
					{
						'type' : 'TRANSFORMS'
						,'targets' : [{
							'bone_target' : control_bone.name
							,'transform_space' : 'LOCAL_SPACE'
							,'transform_type' : 'SCALE_Y'
						}]
					}
				]
			})
		else:
			self.add_ui_data("auto_rubber_hose", self.category, self.limb_ui_name, info)

		for i, str_list in enumerate([str_upper, str_lower]):
			org_bone = self.org_chain[i]
			for str_bone in str_list:
				offset = org_bone.length / 2.5

				# Inverse of distance from center divided by half of bone length
				# This results in 1.0 at the center of the bone and 0.0 at the head or tail of the bone.
				distance_to_org_center = (str_bone.head - org_bone.center).length
				centeredness = 1 - (distance_to_org_center / (org_bone.length/2))

				total_offset = offset * pow(centeredness, 0.5)

				trans_con = str_bone.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose)"
					,subtarget = org_elbow.name
					,map_from = 'ROTATION'
					,map_to_x_from = 'Z'
					,map_to_z_from = 'X'
				)

				# Influence driver
				trans_con.drivers.append({
					'prop' : 'influence'
					,'variables' : [
						(self.properties_bone.name, prop_name),
					]
				})

				# Offset drivers
				driver_to_min_x = {
					'prop' : 'to_min_x'
					,'expression' : f"(var/pi) * {total_offset}"
					,'variables' : [
						{
							'type' : 'TRANSFORMS'
							,'targets' : [{
								'bone_target' : org_elbow.name
								,'transform_space' : 'LOCAL_SPACE'
								,'transform_type' : 'ROT_Z'
							}]
						}
					]
				}

				trans_con.drivers.append(driver_to_min_x)

				driver_to_min_z = deepcopy(driver_to_min_x)
				driver_to_min_z['prop'] = 'to_min_z'
				driver_to_min_z['expression'] += " * -1"
				driver_to_min_z['variables'][0]['targets'][0]['transform_type'] = 'ROT_X'
				trans_con.drivers.append(driver_to_min_z)
			
			# Scale the main STR bone on local Y to get a smooth curve 
			# in spite of Sharp Sections parameter being enabled.
			if i==1:
				main_str = str_list[0].prev
				trans_con = main_str.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose)"
					,subtarget = org_elbow.name
					,map_to = 'SCALE'
				)

				# Influence driver
				trans_con.drivers.append({
					'prop' : 'influence'
					,'variables' : [
						(self.properties_bone.name, prop_name),
					]
				})

				# Offset driver
				trans_con.drivers.append({
					'prop' : 'to_min_y_scale'
					,'expression' : "1 + pow( (abs(rot_x) + abs(rot_z)) / pi, 0.5 ) * 1.5"
					,'variables' : {
						'rot_x' : {
							'type' : 'TRANSFORMS'
							,'targets' : [{
								'bone_target' : org_elbow.name
								,'transform_space' : 'LOCAL_SPACE'
								,'transform_type' : 'ROT_X'
							}]
						}
						,'rot_z' : {
							'type' : 'TRANSFORMS'
							,'targets' : [{
								'bone_target' : org_elbow.name
								,'transform_space' : 'LOCAL_SPACE'
								,'transform_type' : 'ROT_Z'
							}]
						}
					}
				})

	def make_rubber_hose_control(self) -> BoneInfo:
		org_elbow = self.org_chain[1]
		
		control_bone = self.new_bonei(self.fk_extras
			,name = org_elbow.name.replace("ORG", "AutoRubberHose")
			,source = org_elbow
			,parent = org_elbow
			,custom_shape = self.ensure_widget('Double_Arrow')
		)
		# Assign to main FK layer and both IK layers also
		control_bone.set_layers(self.fk_chain.layers, additive=True)
		control_bone.set_layers(self.ik_ctrls.layers, additive=True)
		control_bone.set_layers(self.fk_chain.layers, additive=True)

		# Shift it towards the IK pole or where it would be.
		new_loc = control_bone.head + self.pole_vector.normalized() * org_elbow.bbone_width*self.scale * 6
		control_bone.head = new_loc
		control_bone.vector = org_elbow.vector * 0.3
		control_bone.custom_shape_scale = 0.4
		control_bone.roll_type = 'ACTIVE'
		control_bone.roll_bone = org_elbow
		control_bone.roll = rad(90)
		self.lock_transforms(control_bone, scale=[True, False, True])
		control_bone.add_constraint('LIMIT_SCALE'
			,use_max_y = True
			,max_y = 2
			,use_min_y = True
			,min_y = 1
		)

		dsp_bone = self.create_dsp_bone(control_bone)
		dsp_bone.parent = self.main_str_bones[1].tangent_helper	# Ugly hardcoding...
		dsp_bone.inherit_scale = 'AVERAGE'
		dsp_bone.add_constraint('COPY_SCALE', subtarget=control_bone.name, )

		return control_bone

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "IK Child Controls", preset=8, default_layers=[cls.default_layers('IK_MAIN')])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_limb_show_settings = BoolProperty(
			name		 = "Limb Settings"
			,description = "Reveal settings for the cloud_limb rig type"
		)
		params.CR_limb_auto_hose = BoolProperty(
			name		 = "Auto Rubber Hose"
			,description = "Set up an Auto Rubber Hose setting which when enabled will attempt to automatically add curvature to limbs as they are bent. Chain Segments parameter must be greater than 1 and Smooth Spline must be enabled"
			,default	 = False
		)
		params.CR_limb_auto_hose_control = BoolProperty(
			name		 = "Create Control Bone"
			,description = "Instead of controlling the Auto Rubber Hose property from the rig UI, create a control bone on the FK Extras layer"
			,default	 = False
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

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_limb_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_limb_double_ik")
		cls.draw_prop(layout, params, "CR_limb_lock_yz", text=f"Lock 2nd FK Y/Z")
		row = cls.draw_prop(layout, params, 'CR_limb_auto_hose')
		row.enabled = params.CR_chain_segments > 1 and params.CR_chain_smooth_spline
		if row.enabled and params.CR_limb_auto_hose:
			split = layout.split(factor=0.05)
			split.row()
			cls.draw_prop(split.row(), params, 'CR_limb_auto_hose_control')

		return layout

	##############################
	# Overlay
	@classmethod
	def draw_overlay(cls, context, buffer) -> list((Vector, Vector)):
		active_pb = context.active_pose_bone
		rig_chain = cls.find_rig_of_bone(active_pb)

		pole_angle, pole_vector, pole_location = cls.calculate_ik_info_static(rig_chain[0], rig_chain[1])

		buffer.draw_line_3d(rig_chain[0].tail, pole_location)

class Rig(CloudLimbRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)