import bpy, os, sys, importlib
from ..prefs_save_load import load_prefs_from_file

component_modules = {}


def load_components(dir_path: str, relative=True) -> dict:
    """Manualy imports the rig modules, since they don't get automatically
    loaded because they aren't referenced by the code directly.
    """
    module_info = bpy.path.module_names(dir_path)
    component_modules = {}
    for module_name, module_filepath in module_info:
        if module_name.startswith("_") or module_filepath.endswith("__init__"):
            continue
        if relative:
            delta = (
                module_filepath.replace(dir_path, "")
                .replace(os.sep, ".")
                .replace(".py", "")
            )
            module = importlib.import_module(delta, __package__)
            importlib.reload(module)
        else:
            for file in os.listdir(dir_path):
                if file.endswith(".py"):
                    module = import_from_path("CloudRig.rig_components."+file.replace(".py", ""), os.sep.join([dir_path, file]))
        if not hasattr(module, 'RIG_COMPONENT_CLASS'):
            continue
        component_modules[module_name] = module

    return component_modules


def import_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_external_components():
    """WIP: This works but the external component types don't have bone sets registered, and fixing that is a nightmare."""
    external_modules = {}
    prefs_data = load_prefs_from_file()
    feature_set_infos = prefs_data.get('feature_set_paths')
    for feature_set_info in feature_set_infos:
        name = feature_set_info['name']
        path = feature_set_info['path']
        if os.path.isdir(path) and os.path.exists(path):
            external_modules.update(load_components(path, relative=False))
    return external_modules


def reload_rig_components():
    global component_modules
    component_modules = load_components(os.path.dirname(__file__))
    component_modules.update(load_external_components())


def register():
    reload_rig_components()
