import bpy
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector

from .cloud_aim import CloudAimRig
from .cloud_chain import CloudChainRig

from ..utils.maths import project_vector_on_plane

class CloudEyeRig(CloudAimRig):
	"""Create aim target controls with optional eyelid-like interaction."""

	def initialize(self):
		super().initialize()

		# The aim rig has to be executed AFTER both of the eyelid rigs.
		for lid in [self.params.CR_eye_lower_eyelid, self.params.CR_eye_upper_eyelid]:
			for rig_elem in self.generator.rig_list:
				if rig_elem.base_bone == "ORG-"+lid:
					if not hasattr(rig_elem, 'chain_length'):
						self.raise_error(f"cloud_eye rig must be parented to the eyelid rig ({self.naming.strip_org(rig_elem.base_bone)}) to make sure it's executed in the correct order.")

	def ensure_bone_sets(self):
		super().ensure_bone_sets()

	def prepare_bones(self):
		super().prepare_bones()

		if self.params.CR_eye_lower_eyelid != "":
			self.make_sticky_eyelid(self.params.CR_eye_lower_eyelid)
		if self.params.CR_eye_upper_eyelid != "":
			self.make_sticky_eyelid(self.params.CR_eye_upper_eyelid)

	def make_sticky_eyelid(self, eyelid_bone_name):
		"""Create bones between the base bone and the main STR controls of the eyelid"""

		# Sanity checks
		eyelid_rig = None
		for rig in self.generator.rig_list:
			if self.naming.strip_org(rig.base_bone) == eyelid_bone_name:
				eyelid_rig = rig
		if not eyelid_rig:
			self.raise_error(f"Error: eyelid rig with base bone {eyelid_bone_name} not found.")
		if not isinstance(eyelid_rig, CloudChainRig):
			self.raise_error(f"Error: Eyelid rig must be a CloudChainRig type.")

		sticky_prop_name = "sticky_eyelids_" + self.params.CR_aim_group.lower().replace(" ", "_")
		info = {
			'prop_bone' : self.properties_bone,
			'prop_id' : sticky_prop_name
		}
		self.add_ui_data('face_settings', self.params.CR_aim_group, "Sticky", info, default=0.1)

		eyelid_main_controls = []
		for str_ctr in eyelid_rig.main_str_bones:
			if hasattr(str_ctr, 'merged_control'):
				str_ctr = str_ctr.merged_control
			if str_ctr not in eyelid_main_controls:
				eyelid_main_controls.append(str_ctr)

		if self.params.CR_aim_root:
			self.ensure_eyelid_root(eyelid_main_controls)

		for str_ctr in eyelid_main_controls:
			base_bone = self.org_chain[0]
			rot_name = self.naming.make_name(["ROT"], *self.naming.slice_name(str_ctr)[1:])
			rot_ctr = self.generator.find_bone_info(rot_name)
			if not rot_ctr:
				rot_ctr = self.aim_mch.new(
					name = rot_name
					,source = base_bone
					,tail = str_ctr.head.copy()
					,parent = str_ctr.parent
					,roll_type = 'ACTIVE'
					,roll_bone = base_bone
				)
				copyrot_x = rot_ctr.add_constraint('COPY_ROTATION'
					,name='Copy Rotation X'
					,subtarget=base_bone.name
					,use_xyz = [True, False, False]
				)
				eye_width = (eyelid_rig.org_chain[0].head - eyelid_rig.org_chain[-1].tail).length * 0.55

				# Reject the ROT bone tail onto the eye bone Z axis
				rejection_z = project_vector_on_plane(rot_ctr.vector, self.meta_base_bone.z_axis)
				# Take the distance between that and the base bone's vector
				# to determine the constraints' influence.
				distance = (base_bone.vector - rejection_z).length
				sticky_strength = 1 - distance / eye_width
				copyrot_x.drivers.append({
					'prop' : 'influence'
					,'expression' : f"var*{sticky_strength}"
					,'variables' : [(self.properties_bone.name, sticky_prop_name)]
				})

				copyrot_z = rot_ctr.add_constraint('COPY_ROTATION'
					,name='Copy Rotation Z'
					,subtarget=base_bone.name
					,use_xyz = [False, False, True]
				)

				copyrot_z.drivers.append({
					'prop' : 'influence'
					,'expression' : f"var*{sticky_strength*0.5}"
					,'variables' : [(self.properties_bone.name, sticky_prop_name)]
				})
			str_ctr.parent = rot_ctr

	def ensure_eyelid_root(self, eyelid_main_controls):
		""" Create another root bone that owns the eye root bone as well as the
			eyelid rotation helpers.
		"""
		base_bone = self.org_chain[0]

		# If the root bone already exists, just parent the bones and return.
		if not hasattr(self, 'eyelid_root'):
			self.eyelid_root = self.target_ctrl.new(
				name = base_bone.name.replace("ORG", "ROOT-LID")
				,source = base_bone
				,parent = self.aim_root.parent
				,custom_shape = self.ensure_widget('Square')
				,custom_shape_scale = 3
			)
			self.aim_root.parent = self.eyelid_root

		for str_bone in eyelid_main_controls:
			str_bone.parent = self.eyelid_root

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_eye_show_settings = BoolProperty(name="Eye Settings")

		params.CR_eye_sticky_eyelids = BoolProperty(
			name		 = "Sticky Eyelids"
			,description = "Eyelids will follow the rotation of the eye bone"
			,default	 = False
		)
		params.CR_eye_lower_eyelid = StringProperty(
			name		 = "Lower Eyelid Rig"
			,description = "Select a bone with a cloud_chain rig type that will generate the lower eyelid for this eye"
		)
		params.CR_eye_upper_eyelid = StringProperty(
			name		 = "Upper Eyelid Rig"
			,description = "Select a bone with a cloud_chain rig type that will generate the upper eyelid for this eye"
		)

		super().add_parameters(params)

	@classmethod
	def draw_cloud_params(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_eye_show_settings"): return layout

		ob = bpy.context.object

		layout.prop_search(params, 'CR_eye_lower_eyelid', ob.pose, 'bones')
		layout.prop_search(params, 'CR_eye_upper_eyelid', ob.pose, 'bones')

		return layout

class Rig(CloudEyeRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_eye")