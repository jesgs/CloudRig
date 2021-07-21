from typing import List
from ..bone import BoneInfo

from bpy.props import BoolProperty, StringProperty, IntVectorProperty, BoolVectorProperty, EnumProperty

from .cloud_chain import CloudChainRig

class CloudFKChainRig(CloudChainRig):
	"""FK chain with squash and stretch controls."""

	# Strings to try to communicate obscure behaviours of this rig type in the params UI.
	relinking_behaviour = "Constraints will be moved to the FK controls."

	has_test_animation = True

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

		if not self.params.CR_fk_chain_root:
			self.params.CR_fk_chain_hinge = False

	def create_bone_infos(self):
		super().create_bone_infos()
		if self.params.CR_fk_chain_root:
			# This has to come before make_fk_chain() so inheriting rig classes
			# that override make_fk_chain() can expect root bone to already exist.
			self.root_bone = self.make_root_bone()

		self.make_fk_chain()

		if self.root_bone == self.bone_sets['Original Bones'][0]:
			self.root_bone = self.bone_sets['FK Controls'][0]

		# Default root parenting
		if self.params.CR_fk_chain_root:
			if not self.params.CR_fk_chain_hinge:
				# TODO: This is messy, and could use unit tests to be able to change this code without messing something up.
				self.bone_sets['FK Controls'][0].parent = self.root_bone
			self.root_bone.parent = self.bone_sets['Original Bones'][0].parent

		self.attach_org_to_fk()
		if self.params.CR_chain_preserve_volume:
			self.tweak_def_chain()

	def relink(self):
		"""Override cloud_chain.
		Move constraints from ORG to FK chain and relink them.
		"""
		for i, org in enumerate(self.bone_sets['Original Bones']):
			for c in org.constraint_infos[:]:
				if not c.is_from_real: continue
				to_bone = self.bone_sets['FK Controls'][i]
				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	def make_root_bone(self):
		# Socket/Root bone to parent IK and FK to.
		root_name = self.base_bone.replace("ORG", "ROOT")
		base_bone = self.bone_sets['Original Bones'][0]
		limb_root_bone = self.bone_sets['FK Controls Extra'].new(
			name 			= root_name
			,source 		= base_bone
			,parent 		= base_bone.parent
			,custom_shape 	= self.ensure_widget("Cube")
			,inherit_scale	= self.params.CR_fk_chain_inherit_scale
		)
		return limb_root_bone

	def make_fk_chain(self):
		fk_name = ""

		hng_child = None	# For keeping track of which bone will need to be parented to the Hinge helper bone.
		for i, org_bone in enumerate(self.bone_sets['Original Bones']):
			fk_name = org_bone.name.replace("ORG", "FK")
			fk_bone = self.bone_sets['FK Controls'].new(
				name				= fk_name
				,source				= org_bone
				,custom_shape 		= self.ensure_widget("Circle_Spiked_2")
				,parent				= org_bone.parent
				,inherit_scale		= self.params.CR_fk_chain_inherit_scale
			)
			org_bone.fk_bone = fk_bone
			if i == 0:
				hng_child = fk_bone
				if self.params.CR_fk_chain_double_first:
					# Make a parent for the first control.
					fk_parent_bone = self.create_parent_bone(fk_bone, bone_set=self.bone_sets['FK Controls Extra'])
					fk_parent_bone.custom_shape = fk_bone.custom_shape
					if self.params.CR_fk_chain_display_center:
						self.create_dsp_bone(fk_parent_bone, center=True)
					hng_child = fk_parent_bone
			if i > 0:
				# Parent FK bone to previous FK bone.
				fk_bone.parent = self.bone_sets['Original Bones'][i-1].fk_bone
			if self.params.CR_fk_chain_display_center:
				self.create_dsp_bone(fk_bone, center=True)

		# Create Hinge helper
		if self.params.CR_fk_chain_hinge:
			hng_bone = self.make_hinge_setup(
				bone		 = hng_child
				,bone_set	 = self.bone_sets['FK Helpers']
				,category	 = self.category
				,parent_bone = self.root_bone
				,hng_name	 = self.base_bone.replace("ORG", "FK-HNG")
				,prop_bone	 = self.properties_bone
				,prop_name	 = self.fk_hinge_name
				,limb_name	 = self.limb_ui_name
			)

	def make_hinge_setup(self, bone, category, *,
		prop_bone, prop_name, default_value=0.0,
		parent_bone=None, head_tail=0,
		hng_name=None, limb_name=None, bone_set=None
	):
		""" Create a hinge toggle for a bone.
			Bone is usually the first bone in an FK chain.
			When hinge is turned on, the bone doesn't inherit rotation from its
			parents, but still inherits rotation from the rig's root bone.
		"""

		# Defaults for optional parameters
		if not hng_name:
			sliced = self.naming.slice_name(bone.name)
			sliced[0].insert(0, "HNG")
			hng_name = self.naming.make_name(*sliced)
		if not parent_bone:
			parent_bone = bone.parent
		if not limb_name:
			limb_name = "Hinge: " + self.side_suffix + " " + self.naming.slice_name(bone.name)[1]
		if bone_set==None:
			bone_set = bone.bone_set

		info = {
			"prop_bone"			: prop_bone,
			"prop_id" 			: prop_name,

			"operator" : "pose.cloudrig_snap_bake",
			"bones" : [bone.name]
		}

		# Store UI info
		self.add_ui_data("fk_hinges", category, limb_name, info, default=default_value)

		# Create Hinge helper bone
		hng_bone = bone_set.new(
			name			= hng_name
			,source			= bone
		)

		# Hinge Armature constraint
		hng_con = hng_bone.add_constraint('ARMATURE',
			targets = [
				{
					"subtarget" : 'root'
				},
				{
					"subtarget" : str(parent_bone)
				}
			],
		)

		hng_con.drivers.append({
			'prop' : 'targets[0].weight',
			'variables' : [
				(prop_bone.name, prop_name)
			]
		})

		hng_con.drivers.append({
			'prop' : 'targets[1].weight',
			'expression' : '1-var',
			'variables' : [
				(prop_bone.name, prop_name)
			]
		})

		# Hinge Copy Location constraint
		hng_bone.add_constraint('COPY_LOCATION'
			,space = 'WORLD'
			,subtarget	   = str(parent_bone)
			,head_tail	   = head_tail
		)

		# Parenting
		bone.parent = hng_bone
		return hng_bone

	def make_def_chain(self, str_chain: List[BoneInfo]) -> List[BoneInfo]:
		"""Extend cloud_chain by tweaking some bbone values."""
		def_chain = super().make_def_chain(str_chain)

		last_def = def_chain[-1]
		if last_def == def_chain[0]:
			return

		# If we didn't put a stretch constraint on the final deform bone,
		# it must mean there is no cap control.
		if len(last_def.constraint_infos)==0 and not self.params.CR_chain_unlock_deform:
			if last_def.prev:
				# In this case, set the previous def_bone's easeout to 0.
				last_def.prev.bbone_easeout = 0
			# Also, parent this to the ORG bone. This is so that scaling
			# the last STR control doesn't affect this deform bone.
			if not self.params.CR_chain_unlock_deform:
				last_def.parent = self.bone_sets['Original Bones'][-1]

	def tweak_def_chain(self):
		return # TODO: This seems to break scale inheritance, not fix it? Why was it ever here?
		for i, def_bone in enumerate(self.bone_sets['Deform Bones']):
			fk_control = self.bone_sets['FK Controls'][int(i/self.params.CR_chain_segments)]
			def_bone.inherit_scale = 'FULL'
			for d in def_bone.drivers:
				if 'bbone_scale' not in d['prop']: continue
				d['variables']['scale']['targets'][0]['bone_target'] = fk_control.name

	def attach_org_to_fk(self):
		"""Make ORG bones Copy Transforms of FK bones."""
		for i, org_bone in enumerate(self.bone_sets['Original Bones']):
			if i==0 and self.params.CR_fk_chain_root:
				org_bone.parent = self.root_bone
			fk_bone = self.get_bone_info(org_bone.name.replace("ORG", "FK"))

			org_bone.add_constraint('COPY_TRANSFORMS'
				,space			= 'WORLD'
				,subtarget		= fk_bone.name
				,name			= "Copy Transforms FK"
			)

	##############################
	# Test Action

	def add_test_animation(self, action, start_frame=1, flip_xyz=[False, False, False]) -> int:
		"""Add animation curves to the action to test this rig.

		Return the frame at which animation is finished.
		"""

		if not self.params.CR_fk_chain_test_animation_generate:
			return start_frame

		# Create FCurves
		curve_map = self.test_action_create_fcurves(
			action
			,self.bone_sets['FK Controls']
			,'rotation_euler'
		)

		# Populate FCurves with keyframes
		min_rot = self.params.CR_fk_chain_test_animation_rotation_range[0]
		max_rot = self.params.CR_fk_chain_test_animation_rotation_range[1]

		axes_boolean = self.params.CR_fk_chain_test_animation_axes
		order = [0, 2, 1]
		axes = [order[i] for i in range(3) if axes_boolean[i]]

		last_frame = self.create_keyframes_on_curves(
			curve_map
			,start_frame = start_frame
			,values = [0, max_rot, 0, min_rot, 0]
			,flip_xyz = flip_xyz
			,axes = axes
		)

		return last_frame

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'FK Controls', 		 preset=1, default_layers=[cls.DEFAULT_LAYERS.FK_MAIN])
		cls.define_bone_set(params, 'FK Controls Extra', preset=1, default_layers=[cls.DEFAULT_LAYERS.FK_SECOND])
		cls.define_bone_set(params, 'FK Helpers', 				   default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_fk_chain_show_settings = BoolProperty(
			name="FK Settings"
			,description = "Reveal settings for the cloud_fk_chain rig type"
		)
		# We are re-defining this instead of using the bone's own `inherit_scale` property because we want the default to be 'ALIGNED' instead of 'FULL'.
		params.CR_fk_chain_inherit_scale = EnumProperty(
			 name		 = "Inherit Scale"
			,description = "Scale inheritance type for FK controls"
			,items		 = [
				('NONE', 'None', "Completely ignore parent scaling")
				,('AVERAGE', 'Average', "Inherit uniform scaling representing the overall change in the volume of the parent")
				,('ALIGNED', 'Aligned', "Rotate non-uniform parent scaling to align with the child, applying parent X scale to child X axis, and so forth")
				,('FIX_SHEAR', 'Fix Shear', "Inherit scaling, but remove shearing of the child in the rest orientation")
				,('FULL', 'Full', "Inherit all affects of parent scaling")
			]
			,default	 = 'ALIGNED'
		)
		params.CR_fk_chain_display_center = BoolProperty(
			 name		 = "Display FK in center"
			,description = "Display all FK controls' shapes in the center of the bone, rather than the beginning of the bone"
			,default	 = False
		)
		params.CR_fk_chain_double_first = BoolProperty(
			 name		 = "Double First FK"
			,description = "The first FK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose"
			,default	 = False
		)

		params.CR_fk_chain_root = BoolProperty(
			name		 = "Root Control"
			,description = "Create a root control"
			,default	 = False
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
			,default	 = False
		)
		params.CR_fk_chain_category_name = StringProperty(
			name		 = "Custom Category"
			,default	 = "arms"
			,description = "Limbs in the same category will have their settings displayed in the same column"
		)

		params.CR_fk_chain_test_animation_generate = BoolProperty(
			 name		 = "Generate Test Animation"
			,description = "Include this rig element in the test animation"
			,default	 = False
		)
		params.CR_fk_chain_test_animation_rotation_range = IntVectorProperty(
			 name		 = "Rotation Range"
			,description = "Minimum and Maximum rotations for the test animation"
			,size		 = 2
			,default	 = (-130, 130)
			,min 		 = -180
			,max		 = 180
		)
		params.CR_fk_chain_test_animation_axes = BoolVectorProperty(
			 name		 = "Rotation Axes"
			,description = "Rotation axes to test in the test animation"
			,subtype	 = 'EULER'
			,default	 = (True, True, True)
		)

		super().add_parameters(params)

	@classmethod
	def draw_hinge_param(cls, layout, params):
		row = cls.draw_prop(layout, params, 'CR_fk_chain_hinge')
		row.enabled = params.CR_fk_chain_root

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_fk_chain_show_settings"): return layout

		category_row = layout.row(align=True, heading="UI Category")
		cls.draw_prop(category_row, params, 'CR_fk_chain_use_category_name', new_row=False, text="")
		col = category_row.column()
		cls.draw_prop(col, params, 'CR_fk_chain_category_name', new_row=False, text="")
		col.enabled = params.CR_fk_chain_use_category_name

		limb_row = layout.row(align=True, heading="Limb UI Name")
		cls.draw_prop(limb_row, params, 'CR_fk_chain_use_limb_name', new_row=False, text="")
		col = limb_row.column()
		cls.draw_prop(col, params, 'CR_fk_chain_limb_name', new_row=False, text="")
		col.enabled = params.CR_fk_chain_use_limb_name

		cls.draw_prop(layout, params, 'CR_fk_chain_inherit_scale')
		cls.draw_prop(layout, params, 'CR_fk_chain_display_center')
		cls.draw_prop(layout, params, 'CR_fk_chain_double_first')
		cls.draw_prop(layout, params, 'CR_fk_chain_root')
		cls.draw_hinge_param(layout, params)

		if context.object.data.cloudrig_parameters.generate_test_action:
			cls.draw_prop(layout, params, 'CR_fk_chain_test_animation_generate')
			if params.CR_fk_chain_test_animation_generate:
				row = layout.row()
				row.prop(params, 'CR_fk_chain_test_animation_rotation_range', index=0)
				row.prop(params, 'CR_fk_chain_test_animation_rotation_range', index=1, text="")
				row = layout.row(heading="Rotation Axes", align=True)
				row.prop(params, 'CR_fk_chain_test_animation_axes', text="X", toggle=True, index=0)
				row.prop(params, 'CR_fk_chain_test_animation_axes', text="Y", toggle=True, index=1)
				row.prop(params, 'CR_fk_chain_test_animation_axes', text="Z", toggle=True, index=2)

		return layout

	@classmethod
	def is_using_custom_props(cls, context, params):
		"""Overrides cloud_base."""
		if super().is_using_custom_props(context, params):
			return True

		if not (params.CR_fk_chain_hinge and params.CR_fk_chain_root) and \
			not params.CR_base_parent_switching:
			return False

class Rig(CloudFKChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)