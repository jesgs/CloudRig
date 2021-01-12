from ..cloud_aim import CloudAimRig
from ...bone import BoneInfo, BoneSet

from bpy.props import BoolProperty

class SpriteEyeRig(CloudAimRig):
	"""Tweak a single bone with the same name as this bone in the generated rig."""

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()

		# ORG bone should only inherit rotation, not location or scale.
		org_bi = self.org_chain[0]
		org_bi.constraint_infos[0].mute = True
		c = org_bi.add_constraint('COPY_ROTATION'
			,space = 'WORLD'
			,mix_mode = 'REPLACE'
			,subtarget = self.ctr_bone.name
		)

		# Lock all location and Y scale
		self.lock_transforms(self.ctr_bone, loc=True, rot=False, scale=[False, True, False])

		if self.params.CR_sprite_eye_highlight:
			self.create_eye_highlight(self.ctr_bone)
	
	def create_eye_highlight(self, ctr_bone):
		name_slices = self.naming.slice_name(ctr_bone)
		name_slices[1] += "_Highlight"
		highlight_ctr = self.target_ctrl.new(
			name = self.naming.make_name(*name_slices)
			,source = ctr_bone
			,parent = ctr_bone
			,custom_shape = self.ensure_widget("Oval")
			,length = ctr_bone.length/5
			,custom_shape_scale = ctr_bone.custom_shape_scale/3
		)
		self.lock_transforms(highlight_ctr, loc=True, rot=False, scale=[False, True, False])
		highlight_dsp = self.create_dsp_bone(highlight_ctr)
		highlight_dsp.put(ctr_bone.tail)
		self.make_def_bone(highlight_ctr, self.aim_def)

		# If we have a root bone, parent eye highlight to it and copy local rotation from the ORG bone.
		# This is to prevent the eye highlight control from inheriting scale from the eye control.
		if self.params.CR_aim_root:
			highlight_ctr.parent = self.aim_root
			highlight_ctr.add_constraint('COPY_ROTATION', subtarget=self.org_chain[0].name)

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_sprite_eye_show_settings = BoolProperty(name="Sprite Eye Settings")

		params.CR_sprite_eye_highlight = BoolProperty(
			name		 = "Eye Highlight"
			,description = "Create a highlight control and deform bone attached to the eye control"
			,default	 = True
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)
		if not cls.draw_dropdown_menu(layout, params, "CR_sprite_eye_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_sprite_eye_highlight")

		return layout

class Rig(SpriteEyeRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ...load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)