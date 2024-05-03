import bpy
from . import rig_components

# TODO 4.1: Update all of this.


# This allows you to right click on a button and link to documentation
def cloudrig_manual_map():
    url_manual_prefix = "https://projects.blender.org/Mets/CloudRig/wiki/"
    prefs_path = "bpy.types.cloudrigpreferences."   # Add-on preferences don't seem to be supported at all by manual mapping.
    params_path = "bpy.types.rigcomponent." # This doesn't seem to work with nested PropertyGroups, it just results in `bpy.types.bpy_struct` :(
    generator_path = "bpy.types.generatorproperties."
    generator_params = {
        "target_rig": "", 
        "widget_collection": "", 
        "reload_widgets": "widget-collection", 
        "ensure_root": "", 
        "properties_bone": "", 
        "custom_script": "post-generation-script", 
        "generate_test_action": "", 
        "test_action": "generate-test-action",
    }

    cloud_types = [
        name.replace("cloud_", "") for name in dir(rig_components) if "cloud" in name
    ]

    url_map = []
    # for cloud_type in cloud_types:
    #     url_map.append((params_path + cloud_type + "_*", "CloudRig-Types"))

    # NOTE: More specific data paths have to come FIRST before data paths with wildcards!
    url_map.extend(
        [
            (prefs_path + "advanced_mode", "CloudRig-Types#shared-parameters"), # Doesn't work, see above.
            (prefs_path + "*", "CloudRig-Types#shared-parameters"),             # Doesn't work, see above.
            ("bpy.ops.pose.cloudrig_assign_component_type", "CloudRig-Types"),
            # Generator Parameters
            ("bpy.ops.pose.cloudrig_generate", "Generator-Parameters"),
            *[(generator_path + param, "Generator-Parameters#"+(redirect or param).replace("_", "-")) 
            for param, redirect in generator_params.items()],
            (generator_path + "*", "Generator-Parameters"),
            # Organizing Bones
            (prefs_path + "bone_set_show_advanced", "Organizing-Bones#bone-collections"),
            ("bpy.types.boneset*", "Organizing-Bones#bone-collections"),
            ("bpy.types.rigcomponent.bone_sets*", "Organizing-Bones#bone-collections"),
            # Actions
            (generator_path + "action*", "Actions"),
            ("bpy.ops.object.cloudrig_action*", "Actions"),

            (params_path + "*", "CloudRig-Types"),
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
