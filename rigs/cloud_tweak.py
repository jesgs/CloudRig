from bpy.props import BoolProperty
from .cloud_base import CloudBaseRig

class CloudTweakRig(CloudBaseRig):
	"""Tweak a single bone with the same name as this bone in the generated rig."""

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
		ctr_bone = self.new_bonei(self.template_set
			,name = bone.name.replace('ORG', "CTR")
			,source = bone
			,custom_shape = self.ensure_widget('Circle')
			,parent = bone.parent
		)
		copy_trans = bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
		return ctr_bone

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Template Bones", preset=1,	default_layers=[cls.default_layers('IK_MAIN')])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_tweak_show_settings = BoolProperty(
			name		 = "Tweak Settings"
			,description = "Reveal settings for the cloud_tweak rig type"
		)

		params.CR_bone_transforms = BoolProperty(
			 name="Transforms"
			,description="Replace the matching generated bone's transforms with this bone's transforms" # An idea: when this is False, let the generation script affect the metarig - and move this bone, to where it is in the generated rig.
			,default=False
		)
		params.CR_bone_locks = BoolProperty(
			 name="Locks"
			,description="Replace the matching generated bone's transform locks with this bone's transform locks"
			,default=True
		)
		params.CR_bone_rot_mode = BoolProperty(
			 name="Rotation Mode"
			,description="Set the matching generated bone's rotation mode to this bone's rotation mode"
			,default=False
		)
		params.CR_bone_shape = BoolProperty(
			 name="Bone Shape"
			,description = "Replace the matching generated bone's shape with this bone's shape"
			,default=False
		)
		params.CR_bone_group = BoolProperty(
			 name="Bone Group"
			,description="Replace the matching generated bone's group with this bone's group"
			,default=False
		)
		params.CR_bone_layers = BoolProperty(
			 name="Layers"
			,description="Set the generated bone's layers to this bone's layers"
			,default=False
		)
		params.CR_bone_props = BoolProperty(
			 name="Custom Properties"
			,description="Copy custom properties from this bone to the generated bone"
			,default=False
		)
		params.CR_bone_ik_settings = BoolProperty(
			 name="IK Settings"
			,description="Copy IK settings from this bone to the generated bone"
			,default=False
		)
		params.CR_bone_bbone_props = BoolProperty(
			name="B-Bone Settings"
			,description="Copy B-Bone settings from this bone to the generated bone"
			,default=False
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_tweak_show_settings'): return layout

		layout.prop(params, "CR_bone_constraints_additive")
		layout.prop(params, "CR_bone_transforms")
		layout.prop(params, "CR_bone_locks")
		layout.prop(params, "CR_bone_rot_mode")
		layout.prop(params, "CR_bone_shape")
		layout.prop(params, "CR_bone_group")
		layout.prop(params, "CR_bone_layers")
		layout.prop(params, "CR_bone_props")
		layout.prop(params, "CR_bone_ik_settings")
		layout.prop(params, "CR_bone_bbone_props")

		return layout

# Uncomment the next two lines to make this rig show up in Blender.
class Rig(CloudTweakRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)