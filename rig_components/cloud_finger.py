from typing import List
from ..rig_component_features.bone import BoneInfo
from bpy.props import BoolProperty
from .cloud_ik_chain import Component_Chain_IKFK
from math import radians

class Component_Finger(Component_Chain_IKFK):
	"""An IK chain tailored for fingers. The finger bending axis should be +X."""
	ui_name = "Chain: Finger"
	forced_params = {
		'ik_chain.at_tip' : True,
		'chain.tip_control' : True,
		'fk_chain.root' : True,
		'fk_chain.double_first' : False,
	}

	required_chain_length = 3

	def initialize(self):
		super().initialize()

		self.full_length_ik_name = "finger_ik_full_" + self.limb_name_props

	def setup_ik_pole_follow_slider(self, ik_pole, ik_mstr, stretch_bone):
		"""Overwrite cloud_ik_chain."""
		ik_pole.parent = ik_mstr
		pass

	def add_ui_data(self, panel_name, row_name, info, label_name="", entry_name="", **custom_prop_dict):
		if panel_name == "FK/IK Switch":
			custom_prop_dict['default'] = 0.0

		panel_name = "Fingers"
		if label_name == "IK Pole Follow":
			return

		super().add_ui_data(panel_name, row_name, info
			,label_name = label_name
			,entry_name = entry_name
			,parent_id = 'CLOUDRIG_PT_custom_ik'
			,**custom_prop_dict
		)

	def setup_ik_pole_parent_switch(self, ik_pole, ik_mstr):
		# We don't want IK pole parent switching for finger components.
		pass

	def world_align_last_fk(self):
		# Don't world align last FK, only IK.
		pass

	def create_bone_infos(self, context):
		super().create_bone_infos(context)
		last_org = self.bones_org[-(1+self.params.ik_chain.at_tip)] # TODO: Tip bone shouldn't create an extra ORG bone, name it something else, put it in IK mechanism instead.

		self.ik_mstr.parent = self.root_bone

		if self.params.ik_chain.use_pole:
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
			,parent		 = self.ik_tgt_bone
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
			pole_target		= self.target_rig if pole_target else None,
			pole_subtarget	= pole_target.name if pole_target else "",
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

	def create_fkik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
		"""Overrides cloud_ik_chain"""
		ui_data = super().create_fkik_switch_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

		# It's quite strange to be creating an extra helper bone in this function,
		# but we need it for correct snapping in this case.
		tip_str = self.main_str_bones[-1]
		snap_helper = self.bone_sets['Mechanism Bones'].new(
			source = tip_str
			,parent = tip_str
			,name = "SNAP-"+ik_mstr.name
			,use_inherit_rotation = False
		)

		map_on = [
			(ik_mstr.name, snap_helper.name)
		]

		ui_data["map_on"] = map_on
		return ui_data

class RigComponent(Component_Finger):
	pass
