import bpy
from bpy.props import BoolProperty, StringProperty, PointerProperty
from mathutils import Vector, Matrix

from .cloud_base import CloudBaseRig

def is_curve(self, obj):
	return obj.type=='CURVE'

class CloudCurveRig(CloudBaseRig):
	"""Create hook controls for an existing bezier curve."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()
		self.initialize_curve_rig()

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.curve_hooks = self.ensure_bone_set("Curve Hooks")
		self.curve_handles = self.ensure_bone_set("Curve Handles")

	def apply_custom_root_parent(self, bone=None, parent_name=""):
		"""Overrides cloud_base."""
		super().apply_custom_root_parent(self.root_control)

	def initialize_curve_rig(self):
		curve_ob = self.params.CR_curve_target
		if not curve_ob:
			self.raise_error("Curve object not found!")
		if curve_ob.type != 'CURVE':
			self.raise_error("Curve target must be a curve!")
		self.num_controls = len(curve_ob.data.splines[0].bezier_points)

	def create_bone_infos(self):
		super().create_bone_infos()
		self.make_curve_controls()

	def make_curve_controls(self):
		self.make_curve_root_ctrl()
		self.make_ctrls_for_curve_points()

	def make_curve_root_ctrl(self):
		self.root_control = self.curve_handles.new(
			name						= self.base_bone.replace("ORG", "ROOT")
			,source						= self.org_chain[0]
			,custom_shape				= self.ensure_widget("Cube")
			,use_custom_shape_bone_size = True
		)
		self.org_chain[0].parent = self.root_control

	def make_ctrls_for_curve_points(self):
		curve_ob = self.params.CR_curve_target

		# Function to convert a location vector in the curve's local space into world space.
		# For some reason this doesn't work when the curve object is parented to something, and we need it to be parented to the root bone kindof.
		# Use matrix_basis instead of matrix_world in case there are constraints on the curve.
		worldspace = lambda loc: (curve_ob.matrix_basis @ Matrix.Translation(loc)).to_translation()

		spline = curve_ob.data.splines[0]	# For now we only support a single spline per curve.
		self.hooks = []
		for i, cp in enumerate(spline.bezier_points):
			self.hooks.append(
				self.make_ctrls_for_curve_point(
					loc		  = worldspace(cp.co),
					loc_left  = worldspace(cp.handle_left),
					loc_right = worldspace(cp.handle_right),
					i		  = i,
					cyclic	  = spline.use_cyclic_u
				)
			)

	def make_ctrls_for_curve_point(self, loc, loc_left, loc_right, i, cyclic=False):
		""" Create hook controls for a bezier curve point defined by three points (loc, loc_left, loc_right). """

		hook_name = self.params.CR_curve_hook_name if self.params.CR_curve_hook_name!="" else self.base_bone.replace("ORG-", "")
		suffix = self.side_suffix
		if suffix!="":
			suffix = self.naming.suffix_separator + suffix

		hook_ctr = self.curve_hooks.new(
			name						= f"Hook_{hook_name}_{str(i).zfill(2)}{suffix}"
			,head						= loc
			,tail						= loc_left
			,parent						= self.base_bone
			,use_custom_shape_bone_size	= True
		)

		hook_ctr.left_handle_control = None
		hook_ctr.right_handle_control = None
		handles = []

		if self.params.CR_curve_controls_for_handles:
			hook_ctr.custom_shape = self.ensure_widget("Circle")

			if self.params.CR_curve_separate_radius:
				radius_control = self.curve_handles.new(
					name						= f"Hook_Radius_{hook_name}_{str(i).zfill(2)}{suffix}"
					,source						= hook_ctr
					,parent						= hook_ctr
					,custom_shape				= self.ensure_widget("Circle")
					,use_custom_shape_bone_size	= True
				)
				radius_control.length *= 0.8
				self.lock_transforms(radius_control, loc=True, rot=True, scale=[False, True, False])
				self.lock_transforms(hook_ctr, loc=False, rot=False, scale=[True, False, True])
				hook_ctr.radius_control = radius_control

			if (i != 0) or cyclic:				# Skip for first hook unless cyclic.
				handle_left_ctr = self.curve_handles.new(
					name		  = f"Hook_L_{hook_name}_{str(i).zfill(2)}{suffix}"
					,head 		  = loc
					,tail		  = loc_left
					,parent		  = hook_ctr
					,custom_shape = self.ensure_widget("CurveHandle")
				)
				hook_ctr.left_handle_control = handle_left_ctr
				handles.append(handle_left_ctr)

			if (i != self.num_controls-1) or cyclic:	# Skip for last hook unless cyclic.
				handle_right_ctr = self.curve_handles.new(
					name 		  = f"Hook_R_{hook_name}_{str(i).zfill(2)}{suffix}"
					,head 		  = loc
					,tail 		  = loc_right
					,parent 	  = hook_ctr
					,custom_shape = self.ensure_widget("CurveHandle")
				)
				hook_ctr.right_handle_control = handle_right_ctr
				handles.append(handle_right_ctr)

			for handle in handles:
				handle.use_custom_shape_bone_size = True
				if self.params.CR_curve_rotatable_handles:
					dsp_bone = self.create_dsp_bone(handle)
					dsp_bone.head = handle.tail.copy()
					dsp_bone.tail = handle.head.copy()

					self.lock_transforms(handle, loc=False, rot=False, scale=[True, False, True])

					dsp_bone.add_constraint('DAMPED_TRACK', subtarget=hook_ctr.name)
					dsp_bone.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)
				else:
					head = handle.head.copy()
					handle.head = handle.tail.copy()
					handle.tail = head

					self.lock_transforms(handle, loc=False)

					handle.add_constraint('DAMPED_TRACK', subtarget=hook_ctr.name)
					handle.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)

		else:
			hook_ctr.custom_shape = self.ensure_widget("CurvePoint")

		return hook_ctr

	def make_hook_modifier(self, cp_i, boneinfo, main_handle=False, left_handle=False, right_handle=False):
		""" Create a Hook modifier on the curve(active object, in edit mode), hooking the control point at a given index to a given bone. The bone must exist. """
		if not boneinfo: return

		# Workaround of T74888, can be removed once D7190 is in master. (Preferably wait until it's in a release build)
		curve_ob = self.params.CR_curve_target
		spline = curve_ob.data.splines[0]
		points = spline.bezier_points
		cp = points[cp_i]

		indices = []
		if main_handle:
			indices.append(cp_i*3 + 1)
		if left_handle:
			indices.append(cp_i*3)
		if right_handle:
			indices.append(cp_i*3 + 2)

		# Set active bone
		bone = self.obj.data.bones.get(boneinfo.name)
		self.obj.data.bones.active = bone

		# If the hook modifier already exists, remove it.
		mod = curve_ob.modifiers.get(boneinfo.name)
		if mod:
			curve_ob.modifiers.remove(mod)

		# Add hook modifier
		old_modifiers = [m.name for m in curve_ob.modifiers]
		hook_m = curve_ob.modifiers.new(name=boneinfo.name, type='HOOK')
		hook_m.vertex_indices_set(indices)
		hook_m.show_expanded = False
		hook_m.show_in_editmode = True
		hook_m.use_apply_on_spline = True

		hook_m.object = self.obj
		hook_m.subtarget = boneinfo.name

		for i in range(len(curve_ob.modifiers)):
			bpy.ops.object.modifier_move_up(modifier=hook_m.name)

	def configure_bones(self):
		self.setup_curve(self.hooks)
		super().configure_bones()

	def setup_curve(self, hooks):
		""" Configure the Hook Modifiers for the curve.
		hooks: List of BoneInfo objects that were created with make_ctrls_for_curve_point().
		curve_ob: The curve object.
		Only single-spline curve is supported. That one spline must have the same number of control points as the number of hooks."""

		curve_ob = self.params.CR_curve_target
		if not curve_ob:
			self.raise_error("Curve object not found!")
		curve_visible = self.ensure_visible(curve_ob)

		assert curve_ob.visible_get(), "Curve object could not be made visible. Perhaps it has a driver on its hide_viewport property that forces it to True?"

		spline = curve_ob.data.splines[0]
		points = spline.bezier_points
		num_points = len(points)

		assert num_points == len(hooks), f"Curve object {curve_ob.name} has {num_points} points, but {len(hooks)} hooks were passed."

		# Disable all modifiers on the curve object
		mod_vis_backup = {}
		for m in curve_ob.modifiers:
			mod_vis_backup[m.name] = m.show_viewport
			m.show_viewport = False

		# Disable all constraints on the curve object
		constraint_vis_backup = {}
		for c in curve_ob.constraints:
			constraint_vis_backup[c.name] = c.mute
			c.mute=True

		bpy.context.view_layer.update()

		for i in range(0, num_points):
			hook_b = hooks[i]
			if not self.params.CR_curve_controls_for_handles:
				self.make_hook_modifier(i, hook_b, main_handle=True, left_handle=True, right_handle=True)
			else:
				self.make_hook_modifier(i, hook_b, main_handle=True)
				self.make_hook_modifier(i, hook_b.left_handle_control, left_handle=True)
				self.make_hook_modifier(i, hook_b.right_handle_control, right_handle=True)

			curve_ob.data.twist_mode = 'Z_UP'

			# Add Radius driver
			data_path = f"splines[0].bezier_points[{i}].radius"
			curve_ob.data.driver_remove(data_path)

			D = curve_ob.data.driver_add(data_path)
			driver = D.driver

			driver.expression = "var"
			my_var = driver.variables.new()
			my_var.name = "var"
			my_var.type = 'TRANSFORMS'

			var_tgt = my_var.targets[0]
			var_tgt.id = self.obj
			var_tgt.transform_space = 'WORLD_SPACE'
			var_tgt.transform_type = 'SCALE_X'
			var_tgt.bone_target = hooks[i].name

			# Add Tilt driver
			data_path = f"splines[0].bezier_points[{i}].tilt"
			curve_ob.data.driver_remove(data_path)

			D = curve_ob.data.driver_add(data_path)
			driver = D.driver

			driver.expression = "var"
			my_var = driver.variables.new()
			my_var.name = "var"
			my_var.type = 'TRANSFORMS'

			var_tgt = my_var.targets[0]
			var_tgt.id = self.obj
			var_tgt.transform_space = 'LOCAL_SPACE'
			var_tgt.transform_type = 'ROT_Y'
			var_tgt.bone_target = hooks[i].name

			if self.params.CR_curve_separate_radius:
				var_tgt.bone_target = hooks[i].radius_control.name

		# Restore modifier visibility on curve object
		for m in curve_ob.modifiers:
			if m.name in mod_vis_backup:
				m.show_viewport = mod_vis_backup[m.name]

		# Restore constraints visibility on the curve object
		for c in curve_ob.constraints:
			c.mute = constraint_vis_backup[c.name]

		curve_visible.restore()

		self.meta_base_bone.rigify_parameters.CR_curve_target = curve_ob

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Curve Hooks", preset=0)
		cls.define_bone_set(params, "Curve Handles", preset=8)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		# TODO: Add "X Symmetry" parameter, when enabled, determine hook bone
		#  sides automatically based on X coordinate sign, and flip bones on
		# one side so mirror posing works as expected.
		# An actual symmetrical curve shape is not enforced, but expected.

		params.CR_curve_show_settings = BoolProperty(
			name		 = "Curve Settings"
			,description = "Reveal settings for the cloud_curve rig type"
		)
		params.CR_curve_hook_name = StringProperty(
			 name		 = "Custom Name"
			,description = "Used in the naming of created bones and objects. If empty, use the base bone's name"
			,default	 = ""
		)
		params.CR_curve_controls_for_handles = BoolProperty(
			 name		 = "Controls for Handles"
			,description = "For every curve point control, create two children that control the handles of that curve point"
			,default	 = False
		)
		params.CR_curve_rotatable_handles = BoolProperty(
			 name		 = "Rotatable Handles"
			,description = "Use a setup which allows handles to be rotated and scaled - Will behave oddly when rotation is done after translation"
			,default	 = False
		)
		params.CR_curve_separate_radius = BoolProperty(
			 name		 = "Separate Radius Control"
			,description = "Create a separate control for controlling the curve points' radii, instead of using the hook control's scale"
			,default	 = False
		)

		params.CR_curve_target = PointerProperty(name="Curve", type=bpy.types.Object, poll=is_curve)

		super().add_parameters(params)

	@classmethod
	def is_bone_set_used(cls, params, set_info):
		# We only want to draw Curve Handles bone set UI if the option for it is enabled.
		if set_info['name'] == "Curve Handles":
			return params.CR_curve_controls_for_handles
		return super().is_bone_set_used(params, set_info)

	@classmethod
	def curve_selector_ui(cls, layout, params):
		curve_ob = params.CR_curve_target
		bad_curve = curve_ob==None or curve_ob.type!='CURVE'

		if not cls.draw_dropdown_menu(layout, params, "CR_curve_show_settings", alert=bad_curve): return layout

		icon = 'ERROR' if bad_curve else 'OUTLINER_OB_CURVE'
		cls.draw_prop(layout, params, 'CR_curve_target', icon=icon)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		cls.curve_selector_ui(layout, params)

		if not params.CR_curve_show_settings: return layout

		cls.draw_prop(layout, params, "CR_curve_hook_name")
		cls.draw_prop(layout, params, "CR_curve_controls_for_handles")
		if params.CR_curve_controls_for_handles:
			cls.draw_prop(layout, params, "CR_curve_rotatable_handles")
			cls.draw_prop(layout, params, "CR_curve_separate_radius")

		return layout

class Rig(CloudCurveRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)
	# Need to do some extra stuff...
	curve_ob = bpy.data.objects.get("cloud_curve")
	bpy.context.scene.collection.objects.link(curve_ob)
	curve_ob.location = bpy.context.scene.cursor.location