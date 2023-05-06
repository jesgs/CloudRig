import os, importlib
from typing import Dict
from pathlib import Path

rig_modules = {}

def load_component_modules(dir_path: str, package: str) -> Dict:
    """This function is not only important to populate the global variable rig_modules defined above.

    It also manualy imports the rig modules, which is necessary because 
    >>>Blender only recognizes modules that are imported BY NAME.<<<

    For example, if we were to simply put `from . import *` in this file, and then
    tried accessing the `CloudRig.rig_components.cloud_aim` module from Blender's PyConsole, 
    it WILL NOT WORK.

    If we were to put `from . import cloud_aim`, then it WILL WORK in the PyConsole.
    But we don't want to do that, because I want to be able to add rig implementation
    files without having to modify any surrounding code.
    """
    files = os.listdir(dir_path)

    components = {}

    for f in files:
        path = Path(os.path.join(dir_path, f))
        is_dir = os.path.isdir(path.as_posix())

        if f[0] in {'.', '_'}:
            continue
        
        if is_dir:
            sub_components = load_component_modules(path.as_posix(), package=package+"."+f)
            components.update(sub_components)
        elif f.endswith(".py"):
            filename = f[:-3]
            rig_module = importlib.import_module("."+filename, package=package)
            if hasattr(rig_module, 'RigComponent'):
                components[filename] = rig_module

    return components

def register():
    global rig_modules
    rig_modules = load_component_modules(os.path.dirname(__file__), __package__)
