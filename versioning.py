import bpy
from bpy.types import Object
from typing import Any
from bpy.app.handlers import persistent
from .generation.cloudrig import is_cloud_metarig
from .rig_component_features.ui import get_addon_prefs
from .rig_component_features.object import set_enum_property_by_integer


def update_enum_property(owner, old_key, new_key, int_value):
    enum_string_value = set_enum_property_by_integer(owner, new_key, int_value)
    if enum_string_value:
        print(f"Updated enum property {old_key}->{new_key}, value: {enum_string_value}")
    else:
        # If an enum property's definition is lost, their string value is lost
        # and is left with an int. In this case, just back up that int.
        owner[new_key] = int_value


def rename_parameters(metarig, dictionary):
    """When we change the python name of a parameter, this can be used to find the old data
    and put it on the property with the new name."""
    for pb in metarig.pose.bones:
        if pb.cloudrig_component.component_type == '':
            continue
        for old_key in list(pb.rigify_parameters.keys()):
            if old_key in dictionary:
                new_key = dictionary[old_key]
                value = pb.rigify_parameters[old_key]
                try:
                    print(f"Rename param {pb.name}: {old_key}->{new_key}")
                    setattr(pb.rigify_parameters, new_key, value)
                except:
                    update_enum_property(pb.rigify_parameters, old_key, new_key, value)


def preserve_old_default(metarig: Object, param_name: str, old_default: Any):
    for pb in metarig.pose.bones:
        if param_name not in pb.cloudrig_component.params:
            setattr(pb.cloudrig_component.params, param_name, old_default)
            print(
                f"Preserve old default value: {pb.name} -> {param_name} = {old_default}"
            )


def version_cloud_metarig(metarig):
    """Convert older CloudRig metarigs to work with the current version of
    CloudRig as well as possible. They will still need some manual cleanup!!!"""
    cloudrig = metarig.cloudrig
    target_rig = cloudrig.generator.target_rig

    # NOTE on limitations:
    # The old value is not stored in the file at all if it was left as default, so
    # there's no way to guarantee correct versioning when changing the default value of a parameter.
    # So, make really damn sure that default values are correct when first implementing them!

    metarig_version = get_addon_prefs().cloud_metarig_version
    print(
        f"CloudRig Versioning: {metarig.name} bumping version {cloudrig.metarig_version} -> {metarig_version}"
    )
    if cloudrig.metarig_version < 1:
        # No backwards compatibility with the version of CloudRig that used to be a Rigify feature set.
        pass


@persistent
def update_all_metarigs(dummy):
    metarig_version = get_addon_prefs().cloud_metarig_version
    cloud_metarigs = [
        o for o in bpy.data.objects if o.type == 'ARMATURE' and is_cloud_metarig(o)
    ]
    for metarig in cloud_metarigs:
        if metarig.library or metarig.override_library:
            # Don't try to version linked metarigs, there's no point.
            # Also, metarigs shouldn't get linked and overridden in the first place.
            continue
        if metarig.cloudrig.metarig_version == metarig_version:
            continue
        if metarig.cloudrig.metarig_version > metarig_version:
            print(
                f"\tFound a metarig with a higher metarig version than the current: {metarig.name}"
            )
            print(
                "\tIt must have been created with a newer version of CloudRig, and won't behave as expected."
            )
            print("\tYou should update CloudRig!")
            continue
        version_cloud_metarig(metarig)
        metarig.cloudrig.metarig_version = metarig_version


def register():
    bpy.app.handlers.load_post.append(update_all_metarigs)


def unregister():
    try:
        bpy.app.handlers.load_post.remove(update_all_metarigs)
    except ValueError:
        pass
