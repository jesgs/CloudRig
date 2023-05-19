from typing import List
import sys, importlib, inspect

from bpy.utils import register_class, unregister_class

from . import versioning, manual, operators, rig_components, rig_component_features, utils, ui, properties, prefs
from .generation import troubleshooting, cloud_generator

rigify_info = {
    'name': "CloudRig is no longer a Rigify extension, but a stand-alone add-on!"
    ,'author': "Demeter Dzadik"
    ,'version': (0, 0, 9)
}

max_blender_version = (10, 0, 0) # This should be set for in commits that will be tagged as a release.

bl_info = {
    'name' : "CloudRig",
    'author' : 'Demeter Dzadik',
    'version' : (1, 0, 0),
    'blender' : (3, 6, 0), # This should be the lowest Blender version that is currently compatible.
    'blender_max' : (4, 0, 0),
    'description' : "Rig generation and rigging workflow toolkit by Blender Studio",
    'location': "Properties->Armature Data",
    'category': 'Rigging',
    'doc_url' : "https://gitlab.com/blender/CloudRig/",
}

modules = [
    ui,
    versioning,
    manual,
    operators,
    utils,
    # NOTE: Beyond this point, registration order matters!
    # For CollectionProperties and PointerProperties, their type must 
    # be registered before they themselves are.
    # For Panels, they must be registered before their bl_parent_id is.
    rig_component_features,
    rig_components,
    prefs,
    troubleshooting,
    cloud_generator,
    properties,
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
    # TODO: Throw a useful error when trying to use as a Rigify extension.
    register_unregister_modules(modules, True)
    utils.misc.version_min = bl_info['blender']
    utils.misc.version_max = bl_info['blender_max']

def unregister():
    register_unregister_modules(modules, False)
