import bpy
from . import rig_components


# This allows you to right click on a button and link to documentation
def cloudrig_manual_map():
    url_manual_prefix = "https://studio.blender.org/pipeline/addons/cloudrig/"
    addon_prefs_path = "bpy.types.cloudrigpreferences."  # Add-on preferences don't seem to be supported at all by manual mapping.
    rig_prefs_path = "bpy.types.cloudrig_rigpreferences"
    params_path = "bpy.types.rigcomponent."  # This doesn't seem to work with nested PropertyGroups, it just results in `bpy.types.bpy_struct`. This makes this whole manual mapping pretty pointless. :(
    generator_path = "bpy.types.generatorproperties."
    generator_params = {
        "target_rig": "",
        "widget_collection": "",
        "reload_widgets": "widget-collection",
        "ensure_root": "",
        "properties_bone": "",
        "custom_script": "post-generation-script",
        "generate_test_action": "",
        "test_action": "generate-action",
    }

    if False:
        # This is currently not working due to a bug in Blender, where
        # PropertyGroups within PropertyGroups don't resolve correctly
        # in the Online Manual operator.
        cloud_types = [
            name.replace("cloud_", "")
            for name in dir(rig_components)
            if "cloud" in name
        ]
        for cloud_type in cloud_types:
            url_map.append((params_path + cloud_type + "_*", "cloudrig-types"))

    url_map = []

    # NOTE: More specific data paths have to come FIRST before data paths with wildcards!
    url_map.extend(
        [
            (rig_prefs_path + ".active_collection_index", "bone-organization"),
            ("bpy.ops.pose.cloudrig_collections_reveal_all", "bone-organization"),
            # Troubleshooting
            ("bpy.types.generatorproperties.active_log_index", "troubleshooting"),
            # Addon Prefs also don't work due to a similar bug... https://projects.blender.org/blender/blender/issues/121408
            (addon_prefs_path + "advanced_mode", "cloudrig-types#shared-parameters"),
            (addon_prefs_path + "*", "cloudrig-types#shared-parameters"),
            ("bpy.ops.pose.cloudrig_assign_component_type", "cloudrig-types"),
            # Generator Parameters
            ("bpy.ops.pose.cloudrig_generate", "generator-parameters"),
            *[
                (
                    generator_path + param,
                    "generator-parameters#" + (redirect or param).replace("_", "-"),
                )
                for param, redirect in generator_params.items()
            ],
            (generator_path + "*", "generator-parameters"),
            # Organizing Bones
            (
                addon_prefs_path + "bone_set_show_advanced",
                "organizing-bones#bone-collections",
            ),
            ("bpy.types.boneset*", "organizing-bones#organizing-bones-1"),
            ("bpy.types.rigcomponent.bone_sets*", "organizing-bones#bone-collections"),
            (
                "bpy.ops.pose.cloudrig_bone_set_collection_add",
                "organizing-bones#organizing-bones-1",
            ),
            (
                "bpy.ops.pose.cloudrig_bone_set_collection_remove",
                "organizing-bones#organizing-bones-1",
            ),
            (
                "bpy.ops.pose.cloudrig_bone_set_collection_reset",
                "organizing-bones#organizing-bones-1",
            ),
            # Actions
            (generator_path + "action*", "actions"),
            ("bpy.ops.object.cloudrig_action*", "actions"),
            (params_path + "*", "cloudrig-types"),  # Doesn't work, see above.
        ]
    )
    return url_manual_prefix, url_map


def register():
    bpy.utils.register_manual_map(cloudrig_manual_map)


def unregister():
    try:
        bpy.utils.unregister_manual_map(cloudrig_manual_map)
    except ValueError:
        pass
