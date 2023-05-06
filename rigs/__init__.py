import os, importlib
from pathlib import Path

rig_modules = {}

def load_modules(dir_path: str, package: str):
    """This function is not only important to populate the global variable rig_modules defined above.

    It also manualy imports the rig modules, which is necessary because 
    >>>Blender only recognizes modules that are imported BY NAME.<<<

    For example, if we were to simply put `from . import *` in this file, and then
    tried accessing the `CloudRig.rigs.cloud_aim` module from Blender's PyConsole, 
    it WILL NOT WORK.

    If we were to put `from . import cloud_aim`, then it WILL WORK in the PyConsole.
    But we don't want to do that, because I want to be able to add rig implementation
    files without having to modify any surrounding code.
    """
    files = os.listdir(dir_path)

    rigs = {}

    for f in files:
        path = Path(os.path.join(dir_path, f))
        is_dir = os.path.isdir(path.as_posix())

        if f[0] in {'.', '_'}:
            continue
        
        if is_dir:
            sub_rigs = load_modules(path.as_posix(), package=package+"."+f)
            rigs.update(sub_rigs)
        elif f.endswith(".py"):
            filename = f[:-3]
            rig_module = importlib.import_module("."+filename, package=package)
            if hasattr(rig_module, "Rig"):
                rigs[filename] = rig_module

    return rigs

def register():
    global rig_modules
    rig_modules = load_modules(os.path.dirname(__file__), __package__)
