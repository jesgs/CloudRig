from typing import List
from ..rig_features.bone import BoneInfo
from bpy.props import BoolProperty
from .cloud_ik_chain import CloudIKChainRig
from math import radians

"""TODO:
- Figure out if it would be possible to avoid snapping when IK stretching is engaged. 
- When IK Stretch is disabled, there's still an uneven stretching.
"""

class CloudFingerRig(CloudIKChainRig):
	"""An IK chain tailored for fingers. The finger bending axis should be +X."""

	forced_params = {
		'CR_ik_chain_at_tip' : True,
		'CR_chain_tip_control' : True,
		'CR_fk_chain_root' : True,
		'CR_fk_chain_double_first' : False,

	}

	required_chain_length = 3

	def initialize(self):
		super().initialize()

		self.full_length_ik_name = "finger_ik_full_" + self.limb_name_props

	def add_ui_data(self, panel_name, row_name, info, label_name="", entry_name="", **custom_prop_dict):
		if panel_name == "FK/IK Switch":
			custom_prop_dict['default'] = 0.0

		panel_name = "Finger IK"
		if label_name == "IK Pole Follow":
			return

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

		self.ik_mstr.parent = self.root_bone

		if self.params.CR_ik_chain_use_pole:
			# Parent the pole target to the stretch bone
			self.pole_ctrl.parent = self.stretch_bone
		
		self.create_two_bone_ik_chain(self.bones_org[:-1], self.ik_chain, self.ik_mstr, self.pole_ctrl)
	
	def create_two_bone_ik_chain(self, 
			org_chain: List[BoneInfo]
			,ik_chain: List[BoneInfo]
			,ik_mstr: BoneInfo
			,pole_target: BoneInfo
			,ik_pole_direction = 0
		) -> List[BoneInfo]:
		"""We create an additional IK chain (besides what's inherited from cloud_ik_chain)
		for the 2-length IK behaviour.
		"""

		# We need a bone that copies only the location of the IK master.
		last_org = org_chain[-1]

		ik2_chain = []
		for i, org_bone in enumerate(org_chain):
			ik2_bone = self.bone_sets['IK Mechanism'].new(
				name		 = org_bone.name.replace("ORG", "IK2")
				,source		 = org_bone
				,parent		 = ik2_chain[-1] if ik2_chain else self.root_bone
			)
			ik2_chain.append(ik2_bone)
			# Change ORG bone copy transform targets from IK to IK2.
			org_bone.constraint_infos[-1].subtarget = ik2_bone

		ik2_dt = self.bone_sets['IK Mechanism'].new(
			name		 = org_bone.name.replace("ORG", "IK2-DT")
			,source		 = self.ik_mstr
			,parent		 = self.ik_mstr
		)
		dt_con = ik2_dt.add_constraint('DAMPED_TRACK'
			,subtarget	= ik_chain[-2]
			,track_axis	= 'TRACK_NEGATIVE_Y'
		)

		ik2_rot = self.bone_sets['IK Mechanism'].new(
			name		 = org_bone.name.replace("ORG", "IK2-ROT")
			,source		 = self.ik_mstr
			,parent		 = ik2_dt
		)
		copyrot_con = ik2_rot.add_constraint('COPY_ROTATION'
			,subtarget = self.ik_mstr
		)

		last_ik2 = ik2_chain[-1]
		# Add the IK constraint to the previous bone, targetting this one.
		last_ik2.parent.add_constraint('IK',
			pole_target		= self.obj,
			pole_subtarget	= pole_target.name,
			pole_angle		= self.pole_angle,
			subtarget		= last_ik2,
			chain_count		= 2
		)
		last_ik2.parent = ik2_rot

		# Add UI data for switching between the two IK types
		info = {
			"prop_bone"			: self.properties_bone,
			"prop_id" 			: self.full_length_ik_name,
		}
		self.add_ui_data("IK", self.limb_name, info, label_name="Full IK", entry_name=self.limb_ui_name, default=1.0)

		# Add driver to switch between the two IK types
		driver = {
			'prop' : 'influence'
			,'expression' : "var"
			,'variables' : [
				(self.properties_bone.name, self.full_length_ik_name)
			]
		}
		copyrot_con.drivers.append(driver.copy())
		dt_con.drivers.append(driver)

		return ik2_chain

class Rig(CloudFingerRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)