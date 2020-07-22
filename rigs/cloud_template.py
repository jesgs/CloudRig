from bpy.props import BoolProperty
from .cloud_base import CloudBaseRig

class CloudTemplateRig(CloudBaseRig):
	"""Template for implementing rig types in CloudRig. Just creates a control bone."""

	def initialize(self):
		super().initialize()

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.template_set = self.ensure_bone_set("Template Bones")

	def prepare_bones(self):
		super().prepare_bones()
		if self.params.CR_template_use_control:
			self.make_ctr_bone(self.org_chain[0])

	def make_ctr_bone(self, bone):
		ctr_bone = self.template_set.new(
			name = bone.name.replace("ORG", "CTR")
			,source = bone
			,custom_shape = self.load_widget('Circle')
			,parent = bone.parent
		)
		copy_trans = bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
		return ctr_bone

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Template Bones", preset=1,	default_layers=[cls.default_layers('IK_MAIN')])

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
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
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_template_show_settings"): return layout

		layout.prop(params, "CR_template_use_control")

		return layout

# Uncomment the next two lines to make this rig show up in Blender.
# class Rig(CloudTemplateRig):
# 	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_template")