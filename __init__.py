rigify_info = {
	"name": "CloudRig"
}

from .operators import regenerate_rigify_rigs
from .operators import refresh_drivers
from .operators import mirror_rigify
from . import actions
from . import cloud_generator
from . import ui

import bpy, os
from bpy.props import StringProperty
from . import versioning

# This allows you to right click on a button and link to documentation
def cloudrig_manual_map():
	url_manual_prefix = "https://gitlab.com/blender/CloudRig/-/wikis/"
	params_pref = "bpy.types.rigifyparameters.cr_"
	generator_params_pref = "bpy.types.cloudrigproperties."

	cloud_chain = "CloudRig-Types#cloud_chain"
	cloud_fk_chain = "CloudRig-Types#cloud_fk_chain"
	cloud_ik_chain = "CloudRig-Types#cloud_ik_chain"
	cloud_limb = "CloudRig-Types#cloud_limb"

	url_manual_mapping = (
		("bpy.ops.pose.cloudrig_layer_init", "Organizing-Bones#customizing-bone-layers"),

		("bpy.ops.pose.cloudrig_generate", "Generator-Parameters"),
		(generator_params_pref+"custom_script", "Generator-Parameters#custom-script"),
		(generator_params_pref+"create_root", "Generator-Parameters#create-root"),
		(generator_params_pref+"double_root", "Generator-Parameters#double-root"),
		(generator_params_pref+"mechanism_selectable", "Generator-Parameters#selectable-helpers"),
		(generator_params_pref+"mechanism_movable", "Generator-Parameters#movable-helpers"),
		(generator_params_pref+"prefix_separator", "Generator-Parameters#prefix/suffix-separator"),
		(generator_params_pref+"suffix_separator", "Generator-Parameters#prefix/suffix-separator"),

		(generator_params_pref+"override_options", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"root_bone_group", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"root_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"root_parent_group", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"root_parent_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"override_def_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"def_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"override_mch_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"mch_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"override_org_layers", "Organizing-Bones#bone-sets"),
		(generator_params_pref+"org_layers", "Organizing-Bones#bone-sets"),

		(generator_params_pref+"*", "Generator-Parameters"),

		(params_pref+"show_chain_settings", cloud_chain),
		(params_pref+"deform_segments", cloud_chain),
		(params_pref+"bbone_segments", cloud_chain),
		(params_pref+"shape_key_helpers", cloud_chain),
		(params_pref+"sharp_sections", cloud_chain),
		(params_pref+"cap_control", cloud_chain),

		(params_pref+"show_fk_settings", cloud_fk_chain),
		(params_pref+"use_custom_limb_name", cloud_fk_chain),
		(params_pref+"use_custom_category_name", cloud_fk_chain),
		(params_pref+"custom_limb_name", cloud_fk_chain),
		(params_pref+"custom_category_name", cloud_fk_chain),
		(params_pref+"counter_rotate_str", cloud_fk_chain),
		(params_pref+"center_all_fk", cloud_fk_chain),
		(params_pref+"double_first_control", cloud_fk_chain),
		(params_pref+"use_fk_hinge", cloud_fk_chain),
		(params_pref+"use_custom_category_name", cloud_fk_chain),

		(params_pref+"show_ik_settings", cloud_ik_chain),
		(params_pref+"use_pole_target", cloud_ik_chain),
		(params_pref+"world_aligned_controls", cloud_ik_chain),

		(params_pref+"limb_type", cloud_limb),
		(params_pref+"use_foot_roll", cloud_limb),
		(params_pref+"heel_pivot_bone", cloud_limb),
		(params_pref+"double_ik_control", cloud_limb),
		(params_pref+"limb_lock_yz", cloud_limb),

		(params_pref+"bg_*", "Organizing-Bones#bone-sets"),

		(params_pref+"*", "CloudRig-Types"),

		("bpy.types.cloudrig_properties.*", "Custom-Properties"),
	)
	return url_manual_prefix, url_manual_mapping

modules = [
	regenerate_rigify_rigs,
	refresh_drivers,
	mirror_rigify,
	actions,
	cloud_generator,
	ui,
]

def register():
	from bpy.utils import register_class, register_manual_map
	for m in modules:
		m.register()

	register_manual_map(cloudrig_manual_map)
	versioning.do_blender_versioning()

def unregister():
	from bpy.utils import unregister_class, unregister_manual_map
	for m in reversed(modules):
		m.unregister()

	unregister_manual_map(cloudrig_manual_map)

if versioning.is_before_register_commit():
	print(f"Blender Version older than {register_commit_date}, self-registering CloudRig.")
	register()