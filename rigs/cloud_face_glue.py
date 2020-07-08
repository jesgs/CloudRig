"""
This rig is meant to be used in conjunction with cloud_chain rigs, and is designed to create interactions between such chain rigs.
Other uses are on the table.

- Merge overlapping controls across several rigs, by shrinking them down and parenting them to a new control to replace both old ones, and also move the old ones to a different layer, perhaps MCH?
	Maybe this should be done by the glue rig, but the issue with that is that it would be nice if I didn't have to put glue bones everywhere explicitly. But I have no idea how to avoid that.

"""

import bpy
from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

from rigify.base_rig import stage

from .cloud_utils import make_name, slice_name
from .cloud_base import CloudBaseRig
from .cloud_chain import Rig as CloudChainRig

class CloudChainGlueRig(CloudBaseRig):
	"""Establish a relationship between two points in two or more cloud_face_chain rigs. This rig should be parented in a way to allow it to execute AFTER all such rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_chain rigs from the generator.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if type(rig)==CloudChainRig:
				self.chain_rigs.append(rig)

		for rig in self.chain_rigs:
			print(rig.base_bone)

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.def_bones = self.ensure_bone_set("Glue Deform")

	def make_def_bone(self, control_1, control_2):
		return

	def prepare_bones(self):
		super().prepare_bones()
		if self.params.CR_glue_create_def:
			self.make_def_bone(self.org_chain[0], self.org_chain[0])
	
	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Glue Deform", default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_show_face_glue_parameters = BoolProperty(
			name		 = "Glue Settings"
			,description = "Reveal settings for the cloud_face_glue rig type"
		)
		params.CR_glue_create_def = BoolProperty(
			name		 = "Make Deform"
			,description = "Create a deform bone"
			,default	 = True
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_face_glue_parameters"): return layout

		layout.prop(params, "CR_glue_create_def")

		return layout

class Rig(CloudChainGlueRig):
	pass