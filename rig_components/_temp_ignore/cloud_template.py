from bpy.props import BoolProperty
from bpy.types import PropertyGroup
from .cloud_base import Component_Base
from ..load_metarig import load_sample_by_file

from ..rig_component_features.bone import BoneInfo

class CloudTemplateRig(Component_Base):
	"""Template for implementing rig types in CloudRig. Just creates a control bone."""

	def initialize(self):
		pass

	def create_bone_infos(self, context):
		super().create_bone_infos(context)
		if self.params.template.use_control:
			self.make_ctr_bone(self.bones_org[0])

	def make_ctr_bone(self, bone) -> BoneInfo:
		"""Simple control bone that owns the ORG bone."""
		ctr_bone = self.bone_sets['Template Bones'].new(
			name = bone.name.replace('ORG', "CTR")
			,source = bone
			,custom_shape = self.ensure_widget('Circle')
			,parent = bone.parent
		)
		bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
		return ctr_bone

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Template Bones', preset=1,	default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""

		cls.draw_prop(context, layout, params.template, 'use_control')


class Params(PropertyGroup):
	use_control = BoolProperty(
		name		 = "Make Control"
		,description = "Create a Control bone"
		,default	 = True
	)

class RigComponent(CloudTemplateRig):
	pass

def create_sample(obj):
	# For the rig sample to work, there must be an object in 
	# CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
	load_sample_by_file(__file__)
