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

modules = [
	actions,
	cloud_generator,
	ui,
	versioning,
	manual,
	operators,
]

def register():
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
