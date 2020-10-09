rigify_info = {
	'name': "CloudRig",
	'author': "Demeter Dzadik",
	'version': (0, 0, 4),
	'blender': (2, 82, 0),
	'description': "Feature set developed by the Blender Animation Studio",
	'doc_url': "https://gitlab.com/blender/CloudRig/-/wikis/",
	'tracker_url': "https://gitlab.com/blender/CloudRig/-/issues/new",
	'link': "https://gitlab.com/blender/CloudRig/",
}

import bpy, os

from . import actions
from . import cloud_generator
from . import ui
from . import versioning
from . import manual
from . import operators
from . import overlay
from . import gizmo
from . import troubleshooting

modules = [
	actions,
	troubleshooting,
	cloud_generator, # NOTE: Load order matters, since cloud_generator relies on some types already being registered!
	ui,
	versioning,
	manual,
	operators,
	overlay,
	# gizmo,
]

def register():
	print("Registering CloudRig.")
	from bpy.utils import register_class
	for m in modules:
		m.register()

def unregister():
	from bpy.utils import unregister_class
	for m in reversed(modules):
		m.unregister()

from rigify import feature_set_list
if not hasattr(feature_set_list, 'call_register_function'):
	register()
