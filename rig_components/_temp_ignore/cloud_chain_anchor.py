from bpy.props import BoolProperty

from .cloud_copy import Component_CopyBone
from .cloud_base import Component_Base

class CloudChainAnchorRig(Component_CopyBone):
	"""Create a control on the generated rig that serves as an anchor for cloud_face_chain components."""

	def initialize(self):
		super().initialize()
		self.create_deform_bone = False

	def create_bone_infos(self, context):
		super().create_bone_infos(context)
		bi = self.bones_org[0]
		meta_bone = self.get_metarig_pbone(bi.name)

		if not meta_bone.custom_shape:
			bi.custom_shape = self.ensure_widget('Cube')

	##############################
	# No parameters for this rig type.

class RigComponent(CloudChainAnchorRig):
	pass
