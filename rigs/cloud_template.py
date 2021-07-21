from bpy.props import BoolProperty
from .cloud_base import CloudBaseRig

class CloudTemplateRig(CloudBaseRig):
	"""Template for implementing rig types in CloudRig. Just creates a control bone."""

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()
		if self.params.CR_template_use_control:
			self.make_ctr_bone(self.bones_org[0])

	def make_ctr_bone(self, bone):
		ctr_bone = self.bone_sets['Template Bones'].new(
			name = bone.name.replace('ORG', "CTR")
			,source = bone
			,custom_shape = self.ensure_widget('Circle')
			,parent = bone.parent
		)
		copy_trans = bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
		return ctr_bone

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Template Bones', preset=1,	default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_template_show_settings = BoolProperty(
			name		 = "Template Settings"
			,description = "Reveal settings for the cloud_template rig type"
		)
		params.CR_template_use_control = BoolProperty(
			name		 = "Make Control"
			,description = "Create a Control bone"
			,default	 = True
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_template_show_settings'): return layout

		cls.draw_prop(layout, params, 'CR_template_use_control')

		return layout

# Uncomment the next two lines to make this rig show up in Blender.
# class Rig(CloudTemplateRig):
# 	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..metarigs.load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)