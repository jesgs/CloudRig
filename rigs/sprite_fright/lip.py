from ..cloud_tweak import CloudTweakRig
from ...bone import BoneInfo, BoneSet

"""TODO
We want the lip tweak bones of Sprite rigs to also create two copies of the bone:
P-: Parent bone to hold an Armature constraint for parenting.
CLONE-: Another copy with a Copy World Transforms constraint targetting P-, and parented to a different bone
Then add a Copy Local Location constraint to the tweaked bone, targetting CLONE-.

The idea is that the lip bones should propagate the transformations they get from the lip master control(ie. their direct parent), but NOT the transformations they get from DEF-Head (their indirect parent).

This would be even better if the tweak bones weren't even necessary, and instead this was built into an extension of cloud_face_chain.
"""

class SpriteLipRig(CloudTweakRig):
	"""Tweak a single bone with the same name as this bone in the generated rig."""

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()

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

class Rig(SpriteLipRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ...load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)