from typing import List
import sys, importlib, inspect

from rigify import feature_sets
from bpy.utils import register_class, unregister_class

from . import versioning, manual, operators, rigs, utils, rig_features, ui, properties
from .generation import troubleshooting, cloud_generator

rigify_info = {
	'name': "CloudRig is no longer a Rigify extension, but a stand-alone add-on!"
	,'author': "Demeter Dzadik"
	,'version': (0, 0, 9)
	,'blender': (3, 5, 0)	# This should be the lowest Blender version that is currently compatible.
	,'description': "Feature set developed by the Blender Animation Studio"
	,'doc_url': "https://gitlab.com/blender/CloudRig/-/wikis/"
	,'link': "https://gitlab.com/blender/CloudRig/"
}

max_blender_version = (4, 0, 0) # This should be set for in commits that will be tagged as a release.

bl_info = {
	'name' : "CloudRig"
	,'version' : (1, 0, 0)
	,'blender' : (3, 6, 0)
	,'description' : "Rig generation and rigging workflow toolkit"
	,'location': "Properties->Armature Data"
	,'category': 'Rigging'
	,'doc_url' : "https://gitlab.com/blender/CloudRig/"
}

# NOTE: Load order matters, eg. cloud_generator relies on some types already being registered!
modules = [
	troubleshooting,
	rig_features,
	cloud_generator,
	ui,
	versioning,
	manual,
	operators,
	rigs,
	utils,
	properties
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
	"""Called by Blender when enabling the CloudRig add-on."""
	# TODO: Throw a useful error when trying to use as a Rigify extension.
	register_unregister_modules(modules, True)

def unregister():
	"Called by Rigify when uninstalling or disabling CloudRig."
	register_unregister_modules(modules, False)
	try:
		del feature_sets.CloudRig
	except AttributeError:
		pass
