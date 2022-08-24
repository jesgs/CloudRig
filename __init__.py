from typing import List
import sys, importlib, inspect

from rigify import feature_sets
from bpy.utils import register_class, unregister_class

from . import versioning, manual, operators, ui, ui_rig_types, rigs, utils, rig_features
from .generation import actions, troubleshooting, cloud_generator

rigify_info = {
	'name': "CloudRig"
	,'author': "Demeter Dzadik"
	,'version': (0, 0, 8)
	,'blender': (3, 2, 0)	# This should be the lowest Blender version that is currently compatible.
	,'description': "Feature set developed by the Blender Animation Studio"
	,'doc_url': "https://gitlab.com/blender/CloudRig/-/wikis/"
	,'link': "https://gitlab.com/blender/CloudRig/"
}

bl_info = {
	'name' : "CloudRig is not an Addon!"
	,'version' : (0, 0, 8)
	,'blender' : (3, 2, 0)
	,'description' : "It should be installed as a Feature Set within the Rigify addon"
	,'location': "Addons->Rigify->Feature Sets->Install Feature Set from File"
	,'category': 'Rigging'
	,'doc_url' : "https://gitlab.com/blender/CloudRig/"
}

# NOTE: Load order matters, eg. cloud_generator relies on some types already being registered!
modules = [
	actions,
	troubleshooting,
	rig_features,
	cloud_generator,
	ui,
	versioning,
	manual,
	operators,
	ui_rig_types,
	rigs,
	utils
]

def register_unregister_modules(modules: List, register: bool):
	"""Recursively register or unregister modules by looking for either
	un/register() functions or lists named `registry` which should be a list of 
	registerable classes.
	"""
	register_func = register_class if register else unregister_class

	for m in modules:
		if register:
			importlib.reload(m)
		if hasattr(m, 'registry'):
			for c in m.registry:
				try:
					register_func(c)
				except Exception as e:
					un = 'un' if not register else ''
					print(f"Warning: CloudRig failed to {un}register class: {c.__name__}")
					print(e)

		if hasattr(m, 'modules'):
			register_unregister_modules(m.modules, register)

		if register and hasattr(m, 'register'):
			m.register()
		elif hasattr(m, 'unregister'):
			m.unregister()

def register():
	"""Called by Rigify when installing or enabling CloudRig."""
	caller_name = inspect.stack()[2].function
	trying_to_install_as_addon = caller_name == 'execute'
	assert not trying_to_install_as_addon, "CloudRig is not an addon. Install it as a Feature Set within the Rigify addon."

	rigify_info['tracker_url'] = troubleshooting.url_prefill_from_cloudrig()
	feature_sets.CloudRig = sys.modules[__name__]

	register_unregister_modules(modules, True)

def unregister():
	"Called by Rigify when uninstalling or disabling CloudRig."
	register_unregister_modules(modules, False)
	try:
		del feature_sets.CloudRig
	except AttributeError:
		pass
