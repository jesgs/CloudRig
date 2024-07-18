import bpy
from bpy.types import Object, ID, PoseBone
from bpy.app.handlers import persistent

from ..generation.cloudrig import is_cloud_metarig
from ..rig_component_features.ui import get_addon_prefs
from ..rig_component_features.object import set_enum_property_by_integer
from ..rig_components import component_modules

RIG_TYPE_MAP = {
    key: module.RIG_COMPONENT_CLASS.ui_name for key, module in component_modules.items()
}


def update_enum_property(
    owner: ID | PoseBone,
    old_key: str,
    new_key: str,
    value: int,
):
    enum_string_value = set_enum_property_by_integer(owner, new_key, value)
    if enum_string_value:
        print(f"Updated enum property {old_key}->{new_key}, value: {enum_string_value}")
    else:
        # If an enum property's definition is lost, their string value is lost
        # and is left with an int. In this case, just back up that int.
        owner[new_key] = value


def rename_blender3_parameters(metarig, dictionary):
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


def preserve_old_default(
    metarig: Object, param_name: str, old_default: float | int | bool | str
):
    for pb in metarig.pose.bones:
        if param_name not in pb.cloudrig_component.params:
            setattr(pb.cloudrig_component.params, param_name, old_default)
            print(
                f"Preserve old default value: {pb.name} -> {param_name} = {old_default}"
            )


def copy_property(from_thing, from_name, to_thing, to_name=None):
    if hasattr(from_thing, 'to_dict'):
        from_thing = from_thing.to_dict()
    if from_name not in from_thing:
        return

    if not to_name:
        to_name = from_name

    value = from_thing[from_name]
    if not value:
        return
    setattr(to_thing, to_name, value)


def version_blender3_metarig(metarig):
    cloudrig = metarig.cloudrig
    print(
        "Versioning from pre-Blender 4.0 to post-4.0. This might take a long time for a complex rig."
    )
    # Convert CloudRig rigs from before Blender 4.0, when CloudRig was a Rigify feature set.

    # 1: Generator properties
    if not cloudrig.enabled:
        cloudrig.enabled = True
        copy_property(
            metarig.data, 'rigify_target_rig', cloudrig.generator, 'target_rig'
        )
        copy_property(
            metarig.data,
            'rigify_widgets_collection',
            cloudrig.generator,
            'widget_collection',
        )
        if 'cloudrig_parameters' in metarig.data:
            params = metarig.data['cloudrig_parameters']
            copy_property(params, 'custom_script', cloudrig.generator)
            copy_property(params, 'widget_collection', cloudrig.generator)

    # 2: Bone Layers -> Bone Collections
    if any([c.name.startswith("Layer ") for c in metarig.data.collections_all]):
        for bone_coll in metarig.data.collections_all[:]:
            if not bone_coll.name.startswith("Layer "):
                metarig.data.collections.remove(bone_coll)

        for bone_coll in metarig.data.collections_all[:]:
            number = int(bone_coll.name.split(" ")[1])
            bone_coll.name = metarig.data['rigify_layers'][number - 1]['name']

    # 3: Rig types & parameters
    global RIG_TYPE_MAP
    for pb in metarig.pose.bones:
        if pb.cloudrig_component.component_type:
            continue
        if 'rigify_type' in pb and pb['rigify_type'] in RIG_TYPE_MAP.keys():
            pb.cloudrig_component.component_type = RIG_TYPE_MAP[pb['rigify_type']]
            print(pb.name)
            for old_key in pb['rigify_parameters'].keys():
                key = old_key.replace("CR_", "")
                if key.startswith("BG_LAYERS_"):
                    bone_set_name = key.replace("BG_LAYERS_", "")
                    bone_sets = pb.cloudrig_component.params.bone_sets
                    if hasattr(bone_sets, bone_set_name):
                        bone_set = getattr(bone_sets, bone_set_name)
                        bone_set.collections.clear()
                        layers = pb['rigify_parameters'][old_key]
                        for i, is_assigned in enumerate(layers):
                            if is_assigned:
                                bsc = bone_set.collections.add()
                                bsc.name = metarig.data['rigify_layers'][i]['name']
                    continue

                for rig_type in RIG_TYPE_MAP.keys():
                    rig_type = rig_type.replace("cloud_", "")
                    if key.startswith(rig_type):
                        key = key.replace(rig_type + "_", "")
                        break
                if not hasattr(pb.cloudrig_component.params, rig_type):
                    print("Can't version param: ", old_key, rig_type)
                    break
                params = getattr(pb.cloudrig_component.params, rig_type)
                if hasattr(params, key):
                    value = pb['rigify_parameters'][old_key]
                    if value:
                        try:
                            setattr(params, key, value)
                        except TypeError:
                            set_enum_property_by_integer(params, key, value)

            # Initialize UI bone set data. (No conversion, for now...)
            pb.cloudrig_component.update_ui_bone_sets()

    # Trigger the active component update callback, to initialize some data.
    cloudrig.active_component_index = 0

    # 4: Actions
    action_slots = cloudrig.generator.action_slots
    if len(action_slots) == 0:
        old_slots = []
        if 'rigify_action_slots' in metarig.data:
            old_slots = metarig.data['rigify_action_slots']
        if (
            'cloudrig_parameters' in metarig.data
            and 'action_slots' in metarig.data['cloudrig_parameters']
        ):
            old_slots = metarig.data['cloudrig_parameters']['action_slots']
        for slot_dict in old_slots:
            act_slot = action_slots.add()
            for key, value in slot_dict.items():
                try:
                    setattr(act_slot, key, value)
                except TypeError:
                    if type(value) == int:
                        set_enum_property_by_integer(act_slot, key, value)
                    elif "trigger_action" in key:
                        # For some reason when accessing a null PointerProperty via dictionary syntax,
                        # it returns a <bpy id prop> instead of None.
                        pass


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
    if cloudrig.metarig_version < 2:
        pass


def get_old_cloud_metarigs():
    return [
        o
        for o in bpy.data.objects
        if o.type == 'ARMATURE'
        and 'cloudrig_parameters' in o.data
        and 'ui_data' not in o.data
        and any(['rigify_type' in pb and pb['rigify_type'] for pb in o.pose.bones])
        and not any([pb.cloudrig_component.component_type for pb in o.pose.bones])
    ]


@persistent
def update_all_metarigs(dummy):
    metarig_version = get_addon_prefs().cloud_metarig_version
    pre_blender4_metarigs = get_old_cloud_metarigs()
    for metarig in pre_blender4_metarigs:
        version_blender3_metarig(metarig)

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
