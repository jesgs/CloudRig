from bpy.props import BoolProperty
from .cloud_face_chain import CloudFaceChainRig
from .cloud_aim import CloudAimRig

from ..utils.maths import project_vector_on_plane

class CloudEyelidRig(CloudFaceChainRig):
	"""Extends cloud_face_chain with eyelid functionality.""" #TODO: better description

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()

		self.bone_sets['Original Bones'][0].parent = self.rigify_parent.org_chain[0].parent

		### Following code is only run ONCE by the LAST face_chain_rig.
		if not self.is_last_chain_rig:
			return

		for rig in self.chain_rigs:
			if not rig.params.CR_face_chain_merge: continue
			if not type(rig) == type(self): continue
			rig.make_sticky_eyelid()

	def make_sticky_eyelid(self):
		"""Create ROT helper bones between the aim bone's base and the main STR controls of the eyelid"""

		# Parent rig must be a cloud_aim type rig!
		parent_rig = self.rigify_parent
		if not isinstance(parent_rig, CloudAimRig):
			self.raise_error(f"Eyelid rig's parent MUST be a cloud_aim rig type, not {type(parent_rig)}!")

		sticky_prop_name = "sticky_eyelids_" + parent_rig.params.CR_aim_group.lower().replace(" ", "_")
		self.create_sticky_property(parent_rig, sticky_prop_name)

		# TODO: Maybe cloud_face_chain should to a better job of keeping track of this thing.
		main_controls = []
		for str_ctr in self.main_str_bones:
			if hasattr(str_ctr, 'merged_control'):
				str_ctr = str_ctr.merged_control
			if str_ctr not in main_controls:
				main_controls.append(str_ctr)

		for str_ctr in main_controls:
			eye_bone = parent_rig.org_chain[0]
			rot_name = self.naming.make_name(["ROT"], *self.naming.slice_name(str_ctr)[1:])
			rot_ctr = self.generator.find_bone_info(rot_name)
			if rot_ctr:
				continue

			rot_ctr = self.bone_sets['Eyelid Mechanism'].new(
				name = rot_name
				,source = eye_bone
				,tail = str_ctr.head.copy()
				,parent = parent_rig.org_chain[0].parent
				,roll_type = 'ACTIVE'
				,roll_bone = eye_bone
				,roll = 0
			)
			copyrot_x = rot_ctr.add_constraint('COPY_ROTATION'
				,name = 'Copy Rotation X'
				,subtarget = eye_bone.name
				,use_xyz = [True, False, False]
			)
			eyelid_width = (self.bone_sets['Original Bones'][0].head - self.bone_sets['Original Bones'][-1].tail).length * 0.55

			# Reject the ROT bone tail onto the eye bone Z axis
			rejection_z = project_vector_on_plane(rot_ctr.vector, parent_rig.meta_base_bone.z_axis)
			# Take the distance between that and the base bone's vector
			# to determine the constraints' influence.
			distance = (eye_bone.vector - rejection_z).length
			sticky_strength = 1 - distance / eyelid_width
			copyrot_x.drivers.append({
				'prop' : 'influence'
				,'expression' : f"var*{sticky_strength}"
				,'variables' : [(parent_rig.properties_bone.name, sticky_prop_name)]
			})

			copyrot_z = rot_ctr.add_constraint('COPY_ROTATION'
				,name = 'Copy Rotation Z'
				,subtarget = eye_bone.name
				,use_xyz = [False, False, True]
			)

			copyrot_z.drivers.append({
				'prop' : 'influence'
				,'expression' : f"var*{sticky_strength*0.5}"
				,'variables' : [(self.properties_bone.name, sticky_prop_name)]
			})
			str_ctr.parent = rot_ctr

	def create_sticky_property(self, eye_rig: CloudAimRig, sticky_prop_name):
		info = {
			'prop_bone' : eye_rig.properties_bone,
			'prop_id' : sticky_prop_name
		}
		self.add_ui_data('face_settings', eye_rig.params.CR_aim_group, "Sticky", info, default=0.1)

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Eyelid Mechanism', default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_eyelid_show_settings = BoolProperty(
			name		 = "Eyelid Settings"
			,description = "Reveal settings for the cloud_eyelid rig type"
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_eyelid_show_settings'): return layout

		layout.label(text="Simply make sure this rig is parented to a cloud_aim rig.")

		return layout

class Rig(CloudEyelidRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)