from bpy.props import BoolProperty
from .cloud_ik_chain import CloudIKChainRig
from math import radians

class CloudFingerRig(CloudIKChainRig):
	"""An IK chain tailored for fingers."""

	forced_params = {
		'CR_ik_chain_at_tip' : True,
	}

	def initialize(self):
		super().initialize()

	#HACK: To avoid spamming the Sprite Fright rig UI's with 10x3 more IK/FK sliders.
	# Need to think of a legit solution. Context-sensitive rig UI would solve it.
	def add_ui_data(self, ui_area, row_name, col_name, info, **custom_prop_dict):
		# Create custom property.
		prop_bone = info['prop_bone']
		prop_id = info['prop_id']
		if 'default' not in custom_prop_dict:
			custom_prop_dict['default'] = 0.0
		if prop_id.startswith("ik_pole_follow"):
			custom_prop_dict['default'] = 1.0
		prop_bone.custom_props[prop_id] = custom_prop_dict

	def setup_ik_pole_parent_switch(self, ik_pole, ik_mstr):
		# We don't want IK pole parent switching for finger rigs.
		pass

	def world_align_last_fk(self):
		# Don't world align last FK, only IK.
		pass

	def create_bone_infos(self):
		super().create_bone_infos()

		last_org = self.bones_org[-(1+self.params.CR_ik_chain_at_tip)] # TODO: Tip bone shouldn't create an extra ORG bone, name it something else, put it in IK mechanism instead.

		# Create a control to drive IK/FK switching
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
		toggle_ctrl.custom_shape_translation = self.pole_vector.normalized() * -toggle_ctrl.length/2	# TODO: This is only correct for 1/4 possible finger orientations. Either enforce that one or support all of them.
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

		# Parent the pole target to the stretch bone
		if self.params.CR_ik_chain_use_pole:
			self.pole_ctrl.parent = self.stretch_bone
			self.stretch_bone.add_constraint('COPY_ROTATION', 0
				,subtarget	= self.ik_mstr.name
				,use_xyz	= [False, True, False]
			)

		# Create a helper for X rotation
		x_rot_helper = self.bone_sets['IK Mechanism'].new(
			name		= last_org.name.replace("ORG", "XROT")
			,source		= last_org
			,parent		= last_org
			,head		= last_org.tail
			,tail		= last_org.head
		)

		# Parent stretch helper of last main STR bone
		for main_str_bone in self.main_str_bones[-(1+self.params.CR_ik_chain_at_tip):]:
			main_str_bone.stretch_helper.parent = x_rot_helper
		x_rot_helper.add_constraint('COPY_ROTATION'
			,subtarget = self.ik_mstr.name
			,use_xyz = [True, False, False]
			,invert_xyz = [True, False, False]
		)

	##############################
	# No parameters for this rig type.

class Rig(CloudFingerRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)