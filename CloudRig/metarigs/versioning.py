# SPDX-License-Identifier: GPL-3.0-or-later

from ..generation.actions_component import ActionConstraintSetup
import bpy
from bpy.types import Object
from bpy.app.handlers import persistent

from ..generation.cloudrig import is_cloud_metarig
from ..rig_components import ALL_COMPONENT_MODULES
from ..bs_utils.prefs import get_addon_prefs

RIG_TYPE_MAP = {
    key: module.RIG_COMPONENT_CLASS.ui_name for key, module in ALL_COMPONENT_MODULES.items()
}

def setattr_safe(thing, key, value):
    if hasattr(thing, 'bl_rna') and type(thing.bl_rna.properties[key])==bpy.types.EnumProperty and type(value)==int:
        enum_value = thing.bl_rna.properties[key].enum_items[value].identifier
        setattr(thing, key, enum_value)
    else:
        setattr(thing, key, value)

def preserve_old_default(
    metarig: Object, param_name: str, old_default: float | int | bool | str
):
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
    # NOTE on limitations:
    # The old value is not stored in the file at all if it was left as default, so
    # there's no way to guarantee correct versioning when changing the default value of a parameter.
    # So, make really damn sure that default values are correct when first implementing them!
    metarig_version = get_addon_prefs().cloud_metarig_version
    print(
        f"CloudRig Versioning: {metarig.name} bumping version {cloudrig.metarig_version} -> {metarig_version}"
    )
    if cloudrig.metarig_version < 3:
        # Generated rigs used to keep the metarig data, which confuses some poll functions.
        if 'generation_date' in metarig.data or 'generation_time' in metarig.data or ('is_generated_cloudrig' in metarig.data and metarig.data['is_generated_cloudrig']):
            metarig.property_unset('cloudrig')
            return

    if cloudrig.metarig_version < 4:
        # Action Slots were renamed to Action Set-ups, and now support Blender's Action Slots.
        def find_first_setup_using_action(action: bpy.types.Action) -> ActionConstraintSetup | None:
            if not action:
                return
            for action_setup in cloudrig.generator.action_setups:
                if action_setup.action == action:
                    return action_setup

        generator_properties = cloudrig.generator.bl_system_properties_get()
        old_actions_data = [a.to_dict() for a in generator_properties.get('action_slots', [])]
        for old_setup in old_actions_data:
            new_setup = cloudrig.generator.action_setups.add()
            for key, value in old_setup.items():
                if hasattr(new_setup, key):
                    setattr_safe(new_setup, key, value)

        for old_setup, new_setup in zip(old_actions_data, cloudrig.generator.action_setups):
            if old_setup.get('is_corrective', False):
                new_setup.trigger_a = find_first_setup_using_action(old_setup.get('trigger_action_a', None))
                new_setup.trigger_b = find_first_setup_using_action(old_setup.get('trigger_action_b', None))

        if 'action_slots' in generator_properties:
            del generator_properties['action_slots']

    if cloudrig.metarig_version < 5:
        # Trigger the new set_transform callback in 5.0, which updates the underlying data 
        # of the component_type property to be masked by the transform callbacks, 
        # making it resilient to changing the UI names of components in the future.
        for pbone in metarig.pose.bones:
            if pbone.cloudrig_component.component_type:
                pbone.cloudrig_component.component_type = pbone.cloudrig_component.component_type


@persistent
def update_all_metarigs(dummy=None):
    if not hasattr(bpy.data, 'objects'):
        # We want this function to run on Register, because we want to version metarigs in current scene
        # when user enables CloudRig. But this is not allowed by PyAPI, so we defer the call to until after 
        # add-on registration completes, using a timer.
        bpy.app.timers.register(update_all_metarigs)
        return
    metarig_version = get_addon_prefs().cloud_metarig_version

    cloud_metarigs = [
        o for o in bpy.data.objects if o.type == 'ARMATURE' and is_cloud_metarig(o)
    ]

    for metarig in cloud_metarigs:
        if metarig.library or metarig.override_library:
            # Don't try to version linked metarigs, there's no point.
            # Also, metarigs shouldn't get linked and overridden in the first place.
            continue

        # Trigger component type update callbacks to update_ui_bone_sets().
        # https://projects.blender.org/Mets/CloudRig/issues/164
        for pb in metarig.pose.bones:
            pb.cloudrig_component.update_ui_bone_sets()

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
