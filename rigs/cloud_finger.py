from bpy.props import BoolProperty
from .cloud_ik_chain import CloudIKChainRig
from math import radians

class CloudFingerRig(CloudIKChainRig):
	"""An IK chain tailored for fingers. The finger bending axis should be +X."""

	forced_params = {
		'CR_ik_chain_at_tip' : True,
		'CR_chain_tip_control' : True,
	}

	def initialize(self):
		super().initialize()

	def add_ui_data(self, panel_name, row_name, info, label_name="", entry_name="", **custom_prop_dict):
		panel_name = "Finger IK"
		if label_name == "IK Pole Follow":
			custom_prop_dict['default'] = 1.0
		elif label_name == "FK/IK Switch" and self.params.CR_finger_use_bone_ik_switcher:
			# Don't add IK/FK switch to UI if we're using a control as the switcher.
			label_name = 'NODRAW'

		super().add_ui_data(panel_name, row_name, info
			,label_name = label_name
			,entry_name = entry_name
			,parent_id = 'CLOUDRIG_PT_custom_ik'
			,**custom_prop_dict
		)

	def setup_ik_pole_parent_switch(self, ik_pole, ik_mstr):
		# We don't want IK pole parent switching for finger rigs.
		pass

	def world_align_last_fk(self):
		# Don't world align last FK, only IK.
		pass

	def create_bone_infos(self):
		super().create_bone_infos()
		last_org = self.bones_org[-(1+self.params.CR_ik_chain_at_tip)] # TODO: Tip bone shouldn't create an extra ORG bone, name it something else, put it in IK mechanism instead.

		if self.params.CR_finger_use_bone_ik_switcher:
			self.create_ik_switcher_control(last_org)

		if self.params.CR_ik_chain_use_pole:
			# Parent the pole target to the stretch bone
			self.pole_ctrl.parent = self.stretch_bone
	
		self.create_x_rotation_setup(last_org)

	def create_ik_switcher_control(self, last_org):
		"""Create a control to drive IK/FK switching."""
		toggle_ctrl = self.bone_sets['IK Controls'].new(
			name		  = self.base_bone.replace("ORG-", "IK-SW-")
			,source		  = self.bone_sets['FK Controls'][-1]
			,custom_shape = self.ensure_widget('Arrow_Two-way')
			,parent		  = self.bone_sets['FK Controls'][-1]
		)
		self.lock_transforms(toggle_ctrl, loc=[True, False, True])
		toggle_ctrl.add_constraint('LIMIT_LOCATION'
			,use_min_y = True
			,use_max_y = True
			,max_y = toggle_ctrl.length
		)

		# Make it display nicely
		toggle_ctrl.custom_shape_translation = self.pole_vector.normalized() * -toggle_ctrl.length / 2
		toggle_ctrl.custom_shape_rotation_euler.y -= radians(90)
		toggle_dsp = self.create_dsp_bone(toggle_ctrl)
		toggle_dsp.parent = last_org
		toggle_dsp.add_constraint('COPY_LOCATION', subtarget=toggle_ctrl.name)

		# Hook up the IK/FK switch property to the control with a driver
		self.properties_bone.drivers.append({
			'prop' : f'["{self.ikfk_name}"]',
			'expression' : f'var / {toggle_ctrl.length}',
			'variables' : {
				'var' : {
					'type' : 'TRANSFORMS',
					'targets' : [{
						'bone_target' : toggle_ctrl.name
						,'transform_type' : 'LOC_Y'
						,'transform_space' : 'LOCAL_SPACE'
					}]
				}
			}
		})

	def create_x_rotation_setup(self, last_org):
		"""Create a helper for X rotation."""
		x_rot_helper = self.bone_sets['IK Mechanism'].new(
			name		= last_org.name.replace("ORG", "XROT")
			,source		= self.ik_mstr
			,parent		= last_org
		)
		copyrot = x_rot_helper.add_constraint('COPY_ROTATION'
			,name = "Copy X Rotation"
			,subtarget = self.ik_mstr.name
			,use_xyz = [True, False, False]
		)
		ik_driver = {
			'prop' : 'influence'
			,'variables' : [
				(self.properties_bone.name, self.ikfk_name)
			]
		}
		copyrot.drivers.append(ik_driver.copy())

		# Counter-rotate 2nd to last main STR bone
		counter_rot = self.main_str_bones[-3].add_constraint('COPY_ROTATION' # TODO: Why is this on index -3 instead of -2??
			,name = "Counter X Rotation"
			,subtarget = self.ik_mstr.name
			,use_xyz = [True, False, False]
			,invert_xyz = [True, False, False]
			,influence = 0.5
		)
		counter_rot.drivers.append(ik_driver.copy())

		# Parent stretch helper of last main STR bone (including tip control if it exists)
		for main_str_bone in self.main_str_bones[-(2+self.params.CR_ik_chain_at_tip):]:
			main_str_bone.stretch_helper.parent = x_rot_helper

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		params.CR_finger_use_bone_ik_switcher = BoolProperty(
			 name		 = "Create IK Switch Control"
			,description = "Instead of controlling IK/FK switching of this finger from the rig UI, create a control that can be moved to switch to IK mode"
			,default	 = True
		)

		super().add_parameters(params)


	@classmethod
	def draw_control_params(cls, layout, context, params):
		super().draw_control_params(layout, context, params)

		layout.separator()
		cls.draw_control_label(layout, "Finger")

		cls.draw_prop(layout, params, 'CR_finger_use_bone_ik_switcher')
class Rig(CloudFingerRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)