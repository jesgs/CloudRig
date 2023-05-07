import os, importlib
from typing import Dict
from pathlib import Path
import bpy

rig_modules = {}

def load_component_modules(dir_path: str, package: str) -> Dict:
    """Manualy imports the rig modules, since they don't get automatically
    loaded because they aren't referenced by the code directly.
    """

    files = os.listdir(dir_path)
    module_info = bpy.path.module_names(dir_path)

    components = {}

    for module_name, module_filepath in module_info:
        folder_path = os.path.dirname(__file__)
        # This terrbileness is needed because import_module() does not work
        # with absolute paths containing a period (which Blender scripts 
        # always do because of the version number folder).
        delta = module_filepath.replace(folder_path, "").replace("\\", ".").replace(".py", "")
        if module_name.startswith("_") or module_filepath.endswith("__init__"):
            continue
        module = importlib.import_module(delta, __package__)
        if not hasattr(module, 'RigComponent'):
            continue
        components[module_name] = module

    return components

def register():
    global rig_modules
    rig_modules = load_component_modules(os.path.dirname(__file__), __package__)
