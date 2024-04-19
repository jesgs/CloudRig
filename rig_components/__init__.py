import os, importlib
from typing import Dict
import bpy

component_modules = {}


def load_component_modules(dir_path: str) -> Dict:
    """Manualy imports the rig modules, since they don't get automatically
    loaded because they aren't referenced by the code directly.
    """
    module_info = bpy.path.module_names(dir_path)
    component_modules = {}
    for module_name, module_filepath in module_info:
        # This terrbileness is needed because import_module() does not work
        # with absolute paths containing a period (which Blender scripts
        # always do because of the version number folder).
        delta = (
            module_filepath.replace(dir_path, "")
            .replace(os.sep, ".")
            .replace(".py", "")
        )
        if module_name.startswith("_") or module_filepath.endswith("__init__"):
            continue
        module = importlib.import_module(delta, __package__)
        importlib.reload(module)
        if not hasattr(module, 'RIG_COMPONENT_CLASS'):
            continue
        component_modules[module_name] = module

    return component_modules


def register():
    global component_modules
    component_modules = load_component_modules(os.path.dirname(__file__))
