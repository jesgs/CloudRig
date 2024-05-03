import importlib
import sys
import os
from bpy.utils import register_class, unregister_class
from .metarigs import versioning

from . import (
    manual,
    operators,
    rig_components,
    rig_component_features,
    utils,
    ui,
    properties,
    prefs,
    generation,
    metarigs,
)

# This should be set for in commits that will be tagged as a release.
max_blender_version = (10, 0, 0)

bl_info = {
    'name': "CloudRig",
    'description': "Rig generation and rigging workflow toolkit by Blender Studio",
    'author': 'Demeter Dzadik',
    'version': (2, 0, 0),
    # This should be the lowest Blender version that is currently compatible.
    'blender': (4, 1, 0),
    'location': "Properties->Armature Data",
    'doc_url': "https://projects.blender.org/Mets/CloudRig/wiki",
    'tracker_url': "https://projects.blender.org/Mets/CloudRig/issues/new?template=.gitea/issue_template/bug.yaml",
    'support' : 'OFFICIAL',
    'category': 'Rigging',
}

modules = [
    ui,
    manual,
    utils,
    # NOTE: Beyond this point, registration order matters!
    # - For CollectionProperties and PointerProperties, their type must
    # be registered before they themselves are.
    # - For Panels, they must be registered before their bl_parent_id is.
    # - Hotkeys must come after `cloudrig`, since we're storing them on a panel.
    rig_component_features,
    rig_components,
    versioning,
    prefs,
    generation,
    operators,
    properties,
    metarigs,
]


def register_unregister_modules(modules: list, register: bool):
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
                    print(
                        f"Warning: CloudRig failed to {un}register class: {c.__name__}"
                    )
                    print(e)

        if hasattr(m, 'modules'):
            register_unregister_modules(m.modules, register)

        if register and hasattr(m, 'register'):
            m.register()
        elif hasattr(m, 'unregister'):
            m.unregister()


def ensure_importable_modules():
    """This function is to fix GitLab/GitHub downloads that rename the add-on's 
    root folder (and thereby python module name) from MyAddOn to MyAddOn-master.
    
    We do this by populating the sys.modules dictionary with references to the 
    existing modules, pointed to by the correct names.
    """
    addon_name = bl_info['name']
    if addon_name not in sys.modules:
        dirname = __file__.split(os.sep)[-2]
        stuff = {}
        for name, module in sys.modules.items():
            if dirname in name:
                stuff[name.replace(dirname, addon_name)] = module
        sys.modules.update(stuff)


def register():
    """Called by Blender when enabling the CloudRig add-on."""
    # TODO 4.1: Throw a useful error when trying to use as a Rigify extension.

    ensure_importable_modules()
    register_unregister_modules(modules, True)
    utils.misc.version_min = bl_info['blender']
    utils.misc.version_max = max_blender_version


def unregister():
    register_unregister_modules(modules, False)
