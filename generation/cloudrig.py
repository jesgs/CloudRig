"""
This file is loaded into a self-executing text datablock and attached to all
CloudRig rigs.
It's responsible for drawing the CloudRig panel in the 3D View's Sidebar.
"""

from typing import List, Dict, Tuple, Iterable
import bpy, traceback, json, collections, re
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
    IntProperty,
)
from bpy.types import Object, PoseBone, FCurve

from mathutils import Vector, Matrix
from rna_prop_ui import rna_idprop_quote_path, rna_idprop_ui_prop_update
from bl_ui.generic_ui_list import draw_ui_list

from copy_global_transform import AutoKeying


def is_generated_cloudrig(obj):
    """Return whether obj is marked as being compatible with cloudrig.py."""
    return obj.type == 'ARMATURE' and (
        'is_generated_cloudrig' in obj.data and obj.data['is_generated_cloudrig']
    )


def get_all_generated_cloudrigs():
    """Find all cloudrig armature objects in the file."""
    return [
        o for o in bpy.data.objects if o.type == 'ARMATURE' and is_generated_cloudrig(o)
    ]


def is_active_cloudrig(context):
    """If the active object is a cloudrig, return it."""
    if not hasattr(context, 'pose_object'):
        # Can happen when a file is saved with the UI open,
        # and that UI is trying to draw during file open, when context isn't
        # initialized yet.
        return False
    rig = context.pose_object or context.active_object
    if rig and is_generated_cloudrig(rig):
        return rig


def is_cloud_metarig(rig: Object):
    if not rig:
        return False
    if not rig.type == 'ARMATURE':
        return False
    return hasattr(rig, 'cloudrig') and rig.cloudrig.enabled


def is_active_cloud_metarig(context):
    return is_cloud_metarig(context.active_object)


#######################################
############ Keyframe Baking ##########
#######################################


def set_curve_key_interpolation(curves, ipo, key_range=None):
    "Assign the given interpolation value to all curve keys in range."
    for key in flatten_curve_key_set(curves, key_range):
        key.interpolation = ipo


def delete_curve_keys_in_range(curves: List[FCurve], frame_start: int, frame_end: int):
    "Delete all keys of the given curves within the given range."
    for curve in flatten_curve_set(curves):
        points = curve.keyframe_points
        for i in range(len(points), 0, -1):
            key = points[i - 1]
            if frame_start <= key.co[0] <= frame_end:
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
    "Delete all empty curves from the given action."
    for curve in list(action.fcurves):
        if curve.is_empty:
            action.fcurves.remove(curve)
    action.update_tag()


TRANSFORM_PROPS_LOCATION = frozenset(['location'])
TRANSFORM_PROPS_ROTATION = frozenset(
    ['rotation_euler', 'rotation_quaternion', 'rotation_axis_angle']
)
TRANSFORM_PROPS_SCALE = frozenset(['scale'])
TRANSFORM_PROPS_ALL = frozenset(
    TRANSFORM_PROPS_LOCATION | TRANSFORM_PROPS_ROTATION | TRANSFORM_PROPS_SCALE
)


class FCurveTable(object):
    "Table for efficient lookup of FCurves by properties."

    def __init__(self, action):
        self.action = action
        self.curve_map = self.index_curves(self.action.fcurves)

    def index_curves(self, curves):
        curve_map = collections.defaultdict(dict)
        for curve in curves:
            index = curve.array_index
            if index < 0:
                index = 0
            curve_map[curve.data_path][index] = curve
        return curve_map

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
    if ts.use_keyframe_insert_auto and (
        ignore_keyset or not ts.use_keyframe_insert_keyingset
    ):
        flags = get_keying_flags(context)
        if context.preferences.edit.use_keyframe_insert_available:
            flags.add('INSERTKEY_AVAILABLE')
        if ts.auto_keying_mode == 'REPLACE_KEYS':
            flags.add('INSERTKEY_REPLACE')
        return flags
    else:
        return None


def keyframe_channels(pbone, prop_name):
    prop_value = getattr(pbone, prop_name)
    for i, value in enumerate(prop_value):
        pbone.keyframe_insert(prop_name, index=i, group=pbone.name)


def keyframe_transform_properties(
    obj,
    bone_name,
):
    "Keyframe transformation properties, taking flags and mode into account, and avoiding keying locked channels."
    bone = obj.pose.bones[bone_name]

    # Location.
    if not bone.bone.use_connect:
        keyframe_channels('location', bone.lock_location)

    # Rotation.
    if bone.rotation_mode == 'QUATERNION':
        keyframe_channels('rotation_quaternion')
    elif bone.rotation_mode == 'AXIS_ANGLE':
        keyframe_channels('rotation_axis_angle')
    else:
        keyframe_channels('rotation_euler', bone.lock_rotation)

    # Scale.
    keyframe_channels('scale', bone.lock_scale)


def set_transform_from_matrix(
    context,
    obj,
    bone_name,
    target_matrix,
    *,
    space='POSE',
):
    """Apply the matrix to the transformation of the bone, taking locked channels,
    mode and certain constraints into account, and optionally keyframe it."""
    bone = obj.pose.bones[bone_name]

    # Set the bone transforms in pose space in a way that accounts for additive constraints
    if space != 'POSE':
        target_matrix = obj.convert_space(
            pose_bone=bone, matrix=target_matrix, from_space=space, to_space='POSE'
        )

    pose_matrix_pre_constraints = obj.convert_space(
        pose_bone=bone, matrix=bone.matrix_basis, from_space='LOCAL', to_space='POSE'
    )
    pose_matrix_post_constraints = bone.matrix
    constraint_delta = pose_matrix_post_constraints - pose_matrix_pre_constraints

    bone.matrix = target_matrix - constraint_delta

    AutoKeying.autokey_transformation(context, obj.pose.bones[bone_name])


def get_custom_property_value(rig, bone_name, prop_id):
    prop_bone = rig.pose.bones.get(bone_name)
    assert prop_bone, f"Bone snapping failed: Properties bone {bone_name} not found.)"
    assert (
        prop_id in prop_bone
    ), f"Bone snapping failed: Bone {bone_name} has no property {prop_id}"
    return prop_bone[prop_id]


def set_custom_property_value(obj, bone_name, prop, value, *, keyflags=None):
    "Assign the value of a custom property, and optionally keyframe it."
    bone = obj.pose.bones[bone_name]
    bone[prop] = value
    rna_idprop_ui_prop_update(bone, prop)
    if keyflags is not None:
        bone.keyframe_insert(
            rna_idprop_quote_path(prop), group=bone.name, options=keyflags
        )


class SnapBakeOperator:
    """Change a custom property value, while ensuring certain bones do not move,
    and that these bones get keyed, optionally in a given frame range"""

    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    do_bake: BoolProperty(
        name="Bake Keyframes in Range",
        options={'SKIP_SAVE'},
        description="Bake keyframes for the affected bones and remove keyframes from the switched property",
        default=False,
    )
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")
    bake_every_frame: BoolProperty(
        name="Bake Every Frame",
        description="Insert a keyframe on every frame of the affected bones, rather than only frames which are keyframed on the source bones. Results in a more accurate bake, but takes longer and is harder to edit afterwards",
        default=True,
    )

    bones: StringProperty(name="Control Bones")
    prop_bone: StringProperty(name="Property Bone")
    prop_id: StringProperty(name="Property")
    prop_value: IntProperty(
        name="Property Value",
        description="If the property value is already set to this, the operator will do nothing.",
        default=-1,
    )

    select_bones: BoolProperty(name="Select Affected Bones", default=True)

    @classmethod
    def poll(cls, context):
        return context.pose_object

    def init_bake(self, context):
        # Override to use operator's frame range instead of Rigify's globally set range.
        super().init_bake(context)
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

    def invoke(self, context, event):
        self.init_invoke()

        if hasattr(self, 'draw'):
            return context.window_manager.invoke_props_dialog(self)
        else:
            return context.window_manager.invoke_confirm(self, event)

    def init_invoke(self, context):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        self.bone_names = json.loads(self.bones)

    def init_execute(self, context):
        pass

    def prop_value_matches(self):
        prop_value = get_custom_property_value(
            self.bake_rig, self.prop_bone, self.prop_id
        )
        return self.prop_value == prop_value

    def execute(self, context):
        self.init_execute(context)
        self.init_bake(context)

        if self.prop_value_matches():
            return {'CANCELLED'}

        curves = self.execute_scan_curves(context, self.bake_rig)

        if self.report_bake_empty():
            return {'CANCELLED'}

        try:
            save_state = self.bake_save_state(context)

            context.scene.frame_set(range[0])
            range = self.get_bake_range()
            range_raw = self.nla_to_raw(range)
            range, range_raw = delete_curve_keys_in_range(
                curves, range_raw[0], range_raw[1]
            )

            self.execute_before_apply(context, self.bake_rig, range, range_raw)

            self.bake_apply_state(context, save_state)

        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, 'Exception: ' + str(e))

        return {'FINISHED'}

    # Default behavior implementation
    def init_bake(self, context):
        self.bake_rig = context.active_object
        self.bake_anim = self.bake_rig.animation_data
        self.bake_curve_table = FCurveTable(self.bake_rig.animation_data.action)
        self.bake_current_frame = context.scene.frame_current
        self.bake_frames_raw = set()

        self.keyflags = get_keying_flags(context)
        self.keyflags_switch = None

        if False:  # context.window_manager.rigify_transfer_use_all_keys:
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

    def bake_apply_state(
        self, context, save_state: Dict[int, Tuple[List[Matrix], List[Vector]]]
    ):
        "Scans frames and applies the baking operation."
        rig = self.bake_rig
        scene = context.scene

        for frame in self.bake_frames:
            scene.frame_set(frame)
            self.apply_frame_state(context, rig, save_state.get(frame))

        clean_action_empty_curves(self.bake_rig.animation_data.action)
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
        return list(
            self.bake_curve_table.list_all_prop_curves(
                self.bake_get_bones(bone_names), props
            )
        )

    def bake_get_all_bone_custom_prop_curves(self, bone_names, props):
        "Get a list of all curves for the specified custom properties of the specified bones."
        return self.bake_get_all_bone_curves(
            bone_names, [rna_idprop_quote_path(p) for p in props]
        )

    def bake_get_bone_prop_curves(self, bone_name, prop):
        "Get an index to curve dict for the specified property of the specified bone."
        return self.bake_curve_table.get_prop_curves(
            self.bake_get_bone(bone_name), prop
        )

    def bake_get_bone_custom_prop_curves(self, bone_name, prop):
        "Get an index to curve dict for the specified custom property of the specified bone."
        return self.bake_curve_table.get_custom_prop_curves(
            self.bake_get_bone(bone_name), prop
        )

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
            set_custom_property_value(
                self.bake_rig, bone, prop, new_value, keyflags={'INSERTKEY_AVAILABLE'}
            )
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


#######################################
##### Keyframe Baking Operators #######
#######################################


def get_bones(rig, names):
    """Return a list of pose bones from a string of bone names in json format."""
    return list(filter(None, map(rig.pose.bones.get, json.loads(names))))


class CLOUDRIG_OT_snap_bake(SnapBakeOperator, bpy.types.Operator):
    """Toggle a custom property while ensuring that some bones stay in place."""

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
            self.init_bake(context)

            if self.prop_value_matches():
                return {'CANCELLED'}

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

    def save_frame_state(
        self, context, rig, bone_names=None
    ) -> Tuple[List[Matrix], List[Vector]]:
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
            any_curves_on_property = self.bake_get_bone_prop_curves(
                self.prop_bone, f'["{self.prop_id}"]'
            )
            if any_curves_on_property:
                self.bake_replace_custom_prop_keys_constant(
                    self.prop_bone, self.prop_id, 1 - value
                )
        else:
            set_custom_property_value(
                rig,
                self.prop_bone,
                self.prop_id,
                1 - value,
                keyflags=self.keyflags_switch,
            )
        context.view_layer.update()

    def apply_frame_state(
        self, context, rig, save_state: Tuple[List[Matrix], List[Vector]]
    ):
        """Set the transform matrices of the bones to their saved state."""
        matrices, scales = save_state
        for i, bone_name in enumerate(self.bone_names):
            old_matrix = matrices[i]
            set_transform_from_matrix(
                rig,
                bone_name,
                old_matrix,
            )
            pb = rig.pose.bones.get(bone_name)
            # TODO: For some reason, reading and writing the matrix can result in
            # significant changes to local scale, even when nothing is scaled.
            # So, just keep a copy of the local scale and restore it after applying the matrix.
            pb.scale = scales[i]

            context.evaluated_depsgraph_get().update()  # This matters!!!!


class CLOUDRIG_OT_switch_parent_bake(CLOUDRIG_OT_snap_bake):
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

    selected: EnumProperty(name="Selected Parent", items=parent_items)

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
                rig,
                self.prop_bone,
                self.prop_id,
                int(self.selected),
                keyflags=self.keyflags_switch,
            )
        context.view_layer.update()


class CLOUDRIG_OT_snap_mapped_bake(CLOUDRIG_OT_snap_bake):
    """Extend CLOUDRIG_OT_snap_bake with the ability to snap a list of bones
    to another (equal length) list of bones.
    """

    bl_idname = "pose.cloudrig_snap_mapped_bake"
    bl_label = "Snap And Bake Bones (Mapped)"
    bl_description = "Toggle a custom property and snap some bones to some other bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    map_on: StringProperty()  # Bone name dictionary to use when the property is toggled ON.
    map_off: StringProperty()  # Bone name dictionary to use when the property is toggled OFF.

    hide_on: StringProperty()  # List of bone names to hide when property is toggled ON.
    hide_off: StringProperty()  # List of bone names to hide when property is toggled OFF.

    def init_invoke(self, context):
        rig = context.pose_object or context.active_object
        value = get_custom_property_value(rig, self.prop_bone, self.prop_id)

        map_on = json.loads(self.map_on)
        map_off = json.loads(self.map_off)

        self.bone_map = map_off if value == 1 else map_on
        bone_names = [t[0] for t in self.bone_map]
        self.bones = json.dumps(bone_names)
        super().init_invoke(
            context
        )  # This creates self.bone_names based on self.bones.

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


class CLOUDRIG_OT_ikfk_bake(CLOUDRIG_OT_snap_mapped_bake):
    """Extends CLOUDRIG_OT_snap_mapped_bake with special treatment for the IK elbow."""

    bl_idname = "pose.cloudrig_toggle_ikfk_bake"
    bl_label = "Toggle And Bake IK/FK"
    bl_description = "Toggle a custom property and snap some bones to some other bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    ik_pole: StringProperty()
    fk_first: StringProperty()
    fk_last: StringProperty()

    def init_invoke(self, context):
        rig = context.active_object

        self.pole = rig.pose.bones.get(self.ik_pole)  # Can be None.
        prop_value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
        self.is_pole = prop_value == 0 and self.pole != None

        super().init_invoke(context)

        if self.is_pole:
            self.bone_names.append(self.pole.name)
            self.bones = json.dumps(self.bone_names)

    def save_frame_state(
        self, context, rig, bone_names=None
    ) -> Tuple[List[Matrix], List[Vector]]:
        matrices, scales = super().save_frame_state(context, rig)
        if self.is_pole:
            matrices.append(self.get_pole_target_matrix())
            scales.append(rig.pose.bones.get(self.ik_pole).scale)

        return matrices, scales

    def get_pole_target_matrix(self):
        """Find the matrix where the IK pole should be."""
        """ This is only accurate when the bone chain lies perfectly on a plane
            and the IK Pole Angle is divisible by 90.
            This should be the case for a correct IK chain!
        """

        rig = self.bake_rig

        fk_first = rig.pose.bones.get(self.fk_first)
        fk_last = rig.pose.bones.get(self.fk_last)
        assert (
            fk_first and fk_last
        ), f"Can't calculate pole target location due to one of these FK bones missing: {self.fk_first}, {self.fk_last}"

        chain_length = fk_first.vector.length + fk_last.vector.length
        pole_distance = chain_length / 2

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
        return (is_active_cloudrig(context) is not None) and (
            context.pose_object or context.active_object
        )

    def invoke(self, context, event):
        # Collect and save references to rigs in the scene which have this property somewhere on the rig.
        # TODO: Add an assert that prop_bone and prop_id are found in context.active_object.
        self.rig_bones = {context.active_object.name: self.prop_bone}
        for rig in context.scene.objects:
            if rig.type != 'ARMATURE' or 'cloudrig' not in rig.data:
                continue
            for pb in rig.pose.bones:
                if self.prop_id in pb:
                    self.rig_bones[rig.name] = pb.name

        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object
        prop_value = rig.pose.bones[self.prop_bone][self.prop_id]

        layout.label(
            text=f"{self.prop_id} property will be set to {prop_value} on these bones:"
        )
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
        return (
            (is_active_cloudrig(context) is not None)
            and (context.pose_object or context.active_object)
            and 'ui_data' in context.active_object.data
        )

    def execute(self, context):
        rig = context.pose_object or context.active_object
        data = rig.data

        ui_data = data['ui_data'].to_dict()

        for subpanel, label_dicts in ui_data.items():
            for label_name, row_dicts in label_dicts.items():
                if label_name == 'NODRAW':
                    continue
                if type(row_dicts) == str:
                    # TODO: For some reason, cloud_ik_finger seems to put a string "CLOUDRIG_PT_custom_ik" here, which is the sub-panel that has a sub-panel.
                    continue
                for row_name, col_dicts in row_dicts.items():
                    for col_name, col_dict in col_dicts.items():
                        assert (
                            'prop_bone' in col_dict and 'prop_id' in col_dict
                        ), "Rig UI info entry must have prop_bone and prop_id."
                        prop_bone_name = col_dict['prop_bone']
                        prop_id = col_dict['prop_id']

                        prop_bone = rig.pose.bones.get(prop_bone_name)
                        assert (
                            prop_bone
                        ), f"Property bone non-existent: {prop_bone_name}"

                        value = prop_bone[prop_id]
                        if type(value) not in (int, float):
                            continue
                        set_custom_property_value(
                            rig,
                            prop_bone.name,
                            prop_id,
                            value,
                            keyflags=get_keying_flags(context),
                        )

        return {'FINISHED'}


class CLOUDRIG_OT_reset_rig(bpy.types.Operator):
    """Reset all bone transforms and custom properties to their default values"""

    bl_idname = "pose.cloudrig_reset"
    bl_label = "Reset Rig"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    reset_transforms: BoolProperty(
        name="Transforms", default=True, description="Reset bone transforms"
    )
    reset_props: BoolProperty(
        name="Properties", default=True, description="Reset custom properties"
    )
    selection_only: BoolProperty(
        name="Selected Only",
        default=False,
        description="Affect selected bones rather than all bones",
    )

    @classmethod
    def poll(cls, context):
        return context.pose_object or context.active_object

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
                pb.location = (0, 0, 0)
                pb.rotation_euler = (0, 0, 0)
                pb.rotation_quaternion = (1, 0, 0, 0)
                pb.scale = (1, 1, 1)

            if self.reset_props and len(pb.keys()) > 0:
                rna_properties = [
                    prop.identifier for prop in pb.bl_rna.properties if prop.is_runtime
                ]

                # Reset custom property values to their default value
                for key in pb.keys():
                    if key.startswith("$"):
                        continue
                    if key in rna_properties:
                        continue  # Addon defined property.

                    ui_data = None
                    try:
                        ui_data = pb.id_properties_ui(key)
                        if not ui_data:
                            continue
                        ui_data = ui_data.as_dict()
                        if not 'default' in ui_data:
                            continue
                    except TypeError:
                        # Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
                        pass

                    if not ui_data:
                        continue

                    if type(pb[key]) not in (float, int, bool):
                        continue
                    pb[key] = ui_data['default']

        return {'FINISHED'}


#######################################
############### Rig UI ################
#######################################


class CLOUDRIG_PT_base(bpy.types.Panel):
    """Base class for all CloudRig sidebar panels."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    on_metarigs = False
    on_generated_rigs = True

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        if context.object.type != 'ARMATURE':
            return False
        if not cls.on_generated_rigs and is_active_cloudrig(context):
            return False
        if not cls.on_metarigs and is_active_cloud_metarig(context):
            return False
        return True

    def draw(self, context):
        pass


class CloudRig_Properties(bpy.types.PropertyGroup):
    """PropertyGroup for special custom properties that rely on callback functions."""

    def items_outfit(self, context):
        """Items callback for outfits EnumProperty.
        Build and return a list of outfit names based on a bone naming convention.
        Bones storing an outfit's properties must be named "Properties_Outfit_OutfitName".
        """
        rig = self.id_data
        if not rig:
            return [(('0', 'Default', 'Default'))]

        outfits = []
        for b in rig.pose.bones:
            if b.name.startswith("Properties_Outfit_"):
                outfits.append(b.name.replace("Properties_Outfit_", ""))

        # Convert the list into what an EnumProperty expects.
        items = []
        for i, outfit in enumerate(outfits):
            items.append(
                (outfit, outfit, outfit, i)
            )  # Identifier, name, description, can all be the outfit name.

        # If no outfits were found, don't return an empty list so the console doesn't spam "'0' matches no enum" warnings.
        if items == []:
            return [(('0', 'Default', 'Default'))]

        return items

    def change_outfit(self, context):
        """Update callback of outfits EnumProperty."""

        rig = self.id_data
        if not rig:
            return

        if self.outfit == '':
            self.outfit = self.items_outfit(context)[0][0]

        outfit_bone = rig.pose.bones.get("Properties_Outfit_" + self.outfit)

        if outfit_bone:
            # Reset all settings to default.
            for key in outfit_bone.keys():
                value = outfit_bone[key]
                if type(value) in [float, int]:
                    pass  # TODO: Can't seem to reset custom properties to their default, or even so much as read their default!?!?

            # For outfit properties starting with "_", update the corresponding character property.
            char_bone = get_char_bone(rig)
            for key in outfit_bone.keys():
                if key.startswith("_") and key[1:] in char_bone:
                    char_bone[key[1:]] = outfit_bone[key]

        context.evaluated_depsgraph_get().update()

    # TODO: This should be implemented as an operator instead, just like parent switching.
    outfit: EnumProperty(
        name="Outfit",
        items=items_outfit,
        update=change_outfit,
        options={"LIBRARY_EDITABLE"},  # Make it not animatable.
        override={'LIBRARY_OVERRIDABLE'},
    )


def get_char_bone(rig):
    for b in rig.pose.bones:
        if b.name.startswith("Properties_Character"):
            return b


def draw_rig_settings_per_label(
    layout: bpy.types.UILayout, rig: Object, main_dict: dict
):
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


def draw_rig_settings(layout: bpy.types.UILayout, rig: Object, ui_data: Dict):
    """
    ui_data: Dictionary containing the UI data, created during rig generation.
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

    # Sort the rows alphabetically, just so "Arm" always comes before "Leg".
    # Can get unlucky with "Upperarm" and "Thigh" though, but at least alphabtical is
    # consistent and predictable.
    row_datas = [(row_name, ui_data[row_name]) for row_name in sorted(ui_data.keys())]

    # Each top-level dictionary within the main dictionary defines a row.
    for row_name, row_entries in row_datas:
        row = layout.row()
        # Each second-level dictionary within that defines a slider (and operator, if given).
        # If there is more than one, they will be drawn next to each other, since they're in the same row.
        for entry_name in row_entries.keys():
            info = row_entries[
                entry_name
            ]  # This is the lowest level dictionary that contains the parameters for the slider and its operator, if given.
            if not 'prop_bone' in info and 'prop_id' in info:
                print(
                    f"CloudRig UI Error: Limb definition lacks properties bone or prop ID: {row_name}\n{info}"
                )
                continue
            prop_bone = rig.pose.bones.get(info['prop_bone'])
            prop_id = info['prop_id']
            if not prop_bone and prop_id in prop_bone:
                print(
                    f"CloudRig UI Error: Properties bone or property does not exist: {info}"
                )
                continue
            col = row.column()
            sub_row = col.row(align=True)

            prop_value = prop_bone[prop_id]

            def get_text():
                text = entry_name
                if 'texts' in info:
                    texts = json.loads(info['texts'])
                    value = int(prop_value)
                    if len(texts) > value:
                        text = entry_name + ": " + texts[value]
                return text

            if isinstance(prop_value, bpy.types.Object):
                # Property is an object pointer
                sub_row.prop_search(
                    prop_bone,
                    f'["{prop_id}"]',
                    bpy.data,
                    'objects',
                    icon='OBJECT_DATAMODE',
                    text=entry_name,
                )
            elif type(prop_value) == bool:
                icon = 'CHECKBOX_HLT' if prop_value else 'CHECKBOX_DEHLT'
                sub_row.prop(
                    prop_bone, f'["{prop_id}"]', toggle=True, text=get_text(), icon=icon
                )
            else:
                # Property is a float/int/color

                sub_row.prop(prop_bone, f'["{prop_id}"]', slider=True, text=get_text())

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
    if "$" + prop_id in prop_owner and type(value) == int:
        names = prop_owner["$" + prop_id]
        if value > len(names) - 1:
            print(
                f"cloudrig.py Warning: Name list for this property is not long enough for current value: {prop_id}"
            )
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
        if param in ['bl_idname', 'icon']:
            continue
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
        if not rig:
            return
        rig_props = rig.cloud_rig
        multiple_outfits = len(rig_props.items_outfit(context)) > 1
        outfit_properties_bone = rig.pose.bones.get(
            "Properties_Outfit_" + rig_props.outfit
        )
        char_bone = get_char_bone(rig)

        return multiple_outfits or outfit_properties_bone or char_bone

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object

        rig_props = rig.cloud_rig

        def add_props(prop_owner):
            props_done = []

            def add_prop(layout, prop_owner, prop_id):
                row = layout.row()
                if prop_id in props_done:
                    return

                prop_value = prop_owner[prop_id]
                if type(prop_value) in [int, float]:
                    row.prop(
                        prop_owner,
                        '["' + prop_id + '"]',
                        slider=True,
                        text=get_text(prop_owner, prop_id, prop_value),
                    )
                    if 'op_' + prop_id in prop_owner or prop_id == 'Quality':
                        # HACK: Hard-code behaviour for a property named "Quality", so I don't have to add it on every character manually on Sprite Fright. This needs a more elegant design...
                        if prop_id == 'Quality':
                            op_info = {
                                'bl_idname': 'object.cloudrig_copy_property',
                                'prop_bone': prop_owner.name,
                                'prop_id': 'Quality',
                                'icon': 'WORLD',
                            }
                        else:
                            op_info = prop_owner["op_" + prop_id]
                        if type(op_info) == str:
                            op_info = eval(op_info)
                        add_operator(row, op_info)
                elif str(type(prop_value)) == "<class 'IDPropertyArray'>":
                    # Vectors
                    row.prop(
                        prop_owner, f'["{prop_id}"]', text=prop_id.replace("_", " ")
                    )
                elif type(prop_value) == bool:
                    icon = 'CHECKBOX_HLT' if prop_value else 'CHECKBOX_DEHLT'
                    row.prop(
                        prop_owner,
                        f'["{prop_id}"]',
                        text=prop_id.replace("_", " "),
                        toggle=True,
                        icon=icon,
                    )
                elif isinstance(prop_value, bpy.types.Object):
                    # Property is a pointer
                    row.prop_search(
                        prop_owner,
                        f'["{prop_id}"]',
                        bpy.data,
                        'objects',
                        icon='OBJECT_DATAMODE',
                        text=prop_id,
                    )

            # Drawing properties with hierarchy
            if 'prop_hierarchy' in prop_owner:
                prop_hierarchy = prop_owner['prop_hierarchy']
                if type(prop_hierarchy) == str:
                    prop_hierarchy = eval(prop_hierarchy)

                for parent_prop_name in prop_hierarchy.keys():
                    parent_prop_name_without_values = parent_prop_name
                    values = [
                        1
                    ]  # Values which this property needs to be for its children to show. For bools this is always 1.
                    # Example entry in prop_hierarchy: ['Jacket-23' : ['Hood', 'Belt']] This would mean Hood and Belt are only visible when Jacket is either 2 or 3.
                    if '-' in parent_prop_name:
                        split = parent_prop_name.split('-')
                        parent_prop_name_without_values = split[0]
                        values = [
                            int(val) for val in split[1]
                        ]  # Convert them to an int list ( eg. '23' -> [2, 3] )

                    parent_prop_value = prop_owner[parent_prop_name_without_values]

                    # Drawing parent prop, if it wasn't drawn yet.
                    add_prop(layout, prop_owner, parent_prop_name_without_values)

                    # Marking parent prop as done drawing.
                    props_done.append(parent_prop_name_without_values)

                    # Checking if we should draw children.
                    if parent_prop_value not in values:
                        continue

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
                if prop_id.startswith("_"):
                    continue
                if prop_id in props_done:
                    continue
                addon_props = {
                    prop.identifier
                    for prop in prop_owner.bl_rna.properties
                    if prop.is_runtime
                }
                if prop_id in addon_props:
                    continue

                add_prop(layout, prop_owner, prop_id)

        # Add character properties to the UI, if any.
        char_bone = get_char_bone(rig)
        if char_bone:
            add_props(char_bone)
            layout.separator()

        # Add outfit properties to the UI, if any.
        outfit_properties_bone = rig.pose.bones.get(
            "Properties_Outfit_" + rig_props.outfit
        )
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
        if not rig:
            return
        if 'ui_data' not in rig.data:
            return
        ui_data = rig.data['ui_data'].to_dict()

        if cls.bl_label in ui_data:
            return True

    def draw(self, context):
        rig = is_active_cloudrig(context)
        ui_data = rig.data['ui_data'].to_dict()
        main_dict = ui_data[self.bl_label]  # bl_label is set in ensure_custom_panel().

        draw_rig_settings_per_label(self.layout, rig, main_dict)


custom_panels = []


def ensure_custom_panel(name, parent_id="CLOUDRIG_PT_settings"):
    # Make sure name is alphanumeric
    sane_name = re.sub(r'\W+', '', name)
    full_name = "CLOUDRIG_PT_custom_" + sane_name.lower().replace(" ", "")

    if hasattr(bpy.types, full_name):
        return
    if not hasattr(bpy.types, parent_id):
        parent_id = "CLOUDRIG_PT_settings"

    # Dynamically create a new class, so it can be registered as a sub-panel.
    new_panel = type(
        full_name,
        (CLOUDRIG_PT_custom_panel,),
        {'bl_idname': full_name, 'bl_label': name, 'bl_parent_id': parent_id},
    )

    bpy.utils.register_class(new_panel)

    # Save a reference so it can be un-registered, even though unregister() is never called.
    global custom_panels
    custom_panels.append(new_panel)


def ensure_custom_panels(_dummy1, _dummy2):
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


class CLOUDRIG_PT_settings(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_settings"
    bl_label = "Settings"

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context)

    def draw(self, context):
        layout = self.layout
        rig = is_active_cloudrig(context)
        if not rig:
            return

        layout.operator(
            CLOUDRIG_OT_keyframe_all_settings.bl_idname,
            text='Keyframe All Settings',
            icon='KEYFRAME_HLT',
        )
        layout.operator(
            CLOUDRIG_OT_reset_rig.bl_idname, text='Reset Rig', icon='LOOP_BACK'
        )


#######################################
########### Rig Preferences ###########
#######################################


class CloudRig_RigPreferences(bpy.types.PropertyGroup):
    show_visibility: bpy.props.BoolProperty(
        name="Hide",
        description="Show the Hide setting",
        default=True,
    )
    show_solo: bpy.props.BoolProperty(
        name="Isolate",
        description="Show the Isolate operator",
        default=True,
    )
    show_select: bpy.props.BoolProperty(
        name="Select",
        description="Show the Select operator",
        default=True,
    )


#######################################
###### Nested Bone Collections ########
#######################################


class CloudRigBoneCollection(bpy.types.PropertyGroup):
    def get_collection(self) -> bpy.types.BoneCollection:
        armature = self.id_data
        for coll in armature.collections:
            if coll.cloudrig_info == self:
                return coll

    def update_name(self, context):
        coll = self.get_collection()
        if coll.name == self.name:
            return

        for other_coll in self.id_data.collections:
            if other_coll.cloudrig_info.parent_name == coll.name:
                other_coll.cloudrig_info.parent_name = self.name
        for pb in context.object.pose.bones:
            comp = pb.cloudrig_component
            for bone_set_name in comp.params.bone_sets.keys():
                bone_set = getattr(comp.params.bone_sets, bone_set_name)
                for bone_set_coll in bone_set.collections:
                    if bone_set_coll.name == coll.name:
                        bone_set_coll.name = self.name
                        break

        coll.name = self.name

    name: StringProperty(
        name="Name",
        description="Name of this bone collection",
        update=update_name,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    unfold_children: BoolProperty(
        name="Unfold Children",
        description="Unfold child collections",
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    def update_is_visible(self, context):
        # The is_visible flag is not intended to stay perfectly in sync with the
        # collections themselves. Instead, we consider this a higher level toggle,
        # that controls the hierarchy.
        # So, self.is_visible may be True, but the actual collection underneath
        # will still be hidden, if any of our parent collections is hidden.
        coll = self.get_collection()
        coll.is_visible = self.is_visible
        if self.is_visible:
            self.should_stay_hidden = False
        for child in self.children:
            if not child.cloudrig_info.is_visible and not self.is_visible:
                child.cloudrig_info.should_stay_hidden = True
            if (
                self.is_visible
                and not child.cloudrig_info.is_visible
                and child.cloudrig_info.should_stay_hidden
            ):
                continue
            if not self.is_visible and not child.cloudrig_info.is_visible:
                continue
            child.cloudrig_info.is_visible = self.is_visible

    is_visible: BoolProperty(
        name="Visible",
        description="Toggle the visiblity of this collection, and all child collections",
        default=True,
        update=update_is_visible,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    should_stay_hidden: BoolProperty(
        name="Stay Hidden",
        description="Internal value to preserve hidden state when a parent gets un-hidden",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    parent_name: StringProperty(
        name="Parent",
        description="Parent of this bone collection",
    )

    @property
    def parent_collection(self) -> bpy.types.BoneCollection:
        armature = self.id_data
        return armature.collections.get(self.parent_name)

    @property
    def children(self) -> List[bpy.types.BoneCollection]:
        children = []
        self_coll = self.get_collection()

        # self.name should be the same as self_coll.name.
        # If that's not the case, there's a bug in copy_bone_collections().

        if not self_coll.name:
            return []
        armature = self.id_data
        for coll in armature.collections:
            if (
                self_coll.name == coll.cloudrig_info.parent_name
            ) and self_coll.name != "":
                children.append(coll)
        return children

    @property
    def siblings(self):
        """Includes self!"""
        if not self.parent_collection:
            all_colls = self.id_data.collections
            return [
                coll for coll in all_colls if not coll.cloudrig_info.parent_collection
            ]
        return self.parent_collection.cloudrig_info.children

    @property
    def children_recursive(self) -> List[bpy.types.BoneCollection]:
        children = self.children[:]
        for child in children:
            children += child.children
        return children

    @property
    def all_bones(self) -> List[bpy.types.Bone]:
        bones = self.get_collection().bones[:]
        for child in self.children:
            bones += child.cloudrig_info.all_bones
        return bones

    @property
    def should_draw(self):
        """Return False if any parent up the chain has unfold_children=False"""
        if not self.parent_collection:
            return True

        if not self.parent_collection.cloudrig_info.unfold_children:
            return False

        return self.parent_collection.cloudrig_info.should_draw

    @property
    def should_draw_grayed(self):
        """Return True if any parent up the chain has is_visible=False"""
        if not self.parent_collection:
            return False

        if not self.parent_collection.cloudrig_info.is_visible:
            return True

        return False

    @property
    def hierarchy_depth(self):
        """Return number of parents"""

        parent = self.parent_collection
        counter = 0
        while parent:
            counter += 1
            parent = parent.cloudrig_info.parent_collection

        return counter


class CLOUDRIG_UL_collections(bpy.types.UIList):
    """Draw bone collections with nesting support provided by CloudRig"""

    @staticmethod
    def draw_collection(context, layout, collection):
        cloudrig_info = collection.cloudrig_info

        prefs = context.object.cloudrig_prefs

        row = layout.row(align=True)
        icon = 'TRIA_DOWN' if cloudrig_info.unfold_children else 'TRIA_RIGHT'
        if cloudrig_info.parent_collection:
            split = row.split(factor=0.02 * cloudrig_info.hierarchy_depth)
            split.row()
            row = split.row(align=True)
            row = row.row(align=True)
        if cloudrig_info.children:
            row.prop(cloudrig_info, 'unfold_children', text="", icon=icon, emboss=False)
        else:
            row.label(text="", icon='BLANK1')
        row.prop(cloudrig_info, 'name', text="", emboss=False)

        row = row.row(align=True)
        row.enabled = not cloudrig_info.should_draw_grayed
        icon = 'HIDE_ON'
        if collection.is_visible or (
            cloudrig_info.parent_collection
            and not cloudrig_info.parent_collection.cloudrig_info.is_visible
            and not cloudrig_info.should_stay_hidden
        ):
            icon = 'HIDE_OFF'
        if prefs.show_visibility:
            row.prop(cloudrig_info, 'is_visible', text="", icon=icon)
        if prefs.show_solo:
            row.operator(
                CLOUDRIG_OT_collection_solo.bl_idname, text="", icon='SOLO_ON'
            ).collection_name = collection.name
        if prefs.show_select:
            row.operator(
                CLOUDRIG_OT_collection_select.bl_idname,
                text="",
                icon='RESTRICT_SELECT_OFF',
            ).collection_name = collection.name

        return row

    def draw_item(
        self, context, layout, _data, item, _icon_value, _active_data, _active_propname
    ):
        self.draw_collection(context, layout, item)

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation.
        """
        layout.row().prop(self, "filter_name", text="")

    @staticmethod
    def get_collection_order(collections):
        # Order collections by hierarchy, such that children come after their
        # parents, but the original order is otherwise preserved.

        # Find collections without any parent
        root_colls = [
            coll for coll in collections if coll.cloudrig_info.parent_name == ""
        ]
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.cloudrig_info.children:
                add_children_recursive(child)

        for root_coll in root_colls:
            add_children_recursive(root_coll)

        # NOTE: THIS MUST BE BOMBPROOF, OR BLENDER WILL CRASH!
        return [sorted_colls.index(coll) for coll in collections]

    def filter_items(self, context, data, propname):
        collections = getattr(data, propname)

        # Default return values.
        flt_flags = [self.bitflag_filter_item] * len(collections)
        flt_neworder = []

        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name search.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                collections,
                "name",
                reverse=False,
            )

        # Filter out collections whose parents are collapsed
        flt_flags = [
            flag * int(collections[i].cloudrig_info.should_draw)
            for i, flag in enumerate(flt_flags)
        ]

        flt_neworder = self.get_collection_order(collections)
        return flt_flags, flt_neworder


class CLOUDRIG_PT_sidebar_collections(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_sidebar_collections"
    bl_label = "Bone Collections"

    on_metarigs = True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        self.draw_nested_collections_template(layout, context)

    @staticmethod
    def draw_nested_collections_template(
        layout, context, list_class='CLOUDRIG_UL_collections'
    ):
        if context.pose_object:
            list_path = 'pose_object.data.collections'
        else:
            list_path = 'active_object.data.collections'

        list_col = draw_ui_list(
            layout,
            context,
            class_name='CLOUDRIG_UL_collections',
            list_path=list_path,
            active_index_path=list_path + '.active_index',
            insertion_operators=False,
            move_operators=False,
            unique_id='CloudRig Nested Collections UI',
        )
        list_col.popover(
            panel="CLOUDRIG_PT_collections_filter",
            text="",
            icon='FILTER',
        )

        return list_col


class CLOUDRIG_OT_collection_solo(bpy.types.Operator):
    """Reveal all bones of this collection, and hide all others"""

    bl_idname = "pose.cloudrig_collection_solo"
    bl_label = "Solo Collection"

    collection_name: StringProperty()
    select_bones: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        rig = context.object
        collection = rig.data.collections.get(self.collection_name)

        if not collection:
            collection = rig.data.collections.active
        if not collection:
            return {'CANCELLED'}

        if not collection.is_visible:
            collection.cloudrig_info.is_visible = True

        collection_bones = collection.cloudrig_info.all_bones

        for pb in rig.pose.bones:
            pb.bone.hide = pb.bone not in collection_bones
            if self.select_bones:
                pb.bone.select = True

        return {'FINISHED'}


class CLOUDRIG_OT_collection_select(bpy.types.Operator):
    """Select all bones of this collection"""

    bl_idname = "pose.cloudrig_collection_select"
    bl_label = "Select Bones of Collection"

    collection_name: StringProperty()
    reveal_bones: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        rig = context.object
        collection = rig.data.collections.get(self.collection_name)

        if not collection:
            collection = rig.data.collections.active
        if not collection:
            return {'CANCELLED'}

        if not collection.is_visible:
            collection.cloudrig_info.is_visible = True

        collection_bones = collection.cloudrig_info.all_bones

        for bone in collection_bones:
            if self.reveal_bones:
                bone.hide = False
            bone.select = True

        return {'FINISHED'}


class CLOUDRIG_PT_collections_filter(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label = "Filter"

    def draw(self, context):
        layout = self.layout
        prefs = context.object.cloudrig_prefs
        row = layout.row(align=True)
        row.prop(prefs, "show_visibility", text="", icon='HIDE_OFF')
        row.prop(prefs, "show_solo", text="", icon='SOLO_ON')
        row.prop(prefs, "show_select", text="", icon='RESTRICT_SELECT_OFF')
        layout.separator()


#######################################
############## Hotkeys ################
#######################################


class CLOUDRIG_PT_hotkeys(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_hotkeys"
    bl_label = "Hotkeys"

    keymap_items = []

    @classmethod
    def poll(cls, context):
        rig = is_active_cloudrig(context) or is_active_cloud_metarig(context)
        return True

    @staticmethod
    def draw_kmi(km, kmi, layout):
        """A simplified version of draw_kmi from rna_keymap_ui.py."""

        map_type = kmi.map_type

        col = layout.column()

        split = col.split(factor=0.7)

        # header bar
        row = split.row(align=True)
        row.prop(kmi, "active", text="", emboss=False)
        row.label(text=km.name + ": " + kmi.name)

        row = split.row(align=True)
        row.enabled = kmi.active
        row.prop(kmi, "type", text="", full_event=True)

        if kmi.is_user_modified:
            row.operator(
                "preferences.keyitem_restore", text="", icon='BACK'
            ).item_id = kmi.id

    def draw(self, context):
        layout = self.layout

        for kc, km, kmi in type(self).keymap_items:
            if kc == context.window_manager.keyconfigs.user:
                col = layout.column()
                col.context_pointer_set("keymap", km)
                self.draw_kmi(km, kmi, col)


def register_hotkey(
    bl_idname, hotkey_kwargs, *, key_cat='Window', space_type='EMPTY', op_kwargs={}
):
    wm = bpy.context.window_manager
    addon_keyconfig = wm.keyconfigs.addon
    if not addon_keyconfig:
        # This happens when running Blender in background mode.
        return

    # If it already exists, don't create it again.
    for existing_kmi in bpy.types.CLOUDRIG_PT_hotkeys.keymap_items:
        kc, km, kmi = existing_kmi
        if km.name == key_cat and kmi.idname == bl_idname:
            return

    keyconfigs = [addon_keyconfig, wm.keyconfigs.user]

    for kc in keyconfigs:
        keymaps = addon_keyconfig.keymaps

        km = keymaps.get(key_cat)
        if not km:
            km = keymaps.new(name=key_cat, space_type=space_type)

        kmi = km.keymap_items.new(bl_idname, **hotkey_kwargs)
        bpy.types.CLOUDRIG_PT_hotkeys.keymap_items.append((kc, km, kmi))

        for key in op_kwargs:
            value = op_kwargs[key]
            setattr(kmi.properties, key, value)


#######################################
############## Register ###############
#######################################

classes = (
    CLOUDRIG_OT_switch_parent_bake,
    CLOUDRIG_OT_ikfk_bake,
    CLOUDRIG_OT_snap_mapped_bake,
    CLOUDRIG_OT_snap_bake,
    CLOUDRIG_OT_keyframe_all_settings,
    CLOUDRIG_OT_copy_property,
    CLOUDRIG_OT_reset_rig,
    CloudRig_Properties,
    CLOUDRIG_PT_character,
    CLOUDRIG_PT_settings,
    CloudRig_RigPreferences,
    CloudRigBoneCollection,
    CLOUDRIG_UL_collections,
    CLOUDRIG_PT_sidebar_collections,
    CLOUDRIG_OT_collection_solo,
    CLOUDRIG_OT_collection_select,
    CLOUDRIG_PT_collections_filter,
    CLOUDRIG_PT_hotkeys,
)


def register():
    from bpy.utils import register_class

    keymap_items = []
    if 'CLOUDRIG_PT_hotkeys' in dir(bpy.types):
        keymap_items = bpy.types.CLOUDRIG_PT_hotkeys.keymap_items

    for c in classes:
        if c.__name__ in dir(bpy.types):
            # Don't re-register panels, or sub-panels become top-level.
            continue
        register_class(c)

    # TODO 4.0: These properties for outfit stuff are legacy, remove!
    bpy.types.Object.cloud_rig = PointerProperty(type=CloudRig_Properties)
    bpy.types.Object.cloudrig_prefs = PointerProperty(type=CloudRig_RigPreferences)

    bpy.types.BoneCollection.cloudrig_info = PointerProperty(
        type=CloudRigBoneCollection
    )

    # Ensure custom panels.
    if __name__ != 'CloudRig.generation.cloudrig':
        # This doesn't work during add-on registration, since it relies on context.
        ensure_custom_panels(None, None)
    bpy.app.handlers.load_post.append(ensure_custom_panels)
    bpy.app.handlers.depsgraph_update_post.append(ensure_custom_panels)


def unregister():
    """Since this file runs from the Blender Text Editor, unregister() is never
    called afaik. So this is only here for show.
    """

    for kc, km, kmi in bpy.types.CLOUDRIG_PT_hotkeys.keymap_items:
        km.keymap_items.remove(kmi)
    bpy.types.CLOUDRIG_PT_hotkeys.keymap_items = []

    from bpy.utils import unregister_class

    for c in classes:
        unregister_class(c)

    global custom_panels
    for c in custom_panels:
        unregister_class(c)

    del bpy.types.Object.cloud_rig

    bpy.app.handlers.load_post.remove(ensure_custom_panels)
    bpy.app.handlers.depsgraph_update_post.remove(ensure_custom_panels)


if __name__ in ['__main__', 'builtins', 'CloudRig.generation.cloudrig']:
    # __name__ == `__main__`` when executed in Blender's Text Editor.
    # __name__ == `builtins`` when executed by cloud_generator.
    # __name__ == `CloudRig.generation.cloudrig` when executed by Blender add-on registration.
    register()
