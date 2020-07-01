from bpy.props import BoolProperty, StringProperty

from .cloud_chain import CloudChainRig

class CloudFKChainRig(CloudChainRig):
	"""FK chain with squash and stretch controls."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.category = self.slice_name(self.base_bone)[1]
		if self.params.CR_use_custom_category_name:
			self.category = self.params.CR_custom_category_name
		
		self.limb_name = self.category
		if self.params.CR_use_custom_limb_name:
			self.limb_name = self.params.CR_custom_limb_name								# Name used for naming bones. Should not contain a side identifier like .L/.R.
		self.limb_ui_name = self.side_prefix + " " + self.limb_name	# Name used for UI related things. Should contain the side identifier.

		self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
		self.fk_hinge_name = "fk_hinge_" + self.limb_name_props

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.fk_chain = self.ensure_bone_set("FK Controls")
		self.fk_mch = self.ensure_bone_set("FK Helpers")

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
				if self.params.CR_double_first_control:
					# Make a parent for the first control.
					fk_parent_bone = self.create_parent_bone(fk_bone)
					fk_parent_bone.custom_shape = self.load_widget("FK_Limb")
					if self.params.CR_center_all_fk:
						self.create_dsp_bone(fk_parent_bone, center=True)
					hng_child = fk_parent_bone
			if i > 0:
				# Parent FK bone to previous FK bone.
				fk_bone.parent = self.org_chain[i-1].fk_bone
			if self.params.CR_center_all_fk:
				self.create_dsp_bone(fk_bone, center=True)
			if self.params.CR_counter_rotate_str:
				str_bone = self.main_str_bones[i]
				str_bone.add_constraint('TRANSFORM'
					,subtarget				= fk_bone.name
					,map_from				= 'ROTATION'
					,map_to					= 'ROTATION'
					,use_motion_extrapolate = True
					,from_max_x_rot			= 1
					,from_max_y_rot			= 1
					,from_max_z_rot			= 1
					,to_max_x_rot			= -0.5
					,to_max_y_rot			= -0.5
					,to_max_z_rot			= -0.5
				)

		# Create Hinge helper
		if self.params.CR_use_fk_hinge:
			hng_bone = self.hinge_setup(
				bone = hng_child, 
				category = self.category,
				parent_bone = self.limb_root_bone,
				hng_name = self.base_bone.replace("ORG", "FK-HNG"),
				prop_bone = self.ikfk_properties_bone,
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

		params.CR_show_fk_settings = BoolProperty(
			name="FK Settings"
			,description = "Reveal settings for the cloud_fk_chain rig type"
		)
		params.CR_counter_rotate_str = BoolProperty(
			 name		 = "Counter-Rotate STR"
			,description = "Main STR- bones will counter half the rotation of their parent FK bones. This forces Deform Segments parameter to be 1. Will result in easier to pose smooth curves"
			,default	 = False
		)
		params.CR_center_all_fk = BoolProperty(
			 name		 = "Display FK in center"
			,description = "Display all FK controls' shapes in the center of the bone, rather than the beginning of the bone"
			,default	 = False
		)
		params.CR_double_first_control = BoolProperty(
			 name		 = "Double First FK"
			,description = "The first FK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose"
			,default	 = True
		)

		params.CR_use_fk_hinge = BoolProperty(
			name		 = "Hinge Toggle"
			,description = "Set up a hinge toggle"
			,default	 = True
		)
		
		params.CR_use_custom_limb_name = BoolProperty(
			 name		 = "Custom Limb Name"
			,description = "Specify a name for this limb. Settings for limbs with the same name will be displayed on the same row in the rig UI. If not enabled, use the name of the base bone, without pre and suffixes"
			,default 	 = False
		)
		params.CR_custom_limb_name = StringProperty(
			name		 = "Custom Limb"
			,default	 = "Arm"
			,description = """This name should NOT include a side indicator such as ".L" or ".R", as that will be determined by the bone's name. There can be exactly two limbs with the same name(a left and a right one)"""
		)
		params.CR_use_custom_category_name = BoolProperty(
			 name		 = "Custom Category Name"
			,description = "Specify a category for this limb. If not enabled, use the name of the base bone, without pre and suffixes"
			,default	 = False,
		)
		params.CR_custom_category_name = StringProperty(
			name		 = "Custom Category"
			,default	 = "arms"
			,description = "Limbs in the same category will have their settings displayed in the same column"
		)

		super().add_parameters(params)


	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		ui_rows = super().cloud_params_ui(layout, params)

		icon = 'TRIA_DOWN' if params.CR_show_fk_settings else 'TRIA_RIGHT'
		layout.prop(params, "CR_show_fk_settings", toggle=True, icon=icon)
		if not params.CR_show_fk_settings: return ui_rows

		name_row = layout.row()
		limb_column = name_row.column()
		limb_column.prop(params, "CR_use_custom_limb_name")
		if params.CR_use_custom_limb_name:
			limb_column.prop(params, "CR_custom_limb_name", text="")
		category_column = name_row.column()
		category_column.prop(params, "CR_use_custom_category_name")
		if params.CR_use_custom_category_name:
			category_column.prop(params, "CR_custom_category_name", text="")

		layout.prop(params, "CR_counter_rotate_str")
		layout.prop(params, "CR_center_all_fk")
		layout.prop(params, "CR_double_first_control")
		layout.prop(params, "CR_use_fk_hinge")

		return ui_rows

class Rig(CloudFKChainRig):
	pass

import bpy
def create_sample(obj):
	# generated by rigify.utils.write_metarig
	bpy.ops.object.mode_set(mode='EDIT')
	arm = obj.data

	bones = {}

	bone = arm.edit_bones.new('FK_Chain_1')
	bone.head = 0.0000, 0.0000, 0.0000
	bone.tail = 0.0000, -0.5649, 0.0000
	bone.roll = -3.1416
	bone.use_connect = False
	bone.bbone_x = 0.0399
	bone.bbone_z = 0.0399
	bone.head_radius = 0.0565
	bone.tail_radius = 0.0282
	bone.envelope_distance = 0.1412
	bone.envelope_weight = 1.0000
	bone.use_envelope_multiply = 0.0000
	bones['FK_Chain_1'] = bone.name
	bone = arm.edit_bones.new('FK_Chain_2')
	bone.head = 0.0000, -0.5649, 0.0000
	bone.tail = 0.0000, -1.1299, 0.0000
	bone.roll = -3.1416
	bone.use_connect = True
	bone.bbone_x = 0.0399
	bone.bbone_z = 0.0399
	bone.head_radius = 0.0282
	bone.tail_radius = 0.0565
	bone.envelope_distance = 0.1412
	bone.envelope_weight = 1.0000
	bone.use_envelope_multiply = 0.0000
	bone.parent = arm.edit_bones[bones['FK_Chain_1']]
	bones['FK_Chain_2'] = bone.name
	bone = arm.edit_bones.new('FK_Chain_3')
	bone.head = 0.0000, -1.1299, 0.0000
	bone.tail = 0.0000, -1.6948, -0.0000
	bone.roll = -3.1416
	bone.use_connect = True
	bone.bbone_x = 0.0399
	bone.bbone_z = 0.0399
	bone.head_radius = 0.0565
	bone.tail_radius = 0.0565
	bone.envelope_distance = 0.1412
	bone.envelope_weight = 1.0000
	bone.use_envelope_multiply = 0.0000
	bone.parent = arm.edit_bones[bones['FK_Chain_2']]
	bones['FK_Chain_3'] = bone.name
	bone = arm.edit_bones.new('FK_Chain_4')
	bone.head = 0.0000, -1.6948, -0.0000
	bone.tail = 0.0000, -2.2598, 0.0000
	bone.roll = -3.1416
	bone.use_connect = True
	bone.bbone_x = 0.0399
	bone.bbone_z = 0.0399
	bone.head_radius = 0.0565
	bone.tail_radius = 0.0565
	bone.envelope_distance = 0.1412
	bone.envelope_weight = 1.0000
	bone.use_envelope_multiply = 0.0000
	bone.parent = arm.edit_bones[bones['FK_Chain_3']]
	bones['FK_Chain_4'] = bone.name

	bpy.ops.object.mode_set(mode='OBJECT')
	pbone = obj.pose.bones[bones['FK_Chain_1']]
	pbone.rigify_type = 'cloud_fk_chain'
	pbone.lock_location = (False, False, False)
	pbone.lock_rotation = (False, False, False)
	pbone.lock_rotation_w = False
	pbone.lock_scale = (False, False, False)
	pbone.rotation_mode = 'QUATERNION'
	try:
		pbone.rigify_parameters.CR_subdivide_deform = 10
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_controls_for_handles = True
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_show_spline_ik_settings = True
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_show_display_settings = False
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_rotatable_handles = False
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_hook_name = "Cable"
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_show_chain_settings = True
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_sharp_sections = True
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_bbone_segments = 6
	except AttributeError:
		pass
	try:
		pbone.rigify_parameters.CR_show_fk_settings = True
	except AttributeError:
		pass
	pbone = obj.pose.bones[bones['FK_Chain_2']]
	pbone.rigify_type = ''
	pbone.lock_location = (False, False, False)
	pbone.lock_rotation = (False, False, False)
	pbone.lock_rotation_w = False
	pbone.lock_scale = (False, False, False)
	pbone.rotation_mode = 'QUATERNION'
	pbone = obj.pose.bones[bones['FK_Chain_3']]
	pbone.rigify_type = ''
	pbone.lock_location = (False, False, False)
	pbone.lock_rotation = (False, False, False)
	pbone.lock_rotation_w = False
	pbone.lock_scale = (False, False, False)
	pbone.rotation_mode = 'QUATERNION'
	pbone = obj.pose.bones[bones['FK_Chain_4']]
	pbone.rigify_type = ''
	pbone.lock_location = (False, False, False)
	pbone.lock_rotation = (False, False, False)
	pbone.lock_rotation_w = False
	pbone.lock_scale = (False, False, False)
	pbone.rotation_mode = 'QUATERNION'

	bpy.ops.object.mode_set(mode='EDIT')
	for bone in arm.edit_bones:
		bone.select = False
		bone.select_head = False
		bone.select_tail = False
	for b in bones:
		bone = arm.edit_bones[bones[b]]
		bone.select = True
		bone.select_head = True
		bone.select_tail = True
		arm.edit_bones.active = bone

	return bones