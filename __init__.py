# SPDX-License-Identifier: GPL-3.0-or-later

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
    generation,
    metarigs,
    icons,
    bs_utils,
)

modules = [
    ui,
    manual_mapping,
    utils,
    bs_utils,
    # NOTE: Beyond this point, registration order matters!
    # - For CollectionProperties and PointerProperties, their type must
    # be registered before they themselves are.
    icons,
    rig_component_features,
    rig_components,
    generation,
    operators,
    properties,
    prefs,
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


def register():
    """Called by Blender when enabling the CloudRig add-on, or on Blender launch if already enabled."""

    if __name__.startswith("rigify"):
        # If trying to register as a Rigify feature-set, throw useful error.
        raise Exception(
            "CloudRig is no longer a Rigify feature set. Install it as a regular add-on."
        )

    register_unregister_modules(modules, True)


def unregister():
    """Called by Blender when disabling the CloudRig add-on."""

    # We need to save add-on prefs to file before unregistering anything, 
    # otherwise things can fail in various ways, like hard errors or just
    # data getting saved as integers instead of bools or enums.
    prefs.update_prefs_on_file()

    register_unregister_modules(modules, False)
