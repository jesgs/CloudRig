# SPDX-License-Identifier: GPL-3.0-or-later

"""
This file contains a list of utility functions that can be useful to call from
post-generation scripts.
"""

import bpy
from bpy.types import ID, Object, PoseBone
from rna_prop_ui import rna_idprop_ui_prop_update

from .external.mechanism import make_driver

sides = {'.L': 'Left', '.R': 'Right'}
suffixes = list(sides.keys())

def set_custom_property_value(
    rig: Object, bone_name: str, prop: str, value: int | float | bool | str | ID
):
    """Assign the value of a custom property."""
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        return
    if prop not in bone:
        return  # We don't want to create properties here!
    bone[prop] = value
    rna_idprop_ui_prop_update(bone, prop)


def set_custom_property_default(
    rig: Object, bone_name: str, prop: str, value: int | float | bool | str | ID
):
    """Assign the value of a custom property as the default and current values."""
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        return
    if prop not in bone:
        return  # We don't want to create properties here!
    ui_props = bone.id_properties_ui(prop)
    ui_props.update(default=value)
    set_custom_property_value(rig, bone_name, prop, value)


def rename_bone(rig: Object, name_from: str, name_to: str):
    """Rename a bone and account for all the things that could break when doing so.
    This means also replacing the bone's name in the rig's UI data and in driver
    data paths.
    """
    bone = rig.pose.bones.get(name_from)
    if not bone:
        return
    bone.name = name_to
    replace_in_ui_data(rig, name_from, name_to)
    replace_driver_var_path(rig, name_from, name_to, data_only=True)


def rename_custom_property(rig: Object, bone_name: str, name_from: str, name_to: str):
    """Rename a bone custom property, and account for all the things that could
    break when doing so. This means also replacing the bone's name in the rig's
    UI data and in driver data paths."""
    pb = rig.pose.bones.get(bone_name)
    if not pb:
        return
    if name_from not in pb:
        return
    from_ui_data = pb.id_properties_ui(name_from)
    pb[name_to] = pb[name_from]
    pb.id_properties_ui(name_to).update_from(from_ui_data)
    pb.property_overridable_library_set(f'["{name_to}"]', True)
    replace_driver_var_path(rig, name_from, name_to)
    replace_in_ui_data(rig, name_from, name_to)
    del pb[name_from]


def replace_in_ui_data(rig: Object, from_str: str, to_str: str):
    """Replace occurrences of a string in the rig's UI Data"""

    def replace_data(prop_owner: ID | PoseBone, prop_name: str):
        if prop_name not in prop_owner:
            return
        data_str = str(prop_owner[prop_name].to_dict())
        data_str = data_str.replace(from_str, to_str)
        prop_owner[prop_name] = eval(data_str)

    replace_data(rig.data, 'ui_data')
    replace_data(rig.data, 'gizmo_interactions')


def replace_driver_var_path(rig: Object, from_str: str, to_str: str, data_only=False):
    """Replace a string in all driver data paths of a rig."""
    datablocks = [rig.data]
    if not data_only:
        datablocks.append(rig)
    for db in datablocks:
        if not db.animation_data:
            continue
        for fc in db.animation_data.drivers:
            for var in fc.driver.variables:
                if var.type == 'SINGLE_PROP':
                    for t in var.targets:
                        t.data_path = t.data_path.replace(from_str, to_str)


def GLOBAL_clean_custom_properties(bad_prop_names=[]):
    """Remove a particular set of useless custom props."""

    if not bad_prop_names:
        bad_prop_names = [
            'bone_gizmo',
            'enable_bone_gizmo',
            'pizmo_vis_mesh',
            'BoolToolRoot',
            'active_islands_index',
            'als',
            'hops',
            'island_groups',
            'tissue_tessellate',
            'vs',
            'matrix_world',
            'BBN_info',
        ]

    def clean_prop_owner(prop_owner, bad_keys):
        for key, _value in list(prop_owner.items()):
            if key in bad_keys:
                del prop_owner[key]

    for obj in bpy.data.objects:
        clean_prop_owner(obj, bad_prop_names)
        if obj.data:
            clean_prop_owner(obj.data, bad_prop_names)


def GLOBAL_rename_obdatas():
    """Ensure object data names are same as the object."""
    for ob in bpy.data.objects:
        if not ob.data:
            continue
        # Skip if obj data is linked
        if ob.data.library:
            continue
        ob.data.name = ob.name
        if not hasattr(ob.data, 'shape_keys'):
            continue
        if not ob.data.shape_keys:
            continue
        ob.data.shape_keys.name = ob.name


def LEGACY_auto_assign_bone_gizmo_maps(
    old_rig: Object, new_rig: Object, *, bone_collection: str
):
    """Auto-assign vertex groups/face maps for the Bone Gizmo addon for bones
    of the passed collection."""

    coll = new_rig.data.collections_all.get(bone_collection)
    if not coll:
        return
    for pb in [new_rig.pose.bones.get(b.name) for b in coll.bones]:
        if pb.enable_bone_gizmo:
            continue

        LEGACY_auto_assign_bone_gizmo(pb, old_rig.children_recursive)


def LEGACY_auto_assign_bone_gizmo(pb: PoseBone, obs: list[Object]):
    """Auto-assign vgroups/facemaps for the Bone Gizmo addon for a single bone.
    This is done based on a naming convention basis, with these priorities:
    1. Face map matching the bone's name.
    2. Vertex group matching the name `BG_{bone_name}` (for "BoneGizmo").
    3. Vertex group matching the name `FM_{bone_name}` (for "FaceMap").
    4. Vertex group named "DEF-" and the bone's name after any prefixes separated by `-`.
    """
    for ob in obs:
        if ob.type != 'MESH':
            continue
        if pb.name in ob.data.face_maps:
            pb.enable_bone_gizmo = True
            pb.bone_gizmo.shape_object = ob
            pb.bone_gizmo.use_face_map = True
            pb.bone_gizmo.face_map_name = pb.name
            return

        for prefix in ["BG_", "FM_", ""]:
            prefixed_name = prefix + pb.name
            if prefixed_name in ob.vertex_groups:
                pb.enable_bone_gizmo = True
                pb.bone_gizmo.shape_object = ob
                pb.bone_gizmo.use_face_map = False
                pb.bone_gizmo.vertex_group_name = prefixed_name
                return

        def_name = "DEF-" + pb.name.split("-")[-1]
        if def_name in ob.vertex_groups:
            pb.enable_bone_gizmo = True
            pb.bone_gizmo.shape_object = ob
            pb.bone_gizmo.use_face_map = False
            pb.bone_gizmo.vertex_group_name = def_name


def add_property_drivers(
    rig: Object,
    bone_name: str,
    property_name: str,
    data_path: str,
    driver_expressions: str | list
):
    """Add custom drivers to a bone's properties.

    Args:
        rig: The armature object
        bone_name: Name of the bone to add drivers to
        property_name: Name of the property that will drive the target
        data_path: The RNA data path for the driven property (e.g. 'custom_shape_scale_xyz', 'custom_shape_wire_width')
        driver_expressions: Either a single expression string for a single property,
                            or a list of expressions for transform properties
    """
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        return

    expressions = [driver_expressions] if isinstance(driver_expressions, str) else driver_expressions
    for i, expression in enumerate(expressions):
        index = -1 if isinstance(driver_expressions, str) else i

        make_driver(
            owner=bone,
            prop=data_path,
            index=index,
            expression=expression,
            variables=[(rig, property_name)],
        )


def update_bone_collection(
    rig: Object,
    bone_name: str,
    collection_name: str,
    operation: str
):
    """Add or remove a bone from a specified collection.

    Args:
        rig: The armature object
        bone_name: Name of the bone to update
        collection_name: Name of the Bone Collection
        operation: Either 'add' or 'remove'
    """
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        return

    collection = rig.data.collections_all.get(collection_name)
    if not collection:
        raise ValueError(f"Collection not found: '{collection_name}'")

    if operation.lower() == "add":
        collection.assign(bone)
    else:
        collection.unassign(bone)


def update_widget_properties(
    rig: Object,
    bone_name: str,
    **kwargs
):
    """Apply custom properties to the specified bone.

    Args:
        rig: The armature object
        bone_name: Name of the bone to update
        **kwargs: Keyword arguments for bone properties. Supports both shortened and full property names:
            - custom_shape: custom_shape
            - scale: custom_shape_scale_xyz
            - translation: custom_shape_translation
            - rotation: custom_shape_rotation_euler
            - transform: custom_shape_transform
            - wire_width: custom_shape_wire_width
            - use_bone_size: use_custom_shape_bone_size
    """
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        raise ValueError("Bone '{bone_name}' not found'".format(bone_name=bone_name))

    # Map shortened names to full property names
    property_map = {
        'custom_shape': 'custom_shape',
        'scale': 'custom_shape_scale_xyz',
        'translation': 'custom_shape_translation',
        'rotation': 'custom_shape_rotation_euler',
        'transform': 'custom_shape_transform',
        'wire_width': 'custom_shape_wire_width',
        'use_bone_size': 'use_custom_shape_bone_size'
    }

    for kwarg, value in kwargs.items():
        # Use mapped name if it exists, otherwise use original
        prop_name = property_map.get(kwarg, kwarg)

        if not hasattr(bone, prop_name):
            raise KeyError(f"Unknown property '{prop_name}'")

        # Handle uniform scaling
        if prop_name == "custom_shape_scale_xyz" and isinstance(value, (int, float)):
            value = (value, value, value)

        setattr(bone, prop_name, value)
