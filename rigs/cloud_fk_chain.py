from typing import List
from ..bone import BoneInfo

from bpy.props import BoolProperty, StringProperty

from .cloud_chain import CloudChainRig

class CloudFKChainRig(CloudChainRig):
	"""FK chain with squash and stretch controls."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.category = self.naming.slice_name(self.base_bone)[1]
		if self.params.CR_fk_chain_use_category_name:
			self.category = self.params.CR_fk_chain_category_name

		self.limb_name = self.category
		if self.params.CR_fk_chain_use_limb_name:
			self.limb_name = self.params.CR_fk_chain_limb_name								# Name used for naming bones. Should not contain a side identifier like .L/.R.

		# Name used for UI related things. Should contain the side identifier.
		self.limb_ui_name = self.limb_name
		if self.side_prefix!="":
			self.limb_ui_name = self.side_prefix + " " + self.limb_ui_name

		self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
		self.fk_hinge_name = "fk_hinge_" + self.limb_name_props

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.fk_chain = self.ensure_bone_set("FK Controls")
		self.fk_mch = self.ensure_bone_set("FK Helpers")

	def make_def_chain(self, str_chain: List[BoneInfo]) -> List[BoneInfo]:
		"""Extend cloud_chain by tweaking some bbone values"""
		def_chain = super().make_def_chain(str_chain)
		# If we didn't put a stretch constraint on the final deform bone,
		# it must mean there is no cap control.
		last_def = def_chain[-1]
		if len(last_def.constraint_infos)==0:
			if last_def.prev:
				# In this case, set the previous def_bone's easeout to 0.
				last_def.prev.bbone_easeout = 0
			# Also, parent this to the ORG bone. This is so that scaling
			# the last STR control doesn't affect this deform bone.
			last_def.parent = last_def.parent.org_parent

	def prepare_root_bone(self):
		# Socket/Root bone to parent IK and FK to.
		root_name = self.base_bone.replace("ORG", "ROOT")
		base_bone = self.get_bone(self.base_bone)
		self.limb_root_bone = self.fk_mch.new(
			name 					= root_name
			,source 				= base_bone
			,parent 				= self.bones.parent
			,custom_shape 			= self.load_widget("Cube")
			,custom_shape_scale 	= 0.5
		)
		self.register_parent(self.limb_root_bone, self.limb_ui_name)

	def prepare_fk_chain(self):
		fk_name = ""

		hng_child = None	# For keeping track of which bone will need to be parented to the Hinge helper bone.
		for i, org_bone in enumerate(self.org_chain):
			fk_name = org_bone.name.replace("ORG", "FK")
			fk_bone = self.fk_chain.new(
				name				= fk_name
				,source				= org_bone
				,custom_shape 		= self.load_widget("FK_Limb")
				,custom_shape_scale = org_bone.custom_shape_scale
				,parent				= self.bones.parent
			)
			org_bone.fk_bone = fk_bone
			if i == 0:
				hng_child = fk_bone
				if self.params.CR_fk_chain_double_first:
					# Make a parent for the first control.
					fk_parent_bone = self.create_parent_bone(fk_bone)
					fk_parent_bone.custom_shape = self.load_widget("FK_Limb")
					if self.params.CR_fk_chain_display_center:
						self.create_dsp_bone(fk_parent_bone, center=True)
					hng_child = fk_parent_bone
			if i > 0:
				# Parent FK bone to previous FK bone.
				fk_bone.parent = self.org_chain[i-1].fk_bone
			if self.params.CR_fk_chain_display_center:
				self.create_dsp_bone(fk_bone, center=True)

		# Create Hinge helper
		if self.params.CR_fk_chain_hinge:
			hng_bone = self.hinge_setup(
				bone = hng_child,
				category = self.category,
				parent_bone = self.limb_root_bone,
				hng_name = self.base_bone.replace("ORG", "FK-HNG"),
				prop_bone = self.properties_bone,
				prop_name = self.fk_hinge_name,
				limb_name = self.limb_ui_name,
				bone_set = self.fk_mch
			)

	def prepare_org_chain(self):
		# Find existing ORG bones
		# Add Copy Transforms constraints targetting FK.
		for i, org_bone in enumerate(self.org_chain):
			fk_bone = self.get_bone_info(org_bone.name.replace("ORG", "FK"))

			org_bone.add_constraint('COPY_TRANSFORMS'
				,space			= 'WORLD'
				,subtarget		= fk_bone.name
				,name			= "Copy Transforms FK"
			)

	def prepare_bones(self):
		super().prepare_bones()
		self.prepare_root_bone()
		self.prepare_fk_chain()
		self.prepare_org_chain()

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "FK Controls", preset=1, default_layers=[cls.default_layers('FK_MAIN')])
		cls.define_bone_set(params, "FK Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""

		params.CR_fk_chain_show_settings = BoolProperty(
			name="FK Settings"
			,description = "Reveal settings for the cloud_fk_chain rig type"
		)
		params.CR_fk_chain_display_center = BoolProperty(
			 name		 = "Display FK in center"
			,description = "Display all FK controls' shapes in the center of the bone, rather than the beginning of the bone"
			,default	 = False
		)
		params.CR_fk_chain_double_first = BoolProperty(
			 name		 = "Double First FK"
			,description = "The first FK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose"
			,default	 = True
		)

		params.CR_fk_chain_hinge = BoolProperty(
			name		 = "Hinge Toggle"
			,description = "Set up a hinge toggle"
			,default	 = True
		)

		params.CR_fk_chain_use_limb_name = BoolProperty(
			 name		 = "Custom Limb Name"
			,description = "Specify a name for this limb. Settings for limbs with the same name will be displayed on the same row in the rig UI. If not enabled, use the name of the base bone, without pre and suffixes"
			,default 	 = False
		)
		params.CR_fk_chain_limb_name = StringProperty(
			name		 = "Custom Limb"
			,default	 = "Arm"
			,description = """This name should NOT include a side indicator such as ".L" or ".R", as that will be determined by the bone's name. There can be exactly two limbs with the same name(a left and a right one)"""
		)
		params.CR_fk_chain_use_category_name = BoolProperty(
			 name		 = "Custom Category Name"
			,description = "Specify a category for this limb. If not enabled, use the name of the base bone, without pre and suffixes"
			,default	 = False,
		)
		params.CR_fk_chain_category_name = StringProperty(
			name		 = "Custom Category"
			,default	 = "arms"
			,description = "Limbs in the same category will have their settings displayed in the same column"
		)

		super().add_parameters(params)


	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_fk_chain_show_settings"): return layout

		category_row = layout.row(align=True, heading="UI Category")
		category_row.prop(params, "CR_fk_chain_use_category_name", text="")
		col = category_row.column()
		col.prop(params, "CR_fk_chain_category_name", text="")
		col.enabled = params.CR_fk_chain_use_category_name

		limb_row = layout.row(align=True, heading="Limb UI Name")
		limb_row.prop(params, "CR_fk_chain_use_limb_name", text="")
		col = limb_row.column()
		col.prop(params, "CR_fk_chain_limb_name", text="")
		col.enabled = params.CR_fk_chain_use_limb_name

		center_fk_row = layout.row()
		center_fk_row.prop(params, "CR_fk_chain_display_center")
		cls.ui_rows["CR_fk_chain_display_center"] = center_fk_row
		layout.prop(params, "CR_fk_chain_double_first")
		layout.prop(params, "CR_fk_chain_hinge")

		return layout

class Rig(CloudFKChainRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_fk_chain")