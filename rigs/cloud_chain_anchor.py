import bpy
from bpy.props import BoolProperty

from .cloud_copy import CloudCopyRig
from .cloud_base import CloudBaseRig

class CloudChainAnchorRig(CloudCopyRig):
	"""Create a control on the generated rig that serves as an anchor for cloud_face_chain rigs."""

	def initialize(self):
		super().initialize()
		self.create_deform_bone = False

	def create_bone_infos(self):
		super().create_bone_infos()
		bi = self.bones_org[0]
		meta_bone = self.meta_bone(bi.name)

		if not meta_bone.custom_shape:
			bi.custom_shape = self.ensure_widget('Cube')

		if not meta_bone.bone_group:
			pass # TODO: Add default bone group? Perhaps even add a whole Anchor BoneSet just for this?

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup"""
		super().add_parameters(params)

		params.CR_anchor_show_settings = BoolProperty(
			name		 = "Anchor Settings"
			,description = "Reveal settings for the cloud_chain_anchor rig type"
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = CloudBaseRig.draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_anchor_show_settings'): return layout

		layout.label(text="No parameters for this rig type.")

		return layout

class Rig(CloudChainAnchorRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)