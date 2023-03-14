import bpy

from bpy.types import Object, Spline
from typing import List
from ..rig_features.bone import BoneInfo

from bpy.props import BoolProperty, StringProperty, PointerProperty
from mathutils import Matrix, Vector

from .cloud_base import CloudBaseRig
from ..utils import curve as curve_utils

def is_curve(self, obj):
	return obj.type=='CURVE'

class CloudCurveRig(CloudBaseRig):
	"""Create hook controls for an existing bezier curve."""
	relinking_behaviour = "Constraints will be moved to the Curve Root."

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()
		self.initialize_curve_rig()

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

	def relink(self):
		"""Override cloud_base.
		Move constraints from the ORG to the ROOT bone and relink them.
		"""
		org = self.bones_org[0]
		for c in org.constraint_infos:
			self.root_bone.constraint_infos.append(c)
			org.constraint_infos.remove(c)
			for d in c.drivers:
				self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
			c.relink()

	def make_curve_controls(self):
		self.make_curve_root_ctrl()
		self.make_ctrls_for_curve_points()

	def make_curve_root_ctrl(self):
		self.root_bone = self.bone_sets['Curve Handles'].new(
			name						= self.base_bone.replace("ORG", "ROOT")
			,source						= self.bones_org[0]
			,custom_shape				= self.ensure_widget("Cube")
			,use_custom_shape_bone_size = True
		)
		self.bones_org[0].parent = self.root_bone

	def make_ctrls_for_curve_points(self):
		curve_ob = self.params.CR_curve_target

		# Function to convert a location vector in the curve's local space into world space.
		# For some reason this doesn't work when the curve object is parented to something, and we need it to be parented to the root bone kindof.
		# Use matrix_basis instead of matrix_world in case there are constraints on the curve.
		worldspace = lambda loc: (curve_ob.matrix_basis @ Matrix.Translation(loc)).to_translation()

		self.all_hooks: List[List[BoneInfo]] = []
		for spl_i, spline in enumerate(curve_ob.data.splines):
			hooks = []
			for i, cp in enumerate(spline.bezier_points):
				hooks.append(
					self.make_ctrls_for_curve_point(
						loc			= worldspace(cp.co)
						,loc_left	= worldspace(cp.handle_left)
						,loc_right	= worldspace(cp.handle_right)
						,spline_idx	= spl_i
						,point_idx	= i
						,cyclic		= spline.use_cyclic_u
					)
				)
			self.all_hooks.append(hooks)

	def get_opposite_index(self, spline: Spline, point_idx: int, threshold=0.01) -> int:
		_opp_co, opp_idx, offset = curve_utils.find_opposite_point_on_spline(spline, point_idx)
		if offset > threshold:
			self.raise_error("Curve is not symmetrical"
				,note = f"{point_idx} -> {opp_idx} dist: {offset}"
				,description = f"The nearest point to the X-axis flipped coordinate of point {point_idx} is point {opp_idx}.\n Distance: {offset}\n Threshold: {threshold}\nDistance must be lower than the threshold. Make sure the curve is symmetrical along its X axis."
			)
		return opp_idx

	def make_hook_name(self, spline_idx: int, point_idx: int, prefix="") -> str:
		if self.params.CR_curve_hook_name:
			hook_name = self.params.CR_curve_hook_name
		else:
			hook_name = self.base_bone.replace("ORG-", "")
		suffix = self.side_suffix
		if suffix != "":
			suffix = self.naming.suffix_separator + suffix
		
		spline_part = ""
		if len(self.params.CR_curve_target.data.splines) > 1:
			spline_part = f"_{spline_idx}"

		prefix_part = ""
		if prefix:
			prefix_part = "_"+prefix

		point_name = point_idx
		if self.params.CR_curve_x_axis_symmetry:
			spline = self.params.CR_curve_target.data.splines[spline_idx]
			opp_idx = self.get_opposite_index(spline, point_idx)
			if opp_idx == point_idx:
				suffix = ""
			else:
				point_name = min([point_idx, opp_idx])
				x_co = curve_utils.get_spline_points(spline)[point_idx].co.x
				if x_co > 0:
					suffix = ".L"
				elif x_co < 0:
					suffix = ".R"
				else:
					suffix = ""

		return f"Hook{prefix_part}_{hook_name}{spline_part}_{str(point_name).zfill(2)}{suffix}"

	def make_ctrls_for_curve_point(
			self, 
			loc: Vector, 
			loc_left: Vector, 
			loc_right: Vector, 
			spline_idx: int, 
			point_idx: int, 
			cyclic=False
		):
		""" Create hook controls for a bezier curve point defined by three points (loc, loc_left, loc_right). """

		tail = loc_left
		hook_ctr = self.bone_sets['Curve Hooks'].new(
			name						= self.make_hook_name(spline_idx, point_idx)
			,source						= self.bones_org[0]
			,use_custom_shape_bone_size	= False
			,head						= loc
			,tail						= tail
			,parent						= self.bones_org[0]
			,rotation_mode				= 'YZX'
		)
		if self.params.CR_curve_x_axis_symmetry:
			size = (loc - loc_left).length
			hook_ctr.tail = loc + Vector((0, 0, size))
			hook_dsp_ctr = self.bone_sets['Mechanism Bones'].new(
				name = "DSP-"+hook_ctr.name,
				source = hook_ctr,
				head = loc,
				tail = loc_left,
				parent = hook_ctr
			)
			hook_ctr.custom_shape_transform = hook_dsp_ctr

		hook_ctr.left_handle_control = None
		hook_ctr.right_handle_control = None
		handles = []

		if self.params.CR_curve_controls_for_handles:
			hook_ctr.custom_shape = self.ensure_widget("Circle")

			if self.params.CR_curve_separate_radius:
				radius_control = self.bone_sets['Curve Handles'].new(
					name						= self.make_hook_name(spline_idx, point_idx, "Radius")
					,source						= hook_ctr
					,tail						= loc_left
					,use_custom_shape_bone_size	= False
					,custom_shape_scale			= 0.8
					,parent						= hook_ctr
					,custom_shape				= self.ensure_widget("Circle")
				)
				radius_control.length *= 0.8
				self.lock_transforms(radius_control, loc=True, rot=True, scale=[False, True, False])
				if not self.params.CR_curve_x_axis_symmetry:
					self.lock_transforms(hook_ctr, loc=False, rot=False, scale=[True, False, True])
				hook_ctr.radius_control = radius_control

			left_name = "L"
			right_name = "R"
			if self.params.CR_curve_x_axis_symmetry and loc.x > 0:
				left_name, right_name = right_name, left_name
			if (point_idx != 0) or cyclic:				# Skip for first hook unless cyclic.
				handle_left_ctr = self.bone_sets['Curve Handles'].new(
					name		  = self.make_hook_name(spline_idx, point_idx, left_name)
					,source		  = hook_ctr
					,head 		  = loc
					,tail		  = loc_left
					,parent		  = hook_ctr
					,custom_shape = self.ensure_widget("Curve_Handle")
					,use_custom_shape_bone_size	= False
				)
				hook_ctr.left_handle_control = handle_left_ctr
				handles.append(handle_left_ctr)

			if (point_idx != self.num_controls-1) or cyclic:	# Skip for last hook unless cyclic.
				handle_right_ctr = self.bone_sets['Curve Handles'].new(
					name 		  = self.make_hook_name(spline_idx, point_idx, right_name)
					,source		  = hook_ctr
					,head 		  = loc
					,tail 		  = loc_right
					,parent 	  = hook_ctr
					,custom_shape = self.ensure_widget("Curve_Handle")
					,use_custom_shape_bone_size	= False
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
			hook_ctr.custom_shape = self.ensure_widget("Curve_Point")

		return hook_ctr

	def make_hook_modifier(
			self, 
			rig_ob: Object, 
			bonename: str, 
			curve_ob: Object, 
			spline_i: int, 
			point_i: int, 
			main_handle=False, 
			left_handle=False, 
			right_handle=False
		):
		""" Create a Hook modifier on the curve(active object, in edit mode), hooking the control point at a given index to a given bone. The bone must exist. """
		if not bonename: return

		# Workaround of T74888: Re-grab references to curve object, splines and points.
		# A potential fix, D7190 was sadly rejected.
		curve_ob = self.params.CR_curve_target
		idx_offset = 0
		for i in range(0, spline_i):
			idx_offset += len(curve_ob.data.splines[i].bezier_points) * 3

		indices = []
		if main_handle:
			indices.append(idx_offset + point_i*3 + 1)
		if left_handle:
			indices.append(idx_offset + point_i*3)
		if right_handle:
			indices.append(idx_offset + point_i*3 + 2)

		# Set active bone
		bone = rig_ob.data.bones.get(bonename)
		rig_ob.data.bones.active = bone

		hook_m = curve_ob.modifiers.get(bonename)
		if not hook_m:
			# Add hook modifier
			hook_m = curve_ob.modifiers.new(name=bonename, type='HOOK')

		hook_m.vertex_indices_set(indices)
		hook_m.show_expanded = False
		hook_m.show_in_editmode = True
		hook_m.use_apply_on_spline = True

		hook_m.object = rig_ob
		hook_m.subtarget = bonename

	def configure_bones(self):
		self.setup_curve(self.all_hooks)
		super().configure_bones()

	def setup_curve(self, all_hooks: List[List[BoneInfo]]):
		""" Configure the Hook Modifiers for the curve.
		all_hooks: List of List of BoneInfo objects that were created with make_ctrls_for_curve_point().
				Each list corresponds to one curve spline.
		"""

		curve_ob = self.params.CR_curve_target
		if not curve_ob:
			self.raise_error("Curve object not found!")
		curve_visible = self.ensure_visible(curve_ob)

		if not curve_ob.visible_get():
			self.raise_error(f'Curve "{curve_ob.name}" could not be made visible. Perhaps it has a driver on its hide_viewport property that forces it to True?')

		for spline_i, hooks in enumerate(all_hooks):
			self.setup_spline(curve_ob, spline_i, hooks)
		
		curve_visible.restore()

		self.meta_base_bone.rigify_parameters.CR_curve_target = curve_ob

	def setup_spline(self, curve_ob: Object, spline_i: int, hooks: List[BoneInfo]):
		spline = curve_ob.data.splines[spline_i]
		points = spline.bezier_points
		num_points = len(points)

		assert num_points == len(hooks), f"Curve object {curve_ob.name} spline has {num_points} points, but {len(hooks)} hooks were passed."

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

		for point_i in range(0, num_points):
			hook_b = hooks[point_i]
			shared_kwargs = {
				"rig_ob" : self.obj,
				"curve_ob" : self.params.CR_curve_target,
				"spline_i" : spline_i,
				"point_i" : point_i
			}
			if not self.params.CR_curve_controls_for_handles:
				self.make_hook_modifier(
			    				bonename=hook_b.name, 
								main_handle=True, 
								left_handle=True, 
								right_handle=True,
								**shared_kwargs
				)
			else:
				self.make_hook_modifier(
								bonename = hook_b.name, 
								main_handle=True,
								**shared_kwargs
				)
				self.make_hook_modifier(
								bonename=hook_b.left_handle_control.name,
								left_handle=True,
								**shared_kwargs
				)
				self.make_hook_modifier(
								bonename = hook_b.right_handle_control.name, 
								right_handle=True,
								**shared_kwargs
				)

			# Add Radius driver
			data_path = f"splines[0].bezier_points[{point_i}].radius"
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
			var_tgt.bone_target = hooks[point_i].name

			if self.params.CR_curve_separate_radius:
				var_tgt.bone_target = hooks[point_i].radius_control.name

			# Add Tilt driver
			data_path = f"splines[0].bezier_points[{point_i}].tilt"
			curve_ob.data.driver_remove(data_path)

			D = curve_ob.data.driver_add(data_path)
			driver = D.driver

			driver.expression = "-var"
			my_var = driver.variables.new()
			my_var.name = "var"
			my_var.type = 'TRANSFORMS'

			var_tgt = my_var.targets[0]
			var_tgt.id = self.obj
			var_tgt.transform_space = 'LOCAL_SPACE'
			var_tgt.transform_type = 'ROT_Y'
			var_tgt.rotation_mode = hook_b.rotation_mode
			var_tgt.bone_target = hooks[point_i].name

		# Restore modifier visibility on curve object
		for m in curve_ob.modifiers:
			if m.name in mod_vis_backup:
				m.show_viewport = mod_vis_backup[m.name]

		# Restore constraints visibility on the curve object
		for c in curve_ob.constraints:
			c.mute = constraint_vis_backup[c.name]

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Curve Hooks', preset=0)
		cls.define_bone_set(params, 'Curve Handles', preset=8)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

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
		params.CR_curve_x_axis_symmetry = BoolProperty(
			 name		 = "X Axis Symmetry"
			,description = "Controls will be named with .L/.R suffixes based on their X position. A curve object that is symmetrical around its own X 0 point is expected, otherwise results may be unexpected. Useful for character mouths"
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
		"""Since this rig requires a curve object, draw with alert=True otherwise."""
		curve_ob = params.CR_curve_target
		bad_curve = curve_ob==None or curve_ob.type!='CURVE'

		icon = 'ERROR' if bad_curve else 'OUTLINER_OB_CURVE'
		cls.draw_prop(layout, params, 'CR_curve_target', icon=icon)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		cls.curve_selector_ui(layout, params)

		cls.draw_prop(layout, params, "CR_curve_hook_name")
		cls.draw_prop(layout, params, "CR_curve_x_axis_symmetry")
		cls.draw_prop(layout, params, "CR_curve_controls_for_handles")
		if params.CR_curve_controls_for_handles:
			cls.draw_prop(layout, params, "CR_curve_rotatable_handles")
			cls.draw_prop(layout, params, "CR_curve_separate_radius")


class Rig(CloudCurveRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)
	# load_sample_by_file() does not deal with additional dependent objects,
	# so we have to bring the curve object into the scene collection.
	curve_ob = bpy.data.objects.get(("cloud_curve", None))
	context = bpy.context
	context.scene.collection.objects.link(curve_ob)
	curve_ob.location = context.scene.cursor.location