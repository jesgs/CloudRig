"""
This file is executed and loaded into a self-registering text datablock when a
rig is generated with the CloudRig feature set.
It's responsible for drawing rig UI and operators such as IK/FK snapping and
keyframe baking.

The only change made during rig generation is replacing SCRIPT_ID with the name
of the blend file. This is used to allow multiple characters generated with
different versions of CloudRig to co-exist in the same scene. So each rig uses
the script that belongs to it, and not another, potentially newer or older version.
"""

import bpy, traceback, json, collections
from typing import List, Dict
from bpy.props import (
						StringProperty, BoolProperty, BoolVectorProperty,
						EnumProperty, FloatVectorProperty, PointerProperty,
						CollectionProperty, IntProperty
					)
from mathutils import Vector, Matrix
from math import radians, acos
from rna_prop_ui import rna_idprop_quote_path, rna_idprop_ui_prop_update

script_id = "SCRIPT_ID"

def get_rigs():
	""" Find all cloudrig armatures in the file. """
	return [o for o in bpy.data.objects if o.type=='ARMATURE' and 'cloudrig' in o.data]

def active_cloudrig(context):
	""" If the active object is a cloudrig, return it. """
	rig = context.pose_object or context.object
	if 		rig and \
			rig.type == 'ARMATURE' and \
			'cloudrig' in rig.data and \
			rig.data['cloudrig'] == script_id:
		return rig

def active_cloud_metarig(context):
	rig = context.pose_object or context.object
	if rig and rig.type=='ARMATURE' and 'rig_id' not in rig.data:
		for pb in rig.pose.bones:
			if not hasattr(pb, 'rigify_type'):
				return None
			if 'cloud' in pb.rigify_type:
				return rig


#######################################
# Keyframe baking framework from Rigify
#######################################

###########################
## Animation curve tools ##
###########################

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

def set_transform_from_matrix(obj, bone_name, matrix, *, space='POSE', ignore_locks=False, no_loc=False, no_rot=False, no_scale=False, keyflags=None):
	"Apply the matrix to the transformation of the bone, taking locked channels, mode and certain constraints into account, and optionally keyframe it."
	bone = obj.pose.bones[bone_name]

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

	# Save the old values of the properties
	old_loc = Vector(bone.location)
	old_rot_euler = Vector(bone.rotation_euler)
	old_rot_quat = Vector(bone.rotation_quaternion)
	old_rot_axis = Vector(bone.rotation_axis_angle)
	old_scale = Vector(bone.scale)

	# Compute and assign the local matrix
	if space != 'LOCAL':
		matrix = obj.convert_space(pose_bone=bone, matrix=matrix, from_space=space, to_space='LOCAL')

	# if undo_copy_scale:
	#	 matrix = undo_copy_scale_constraints(obj, bone, matrix)

	bone.matrix_basis = matrix

	# Restore locked properties
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
		return context.mode=='POSE'#find_action(context.active_object) is not None

	def invoke(self, context, event):
		self.init_invoke(context)

		if hasattr(self, 'draw'):
			return context.window_manager.invoke_props_dialog(self)
		else:
			return context.window_manager.invoke_confirm(self, event)

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

		if context.window_manager.rigify_transfer_use_all_keys:
			self.bake_add_curve_frames(self.bake_curve_table.curve_map)

	def execute_scan_curves(self, context, obj):
		"Override to register frames to be baked, and return curves that should be cleared."
		raise NotImplementedError()

	def bake_save_state(self, context) -> Dict[int, List[Matrix]]:
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

	def bake_apply_state(self, context, save_state: Dict[int, List[Matrix]]):
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
########### Keyframe baking ###########
#######################################

def get_bones(rig, names):
	""" Return a list of pose bones from a string of bone names in json format. """
	return list(filter(None, map(rig.pose.bones.get, json.loads(names))))

class CloudRigSnapBakeMixin(RigifyBakeKeyframesMixin):
	""" Extend Rigify's keyframe baking with the ability to select the frame range
		as part of the operator, make baking optional,
		and add the ability to affect more than a single bone.
	"""
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	bones:		  StringProperty(name="Control Bones")
	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

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
		self.bake_add_bone_frames(self.bone_names)
		return None

	def set_selection(self, context, bones):
		if self.select_bones:
			for b in context.selected_pose_bones:
				b.bone.select = False
			for b in bones:
				b.bone.select = True

class CLOUDRIG_OT_snap_bake(CloudRigSnapBakeMixin, bpy.types.Operator):
	""" Toggle a custom property while ensuring that some bones stay in place. """
	bl_idname = "pose.cloudrig_snap_bake_" + script_id
	bl_label = "Snap And Bake Bones"

	def draw(self, context):
		# TODO: Display name of the property bone and property whose keyframes will be cleared.
		layout = self.layout

		self.layout.prop(self, 'do_bake')
		time_row = layout.row(align=True)
		if self.do_bake:
			time_row.prop(self, 'frame_start')
			time_row.prop(self, 'frame_end')

		bone_column = layout.column(align=True)
		bone_column.label(text="Affected bones:")
		for b in self.bone_names:
			bone_column.label(text=" "*10 + b)

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
				matrices = self.save_frame_state(context, rig)
				self.after_save_state(context, rig)
				self.apply_frame_state(context, rig, matrices)

			except Exception as e:
				traceback.print_exc()
				self.report({'ERROR'}, 'Exception: ' + str(e))

		bones = get_bones(rig, self.bones)
		self.set_selection(context, bones)

		return ret

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		if not bone_names:
			bone_names = self.bone_names

		matrices = [rig.pose.bones.get(bone_name).matrix.copy() for bone_name in bone_names]
		return matrices

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value."""
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		if self.do_bake:
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

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Restore transform matrices
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)

class CLOUDRIG_OT_switch_parent_bake(CLOUDRIG_OT_snap_bake):
	"""Extend CLOUDRIG_OT_snap_bake with a parent selector."""
	bl_idname = "pose.cloudrig_switch_parent_bake_" + script_id
	bl_label = "Apply Switch Parent To Keyframes"
	bl_description = "Switch parent over a frame range, adjusting keys to preserve the bone position and orientation"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	bones:		  StringProperty(name="Control Bones")
	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	parent_names: StringProperty(name="Parent Names")

	def parent_items(self, context):
		parents = json.loads(self.parent_names)
		items = [(str(i), name, name) for i, name in enumerate(parents)]
		return items

	selected: EnumProperty(
		name='Selected Parent',
		items=parent_items
	)

	def draw(self, context):
		layout = self.layout

		self.layout.prop(self, 'selected', text='')
		super().draw(context)

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value."""
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
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

class CLOUDRIG_OT_snap_mapped_bake(CLOUDRIG_OT_snap_bake):
	""" Extend CLOUDRIG_OT_snap_bake with the ability to snap a list of bones
		to another (equal length) list of bones.
	"""

	bl_idname = "pose.cloudrig_snap_mapped_bake_" + script_id
	bl_label = "Snap And Bake Bones (Mapped)"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	map_on:		  StringProperty()		# Bone name dictionary to use when the property is toggled ON.
	map_off:	  StringProperty()		# Bone name dictionary to use when the property is toggled OFF.

	hide_on:	  StringProperty()		# List of bone names to hide when property is toggled ON.
	hide_off:	  StringProperty()		# List of bone names to hide when property is toggled OFF.

	# In save_frame_state, we save the states of the bones we're mapping to, and in apply_frame_state, we apply those states to the bones we're mapping from.
	# That should be the only tricky part I think... but I'm probably wrong.
	# For initial testing, use this for IK/FK switching (ignore pole target)

	def init_invoke(self, context):
		rig = context.pose_object or context.active_object
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)

		map_on = json.loads(self.map_on)
		map_off = json.loads(self.map_off)

		self.bone_map = map_off if value==1 else map_on
		bone_names = [t[0] for t in self.bone_map]
		self.bones = json.dumps(bone_names)
		super().init_invoke(context)	# This creates self.bone_names based on self.bones.

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		if not bone_names:
			bone_names = [t[1] for t in self.bone_map]
		return super().save_frame_state(context, rig, bone_names)

	def execute_scan_curves(self, context, obj):
		"Register frames to be baked, and return curves that should be cleared."
		bone_names = [t[1] for t in self.bone_map]
		self.bake_add_bone_frames(bone_names)
		bone_names = [t[0] for t in self.bone_map]
		self.bake_add_bone_frames(bone_names)
		return None

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Slap the transform matrices of the map_from bones to the map_to bones
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, space='WORLD', keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)
			context.evaluated_depsgraph_get().update()	# This matters!!!!

class CLOUDRIG_OT_ikfk_bake(CLOUDRIG_OT_snap_mapped_bake):
	""" This should extend CLOUDRIG_OT_snap_mapped_bake with special treatment
		for the IK elbow.
	"""

	bl_idname = "pose.cloudrig_toggle_ikfk_bake_" + script_id
	bl_label = "Toggle And Bake IK/FK"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	map_on:		  StringProperty()		# Bone name dictionary to use when the property is toggled ON.
	map_off:	  StringProperty()		# Bone name dictionary to use when the property is toggled OFF.

	hide_on:	  StringProperty()		# List of bone names to hide when property is toggled ON.
	hide_off:	  StringProperty()		# List of bone names to hide when property is toggled OFF.

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

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		matrices = super().save_frame_state(context, rig)
		if self.is_pole:
			matrices.append(self.get_pole_target_matrix())

		return matrices

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Restore transform matrices
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)
			context.evaluated_depsgraph_get().update()

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

class CLOUDRIG_OT_keyframe_all_settings(bpy.types.Operator):
	"""Keyframe all custom properties on the Properties bone"""
	bl_idname = "pose.cloudrig_keyframe_all_settings_" + script_id
	bl_label = "Keyframe CloudRig Settings"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		return (active_cloudrig(context) is not None) and (context.pose_object or context.active_object)

	def execute(self, context):
		rig = context.pose_object or context.active_object
		properties_bone = rig.pose.bones.get('Properties')
		if not properties_bone:
			return {'CANCELLED'}

		for prop_name in properties_bone.keys():
			if prop_name=='_RNA_UI': continue
			value = properties_bone[prop_name]
			if type(value) not in (int, float):
				continue
			set_custom_property_value(rig, properties_bone.name, prop_name, value, keyflags={'INSERTKEY_NEEDED'})

		return {'FINISHED'}

############################################
############ UI

def get_char_bone(rig):
	for b in rig.pose.bones:
		if b.name.startswith("Properties_Character"):
			return b

def draw_rig_settings(layout, rig, dict_name, label=""):
	"""
	dict_name is the name of the custom property dictionary that we expect to find in the rig.
	Everything stored in a single dictionary is drawn in one call of this function.
	These dictionaries are created during rig generation.

	For an example dictionary, select an existing CloudRig, and put this in the PyConsole:
	>>> import json
	>>> print(json.dumps(C.object.data['ik_stretches'].to_dict(), indent=4))

	Parameters expected to be found in the dictionary:
		prop_bone: Name of the pose bone that holds the custom property.
		prop_id: Name of the custom property on aforementioned bone. This is the property that gets drawn in the UI as a slider.

	Further optional parameters:
		texts: List of strings to display alongside an integer property slider.
		operator: Specify an operator to draw next to the slider.
		icon: Override the icon of the operator. If not specified, default to 'FILE_REFRESH'.
		Any other arbitrary parameters will be passed on to the operator as kwargs.
	"""

	if dict_name not in rig.data: return

	if label != "":
		layout.label(text=label)

	main_dict = rig.data[dict_name].to_dict()
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
				# HACK: We want to add script_id to operator names for when multiple characters are in the same file
				# But this means having to add it here as well, which is a bit nasty.
				if info['operator'].startswith("pose.cloudrig"):
					info['operator'] += "_"+script_id
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

class CloudRig_Properties(bpy.types.PropertyGroup):
	""" PropertyGroup for storing fancy custom properties in. """

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

class CLOUDRIG_PT_main(bpy.types.Panel):
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = 'CloudRig'

	@classmethod
	def poll(cls, context):
		return active_cloudrig(context) is not None

	def draw(self, context):
		layout = self.layout

class CLOUDRIG_PT_character(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_character_" + script_id
	bl_label = "Character"

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False

		# Only display this panel if there is either an outfit with options, multiple outfits, or character options.
		rig = active_cloudrig(context)
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

			def get_text(prop_id, value):
				""" If there is a property on prop_owner named $prop_id, expect it to be a list of strings and return the valueth element."""
				text = prop_id.replace("_", " ")
				if "$"+prop_id in prop_owner and type(value)==int:
					names = prop_owner["$"+prop_id]
					if value > len(names)-1:
						print(f"cloudrig.py Warning: Name list for this property is not long enough for current value: {prop_id}")
						return text
					return text + ": " + names[value]
				else:
					return text

			def add_prop(layout, prop_owner, prop_id):
				if prop_id in props_done: return

				if type(prop_owner[prop_id]) in [int, float]:
					layout.prop(prop_owner, '["'+prop_id+'"]', slider=True,
						text = get_text(prop_id, prop_owner[prop_id])
					)
				elif str(type(prop_owner[prop_id])) == "<class 'IDPropertyArray'>":
					# Vectors
					layout.prop(prop_owner, '["'+prop_id+'"]', text=prop_id.replace("_", " "))

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
			layout.prop(cloudrig, 'show_layers_preview_hidden', text="Show Hidden")
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

class CLOUDRIG_PT_layers(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_layers_" + script_id
	bl_label = "Layers"

	@classmethod
	def poll(cls, context):
		return active_cloudrig(context) or active_cloud_metarig(context)

	def draw(self, context):
		rig = active_cloudrig(context) 
		if not rig:
			rig = active_cloud_metarig(context)
		if not rig: return
		draw_layers_ui(self.layout, rig)

class CLOUDRIG_PT_settings(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_settings_" + script_id
	bl_label = "Settings"

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		layout.operator(CLOUDRIG_OT_keyframe_all_settings.bl_idname, text='Keyframe All Settings', icon='KEYFRAME_HLT')

class CLOUDRIG_PT_fkik(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_fkik_" + script_id
	bl_label = "FK/IK Switch"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig(context)
		return rig and "ik_switches" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		draw_rig_settings(layout, rig, "ik_switches")

class CLOUDRIG_PT_ik(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_ik_" + script_id
	bl_label = "IK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig(context)
		if not rig: return False
		ik_settings = ['ik_stretches', 'ik_hinges', 'parents', 'ik_pole_follows']
		for ik_setting in ik_settings:
			if ik_setting in rig.data:
				return True
		return False

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		draw_rig_settings(layout, rig, "ik_stretches", label="IK Stretch")
		draw_rig_settings(layout, rig, "ik_parents", label="IK Parents")
		draw_rig_settings(layout, rig, "ik_hinges", label="IK Hinge")
		draw_rig_settings(layout, rig, "ik_pole_follows", label="IK Pole Follow")

class CLOUDRIG_PT_fk(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_fk_" + script_id
	bl_label = "FK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig(context)
		if not rig: return False
		fk_settings = ['fk_hinges', 'auto_rubber_hose']
		for fk_setting in fk_settings:
			if fk_setting in rig.data:
				return True
		return False

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		draw_rig_settings(layout, rig, "fk_hinges", label='FK Hinge')
		draw_rig_settings(layout, rig, "auto_rubber_hose", label='Auto Rubber Hose')

class CLOUDRIG_PT_face(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_face_" + script_id
	bl_label = "Face Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig(context)
		return rig and "face_settings" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		draw_rig_settings(layout, rig, "face_settings", label='')

class CLOUDRIG_PT_misc(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_misc_" + script_id
	bl_label = "Misc"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig(context)
		return rig and "misc_settings" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig(context)
		if not rig: return

		draw_rig_settings(layout, rig, "misc_settings", label='')

classes = (
	CLOUDRIG_OT_switch_parent_bake
	,CLOUDRIG_OT_ikfk_bake
	,CLOUDRIG_OT_snap_mapped_bake
	,CLOUDRIG_OT_snap_bake

	,CLOUDRIG_OT_keyframe_all_settings

	,CloudRig_Properties

	,CLOUDRIG_PT_character
	,CLOUDRIG_PT_layers
	,CLOUDRIG_PT_settings
	,CLOUDRIG_PT_fkik
	,CLOUDRIG_PT_ik
	,CLOUDRIG_PT_fk
	,CLOUDRIG_PT_face
	,CLOUDRIG_PT_misc
)

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

	# We store everything in Object rather than Armature because Armature data cannot be accessed on proxy armatures.
	bpy.types.Object.cloud_rig = PointerProperty(type=CloudRig_Properties)

def unregister():
	from bpy.utils import unregister_class
	for c in classes:
		unregister_class(c)

	del bpy.types.Object.cloud_rig

if __name__ in ['__main__', 'builtins']:
	# __name__ is __main__ when the script is executed in the text editor.
	# __name__ is builtins when the script is executed via exec() in cloud_generator.
	print("Cloudrig registering...")
	register()