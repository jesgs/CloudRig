import importlib
import os
import sys
from types import ModuleType

import bpy

ALL_COMPONENT_MODULES = {}


def load_components(dir_path: str, relative=True) -> dict[str, ModuleType]:
    """Import the rig_components modules dynamically (and recursively).
    Users can even symlink a subfolder in there with external component types.
    """
    module_info = bpy.path.module_names(dir_path, recursive=True)
    component_modules = {}
    for module_name, module_filepath in module_info:
        if module_name.startswith("_") or module_filepath.endswith("__init__"):
            continue
        if relative:
            delta = module_filepath.replace(dir_path, "").replace(os.sep, ".").replace(".py", "")
            module = importlib.import_module(delta, __package__)
            importlib.reload(module)
        else:
            for file in os.listdir(dir_path):
                if file.endswith(".py"):
                    module = import_from_path(
                        "CloudRig.rig_components." + file.replace(".py", ""), os.sep.join([dir_path, file])
                    )
        if not hasattr(module, 'RIG_COMPONENT_CLASS'):
            continue
        component_modules[module_name] = module

    return component_modules


def import_from_path(module_name: str, file_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def reload_rig_components():
    """This only loads the Python modules, does not actually register them in Blender RNA."""
    global ALL_COMPONENT_MODULES
    ALL_COMPONENT_MODULES = load_components(os.path.dirname(__file__))


def register():
    reload_rig_components()
