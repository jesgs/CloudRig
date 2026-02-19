# SPDX-License-Identifier: GPL-3.0-or-later

import importlib
from types import ModuleType

import bpy
from bpy.utils import register_class, unregister_class

from . import (
    bs_utils,
    generation,
    icons,
    manual_mapping,
    metarigs,
    operators,
    prefs,
    properties,
    rig_component_features,
    rig_components,
    translations,
    ui,
    utils,
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
    translations,
]


def recurive_register(modules: list[ModuleType], register: bool):
    """Recursively register or unregister modules by looking for either
    un/register() functions or lists named `registry` which should be a list of
    registerable classes.
    """
    register_func = register_class if register else unregister_class

    for m in modules:
        un = "un"
        if register:
            importlib.reload(m)
            un = ""

        if hasattr(m, 'registry'):
            for c in m.registry:
                try:
                    register_func(c)
                except Exception as e:
                    print(f"CloudRig: Failed to {un}register class: {c.__name__}")
                    print(e)

        if hasattr(m, 'modules'):
            recurive_register(m.modules, register)

        if register and hasattr(m, 'register'):
            m.register()
        elif hasattr(m, 'unregister'):
            m.unregister()


def register():
    """Very first entry point called by Blender when enabling the add-on."""
    if __name__.startswith("rigify"):
        raise Exception("CloudRig is not a Rigify feature set!")
    recurive_register(modules, True)
    bpy.app.translations.register(__name__, translations.translations_dict)


def unregister():
    """Called by Blender when disabling the add-on."""

    # We want to save add-on prefs to file so they don't get lost when the add-on is disabled.
    # This should be done before unregistering anything, otherwise things can fail.
    prefs.update_prefs_on_file()

    recurive_register(modules, False)
    bpy.app.translations.unregister(__name__)
