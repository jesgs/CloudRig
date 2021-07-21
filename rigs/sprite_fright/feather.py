from ..cloud_fk_chain import CloudFKChainRig

class SpriteFeatherRig(CloudFKChainRig):
	"""Slightly modified version of cloud_fk_chain, for rigging the Sprite Fright bird's feathers."""

	forced_params = {
		'CR_chain_segments' : 1
		,'CR_chain_tip_control' : True
		,'CR_fk_chain_display_center' : False
	}

	def initialize(self):
		super().initialize()

		if self.params.CR_spine_use_ik:
			assert self.bone_count==1, "Feather rig must consist of exactly 1 bone."

	def create_bone_infos(self):
		super().create_bone_infos()

		self.bone_sets['FK Controls'][0].custom_shape = self.ensure_widget("Feather")
		fk_dsp = self.create_dsp_bone(self.bone_sets['FK Controls'][0])
		fk_dsp.put(loc=fk_dsp.tail)

		# Create a new bone parented to ORG, and parent the tip control to it.
		org = self.bones_org[0]
		bend_ctr = self.bone_sets['FK Controls Extra'].new(
			name 			= org.name.replace("ORG", "BEND")
			,source 		= org
			,parent 		= org
			,custom_shape 	= self.ensure_widget("Feather")
		)
		bend_ctr.bone_group = self.bone_sets['Stretch Controls'].bone_group
		self.bone_sets['Stretch Controls'][-1].parent = bend_ctr

		bend_dsp = self.create_dsp_bone(bend_ctr)
		dsp_loc = bend_ctr.head + (bend_ctr.tail-bend_ctr.head)*0.95
		bend_dsp.put(loc=dsp_loc)

		# Create a visual helper line from the bend to the FK control's display positions.
		line = self.bone_sets['FK Controls Extra'].new(
			name	= org.name.replace("ORG", "LINE-BEND")
			,source = bend_dsp
			,parent = bend_dsp
			,custom_shape = self.ensure_widget("Line")
			,use_custom_shape_bone_size = True
		)
		line.bone_group = self.bone_sets['Stretch Controls'].bone_group
		line.hide_select = True

		line.tail = fk_dsp.head.copy()
		line.add_constraint('STRETCH_TO', subtarget=fk_dsp.name)

		# Make the tip control copy partial rotation of the bend control
		self.bone_sets['Stretch Controls'][-1].add_constraint('COPY_ROTATION', subtarget=bend_ctr.name, influence=0.4)

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

class Rig(SpriteFeatherRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ...load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)