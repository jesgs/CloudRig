from bpy.props import BoolProperty, IntProperty

from .cloud_utils import make_name, slice_name
from .cloud_chain import CloudChainRig

"""
TODO: Currently, the only way in which two chain rigs interact is that if the parent of one chain rig is another chain rig without a cap control, they get connected with a single control.
Instead of doing that, chain rigs with a new CR_merge_chain_controls parameter set to True should look through all existing chain rigs, and if they find any, ensure a combined control for them, and parent the existing controls to that combined control, while moving the existing controls to the MCH layer.
	it's just sort of a shame that this param wouldn't really be useful for FK rigs or so.
Maybe we should extend cloud_chain into cloud_face_chain and implement this only there. Then we could also rename cloud_glue to cloud_face_glue.
"""

class CloudFaceChainRig(CloudChainRig):
	"""Chain with cartoony squash and stretch controls, with modifications and extra features for face rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_face_chain rigs from the generator, including self.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if type(rig) == type(self):
				self.chain_rigs.append(rig)

		for rig in self.chain_rigs:
			print(rig.base_bone)

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
        # This bone set is special in that its .new() function should never be called, and therefore it never creates any bones.
        # However, pre-existing STR bones who then had a merged control created for them will be assigned the bone group and layer of this BoneSet.
		self.merged_controls = self.ensure_bone_set("Merged Controls")

	def prepare_bones(self):
		super().prepare_bones()
		if self.params.CR_face_chain_merge:
			self.merge_controls()

	def merge_controls(self):
		pass

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Merged Controls", preset=1,	default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_show_face_chain_parameters = BoolProperty(
			name		 = "Face Chain Settings"
			,description = "Reveal settings for the cloud_face_chain rig type"
		)
		params.CR_face_chain_merge = BoolProperty(
			name		 = "Merge Controls"
			,description = "If any controls of this rig overlap with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer"
			,default	 = True
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_face_chain_parameters"): return layout

		layout.prop(params, "CR_face_chain_merge")

		return layout

class Rig(CloudFaceChainRig):
	pass