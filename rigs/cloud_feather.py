from .cloud_fk_chain import CloudFKChainRig

class CloudFeatherRig(CloudFKChainRig):
	"""Single-bone rig for a simple feather."""

	forced_params = {
		'CR_chain_segments' : 1
		,'CR_chain_tip_control' : True
		,'CR_fk_chain_display_center' : False
	}

	def initialize(self):
		super().initialize()

		if self.bone_count != 1:
			self.raise_error("Feather rig must consist of exactly 1 bone.")

	def create_bone_infos(self):
		super().create_bone_infos()

		first_fk = self.bone_sets['FK Controls'][0]
		first_fk.custom_shape = self.ensure_widget("Feather")
		first_fk.custom_shape_along_length = 1

		# Create a new bone parented to ORG, and parent the tip control to it.
		org = self.bones_org[0]
		bend_ctr = self.bone_sets['FK Controls Extra'].new(
			name 			= org.name.replace("ORG", "BEND")
			,source 		= org
			,parent 		= org
			,custom_shape 	= self.ensure_widget("Feather")
		)
		self.main_str_bones[-1].parent = bend_ctr
		bend_ctr.custom_shape_along_length = 0.95

		# Create a visual helper line from the bend to the FK control's display positions.
		line = self.bone_sets['FK Controls Extra'].new(
			name	= org.name.replace("ORG", "LINE-BEND")
			,source = bend_ctr
			,parent = bend_ctr
			,head	= bend_ctr.head + bend_ctr.vector * 0.95
			,tail	= bend_ctr.tail
			,custom_shape = self.ensure_widget("Line")
			,use_custom_shape_bone_size = True
		)
		bend_ctr.bone_group = line.bone_group = self.bone_sets['Stretch Controls'].bone_group
		line.bbone_width *= 0.2
		line.hide_select = True

		line.add_constraint('STRETCH_TO', subtarget=first_fk.name, head_tail=1)

		# Make the tip control copy partial rotation of the bend control
		self.main_str_bones[-1].add_constraint('COPY_ROTATION', subtarget=bend_ctr.name, influence=0.4)

	##############################
	# No parameters for this rig type.

class Rig(CloudFeatherRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)
