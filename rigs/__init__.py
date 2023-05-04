import os, importlib
from pathlib import Path

def load_modules(dir_path: str, package: str):
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
    load_modules(os.path.dirname(__file__), __package__)
