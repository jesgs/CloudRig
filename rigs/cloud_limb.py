from typing import List
from ..rig_features.bone import BoneInfo

from bpy.props import BoolProperty, EnumProperty
from mathutils import Vector
from math import radians as rad
from math import pow
from copy import deepcopy

from .cloud_ik_chain import CloudIKChainRig

class CloudLimbRig(CloudIKChainRig):
	"""IK chain with extra features such as Auto-Rubberhose for a simple limb like an arm."""

	forced_params = {
		'CR_ik_chain_at_tip' : False
		,'CR_fk_chain_root' : True
		,'CR_chain_sharp' : True
	}

	required_chain_length = 3

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""

		if not self.params.CR_chain_smooth_spline:
			self.params.CR_limb_auto_hose = False

		# IK values
		self.ik_pole_direction = 1

		self.check_correct_chain_length()

	def check_correct_chain_length(self):
		req_len = type(self).required_chain_length
		if self.bone_count != req_len:
			self.raise_error(f"Chain must be exactly {req_len} connected bones.")

	def create_bone_infos(self):
		super().create_bone_infos()
		self.tweak_str_limb()
		segments = self.params.CR_chain_segments
		if self.params.CR_limb_auto_hose and segments > 1:
			upper = self.bone_sets['Stretch Controls'][1:segments]
			lower = self.bone_sets['Stretch Controls'][segments+1:segments*2]
			self.setup_rubber_hose(self.bones_org[1], upper, lower)

	##############################
	# Override some inherited functionality

	def generate_properties_bone(self) -> BoneInfo:
		"""Overrides cloud_base.
		Place the properties bone near the end of the limb, parented to the last ORG bone.
		"""
		properties_bone = super().generate_properties_bone()
		properties_bone.head = self.bones_org[-1].head.copy() + Vector((0, self.scale/1.5, 0))
		properties_bone.tail = properties_bone.head + Vector((0, 0, self.scale/2))
		properties_bone.parent = self.bones_org[-1]
		return properties_bone

	def determine_segments(self, org_bone):
		"""Overrides function from cloud_chain."""
		segments, bbone_density = super().determine_segments(org_bone)

		# Force strictly 1 segment on the toe.
		if org_bone == self.bones_org[-1]:
			if self.params.CR_chain_tip_control:
				return 1, bbone_density
			else:
				return 1, 1

		return segments, bbone_density

	def make_ik_setup(self):
		"""Override."""
		super().make_ik_setup()

		# Parent control
		if self.params.CR_limb_double_ik:
			old_name = self.ik_mstr.name
			self.ik_mstr.name = self.naming.add_prefix(self.ik_mstr, "C")
			double_control = self.create_parent_bone(self.ik_mstr, self.bone_sets['IK Child Controls'])
			double_control.name = old_name
			double_control.layers, self.ik_mstr.layers = self.ik_mstr.layers, double_control.layers

		# Counter-Rotate setup for the first section of STR bones.
		for i in range(0, self.params.CR_chain_segments):
			factor_unit = 0.9 / self.params.CR_chain_segments
			factor = 0.9 - factor_unit * i
			self.add_counterrotate_constraint(self.bone_sets['Stretch Controls'][i], self.bones_org[0], factor)

	def create_ik_master(self, bone_set, source_bone, bone_name="", shape_name=""):
		"""Override."""
		if shape_name=="":
			shape_name="Hyperbola"
		ik_master = super().create_ik_master(bone_set, source_bone, bone_name, shape_name)
		ik_master.custom_shape_scale = 0.8

		return ik_master

	def apply_parent_switching(self, parent_slots, *, 
			child_bone=None, prop_bone=None, prop_name="",
			panel_name="IK", row_name="", label_name="Parent Switching", entry_name=""
		):
		"""Overrides cloud_ik_chain."""

		if self.params.CR_limb_double_ik:
			child_bone = self.ik_mstr.parent

		super().apply_parent_switching(parent_slots, 
			child_bone = child_bone
			,prop_bone = prop_bone
			,prop_name = prop_name
			,panel_name = panel_name
			,row_name = row_name
			,label_name = label_name
			,entry_name = entry_name
		)

	def setup_ik_pole_parent_switch(self, ik_pole, ik_mstr):
		"""Overrides cloud_ik_chain."""
		if self.params.CR_limb_double_ik:
			ik_mstr = ik_mstr.parent
			# TODO: These checks for CR_limb_double_ik should be replaced with a @property.

		super().setup_ik_pole_parent_switch(ik_pole, ik_mstr)

	def create_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
		"""Override."""
		ui_data = super().create_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

		if self.params.CR_limb_double_ik:
			ui_data['hide_off'].append(ik_mstr.parent.name)
			map_on = []
			# Need to awkwardly insert IK master parent->last FK bone switching BEFORE IK master parent.
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
		if self.params.CR_chain_segments > 1:
			for b in self.main_str_bones[0].sub_bones:
				str_h_bone = b.parent
				str_h_bone.constraint_infos[2].mute = True

	def add_counterrotate_constraint(self, str_bone, org_bone, factor):
		str_bone.add_constraint('TRANSFORM'
			,name					= "Transformation (Counter-Rotate)"
			,subtarget				= org_bone.name
			,map_from				= 'ROTATION'
			,map_to					= 'ROTATION'
			,use_motion_extrapolate = True
			,from_min_y_rot			= -1
			,from_max_y_rot			= 1
			,to_min_y_rot			= factor
			,to_max_y_rot			= -factor
			,from_rotation_mode		= 'SWING_TWIST_Y'
			# TODO: This 0.5 influence doesn't seem correct while rigging Jay. (Should be 1.0) Odd that it wasn't noticable on any other character?
			,influence				= 0.5
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
			# Don't create a control bone, instead just add a slider in the UI.
			self.add_ui_data("Auto Rubber Hose", self.limb_name, info, entry_name=self.limb_ui_name)

		self.make_rubber_hose_constraints(org_elbow, str_upper, str_lower, prop_name)

	def make_rubber_hose_control(self) -> BoneInfo:
		org_elbow = self.bones_org[1]

		control_bone = self.bone_sets['FK Controls Extra'].new(
			name = org_elbow.name.replace("ORG", "AutoRubberHose")
			,source = org_elbow
			,parent = org_elbow
			,custom_shape = self.ensure_widget('Arrow_Two-way')
		)
		# Assign to main FK layer and both IK layers also
		control_bone.set_layers(self.bone_sets['FK Controls'].layers, additive=True)
		control_bone.set_layers(self.bone_sets['IK Controls'].layers, additive=True)
		control_bone.set_layers(self.bone_sets['FK Controls'].layers, additive=True)

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
		dsp_bone.add_constraint('ARMATURE'
			,use_deform_preserve_volume = True
			,targets = [
				{"subtarget" : self.bones_def[self.params.CR_chain_segments-1].name}
				,{"subtarget" : self.bones_def[self.params.CR_chain_segments].name}
			]
		)
		dsp_bone.add_constraint('COPY_SCALE', subtarget=control_bone.name)

		return control_bone

	def make_rubber_hose_constraints(self, org_elbow: BoneInfo, str_upper: List[BoneInfo], str_lower: List[BoneInfo], prop_name: str):
		# TODO: This function is too big!
		driver_influence = {
			'prop' : 'influence'
			,'expression' : 'var'
			,'variables' : [
				(self.properties_bone.name, prop_name),
			]
		}

		for i, str_list in enumerate([str_upper, str_lower]):
			org_bone = self.bones_org[i]
			for str_bone in str_list:
				offset = org_bone.length / 2.5

				# Inverse of distance from center divided by half of bone length
				# This results in 1.0 at the center of the bone and 0.0 at the head or tail of the bone.
				distance_to_org_center = (str_bone.head - org_bone.center).length
				centeredness = 1 - (distance_to_org_center / (org_bone.length/2))

				total_offset = offset * pow(centeredness, 0.5)

				trans_con = str_bone.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose STR)"
					,subtarget = org_elbow.name
					,map_from = 'ROTATION'
					,map_to_x_from = 'Z'
					,map_to_z_from = 'X'
				)

				# Influence driver
				driver = deepcopy(driver_influence)
				if self.params.CR_limb_auto_hose_type=='ELBOW_IN':
					# For the alternate auto hose type, the shifting just needs to be reduced by half.
					driver['expression'] += "/2"

				trans_con.drivers.append(driver)

				# Translation drivers
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
								,'rotation_mode' : 'SWING_TWIST_Y'
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
				# Scale constraint
				scale_con = main_str.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose Elbow Scale)"
					,subtarget = org_elbow.name
					,map_to = 'SCALE'
				)

				# Influence driver
				scale_con.drivers.append(deepcopy(driver_influence))

				# Scale driver
				scale_con.drivers.append({
					'prop' : 'to_min_y_scale'
					,'expression' : "1 + pow( (abs(rot_x) + abs(rot_z)) / pi, 0.5 ) * 1.5"
					,'variables' : {
						'rot_x' : {
							'type' : 'TRANSFORMS'
							,'targets' : [{
								'bone_target' : org_elbow.name
								,'transform_space' : 'LOCAL_SPACE'
								,'transform_type' : 'ROT_X'
								,'rotation_mode' : 'SWING_TWIST_Y'
							}]
						}
						,'rot_z' : {
							'type' : 'TRANSFORMS'
							,'targets' : [{
								'bone_target' : org_elbow.name
								,'transform_space' : 'LOCAL_SPACE'
								,'transform_type' : 'ROT_Z'
								,'rotation_mode' : 'SWING_TWIST_Y'
							}]
						}
					}
				})

				if not self.params.CR_limb_auto_hose_type=='ELBOW_IN':
					return

				### Additional constraints for alternate, "Long" rubberhose type
				# Translation constraint
				trans_con = main_str.add_constraint('TRANSFORM'
					,name = "Transformation (Rubber Hose Elbow Translate)"
					,subtarget = org_elbow.name
				)

				# Influence driver
				trans_con.drivers.append(deepcopy(driver_influence))

				# Translation drivers
				var_x = {
					'type' : 'TRANSFORMS'
					,'targets' : [{
						'bone_target' : org_elbow.name
						,'transform_space' : 'LOCAL_SPACE'
						,'transform_type' : 'ROT_X'
						,'rotation_mode' : 'SWING_TWIST_Y'
					}]
				}
				var_z = deepcopy(var_x)
				var_z['targets'][0]['transform_type'] = 'ROT_Z'
				driver_to_min_y = {
					'prop' : 'to_min_y'
					,'expression' : f"(abs(x + z)/pi) * {org_elbow.length/4}"
					,'variables' :
						{
							'x' : var_x,
							'z' : var_z,
						}
				}

				trans_con.drivers.append(driver_to_min_y)

				driver_to_min_z = deepcopy(driver_to_min_y)
				driver_to_min_z['prop'] = 'to_min_z'
				driver_to_min_z['expression'] = f"(x/pi) * {org_elbow.length/4}"
				trans_con.drivers.append(driver_to_min_z)

				driver_to_min_x = deepcopy(driver_to_min_y)
				driver_to_min_x['prop'] = 'to_min_x'
				driver_to_min_x['expression'] = f"(-z/pi) * {org_elbow.length/4}"
				trans_con.drivers.append(driver_to_min_x)

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'IK Child Controls', preset=8, default_layers=[cls.DEFAULT_LAYERS.IK_SECOND])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_limb_auto_hose = BoolProperty(
			name		 = "Rubber Hose"
			,description = "Set up an Auto Rubber Hose setting which when enabled will attempt to automatically add curvature to limbs as they are bent. Chain Segments parameter must be >1, Smooth Spline must be enabled and the chain's bone rolls must be similar"
			,default	 = False
		)
		params.CR_limb_auto_hose_control = BoolProperty(
			name		 = "With Control"
			,description = "Instead of controlling the Auto Rubber Hose property from the rig UI, create a control bone on the FK Extras layer"
			,default	 = False
		)
		params.CR_limb_auto_hose_type = EnumProperty(
			name		 = "Type"
			,description = "The rubber hosing effect can be achieved in different ways. This lets you pick which one you prefer"
			,items	 = [
				('MIDDLE_OUT', "Long", "Shift mid-limb STR bones away from the elbow bending direction. As a result, the limb becomes longer")
				,('ELBOW_IN', "Short", "Shift the elbow STR bone towards the elbow bending direction, and counter-shift the mid-limb STR bones so they stay roughly in place. As a result, the limb becomes shorter")
			]
		)

		params.CR_limb_double_ik = BoolProperty(
			 name		 = "Duplicate IK Master"
			,description = "The IK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose"
			,default	 = False
		)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)

		cls.draw_prop(layout, params, "CR_limb_double_ik")

		layout.separator()
		cls.draw_control_label(layout, "Limb")

		row = cls.draw_prop(layout, params, 'CR_limb_auto_hose')
		row.enabled = params.CR_chain_segments > 1 and params.CR_chain_smooth_spline
		if row.enabled and params.CR_limb_auto_hose:
			split = layout.split(factor=0.1)
			split.row()
			cls.draw_prop(split.row(), params, 'CR_limb_auto_hose_control')
			split = layout.split(factor=0.1)
			split.row()
			cls.draw_prop(split.row(), params, 'CR_limb_auto_hose_type', expand=True)

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