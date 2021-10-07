rigify_info = {
	'name': "CloudRig"
	,'author': "Demeter Dzadik"
	,'version': (0, 0, 7)
	,'blender': (3, 0, 0)	# This should be the lowest Blender version that is currently compatible.
	,'description': "Feature set developed by the Blender Animation Studio"
	,'doc_url': "https://gitlab.com/blender/CloudRig/-/wikis/"
	,'link': "https://gitlab.com/blender/CloudRig/"
}

bl_info = {
	'name' : "CloudRig is not an Addon!"
	,'version' : (0, 0, 7)
	,'blender' : (3, 0, 0)
	,'description' : "It should be installed as a Feature Set within the Rigify addon"
	,'location': "Addons->Rigify->Feature Sets->Install Feature Set from File"
	,'category': 'Rigging'
	,'doc_url' : "https://gitlab.com/blender/CloudRig/"
}

import importlib
from bpy.utils import register_class, unregister_class

from rigify import feature_sets
import sys

from .utils import ui_list
from .rig_features import bone_set
from .rig_features import parent_switching
from .generation import actions
from .generation import troubleshooting
from .generation import cloud_generator
from . import versioning
from . import manual
from . import operators
from . import ui
from . import ui_rig_types
from . import rigs

# NOTE: Load order matters, eg. cloud_generator relies on some types already being registered!
modules = [
	ui_list,
	actions,
	troubleshooting,
	bone_set,
	cloud_generator,
	ui,
	versioning,
	manual,
	operators,
	parent_switching,
	ui_rig_types,
	rigs
]

def register():
	import inspect
	caller_name = inspect.stack()[2].function
	trying_to_install_as_addon = caller_name == 'execute'
	assert not trying_to_install_as_addon, "CloudRig is not an addon. Install it as a Feature Set within the Rigify addon."

	rigify_info['tracker_url'] = troubleshooting.url_prefill_from_cloudrig()
	feature_sets.CloudRig = sys.modules[__name__]

	for m in modules:
		importlib.reload(m)
		if hasattr(m, 'registry'):
			for c in m.registry:
				register_class(c)
		if hasattr(m, 'register'):
			m.register()

def unregister():
	for m in reversed(modules):
		if hasattr(m, 'unregister'):
			m.unregister()
		if hasattr(m, 'registry'):
			for c in m.registry:
				unregister_class(c)

	del feature_sets.CloudRig