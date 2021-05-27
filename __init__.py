import bpy, os, importlib

from . import actions
from . import cloud_generator
from . import ui
from . import versioning
from . import manual
from . import operators
from . import overlay
from . import gizmo
from . import troubleshooting
from . import parent_switching

rigify_info = {
	'name': "CloudRig",
	'author': "Demeter Dzadik",
	'version': (0, 0, 7),
	'blender': (3, 0, 0),	# This should be the lowest Blender version that is currently compatible.
	'description': "Feature set developed by the Blender Animation Studio",
	'doc_url': "https://gitlab.com/blender/CloudRig/-/wikis/",
	'link': "https://gitlab.com/blender/CloudRig/",
}

modules = [
	actions,
	troubleshooting,
	cloud_generator, # NOTE: Load order matters, since cloud_generator relies on some types already being registered!
	ui,
	versioning,
	manual,
	operators,
	overlay,
	parent_switching,
	# gizmo,
]

def register():
	from bpy.utils import register_class
	for m in modules:
		importlib.reload(m)
		m.register()

	rigify_info['tracker_url'] = troubleshooting.url_prefill_from_cloudrig()

def unregister():
	from bpy.utils import unregister_class
	for m in reversed(modules):
		m.unregister()

from rigify import feature_set_list
if not hasattr(feature_set_list, 'call_register_function'):
	register()
