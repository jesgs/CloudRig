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

	cloud_types_pref = "CloudRig-Types#cloud_"
	cloud_types = ['bone', 'chain', 'curve', 'face_chain', 'fk_chain', 'ik_chain', 'limbs', 'shoulder', 'spine', 'spline_ik', 'eye']

	# All CloudRig type parameters are expected to be prefixed with
	# CR_<rig_type>_, eg. CR_chain_segments for cloud_chain.

	# Also on the wiki, all CloudRig types should have a paragraph in the
	# CloudRig-Types page with the name of the type.

	# Knowing this, we can build a URL mapping automatically, which also
	# enables us to add or remove parameters in the future without having to
	# worry about keeping the URL mapping up to date, as long as we stick to the
	# naming conventions above.
	url_map = []
	for t in cloud_types:
		url_map.append(
			(params_pref + t + "_*", cloud_types_pref+t)
		)

	# The following mapping has to be kept updated manually however.
	# IMPORTANT: More specific data paths have to come FIRST before data paths with wildcards!
	url_map.extend([
		# Generator Parameters
		("bpy.ops.pose.cloudrig_generate", "Generator-Parameters"),
		(generator_params_pref+"custom_script", "Generator-Parameters#custom-script"),
		(generator_params_pref+"create_root", "Generator-Parameters#create-root"),
		(generator_params_pref+"double_root", "Generator-Parameters#double-root"),
		(generator_params_pref+"mechanism_selectable", "Generator-Parameters#selectable-helpers"),
		(generator_params_pref+"mechanism_movable", "Generator-Parameters#movable-helpers"),

		# Organizing Bones
		("bpy.ops.pose.cloudrig_layer_init", "Organizing-Bones#customizing-bone-layers"),
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
		(generator_params_pref+"show_layers_preview_hidden", "Organizing-Bones#bone-sets"),
		(params_pref+"show_bone_sets", "Organizing-Bones#bone-sets"),
		(params_pref+"bg_*", "Organizing-Bones#bone-sets"),

		# Actions
		("bpy.ops.pose.cloudrig_action_*", "Actions"),
		(generator_params_pref+"active_action_index", "Actions"),
		("bpy.types.cloudrigaction.*", "Actions"),

		# Catch-alls
		(generator_params_pref+"*", "Generator-Parameters"),
		(params_pref+"*", "CloudRig-Types"),
		("bpy.types.cloudrig_properties.*", "Custom-Properties"),
	])
	return url_manual_prefix, url_map

modules = [
	regenerate_rigify_rigs,
	refresh_drivers,
	mirror_rigify,
	actions,
	cloud_generator,
	ui,
	versioning
]

def register():
	from bpy.utils import register_class, register_manual_map
	for m in modules:
		m.register()

	register_manual_map(cloudrig_manual_map)

def unregister():
	from bpy.utils import unregister_class, unregister_manual_map
	for m in reversed(modules):
		m.unregister()

	unregister_manual_map(cloudrig_manual_map)

if versioning.is_before_register_commit():
	register()