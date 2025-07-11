# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, os
import importlib
from bpy.utils import register_class, unregister_class

from . import (
    manual_mapping,
    operators,
    rig_components,
    rig_component_features,
    utils,
    ui,
    properties,
    prefs,
    prefs_save_load,
    generation,
    metarigs,
    icons,
)

bl_info = {
    'name': "CloudRig",
    'description': "Rig generation and rigging workflow toolkit by Blender Studio",
    'author': 'Demeter Dzadik',
    'version': (2, 1, 21),
    # This should be the lowest Blender version that is currently compatible.
    'blender': (4, 2, 0),
    'location': "Properties->Armature Data",
    'doc_url': "https://projects.blender.org/Mets/CloudRig/wiki",
    'tracker_url': "https://projects.blender.org/studio/blender-studio-pipeline/issues/new?template=.gitea/issue_template/cloudrig_bug.yaml",
    'support': 'COMMUNITY',
    'category': 'Rigging',
}
bl_info_copy = bl_info.copy()

modules = [
    ui,
    manual_mapping,
    utils,
    # NOTE: Beyond this point, registration order matters!
    # - For CollectionProperties and PointerProperties, their type must
    # be registered before they themselves are.
    # - For Panels, they must be registered before their bl_parent_id is.
    # - Hotkeys must come after `cloudrig`, since we're storing them on a panel.
    rig_component_features,
    prefs_save_load,
    rig_components,
    generation,
    operators,
    properties,
    prefs,
    metarigs,
    icons,
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
    """For the sake of post-generation scripts and external rig components, 
    we want to make sure CloudRig modules can be imported without the extension prefixes.
    """
    import sys
    addon_name = bl_info_copy['name']
    if addon_name not in sys.modules:
        dirname = __file__.split(os.sep)[-2]
        module_mapping = {}
        for mod_name, module in sys.modules.items():
            if bpy.app.version < (4, 2, 0):
                if dirname in mod_name:
                    module_mapping[mod_name.replace(dirname, addon_name)] = module
            else:
                pass
                # This works, but it results in policy violation.
                # if dirname in mod_name and mod_name.startswith("bl_ext"):
                #     module_mapping[dirname+mod_name.split(dirname)[-1]] = module

        sys.modules.update(module_mapping)


def register():
    """Called by Blender when enabling the CloudRig add-on, or on Blender launch if already enabled."""

    if __name__.startswith("rigify"):
        # If trying to register as a Rigify feature-set, throw useful error.
        raise Exception(
            "CloudRig is no longer a Rigify feature set. Install it as a regular add-on."
        )

    ensure_importable_modules()
    register_unregister_modules(modules, True)


def unregister():
    """Called by Blender when disabling the CloudRig add-on."""

    # We need to save add-on prefs to file before unregistering anything, 
    # otherwise things can fail in various ways, like hard errors or just
    # data getting saved as integers instead of bools or enums.
    prefs.update_prefs_on_file()

    register_unregister_modules(modules, False)
