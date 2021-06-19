from ..cloud_fk_chain import CloudFKChainRig

class SpriteFingerRig(CloudFKChainRig):
	"""Slightly modified version of cloud_fk_chain, for rigging the Sprites' fingers."""

	forced_params = {
		'CR_chain_segments' : 1
		,'CR_chain_tip_control' : True
		,'CR_fk_chain_display_center' : True
	}

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()

		# Create curl control
		curl_ctrl = self.fk_extras.new(
			name = self.fk_chain[0].name.replace("FK", "CURL")
			,source = self.fk_chain[0]
			,custom_shape = self.ensure_widget("Finger_Curl")
		)
		offset = -self.meta_base_bone.z_axis * self.meta_base_bone.length/2
		curl_ctrl.head += offset
		curl_ctrl.tail += offset
		# curl_ctrl.put(curl_ctrl.head + offset)

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		return layout

class Rig(SpriteFingerRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ...load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)