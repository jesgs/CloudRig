"""
This file is executed and loaded into a self-registering text datablock when a
rig is generated with the CloudRig feature set.
It's responsible for drawing rig UI and operators such as IK/FK snapping and
keyframe baking.

Only one instance of this script is required to run in a scene, regardless of how
many CloudRig characters are in the scene.
"""

from typing import List, Dict, Tuple
import bpy, traceback, json, collections, re
from bpy.props import (
						StringProperty, BoolProperty, BoolVectorProperty,
						EnumProperty, PointerProperty, IntProperty
					)
from mathutils import Vector, Matrix
from rna_prop_ui import rna_idprop_quote_path, rna_idprop_ui_prop_update

def is_cloudrig(obj):
	"""Return whether obj is marked as being compatible with this script file."""
	return obj.type=='ARMATURE' and (
			('rig_id' in obj.data and obj.data['rig_id'] == 'cloudrig') or \
			('cloudrig' in obj.data)
		)

def get_rigs():
	""" Find all cloudrig armature objects in the file. """
	return [o for o in bpy.data.objects if o.type=='ARMATURE' and is_cloudrig(o)]

def is_active_cloudrig(context):
	""" If the active object is a cloudrig, return it. """
	rig = context.pose_object or context.object
	if rig and is_cloudrig(rig):
		return rig

def is_active_cloud_metarig(context):
	""" If the active object is a cloud metarig, return it. """
	rig = context.pose_object or context.object
	if rig and rig.type=='ARMATURE' and not is_cloudrig(rig):
		for pb in rig.pose.bones:
			if not hasattr(pb, 'rigify_type'):
				return None
			if 'cloud' in pb.rigify_type:
				return rig

#######################################
###### Keyframe baking framework ######
###### from Rigify ####################

def set_curve_key_interpolation(curves, ipo, key_range=None):
	"Assign the given interpolation value to all curve keys in range."
	for key in flatten_curve_key_set(curves, key_range):
		key.interpolation = ipo

def delete_curve_keys_in_range(curves, key_range=None):
	"Delete all keys of the given curves within the given range."
	for curve in flatten_curve_set(curves):
		points = curve.keyframe_points
		for i in range(len(points), 0, -1):
			key = points[i - 1]
			if key_range is None or key_range[0] <= key.co[0] <= key_range[1]:
				points.remove(key, fast=True)
		curve.update()

def flatten_curve_set(curves):
	"Iterate over all FCurves inside a set of nested lists and dictionaries."
	if curves is None:
		pass
	elif isinstance(curves, bpy.types.FCurve):
		yield curves
	elif isinstance(curves, dict):
		for sub in curves.values():
			yield from flatten_curve_set(sub)
	else:
		for sub in curves:
			yield from flatten_curve_set(sub)

def flatten_curve_key_set(curves, key_range=None):
	"Iterate over all keys of the given fcurves in the specified range."
	for curve in flatten_curve_set(curves):
		for key in curve.keyframe_points:
			if key_range is None or key_range[0] <= key.co[0] <= key_range[1]:
				yield key

def get_curve_frame_set(curves, key_range=None):
	"Compute a set of all time values with existing keys in the given curves and range."
	return set(key.co[0] for key in flatten_curve_key_set(curves, key_range))

def clean_action_empty_curves(action):
	"Delete completely empty curves from the given action."
	action = find_action(action)
	for curve in list(action.fcurves):
		if curve.is_empty:
			action.fcurves.remove(curve)
	action.update_tag()

def find_action(action):
	if isinstance(action, bpy.types.Object):
		action = action.animation_data
	if isinstance(action, bpy.types.AnimData):
		action = action.action
	if isinstance(action, bpy.types.Action):
		return action
	else:
		return None

TRANSFORM_PROPS_LOCATION = frozenset(['location'])
TRANSFORM_PROPS_ROTATION = frozenset(['rotation_euler', 'rotation_quaternion', 'rotation_axis_angle'])
TRANSFORM_PROPS_SCALE = frozenset(['scale'])
TRANSFORM_PROPS_ALL = frozenset(TRANSFORM_PROPS_LOCATION | TRANSFORM_PROPS_ROTATION | TRANSFORM_PROPS_SCALE)

class FCurveTable(object):
	"Table for efficient lookup of FCurves by properties."

	def __init__(self):
		self.curve_map = collections.defaultdict(dict)

	def index_curves(self, curves):
		for curve in curves:
			index = curve.array_index
			if index < 0:
				index = 0
			self.curve_map[curve.data_path][index] = curve

	def get_prop_curves(self, ptr, prop_path):
		"Returns a dictionary from array index to curve for the given property, or Null."
		return self.curve_map.get(ptr.path_from_id(prop_path))

	def list_all_prop_curves(self, ptr_set, path_set):
		"Iterates over all FCurves matching the given object(s) and properti(es)."
		if isinstance(ptr_set, bpy.types.bpy_struct):
			ptr_set = [ptr_set]
		for ptr in ptr_set:
			for path in path_set:
				curves = self.get_prop_curves(ptr, path)
				if curves:
					yield from curves.values()

	def get_custom_prop_curves(self, ptr, prop):
		return self.get_prop_curves(ptr, rna_idprop_quote_path(prop))

class ActionCurveTable(FCurveTable):
	"Table for efficient lookup of Action FCurves by properties."

	def __init__(self, action):
		super().__init__()
		self.action = find_action(action)
		if self.action:
			self.index_curves(self.action.fcurves)

def nla_tweak_to_scene(anim_data, frames, invert=False):
	"Convert a frame value or list between scene and tweaked NLA strip time."
	if frames is None:
		return None
	elif anim_data is None or not anim_data.use_tweak_mode:
		return frames
	elif isinstance(frames, (int, float)):
		return anim_data.nla_tweak_strip_time_to_scene(frames, invert=invert)
	else:
		return type(frames)(
			anim_data.nla_tweak_strip_time_to_scene(v, invert=invert) for v in frames
		)

def add_flags_if_set(base, new_flags):
	"Add more flags if base is not None."
	if base is None:
		return None
	else:
		return base | new_flags

def get_keying_flags(context):
	"Retrieve the general keyframing flags from user preferences."
	prefs = context.preferences
	ts = context.scene.tool_settings
	flags = set()
	# Not adding INSERTKEY_VISUAL
	if prefs.edit.use_keyframe_insert_needed:
		flags.add('INSERTKEY_NEEDED')
	if prefs.edit.use_insertkey_xyz_to_rgb:
		flags.add('INSERTKEY_XYZ_TO_RGB')
	if ts.use_keyframe_cycle_aware:
		flags.add('INSERTKEY_CYCLE_AWARE')
	return flags

def get_autokey_flags(context, ignore_keyset=False):
	"Retrieve the Auto Keyframe flags, or None if disabled."
	ts = context.scene.tool_settings
	if ts.use_keyframe_insert_auto and (ignore_keyset or not ts.use_keyframe_insert_keyingset):
		flags = get_keying_flags(context)
		if context.preferences.edit.use_keyframe_insert_available:
			flags.add('INSERTKEY_AVAILABLE')
		if ts.auto_keying_mode == 'REPLACE_KEYS':
			flags.add('INSERTKEY_REPLACE')
		return flags
	else:
		return None

def keyframe_transform_properties(obj, bone_name, keyflags, *, ignore_locks=False, no_loc=False, no_rot=False, no_scale=False):
	"Keyframe transformation properties, taking flags and mode into account, and avoiding keying locked channels."
	bone = obj.pose.bones[bone_name]

	def keyframe_channels(prop, locks):
		if ignore_locks or not all(locks):
			if ignore_locks or not any(locks):
				bone.keyframe_insert(prop, group=bone_name, options=keyflags)
			else:
				for i, lock in enumerate(locks):
					if not lock:
						bone.keyframe_insert(prop, index=i, group=bone_name, options=keyflags)

	if not (no_loc or bone.bone.use_connect):
		keyframe_channels('location', bone.lock_location)

	if not no_rot:
		if bone.rotation_mode == 'QUATERNION':
			keyframe_channels('rotation_quaternion', get_4d_rotlock(bone))
		elif bone.rotation_mode == 'AXIS_ANGLE':
			keyframe_channels('rotation_axis_angle', get_4d_rotlock(bone))
		else:
			keyframe_channels('rotation_euler', bone.lock_rotation)

	if not no_scale:
		keyframe_channels('scale', bone.lock_scale)

def set_transform_from_matrix(obj, bone_name, target_matrix, *, space='POSE', ignore_locks=False, no_loc=False, no_rot=False, no_scale=False, keyflags=None):
	"Apply the matrix to the transformation of the bone, taking locked channels, mode and certain constraints into account, and optionally keyframe it."
	bone = obj.pose.bones[bone_name]

	# Save the old values of the local transforms
	old_loc = Vector(bone.location)
	old_rot_euler = Vector(bone.rotation_euler)
	old_rot_quat = Vector(bone.rotation_quaternion)
	old_rot_axis = Vector(bone.rotation_axis_angle)
	old_scale = Vector(bone.scale)

	# Set the bone transforms in pose space in a way that accounts for additive constraints
	if space != 'POSE':
		target_matrix = obj.convert_space(pose_bone=bone, matrix=target_matrix, from_space=space, to_space='POSE')

	pose_matrix_pre_constraints = obj.convert_space(pose_bone=bone, matrix=bone.matrix_basis, from_space='LOCAL', to_space='POSE')
	pose_matrix_post_constraints = bone.matrix
	constraint_delta = pose_matrix_post_constraints - pose_matrix_pre_constraints

	bone.matrix = target_matrix - constraint_delta

	# Restore locked properties
	def restore_channels(prop, old_vec, locks, extra_lock):
		if extra_lock or (not ignore_locks and all(locks)):
			setattr(bone, prop, old_vec)
		else:
			if not ignore_locks and any(locks):
				new_vec = Vector(getattr(bone, prop))

				for i, lock in enumerate(locks):
					if lock:
						new_vec[i] = old_vec[i]

				setattr(bone, prop, new_vec)

	restore_channels('location', old_loc, bone.lock_location, no_loc or bone.bone.use_connect)

	if bone.rotation_mode == 'QUATERNION':
		restore_channels('rotation_quaternion', old_rot_quat, get_4d_rotlock(bone), no_rot)
		bone.rotation_axis_angle = old_rot_axis
		bone.rotation_euler = old_rot_euler
	elif bone.rotation_mode == 'AXIS_ANGLE':
		bone.rotation_quaternion = old_rot_quat
		restore_channels('rotation_axis_angle', old_rot_axis, get_4d_rotlock(bone), no_rot)
		bone.rotation_euler = old_rot_euler
	else:
		bone.rotation_quaternion = old_rot_quat
		bone.rotation_axis_angle = old_rot_axis
		restore_channels('rotation_euler', old_rot_euler, bone.lock_rotation, no_rot)

	restore_channels('scale', old_scale, bone.lock_scale, no_scale)

	# Keyframe properties
	if keyflags is not None:
		keyframe_transform_properties(
			obj, bone_name, keyflags, ignore_locks=ignore_locks,
			no_loc=no_loc, no_rot=no_rot, no_scale=no_scale
		)

def get_custom_property_value(rig, bone_name, prop_id):
	prop_bone = rig.pose.bones.get(bone_name)
	assert prop_bone, f"Bone snapping failed: Properties bone {bone_name} not found.)"
	assert prop_id in prop_bone, f"Bone snapping failed: Bone {bone_name} has no property {bone_id}"
	return prop_bone[prop_id]

def set_custom_property_value(obj, bone_name, prop, value, *, keyflags=None):
	"Assign the value of a custom property, and optionally keyframe it."
	bone = obj.pose.bones[bone_name]
	bone[prop] = value
	rna_idprop_ui_prop_update(bone, prop)
	if keyflags is not None:
		bone.keyframe_insert(rna_idprop_quote_path(prop), group=bone.name, options=keyflags)

class RigifyOperatorMixinBase:
	bl_options = {'UNDO', 'INTERNAL'}

	def init_invoke(self, context):
		"Override to initialize the operator before invoke."

	def init_execute(self, context):
		"Override to initialize the operator before execute."

	def before_save_state(self, context, rig):
		"Override to prepare for saving state."

	def after_save_state(self, context, rig):
		"Override to undo before_save_state."

class RigifyBakeKeyframesMixin(RigifyOperatorMixinBase):
	"""Basic framework for an operator that updates a set of keyed frames."""

	@classmethod
	def poll(cls, context):
		return context.mode=='POSE'

	def invoke(self, context, event):
		self.init_invoke(context)

		self.invoked = True
		if hasattr(self, 'draw'):
			return context.window_manager.invoke_props_dialog(self)
		else:
			return context.window_manager.invoke_confirm(self, event)

	def init_execute(self, context):
		if not hasattr(self, 'invoked'):
			# Ensure init_invoke has run, even if the operator is called from Python.
			self.init_invoke(context)

	def execute(self, context):
		self.init_execute(context)
		self.bake_init(context)

		curves = self.execute_scan_curves(context, self.bake_rig)

		if self.report_bake_empty():
			return {'CANCELLED'}

		try:
			save_state = self.bake_save_state(context)

			range, range_raw = self.bake_clean_curves_in_range(context, curves)

			self.execute_before_apply(context, self.bake_rig, range, range_raw)

			self.bake_apply_state(context, save_state)

		except Exception as e:
			traceback.print_exc()
			self.report({'ERROR'}, 'Exception: ' + str(e))

		return {'FINISHED'}

	# Default behavior implementation
	def bake_init(self, context):
		self.bake_rig = context.active_object
		self.bake_anim = self.bake_rig.animation_data
		# self.bake_frame_range = RIGIFY_OT_get_frame_range.get_range(context)
		# self.bake_frame_range_raw = self.nla_to_raw(self.bake_frame_range)
		self.bake_curve_table = ActionCurveTable(self.bake_rig)
		self.bake_current_frame = context.scene.frame_current
		self.bake_frames_raw = set()

		self.keyflags = get_keying_flags(context)
		self.keyflags_switch = None

		if False:#context.window_manager.rigify_transfer_use_all_keys:
			self.bake_add_curve_frames(self.bake_curve_table.curve_map)

	def execute_scan_curves(self, context, obj):
		"Override to register frames to be baked, and return curves that should be cleared."
		raise NotImplementedError()

	def bake_save_state(self, context) -> Dict[int, Tuple[List[Matrix], List[Vector]]]:
		"Scans frames and collects data for baking before changing anything."
		rig = self.bake_rig
		scene = context.scene

		save_state = dict()

		try:
			self.before_save_state(context, rig)

			for frame in self.bake_frames:
				scene.frame_set(frame)
				save_state[frame] = self.save_frame_state(context, rig)

		finally:
			self.after_save_state(context, rig)

		return save_state

	def execute_before_apply(self, context, obj, range, range_raw):
		"Override to execute code one time before the bake apply frame scan."
		pass

	def bake_apply_state(self, context, save_state: Dict[int, Tuple[List[Matrix], List[Vector]]]):
		"Scans frames and applies the baking operation."
		rig = self.bake_rig
		scene = context.scene

		for frame in self.bake_frames:
			scene.frame_set(frame)
			self.apply_frame_state(context, rig, save_state.get(frame))

		clean_action_empty_curves(self.bake_rig)
		scene.frame_set(self.bake_current_frame)

	# Utilities

	def bake_get_bone(self, bone_name):
		"Get pose bone by name."
		return self.bake_rig.pose.bones[bone_name]

	def bake_get_bones(self, bone_names):
		"Get multiple pose bones by name."
		if isinstance(bone_names, (list, set)):
			return [self.bake_get_bone(name) for name in bone_names]
		else:
			return self.bake_get_bone(bone_names)

	def bake_get_all_bone_curves(self, bone_names, props):
		"Get a list of all curves for the specified properties of the specified bones."
		return list(self.bake_curve_table.list_all_prop_curves(self.bake_get_bones(bone_names), props))

	def bake_get_all_bone_custom_prop_curves(self, bone_names, props):
		"Get a list of all curves for the specified custom properties of the specified bones."
		return self.bake_get_all_bone_curves(bone_names, [rna_idprop_quote_path(p) for p in props])

	def bake_get_bone_prop_curves(self, bone_name, prop):
		"Get an index to curve dict for the specified property of the specified bone."
		return self.bake_curve_table.get_prop_curves(self.bake_get_bone(bone_name), prop)

	def bake_get_bone_custom_prop_curves(self, bone_name, prop):
		"Get an index to curve dict for the specified custom property of the specified bone."
		return self.bake_curve_table.get_custom_prop_curves(self.bake_get_bone(bone_name), prop)

	def bake_add_curve_frames(self, curves):
		"Register frames keyed in the specified curves for baking."
		self.bake_frames_raw |= get_curve_frame_set(curves, self.bake_frame_range_raw)

	def bake_add_bone_frames(self, bone_names, props=TRANSFORM_PROPS_ALL):
		"Register frames keyed for the specified properties of the specified bones for baking."
		curves = self.bake_get_all_bone_curves(bone_names, props)
		self.bake_add_curve_frames(curves)
		return curves

	def bake_replace_custom_prop_keys_constant(self, bone, prop, new_value):
		"If the property is keyframed, delete keys in bake range and re-key as Constant."
		prop_curves = self.bake_get_bone_custom_prop_curves(bone, prop)

		if prop_curves and 0 in prop_curves:
			range_raw = self.nla_to_raw(self.get_bake_range())
			delete_curve_keys_in_range(prop_curves, range_raw)
			set_custom_property_value(self.bake_rig, bone, prop, new_value, keyflags={'INSERTKEY_AVAILABLE'})
			set_curve_key_interpolation(prop_curves, 'CONSTANT', range_raw)

	def bake_add_frames_done(self):
		"Computes and sets the final set of frames to bake."
		frames = self.nla_from_raw(self.bake_frames_raw)
		self.bake_frames = sorted(set(map(round, frames)))

	def nla_from_raw(self, frames):
		"Convert frame(s) from inner action time to scene time."
		return nla_tweak_to_scene(self.bake_anim, frames)

	def nla_to_raw(self, frames):
		"Convert frame(s) from scene time to inner action time."
		return nla_tweak_to_scene(self.bake_anim, frames, invert=True)

	def is_bake_empty(self):
		return len(self.bake_frames_raw) == 0

	def report_bake_empty(self):
		self.bake_add_frames_done()
		if self.is_bake_empty():
			self.report({'WARNING'}, 'No keys to bake.')
			return True
		return False

	def get_bake_range(self):
		"Returns the frame range that is being baked."
		if self.bake_frame_range:
			return self.bake_frame_range
		else:
			frames = self.bake_frames
			return (frames[0], frames[-1])

	def get_bake_range_pair(self):
		"Returns the frame range that is being baked, both in scene and action time."
		range = self.get_bake_range()
		return range, self.nla_to_raw(range)

	def bake_clean_curves_in_range(self, context, curves):
		"Deletes all keys from the given curves in the bake range."
		range, range_raw = self.get_bake_range_pair()

		context.scene.frame_set(range[0])
		delete_curve_keys_in_range(curves, range_raw)

		return range, range_raw

#######################################
##### Keyframe Baking Operators #######
#######################################

def get_bones(rig, names):
	""" Return a list of pose bones from a string of bone names in json format. """
	return list(filter(None, map(rig.pose.bones.get, json.loads(names))))

class Params_SnapBase:
	"""A non-Operator class must be used to properly inherit operator parameters as annotations.
	Not sure why."""
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")
	bake_every_frame: BoolProperty(
		name		 = "Bake Every Frame"
		,description = "Insert a keyframe on every frame of the affected bones, rather than only frames which are keyframed on the source bones. Results in a more accurate bake, but takes longer and is harder to edit afterwards"
		,default	 = True
	)

	bones:		  StringProperty(name="Control Bones")
	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

class CloudRigSnapBakeMixin(Params_SnapBase, RigifyBakeKeyframesMixin):
	""" Extend Rigify's keyframe baking with the ability to select the frame range
		as part of the operator, make baking optional,
		and add the ability to affect more than a single bone.
	"""
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		return context.pose_object

	### Override some inherited functions
	def init_invoke(self, context):
		self.frame_start = context.scene.frame_start
		self.frame_end = context.scene.frame_end
		self.bone_names = json.loads(self.bones)

	def bake_init(self, context):
		# Override to use operator's frame range instead of Rigify's globally set range.
		super().bake_init(context)
		self.bake_frame_range = (self.frame_start, self.frame_end)
		self.bake_frame_range_raw = self.nla_to_raw(self.bake_frame_range)

	def execute_scan_curves(self, context, obj):
		"Register frames to be baked, and return curves that should be cleared."
		if self.bake_every_frame:
			self.bake_frames_raw = [i for i in range(self.frame_start, self.frame_end)]
		else:
			self.bake_add_bone_frames(self.bone_names)
		return None

	def set_selection(self, context, bones):
		if self.select_bones:
			for b in context.selected_pose_bones:
				b.bone.select = False
			for b in bones:
				b.bone.select = True

class CLOUDRIG_OT_snap_bake(CloudRigSnapBakeMixin, Params_SnapBase, bpy.types.Operator):
	""" Toggle a custom property while ensuring that some bones stay in place. """
	bl_idname = "pose.cloudrig_snap_bake"
	bl_label = "Snap And Bake Bones"

	def draw_affected_bones(self, layout, context):
		bone_column = layout.column(align=True)
		bone_column.label(text="Affected bones:")
		for b in self.bone_names:
			bone_column.label(text=f"{' '*10} {b}")
		# bone_column.label(text=f"Affected property:")
		# bone_column.label(text=f'    pose.bones["{self.prop_bone}"]["{self.prop_id}"]')

	def draw(self, context):
		layout = self.layout

		self.layout.prop(self, 'do_bake')
		split = layout.split(factor=0.1)
		split.row()
		col = split.column()
		if self.do_bake:
			time_row = col.row(align=True)
			time_row.prop(self, 'frame_start')
			time_row.prop(self, 'frame_end')
			col.row().prop(self, 'bake_every_frame')

		self.draw_affected_bones(layout, context)

	def execute(self, context):
		rig = context.pose_object or context.active_object
		self.keyflags = get_autokey_flags(context, ignore_keyset=True)
		self.keyflags_switch = add_flags_if_set(self.keyflags, {'INSERTKEY_AVAILABLE'})

		ret = {'FINISHED'}
		if self.do_bake:
			ret = super().execute(context)
		else:
			self.init_execute(context)
			self.bake_init(context)

			try:
				frame_state = self.save_frame_state(context, rig)
				self.after_save_state(context, rig)
				self.apply_frame_state(context, rig, frame_state)

			except Exception as e:
				traceback.print_exc()
				self.report({'ERROR'}, 'Exception: ' + str(e))

		bones = get_bones(rig, self.bones)
		self.set_selection(context, bones)

		return ret

	def save_frame_state(self, context, rig, bone_names=None) -> Tuple[List[Matrix], List[Vector]]:
		"""Return the Pose Space matrices of the affected bones so they can be restored later."""
		if not bone_names:
			bone_names = self.bone_names

		matrices = []
		scales = []
		for bn in bone_names:
			pb = rig.pose.bones.get(bn)
			assert pb, "Bone does not exist: " + bn
			matrices.append(pb.matrix.copy())
			scales.append(pb.scale.copy())

		return matrices, scales

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value.
		It is expected that the rig has drivers which causes this property value
		change to affect the bones' transforms."""
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		if self.do_bake:
			# If we want the snapping to affect existing animation, rather than just the current pose.
			any_curves_on_property = self.bake_get_bone_prop_curves(self.prop_bone, f'["{self.prop_id}"]')
			if any_curves_on_property:
				self.bake_replace_custom_prop_keys_constant(
					self.prop_bone, self.prop_id, 1-value
				)
		else:
			set_custom_property_value(
				rig, self.prop_bone, self.prop_id, 1-value,
				keyflags=self.keyflags_switch
			)
		context.view_layer.update()

class CLOUDRIG_OT_switch_parent_bake(CLOUDRIG_OT_snap_bake, Params_SnapBase):
	"""Extend CLOUDRIG_OT_snap_bake with a parent selector."""
	bl_idname = "pose.cloudrig_switch_parent_bake"
	bl_label = "Apply Switch Parent To Keyframes"
	bl_description = "Switch parent over a frame range, adjusting keys to preserve the bone position and orientation"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	parent_names: StringProperty(name="Parent Names")

	def parent_items(self, context):
		parents = json.loads(self.parent_names)
		items = [(str(i), name, name) for i, name in enumerate(parents)]
		return items

	selected: EnumProperty(
		name = "Selected Parent",
		items = parent_items
	)

	def draw(self, context):
		self.layout.prop(self, 'selected', text='')
		super().draw(context)

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value."""
		# value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		if self.do_bake:
			self.bake_replace_custom_prop_keys_constant(
				self.prop_bone, self.prop_id, int(self.selected)
			)
		else:
			set_custom_property_value(
				rig, self.prop_bone, self.prop_id, int(self.selected),
				keyflags=self.keyflags_switch
			)
		context.view_layer.update()

class Params_SnapMapped:
	"""A non-Operator class must be used to properly inherit operator parameters as annotations.
	Not sure why."""
	map_on:		  StringProperty()		# Bone name dictionary to use when the property is toggled ON.
	map_off:	  StringProperty()		# Bone name dictionary to use when the property is toggled OFF.

	hide_on:	  StringProperty()		# List of bone names to hide when property is toggled ON.
	hide_off:	  StringProperty()		# List of bone names to hide when property is toggled OFF.

class CLOUDRIG_OT_snap_mapped_bake(CLOUDRIG_OT_snap_bake, Params_SnapBase, Params_SnapMapped):
	""" Extend CLOUDRIG_OT_snap_bake with the ability to snap a list of bones
		to another (equal length) list of bones.
	"""

	bl_idname = "pose.cloudrig_snap_mapped_bake"
	bl_label = "Snap And Bake Bones (Mapped)"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	def init_invoke(self, context):
		rig = context.pose_object or context.active_object
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)

		map_on = json.loads(self.map_on)
		map_off = json.loads(self.map_off)

		self.bone_map = map_off if value==1 else map_on
		bone_names = [t[0] for t in self.bone_map]
		self.bones = json.dumps(bone_names)
		super().init_invoke(context)	# This creates self.bone_names based on self.bones.

	def draw_affected_bones(self, layout, context):
		bone_column = layout.column(align=True)
		bone_column.label(text="Snapped bones:")
		for from_bone, to_bone in self.bone_map:
			bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		if not bone_names:
			bone_names = [t[1] for t in self.bone_map]
		return super().save_frame_state(context, rig, bone_names)

	def execute_scan_curves(self, context, obj):
		"Register frames to be baked, and return curves that should be cleared."

		if self.bake_every_frame:
			self.bake_frames_raw = [i for i in range(self.frame_start, self.frame_end)]
		else:
			bone_names = [t[1] for t in self.bone_map]
			self.bake_add_bone_frames(bone_names)
			bone_names = [t[0] for t in self.bone_map]
			self.bake_add_bone_frames(bone_names)
		return None

	def apply_frame_state(self, context, rig, save_state: Tuple[List[Matrix], List[Vector]]):
		"""Set the transform matrices of the map_from bones to the map_to bones"""
		matrices, scales = save_state
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, # space='WORLD'
				keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)
			pb = rig.pose.bones.get(bone_name)
			# For some reason, reading and writing the matrix can result in 
			# significant changes to local scale, even when nothing is scaled.
			# So, just keep a copy of the local scale and restore it after applying the matrix.
			pb.scale = scales[i]
			context.evaluated_depsgraph_get().update()	# This matters!!!!

class CLOUDRIG_OT_ikfk_bake(CLOUDRIG_OT_snap_mapped_bake, Params_SnapBase, Params_SnapMapped):
	""" This should extend CLOUDRIG_OT_snap_mapped_bake with special treatment
		for the IK elbow.
	"""

	bl_idname = "pose.cloudrig_toggle_ikfk_bake"
	bl_label = "Toggle And Bake IK/FK"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	ik_pole:	StringProperty()
	fk_first:	StringProperty()
	fk_last:	StringProperty()

	def init_invoke(self, context):
		rig = context.object

		self.pole = rig.pose.bones.get(self.ik_pole)	# Can be None.
		prop_value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		self.is_pole = prop_value==0 and self.pole!=None

		super().init_invoke(context)

		if self.is_pole:
			self.bone_names.append(self.pole.name)
			self.bones = json.dumps(self.bone_names)

	def save_frame_state(self, context, rig, bone_names=None) -> Tuple[List[Matrix], List[Vector]]:
		matrices, scales = super().save_frame_state(context, rig)
		if self.is_pole:
			matrices.append(self.get_pole_target_matrix())
			scales.append(rig.pose.bones.get(self.ik_pole).scale)

		return matrices, scales

	def get_pole_target_matrix(self):
		""" Find the matrix where the IK pole should be. """
		""" This is only accurate when the bone chain lies perfectly on a plane
			and the IK Pole Angle is divisible by 90.
			This should be the case for a correct IK chain!
		"""

		rig = self.bake_rig

		fk_first = rig.pose.bones.get(self.fk_first)
		fk_last = rig.pose.bones.get(self.fk_last)
		assert fk_first and fk_last, f"Can't calculate pole target location due to one of these FK bones missing: {self.fk_first}, {self.fk_last}"

		chain_length = fk_first.vector.length + fk_last.vector.length
		pole_distance = chain_length/2

		pole_direction = (fk_first.vector - fk_last.vector).normalized()

		pole_loc = fk_first.tail + pole_direction * pole_distance

		mat = self.pole.matrix.copy()
		mat.translation = pole_loc
		return mat

#######################################
######## Convenience Operators ########
#######################################

class CLOUDRIG_OT_copy_property(bpy.types.Operator):
	"""Set the value of a property on all other CloudRig rigs in the scene"""
	# Currently used for the rig Quality setting, to easily switch all characters to Render or Animation quality.
	bl_idname = "object.cloudrig_copy_property"
	bl_label = "Set Property value on All CloudRigs"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	prop_bone: StringProperty()
	prop_id: StringProperty()

	@classmethod
	def poll(cls, context):
		return (is_active_cloudrig(context) is not None) and (context.pose_object or context.active_object)

	def invoke(self, context, event):
		# Collect and save references to rigs in the scene which have this property somewhere on the rig.
		# TODO: Add an assert that prop_bone and prop_id are found in context.object.
		self.rig_bones = {context.object.name : self.prop_bone}
		for rig in context.scene.objects:
			if rig.type!='ARMATURE' or 'cloudrig' not in rig.data: continue
			for pb in rig.pose.bones:
				if self.prop_id in pb:
					self.rig_bones[rig.name] = pb.name

		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		rig = context.pose_object or context.active_object
		prop_value = rig.pose.bones[self.prop_bone][self.prop_id]

		layout.label(text=f"{self.prop_id} property will be set to {prop_value} on these bones:")
		for rigname, bonename in self.rig_bones.items():
			split = layout.split(factor=0.4)
			split.label(text=rigname, icon='ARMATURE_DATA')
			split.label(text=bonename, icon='BONE_DATA')

	def execute(self, context):
		rig = context.pose_object or context.active_object
		prop_value = rig.pose.bones[self.prop_bone][self.prop_id]

		for rigname, bonename in self.rig_bones.items():
			rig = context.scene.objects[rigname]
			pb = rig.pose.bones[bonename]
			pb[self.prop_id] = prop_value

		return {'FINISHED'}

class CLOUDRIG_OT_keyframe_all_settings(bpy.types.Operator):
	"""Keyframe all rig settings that are being drawn in the below UI"""
	bl_idname = "pose.cloudrig_keyframe_all_settings"
	bl_label = "Keyframe CloudRig Settings"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		return (is_active_cloudrig(context) is not None) and (context.pose_object or context.active_object)

	def execute(self, context):
		rig = context.pose_object or context.active_object
		data = rig.data

		for area_name in area_names:
			if area_name not in data: continue
			area_dict = data[area_name].to_dict()
			for row_dict in list(area_dict.values()):
				for col_dict in list(row_dict.values()):
					assert 'prop_bone' in col_dict and 'prop_id' in col_dict, "Rig UI info entry must have prop_bone and prop_id."
					prop_bone_name = col_dict['prop_bone']
					prop_id = col_dict['prop_id']

					prop_bone = rig.pose.bones.get(prop_bone_name)
					assert prop_bone, f"Property bone non-existent: {prop_bone_name}"

					value = prop_bone[prop_id]
					if type(value) not in (int, float):
						continue
					set_custom_property_value(rig, prop_bone.name, prop_id, value, keyflags=get_keying_flags(context))

		return {'FINISHED'}

class CLOUDRIG_OT_reset_rig(bpy.types.Operator):
	"""Reset all bone transforms and custom properties to their default values"""
	bl_idname = "pose.cloudrig_reset"
	bl_label = "Reset Rig"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	reset_transforms: BoolProperty(name="Transforms", default=True, description="Reset bone transforms")
	reset_props: BoolProperty(name="Properties", default=True, description="Reset custom properties")
	selection_only: BoolProperty(name="Selected Only", default=False, description="Affect selected bones rather than all bones")

	@classmethod
	def poll(cls, context):
		return (is_active_cloudrig(context) is not None) and (context.pose_object or context.active_object)

	def invoke(self, context, event):
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def execute(self, context):
		rig = context.pose_object or context.active_object
		bones = rig.pose.bones
		if self.selection_only:
			bones = context.selected_pose_bones
		for pb in bones:
			if self.reset_transforms:
				pb.location = ((0, 0, 0))
				pb.rotation_euler = ((0, 0, 0))
				pb.rotation_quaternion = ((1, 0, 0, 0))
				pb.scale = ((1, 1, 1))

			if self.reset_props and len(pb.keys()) > 0:
				# Reset custom property values to their default value
				for key in pb.keys():
					if key.startswith("$"): continue

					try:
						ui_data = pb.id_properties_ui(key)
						if not ui_data: continue
						ui_data = ui_data.as_dict()
						if not 'default' in ui_data: continue
					except TypeError:
						# Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
						pass

					if type(pb[key]) not in (float, int): continue
					pb[key] = ui_data['default']

		return {'FINISHED'}

#######################################
###### Override Troubleshooting #######
##### TODO: Remove after Sprites. #####
#######################################

class CLOUDRIG_OT_delete_override_leftovers(bpy.types.Operator):
	"""Delete the Override Resync Leftovers (Warning! Might lose your data!)"""
	bl_idname = "object.cloudrig_delete_leftovers"
	bl_label = "Delete Override Leftovers"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		return 'OVERRIDE_RESYNC_LEFTOVERS' in bpy.data.collections

	def invoke(self, context, event):
		if context.active_pose_bone and context.active_pose_bone.bone_group:
			self.bone_group = context.active_pose_bone.bone_group.name

		if len(context.object.pose.bone_groups) == 0:
			self.operation = 'NEW'

		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		col = layout.column()
		col.alert = True
		col.row().label(text="This will nuke the OVERRIDE_RESYNC_LEFTOVERS")
		col.row().label(text="collection and its contents. You could lose data!")

	def execute(self, context):
		bpy.data.collections.remove(bpy.data.collections['OVERRIDE_RESYNC_LEFTOVERS'])
		return {'FINISHED'}

class CLOUDRIG_OT_override_fix_name(bpy.types.Operator):
	"""Try to ensure the name of this object or collection ends with the correct suffix"""
	# We hijack the Rigify Log for this, why not...
	bl_idname = "object.cloudrig_fix_name"
	bl_label = "Fix Name"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	old_name: StringProperty()
	new_name: StringProperty()
	is_collection: BoolProperty(default=False, description="Whether the target for renaming is a collection rather than an object")

	def execute(self, context):
		rig = context.object

		# In all the get() functions here we pass a tuple to make sure we get the LOCAL object based on the name
		# This is to work around potential clashing names
		# https://docs.blender.org/api/master/info_gotcha.html#library-collisions

		if not self.is_collection:
			obj = bpy.data.objects.get((self.old_name, None))
			occupied = bpy.data.objects.get((self.new_name, None))
			if occupied:
				self.report({'ERROR'}, f"Target name {self.new_name} is already taken, cancelling!")
				return {'CANCELLED'}
			obj.name = self.new_name
		else:
			coll = bpy.data.collections.get((self.old_name, None))
			occupied = bpy.data.collections.get((self.new_name, None))
			if occupied:
				self.report({'ERROR'}, f"Target name {self.new_name} is already taken, cancelling!")
				return {'CANCELLED'}
			coll.name = self.new_name

		return {'FINISHED'}

class CLOUDRIG_PT_base(bpy.types.Panel):
	"""Base class for all CloudRig sidebar panels."""
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = 'CloudRig'
	bl_options = {'DEFAULT_CLOSED'}

	@classmethod
	def poll(cls, context):
		return is_active_cloudrig(context) is not None

	def draw(self, context):
		pass

def has_number_suffix(name):
	return all([char in "0123456789" for char in name[-3:]]) and name[-4]=="."

class CLOUDRIG_PT_troubleshoot_overrides(CLOUDRIG_PT_base):
	bl_idname = "CLOUDRIG_PT_troubleshoot_overrides"
	bl_label = "Troubleshoot"

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False

		rig = is_active_cloudrig(context)
		if rig.override_library: return True

	@staticmethod
	def draw_override_purge(layout):
		"""Check if an 'OVERRIDE_RESYNC_LEFTOVERS' collection exists and
		draw a button to delete it.
		"""
		if 'OVERRIDE_RESYNC_LEFTOVERS' in bpy.data.collections:
			row = layout.row()
			row.alert=True
			row.operator(CLOUDRIG_OT_delete_override_leftovers.bl_idname, icon='TRASH')

		purge = layout.operator('outliner.orphans_purge', text="Purge Unused", icon='ORPHAN_DATA')
		purge.do_recursive=True

	@staticmethod
	def get_override_collection(obj):
		"""Find first overridden collection that contains obj."""
		owner_collection = obj.users_collection[0]
		while owner_collection.override_library!=None:
			for c in bpy.data.collections:
				if owner_collection in c.children[:]:
					if c.override_library==None:
						break
					owner_collection = c
			break
		return owner_collection

	@staticmethod
	def draw_troubleshoot_name(layout, thing, *, suffix, is_collection):
		icon = 'OUTLINER_COLLECTION' if is_collection else 'OBJECT_DATAMODE'
		if (suffix=="" and has_number_suffix(thing.name)) or (suffix!="" and not thing.name.endswith(suffix)):
			split = layout.split(factor=0.3)
			split.row().label(text="Wrong suffix: ")
			split = split.row().split(factor=0.9)
			split.row().label(text=thing.name, icon=icon)
			op = split.row().operator(
				CLOUDRIG_OT_override_fix_name.bl_idname
				,text = ""
				,icon = 'FILE_TEXT'
			)
			op.old_name = thing.name
			op.new_name = thing.name[:-4] + suffix
			op.is_collection = is_collection

	@staticmethod
	def draw_troubleshoot_names(layout, things, *, suffix, is_collection):
		for thing in things:
			if thing.name.startswith("WGT-"):
				# Bone widgets are handled specially by overrides;
				# They are not overridden, because they don't need to be, but stay linked.
				# For now let this be handled by naming convention:
				# Bone shapes should start with "WGT-". Otherwise, we could scan
				# through every bone and save a list of widget names to ignore here.
				continue
			CLOUDRIG_PT_troubleshoot_overrides.draw_troubleshoot_name(
				layout, thing, suffix=suffix, is_collection=is_collection)

	@staticmethod
	def draw_troubleshoot_object(layout, ob):
		for m in ob.modifiers:
			if hasattr(m, 'object') and m.object==None:
				split = layout.split(factor=0.3)
				split.row().label(text="Missing modifier target: ")
				split = split.row().split(factor=0.9)
				split.row().label(text=ob.name + ": " + m.name, icon='MODIFIER')

		for c in ob.constraints:
			if c.type=='ARMATURE':
				pass
				# TODO: special treatment
			if hasattr(c, 'target') and c.target==None:
				split = layout.split(factor=0.3)
				split.row().label(text="Missing object constraint target: ")
				split = split.row().split(factor=0.9)
				split.row().label(text=ob.name + ": " + c.name, icon='CONSTRAINT')

	@staticmethod
	def draw_collection_info(layout, rig, coll):
		lib = rig.override_library.reference.library
		if not lib.filepath.startswith("//"):
			row = layout.row()
			row.alert = True
			row.prop(rig.override_library.reference, 'library', text="Library", icon='ERROR')
			row.alert = False
			row.operator('file.make_paths_relative', icon='CHECKMARK', text="")
		else:
			layout.prop(rig.override_library.reference, 'library', text="Library")
		layout.prop(rig.override_library, 'reference', text="Linked Object: ")
		layout.prop(rig, 'name', text="Overridden Object", icon='OBJECT_DATAMODE')

		layout.prop(coll, 'name', text="Base Collection", icon='OUTLINER_COLLECTION')

		# Determine if a number suffix is expected on the objects of this collection, and what it is,
		# based on if the collection has such a suffix.

		suffix = ""
		if has_number_suffix(coll.name):
			suffix = coll.name[-4:]

		split=layout.split(factor=0.4)
		split.row()
		split.row().label(text="Expected suffix: " + suffix)

		return suffix

	@staticmethod
	def draw_troubleshoot_rig(layout, rig):
		for pb in rig.pose.bones:
			for c in pb.constraints:
				if c.type=='ARMATURE':
					pass
					# TODO: special treatment, de-duplication
				if hasattr(c, 'target') and c.target==None:
					split = layout.split(factor=0.3)
					split.row().label(text="Missing bone constraint target: ")
					split = split.row().split(factor=0.9)
					split.row().label(text=pb.name + ": " + c.name, icon='CONSTRAINT_BONE')

	@staticmethod
	def draw_troubleshoot_collections(layout, coll, *, suffix: str):
		def get_subcollections_recursive(collection, col_list):
			col_list.append(collection)
			for sub_collection in collection.children:
				get_subcollections_recursive(sub_collection, col_list)
			return col_list

		all_colls = get_subcollections_recursive(coll, [])
		CLOUDRIG_PT_troubleshoot_overrides.draw_troubleshoot_names(
			layout, all_colls, suffix=suffix, is_collection=True)

	def draw(self, context):
		layout = self.layout
		col = layout.column()
		col.use_property_split=True
		col.use_property_decorate=False

		self.draw_override_purge(layout)
		layout.separator()

		rig = context.object
		owner_collection = self.get_override_collection(rig)

		suffix = self.draw_collection_info(layout, rig, owner_collection)

		self.draw_troubleshoot_names(
			layout, owner_collection.all_objects, suffix=suffix, is_collection=False)
		for ob in owner_collection.all_objects:
			self.draw_troubleshoot_object(layout, ob)

		self.draw_troubleshoot_rig(layout, rig)
		self.draw_troubleshoot_collections(layout, owner_collection, suffix=suffix)

#######################################
############### Rig UI ################
#######################################

def get_char_bone(rig):
	for b in rig.pose.bones:
		if b.name.startswith("Properties_Character"):
			return b

class CloudRig_Properties(bpy.types.PropertyGroup):
	"""PropertyGroup for special custom properties that rely on callback functions."""

	def get_rig(self):
		""" Find the armature object that is using this instance (self). """

		for rig in get_rigs():
			if rig.cloud_rig == self:
				return rig

	def items_outfit(self, context):
		""" Items callback for outfits EnumProperty.
			Build and return a list of outfit names based on a bone naming convention.
			Bones storing an outfit's properties must be named "Properties_Outfit_OutfitName".
		"""
		rig = self.get_rig()
		if not rig: return [(('0', 'Default', 'Default'))]

		outfits = []
		for b in rig.pose.bones:
			if b.name.startswith("Properties_Outfit_"):
				outfits.append(b.name.replace("Properties_Outfit_", ""))

		# Convert the list into what an EnumProperty expects.
		items = []
		for i, outfit in enumerate(outfits):
			items.append((outfit, outfit, outfit, i))	# Identifier, name, description, can all be the outfit name.

		# If no outfits were found, don't return an empty list so the console doesn't spam "'0' matches no enum" warnings.
		if items==[]:
			return [(('0', 'Default', 'Default'))]

		return items

	def change_outfit(self, context):
		""" Update callback of outfits EnumProperty. """

		rig = self.get_rig()
		if not rig: return

		if self.outfit == '':
			self.outfit = self.items_outfit(context)[0][0]

		outfit_bone = rig.pose.bones.get("Properties_Outfit_"+self.outfit)

		if outfit_bone:
			# Reset all settings to default.
			for key in outfit_bone.keys():
				value = outfit_bone[key]
				if type(value) in [float, int]:
					pass # TODO: Can't seem to reset custom properties to their default, or even so much as read their default!?!?

			# For outfit properties starting with "_", update the corresponding character property.
			char_bone = get_char_bone(rig)
			for key in outfit_bone.keys():
				if key.startswith("_") and key[1:] in char_bone:
					char_bone[key[1:]] = outfit_bone[key]

		context.evaluated_depsgraph_get().update()

	# TODO: This should be implemented as an operator instead, just like parent switching.
	outfit: EnumProperty(
		name	= "Outfit",
		items	= items_outfit,
		update	= change_outfit,
		options	= {"LIBRARY_EDITABLE"} # Make it not animatable.
	)


def draw_rig_settings_per_label(layout, rig, main_dict):
	"""Each top-level dictionary within the main dictionary defines a panel.
	Each panel is split into sub-sections via labels.
	"""
	top = layout.column()
	for label_name in main_dict.keys():
		ui = layout
		if label_name == 'parent_id':
			continue
		if label_name == 'NODRAW':
			continue
		if label_name != "":
			layout.label(text=label_name)
		else:
			# Label-less properties should be at the top of the sub-panel.
			ui = top
		draw_rig_settings(ui, rig, main_dict[label_name])

def draw_rig_settings(layout, rig, main_dict):
	"""
	main_dict: Dictionary containing the UI data, created during rig generation.
	The top-level represents rows, and each row can contain any number of slider definitions.

	A slider definition must have the following keywords:
		prop_bone: Name of the pose bone that holds the custom property.
		prop_id: Name of the custom property on the bone, to be drawn as a slider.

	Optional keywords:
		texts: List of strings to display alongside an integer property slider.
		operator: Specify an operator to draw next to the slider.
		icon: Override the icon of the operator. If not specified, default to 'FILE_REFRESH'.

		Any further arguments will be passed on to the operator button as keyword arguments.
	"""

	# Each top-level dictionary within the main dictionary defines a row.
	for row_name in main_dict.keys():
		row = layout.row()
		# Each second-level dictionary within that defines a slider (and operator, if given).
		# If there is more than one, they will be drawn next to each other, since they're in the same row.
		row_entries = main_dict[row_name]
		for entry_name in row_entries.keys():
			info = row_entries[entry_name]		# This is the lowest level dictionary that contains the parameters for the slider and its operator, if given.
			assert 'prop_bone' in info and 'prop_id' in info, f"Limb definition lacks properties bone or prop ID: {row_name}, {info}"
			prop_bone = rig.pose.bones.get(info['prop_bone'])
			prop_id = info['prop_id']
			assert prop_bone and prop_id in prop_bone, f"Properties bone or property does not exist: {info}"

			col = row.column()
			sub_row = col.row(align=True)

			slider_text = entry_name
			if 'texts' in info:
				texts = json.loads(info['texts'])
				prop_value = prop_bone[prop_id]
				value = int(prop_value)
				if len(texts) > value:
					slider_text = entry_name + ": " + texts[value]

			sub_row.prop(prop_bone, '["' + prop_id + '"]', slider=True, text=slider_text)

			# Draw an operator if provided.
			if 'operator' in info:
				icon = 'FILE_REFRESH'
				if 'icon' in info:
					icon = info['icon']

				operator = sub_row.operator(info['operator'], text="", icon=icon)
				# Pass on any paramteres to the operator that it will accept.
				for param in info.keys():
					if hasattr(operator, param):
						value = info[param]
						# Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
						if type(value) in [list, dict]:
							value = json.dumps(value)
						setattr(operator, param, value)

def get_text(prop_owner, prop_id, value):
	"""If there is a property on prop_owner named $prop_id, expect it to be a list of strings and return the valueth element."""
	text = prop_id.replace("_", " ")
	if "$"+prop_id in prop_owner and type(value)==int:
		names = prop_owner["$"+prop_id]
		if value > len(names)-1:
			print(f"cloudrig.py Warning: Name list for this property is not long enough for current value: {prop_id}")
			return text
		return text + ": " + names[value]
	else:
		return text

def add_operator(layout, op_info: dict):
	"""Add an operator button to layout.
	op_info should include a bl_idname, can include an icon, and operator kwargs.
	"""

	icon = 'LAYER_ACTIVE'
	if 'icon' in op_info:
		icon = op_info['icon']

	operator = layout.operator(op_info['bl_idname'], text="", icon=icon)
	# Pass on any paramteres to the operator that it will accept.
	for param in op_info.keys():
		if param in ['bl_idname', 'icon']: continue
		if hasattr(operator, param):
			value = op_info[param]
			# Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
			if type(value) in [list, dict]:
				value = json.dumps(value)
			setattr(operator, param, value)

class CLOUDRIG_PT_character(CLOUDRIG_PT_base):
	bl_idname = "CLOUDRIG_PT_character"
	bl_label = "Character"

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False

		# Only display this panel if there is either an outfit with options, multiple outfits, or character options.
		rig = is_active_cloudrig(context)
		if not rig: return
		rig_props = rig.cloud_rig
		multiple_outfits = len(rig_props.items_outfit(context)) > 1
		outfit_properties_bone = rig.pose.bones.get("Properties_Outfit_"+rig_props.outfit)
		char_bone = get_char_bone(rig)

		return multiple_outfits or outfit_properties_bone or char_bone

	def draw(self, context):
		layout = self.layout
		rig = context.pose_object or context.object

		rig_props = rig.cloud_rig

		def add_props(prop_owner):
			props_done = []

			def add_prop(layout, prop_owner, prop_id):
				row = layout.row()
				if prop_id in props_done: return

				if type(prop_owner[prop_id]) in [int, float]:
					row.prop(prop_owner, '["'+prop_id+'"]', slider=True,
						text = get_text(prop_owner, prop_id, prop_owner[prop_id])
					)
					if 'op_'+prop_id in prop_owner or prop_id=='Quality':
						# HACK: Hard-code behaviour for a property named "Quality", so I don't have to add it on every character manually on Sprite Fright. This needs a more elegant design...
						if prop_id=='Quality':
							op_info = {'bl_idname': 'object.cloudrig_copy_property', 'prop_bone':prop_owner.name, 'prop_id':'Quality', 'icon':'WORLD'}
						else:
							op_info = prop_owner["op_"+prop_id]
						if type(op_info)==str:
							op_info = eval(op_info)
						add_operator(row, op_info)
				elif str(type(prop_owner[prop_id])) == "<class 'IDPropertyArray'>":
					# Vectors
					row.prop(prop_owner, '["'+prop_id+'"]', text=prop_id.replace("_", " "))

			# Drawing properties with hierarchy
			if 'prop_hierarchy' in prop_owner:
				prop_hierarchy = prop_owner['prop_hierarchy']
				if type(prop_hierarchy)==str:
					prop_hierarchy = eval(prop_hierarchy)

				for parent_prop_name in prop_hierarchy.keys():
					parent_prop_name_without_values = parent_prop_name
					values = [1]	# Values which this property needs to be for its children to show. For bools this is always 1.
					# Example entry in prop_hierarchy: ['Jacket-23' : ['Hood', 'Belt']] This would mean Hood and Belt are only visible when Jacket is either 2 or 3.
					if '-' in parent_prop_name:
						split = parent_prop_name.split('-')
						parent_prop_name_without_values = split[0]
						values = [int(val) for val in split[1]]	# Convert them to an int list ( eg. '23' -> [2, 3] )

					parent_prop_value = prop_owner[parent_prop_name_without_values]

					# Drawing parent prop, if it wasn't drawn yet.
					add_prop(layout, prop_owner, parent_prop_name_without_values)

					# Marking parent prop as done drawing.
					props_done.append(parent_prop_name_without_values)

					# Checking if we should draw children.
					if parent_prop_value not in values: continue

					# Drawing children.
					childrens_box = None
					for child_prop_name in prop_hierarchy[parent_prop_name]:
						if not childrens_box:
							childrens_box = layout.box()
						add_prop(childrens_box, prop_owner, child_prop_name)

				# Marking child props as done drawing. (Regardless of whether they were actually drawn or not, since if the parent is disabled, we don't want to draw them.)
				for parent in prop_hierarchy.keys():
					for child in prop_hierarchy[parent]:
						props_done.append(child)

			# Drawing properties without hierarchy
			for prop_id in sorted(prop_owner.keys()):
				if prop_id.startswith("_"): continue
				if prop_id in props_done: continue

				add_prop(layout, prop_owner, prop_id)

		# Add character properties to the UI, if any.
		char_bone = get_char_bone(rig)
		if char_bone:
			add_props(char_bone)
			layout.separator()

		# Add outfit properties to the UI, if any.
		outfit_properties_bone = rig.pose.bones.get("Properties_Outfit_"+rig_props.outfit)
		if outfit_properties_bone:
			layout.prop(rig_props, 'outfit')
			add_props(outfit_properties_bone)

class CLOUDRIG_PT_custom_panel(CLOUDRIG_PT_base):
	"""Base class for dynamically created sub-panels for the rig UI, created in ensure_custom_panel()."""
	bl_parent_id = "CLOUDRIG_PT_settings"
	bl_options = {'DEFAULT_CLOSED'}

	@classmethod
	def poll(cls, context):
		rig = is_active_cloudrig(context)
		if not rig: return
		if 'ui_data' not in rig.data: return
		ui_data = rig.data['ui_data'].to_dict()

		if cls.bl_label in ui_data:
			return True

	def draw(self, context):
		rig = is_active_cloudrig(context)
		ui_data = rig.data['ui_data'].to_dict()
		main_dict = ui_data[self.bl_label]		# bl_label is set in ensure_custom_panel().

		draw_rig_settings_per_label(self.layout, rig, main_dict)

custom_panels = []

def ensure_custom_panel(name, parent_id="CLOUDRIG_PT_settings"):
	# Make sure name is alphanumeric
	sane_name = re.sub(r'\W+', '', name)
	full_name = "CLOUDRIG_PT_custom_"+sane_name.lower().replace(" ", "")

	if hasattr(bpy.types, full_name):
		return
	if not hasattr(bpy.types, parent_id):
		parent_id  = "CLOUDRIG_PT_settings"

	# Dynamically create a new class, so it can be registered as a sub-panel.
	new_panel = type(
		full_name
		,(CLOUDRIG_PT_custom_panel,)
		,{'bl_idname': full_name, 'bl_label': name, 'bl_parent_id': parent_id}
	)

	bpy.utils.register_class(new_panel)

	# Save a reference so it can be un-registered, even though unregister() is never called.
	global custom_panels
	custom_panels.append(new_panel)

def ensure_custom_panels(scene, depsgraph):
	rig = is_active_cloudrig(bpy.context)
	if not rig:
		return
	if 'ui_data' not in rig.data:
		return
	custom_panels = rig.data['ui_data'].to_dict()

	# We expect a dictionary of {"Panel Name" : {UI data, see draw_rig_settings.}}
	for panel_name in custom_panels.keys():
		parent_id = "CLOUDRIG_PT_settings"
		if 'parent_id' in custom_panels[panel_name]:
			parent_id = custom_panels[panel_name]['parent_id']
		ensure_custom_panel(panel_name, parent_id)

#####################################
#### LEGACY UI ######################
#### TODO: Remove after Sprites. ####
#####################################

# This list of property names are hard coded identifiers of different areas in the rig UI.
area_names = ['face_settings', 'fk_hinges', 'ik_parents', 'ik_pole_follows', 'ik_stretches', 'ik_switches', 'misc_settings']

class CLOUDRIG_PT_settings(CLOUDRIG_PT_base):
	bl_idname = "CLOUDRIG_PT_settings"
	bl_label = "Settings"

	@classmethod
	def poll(cls, context):
		rig = is_active_cloudrig(context)
		if not rig: return False
		if 'ui_data' in rig.data:
			return True
		for area_name in area_names:
			if area_name in rig.data:
				return True

	def draw(self, context):
		layout = self.layout
		rig = is_active_cloudrig(context)
		if not rig: return

		layout.operator(CLOUDRIG_OT_keyframe_all_settings.bl_idname, text='Keyframe All Settings', icon='KEYFRAME_HLT')
		layout.operator(CLOUDRIG_OT_reset_rig.bl_idname, text='Reset Rig', icon='LOOP_BACK')

class CLOUDRIG_PT_sub_settings(CLOUDRIG_PT_base):
	"""Base class for sub-panels of the Settings panel."""

	# 'area_name' : "UI Label"
	# UI Label is optional. Area name should be one of the strings in the area_names list above.
	area_names = {}

	@classmethod
	def poll(cls, context):
		rig = is_active_cloudrig(context)
		if not rig: return False
		for area_name in cls.area_names.keys():
			if area_name in rig.data:
				return True
		return False

	def draw(self, context):
		layout = self.layout
		rig = is_active_cloudrig(context)
		if not rig: return

		area_names = type(self).area_names

		for area_name in area_names.keys():
			if area_name not in rig.data: continue

			label=area_names[area_name]
			if label != "":
				layout.label(text=label)

			main_dict = rig.data[area_name].to_dict()
			draw_rig_settings(layout, rig, main_dict)

class CLOUDRIG_PT_fkik(CLOUDRIG_PT_sub_settings):
	bl_idname = "CLOUDRIG_PT_fkik"
	bl_label = "FK/IK Switch"
	bl_parent_id = "CLOUDRIG_PT_settings"

	area_names = {'ik_switches' : ""}

class CLOUDRIG_PT_ik(CLOUDRIG_PT_sub_settings):
	bl_idname = "CLOUDRIG_PT_ik"
	bl_label = "IK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings"

	area_names = {
		'ik_stretches' : "IK Stretch"
		,'ik_parents' : "IK Parents"
		,'ik_hinges' : "IK Hinge"
		,'ik_pole_follows' : "IK Pole Follow"
	}

class CLOUDRIG_PT_fk(CLOUDRIG_PT_sub_settings):
	bl_idname = "CLOUDRIG_PT_fk"
	bl_label = "FK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings"

	area_names = {
		'fk_hinges' : "FK Hinge"
		,'auto_rubber_hose' : "Auto Rubber Hose"
	}

class CLOUDRIG_PT_face(CLOUDRIG_PT_sub_settings):
	bl_idname = "CLOUDRIG_PT_face"
	bl_label = "Face Settings"
	bl_parent_id = "CLOUDRIG_PT_settings"

	area_names = {'face_settings' : ""}

class CLOUDRIG_PT_misc(CLOUDRIG_PT_sub_settings):
	bl_idname = "CLOUDRIG_PT_misc"
	bl_label = "Misc"
	bl_parent_id = "CLOUDRIG_PT_settings"

	area_names = {'misc_settings' : ""}

#######################################
############# Rig Layers ##############
#######################################

def draw_layers_ui(layout, rig, show_hidden_checkbox=True, owner=None, layers_prop='layers'):
	""" Draw rig layer toggles based on data stored in rig.data.rigify_layers. """
	# This should be able to run even if the Rigify addon is disabled.

	data = rig.data
	if not owner:
		owner = data

	# Hidden layers will only work if CloudRig is enabled.
	if hasattr(data, 'cloudrig_parameters'):	# If CloudRig is enabled:
		cloudrig = data.cloudrig_parameters
		if show_hidden_checkbox:
			layout.prop(cloudrig, 'show_layers_preview_hidden', text="Show Hidden Layers")
		show_hidden = cloudrig.show_layers_preview_hidden
	else:
		show_hidden = False

	if 'rigify_layers' not in data:
		row = layout.row()
		row.alert=True
		row.label(text="Create Rigify layer data in the Rigify Layer Names panel.")
		return
	layer_data = data['rigify_layers']
	rigify_layers = [dict(l) for l in layer_data]

	for i, l in enumerate(rigify_layers):
		# When the Rigify addon is not enabled, finding the original index after sorting is impossible, so just store it.
		l['index'] = i
		if 'row' not in l:
			l['row'] = 1

	sorted_layers = sorted(rigify_layers, key=lambda l: l['row'])
	sorted_layers = [l for l in sorted_layers if 'name' in l and l['name']!=" "]
	current_row_index = 0
	for rigify_layer in sorted_layers:
		if rigify_layer['name'] in ["", " "]: continue
		if rigify_layer['name'].startswith("$") and not show_hidden: continue

		if rigify_layer['row'] > current_row_index:
			current_row_index = rigify_layer['row']
			row = layout.row()
		row.prop(owner, layers_prop, index=rigify_layer['index'], toggle=True, text=rigify_layer['name'])

class CLOUDRIG_PT_layers(CLOUDRIG_PT_base):
	bl_idname = "CLOUDRIG_PT_layers"
	bl_label = "Layers"

	@classmethod
	def poll(cls, context):
		rig = is_active_cloudrig(context) or is_active_cloud_metarig(context)
		if not rig: return False

		if 'rigify_layers' in rig.data and len(rig.data['rigify_layers'][:]) > 0:
			return True

	def draw(self, context):
		rig = is_active_cloudrig(context)
		if not rig:
			rig = is_active_cloud_metarig(context)
		if not rig: return
		draw_layers_ui(self.layout, rig, show_hidden_checkbox = True)

class CLOUDRIG_OT_layer_select(bpy.types.Operator):
	"""Select active layers for this armature using the named Rigify layers"""
	bl_idname = "pose.cloudrig_select_layers"
	bl_label = "Select Armature Layers"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return is_active_cloudrig(context) or is_active_cloud_metarig(context)

	def invoke(self, context, event):
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		draw_layers_ui(self.layout, context.pose_object, show_hidden_checkbox=True)

	def execute(self, context):
		return {'FINISHED'}

#######################################
############## Hotkeys ################
#######################################

class CLOUDRIG_PT_hotkeys(CLOUDRIG_PT_base):
	bl_idname = "CLOUDRIG_PT_hotkeys"
	bl_label = "Hotkeys"

	@classmethod
	def poll(cls, context):
		rig = is_active_cloudrig(context) or is_active_cloud_metarig(context)
		return rig is not None

	@staticmethod
	def draw_kmi(km, kmi, layout):
		"""A simplified version of draw_kmi from rna_keymap_ui.py."""

		map_type = kmi.map_type

		col = layout.column()

		split = col.split(factor=0.7)

		# header bar
		row = split.row(align=True)
		row.prop(kmi, "active", text="", emboss=False)
		row.label(text=km.name+": " + kmi.name)

		row = split.row(align=True)
		row.enabled = kmi.active
		row.prop(kmi, "type", text="", full_event=True)

		if kmi.is_user_modified:
			row.operator("preferences.keyitem_restore", text="", icon='BACK').item_id = kmi.id

	def draw(self, context):
		layout = self.layout
		kc = context.window_manager.keyconfigs.user
		# NOTE: It's very important that we do NOT expose any UI pointing at
		# keyconfigs.addons. Messing with that copy of the hotkeys after registration
		# results in ghost hotkeys and very hard to troubleshoot issues.

		for km in kc.keymaps:
			for kmi in km.keymap_items:
				if 'cloudrig' in kmi.idname or 'rigify' in kmi.idname:
					col = layout.column()
					col.context_pointer_set("keymap", km)
					self.draw_kmi(km, kmi, col)

def register_hotkey(bl_idname, hotkey_kwargs, *, key_cat='Window', space_type='EMPTY', op_kwargs={}):
	wm = bpy.context.window_manager
	keymaps = wm.keyconfigs.addon.keymaps

	km = keymaps.get(key_cat)
	if not km:
		km = keymaps.new(name=key_cat, space_type=space_type)
	if bl_idname not in km.keymap_items:
		kmi = km.keymap_items.new(bl_idname, **hotkey_kwargs)
	for key in op_kwargs:
		value = op_kwargs[key]
		setattr(kmi.properties, key, value)

# Ensure hotkeys, whether loaded as an addon or part of a rig.
register_hotkey(CLOUDRIG_OT_layer_select.bl_idname
	,hotkey_kwargs = {'type': 'M', 'value': 'PRESS', 'shift': True}
	,key_cat = 'Pose'
	,space_type = 'VIEW_3D'
)
register_hotkey(CLOUDRIG_OT_layer_select.bl_idname
	,hotkey_kwargs = {'type': 'M', 'value': 'PRESS', 'shift': True}
	,key_cat = 'Armature'
)

#######################################
############## Register ###############
#######################################

classes = (
	CLOUDRIG_OT_switch_parent_bake
	,CLOUDRIG_OT_ikfk_bake
	,CLOUDRIG_OT_snap_mapped_bake
	,CLOUDRIG_OT_snap_bake

	,CLOUDRIG_OT_keyframe_all_settings
	,CLOUDRIG_OT_copy_property
	,CLOUDRIG_OT_reset_rig

	,CLOUDRIG_OT_delete_override_leftovers
	,CLOUDRIG_OT_override_fix_name
	,CLOUDRIG_PT_troubleshoot_overrides

	,CloudRig_Properties

	,CLOUDRIG_PT_character
	,CLOUDRIG_PT_layers
	,CLOUDRIG_OT_layer_select
	,CLOUDRIG_PT_settings
	,CLOUDRIG_PT_fkik
	,CLOUDRIG_PT_ik
	,CLOUDRIG_PT_fk
	,CLOUDRIG_PT_face
	,CLOUDRIG_PT_misc

	,CLOUDRIG_PT_hotkeys
)

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

	# Store outfit properties in Object because it can be accessed on Proxies.
	bpy.types.Object.cloud_rig = PointerProperty(type=CloudRig_Properties)

	bpy.app.handlers.load_post.append(ensure_custom_panels)
	bpy.app.handlers.depsgraph_update_post.append(ensure_custom_panels)

def unregister():
	"""Since this file runs from the Blender Text Editor, unregister() is never
	called afaik. So this is only here for show.
	"""

	from bpy.utils import unregister_class
	for c in classes:
		unregister_class(c)

	global custom_panels
	for c in custom_panels:
		unregister_class(c)

	del bpy.types.Object.cloud_rig

	bpy.app.handlers.load_post.remove(ensure_custom_panels)
	bpy.app.handlers.depsgraph_update_post.remove(ensure_custom_panels)

if __name__ in ['__main__', 'builtins']:
	# __name__ is __main__ when the script is executed in the text editor.
	# __name__ is builtins when the script is executed via exec() in cloud_generator.
	# This is to make sure that we do NOT register cloudrig.py when the CloudRig module is loaded.
	# In that case __name__ is "rigify.feature_sets.CloudRig.cloudrig"
	register()
