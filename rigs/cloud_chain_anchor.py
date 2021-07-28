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
	# No parameters for this rig type.

class Rig(CloudChainAnchorRig):
	pass

from ..metarigs.load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)