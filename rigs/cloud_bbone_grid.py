import bpy
from bpy.props import *
from mathutils import Vector

from rigify.base_rig import stage

from .cloud_base import CloudBaseRig

class CloudBBoneGridRig(CloudBaseRig):
	"""Set up a grid of Bendy Bones and their controls. They must already exist as the children of this bone."""

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.ctr_bones = self.ensure_bone_set("BBone Controls")
		self.bendy_bones = self.ensure_bone_set("Deform BBones")
		self.tangent_bones = self.ensure_bone_set("Tangent Handle Helpers")

	def load_bone_hierarchy(self, edit_bone):
		""" Recursively load children of edit_bone into self.ctr_bones and self.bendy_bones Bone Sets. """

		for eb in edit_bone.children:
			bone_set = self.ctr_bones
			hide_select = False
			if eb.bbone_segments > 1:
				bone_set = self.bendy_bones
				hide_select = self.mch_disable_select

			bone_set.new(
				name		 = eb.name
				,source		 = eb
				,hide_select = hide_select
			)
			self.load_bone_hierarchy(eb)

	def load_org_bones(self):
		super().load_org_bones()
		# Load BBone Controls and Deform BBones into BoneInfo instances.
		base_eb = self.get_bone(self.base_bone)
		self.load_bone_hierarchy(base_eb)

		print("Bendy bones:")
		for bi in self.bendy_bones:
			print(bi.name)

		print("Control bones:")
		for bi in self.ctr_bones:
			print(bi.name)

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "BBone Controls", preset=4, default_layers=[cls.default_layers('FACE_TWEAK')])
		cls.define_bone_set(params, "Deform BBones", default_layers=[cls.default_layers('DEF')], override='DEF')
		cls.define_bone_set(params, "Tangent Handle Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_show_bbgrid_settings = BoolProperty(name="BBone Grid Rig")
		
		# Meh, this probably needs to exist on each BBone individually. Sometimes we want Automatic, sometimes Tangent, sometimes Auto+Tangent. Sometimes even different things for the head and the tail of the same bone.
		params.CR_auto_tangent = BoolProperty(
			 name="Auto+Tangent"
			,description="BBones in the grid whose handle type is set to Tangent will behave more as if their handle type was set to Automatic, while still being controllable via rotation."
			,default=False
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		ui_rows = super().cloud_params_ui(layout, params)

		icon = 'TRIA_DOWN' if params.CR_show_bbgrid_settings else 'TRIA_RIGHT'
		layout.prop(params, "CR_show_bbgrid_settings", toggle=True, icon=icon)
		if not params.CR_show_bbgrid_settings: return ui_rows

		layout.prop(params, "CR_auto_tangent")

		return ui_rows


class Rig(CloudBBoneGridRig):
	pass