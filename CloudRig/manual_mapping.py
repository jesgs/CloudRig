# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from . import rig_components


# This allows you to right click on a button and link to documentation
def cloudrig_manual_map():
    url_manual_prefix = "https://studio.blender.org/tools/addons/cloudrig/"
    addon_prefs = "bpy.types.CloudRigPreferences"
    rig_prefs = "bpy.types.CloudRig_RigPreferences"
    rig_component = "bpy.types.RigComponent"
    params = "bpy.types.Params"
    generator = "bpy.types.GeneratorProperties"
    cloudrig_props = "bpy.types.Properties_Cloudrig"
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

    url_map = []

    # This is currently not working due to a bug in Blender, where
    # PropertyGroups within PropertyGroups don't resolve correctly
    # in the Online Manual operator.
    cloud_types = [name.replace("cloud_", "") for name in dir(rig_components) if "cloud" in name]
    for cloud_type in cloud_types:
        url_map.append((rig_component + cloud_type + "_*", "cloudrig-types"))

    # NOTE: More specific data paths have to come FIRST before data paths with wildcards!
    url_map.extend(
        [
            # Organizing Bones
            (f"{rig_prefs}.collection_ui_type", "organizing-bones#bone-collections"),
            (f"{rig_prefs}.active_collection_index", "organizing-bones#bone-collections"),
            ("bpy.ops.pose.cloudrig_collection_clipboard_*", "organizing-bones#quick-select"),
            ("bpy.types.cloudrigbonecollection.quick_access", "organizing-bones#quick-select"),
            ("bpy.ops.pose.cloudrig_collection_*", "organizing-bones#bone-collections"),
            ("bpy.ops.pose.cloudrig_collections_reveal_all", "organizing-bones#bone-collections"),
            ("bpy.ops.pose.cloudrig_reorder_collections", "organizing-bones#bone-collections"),
            (f"{addon_prefs}.bone_set_show_advanced", "organizing-bones#bone-collections"),
            ("bpy.types.boneset*", "organizing-bones#organizing-bones-1"),
            (f"{rig_component}.bone_sets*", "organizing-bones#organizing-bones-1"),
            ("bpy.ops.pose.cloudrig_bone_set_collection_*", "organizing-bones#organizing-bones-1"),
            ("bpy.types.nameproperty.*", "organizing-bones#organizing-bones-1"),
            # Rig UI
            ("bpy.ops.pose.cloudrig_keyframe_all_settings", "rig-ui"),
            ("bpy.ops.pose.armature_reset", "rig-ui"),
            (f"{cloudrig_props}.ui_edit_mode", "rig-ui"),
            # Troubleshooting
            (f"{generator}.active_log_index", "troubleshooting"),
            ("bpy.types.CloudRigLogEntry.*", "troubleshooting"),
            ("bpy.ops.armature.jump_to_bone", "troubleshooting"),
            # TODO: Quick Fix operators?
            # Addon Prefs
            (f"{addon_prefs}.widget_*", "cloudrig-types#appearance"),
            (f"{addon_prefs}.advanced_mode", "cloudrig-types#advanced-mode"),
            (f"{addon_prefs}.*", "cloudrig-types#shared-parameters"),
            ("bpy.ops.wm.cloudrig_report_bug", "introduction"),
            ("bpy.ops.preferences.set_bone_color_presets", "organizing-bones#bone-colors"),
            # Generator Parameters
            ("bpy.ops.pose.cloudrig_generate", "generator-parameters"),
            *[
                (
                    generator + "." + param,
                    "generator-parameters#" + (redirect or param).replace("_", "-"),
                )
                for param, redirect in generator_params.items()
            ],
            (f"{generator}.*", "generator-parameters"),
            # TODO: This gets masked by core Blender, seems like a bug.
            ("bpy.ops.object.cloudrig_metarig_toggle", "workflow-enhancements#metarig-swapping"),
            # Actions
            (f"{generator}.action*", "actions"),
            ("bpy.ops.object.cloudrig_action*", "actions"),
            # Component Types
            ("bpy.ops.pose.cloudrig_assign_component_type", "cloudrig-types#assigning-components"),
            ("bpy.ops.pose.cloudrig_copy_component", "cloudrig-types#assigning-components"),
            ("bpy.ops.pose.cloudrig_symmetrize_components", "cloudrig-types#assigning-components"),
            ("bpy.ops.armature.flatten_ik_chain", "cloudrig-types#flatten-bone-chain"),
            (f"{rig_component}.component_type", "cloudrig-types#assigning-components"),
            (f"{params}.*", "cloudrig-types"),  # TODO: This still does not work, report as bug?
        ]
    )

    # Make everything lower-case.
    url_map = [(tup[0].lower(), tup[1].lower()) for tup in url_map]

    return url_manual_prefix, url_map


def register():
    bpy.utils.register_manual_map(cloudrig_manual_map)


def unregister():
    try:
        bpy.utils.unregister_manual_map(cloudrig_manual_map)
    except ValueError:
        pass
