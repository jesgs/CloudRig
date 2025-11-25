import bpy
from pathlib import Path

def install_this(context, enable=True):
    """Install this add-on by adding its parent folder as a local repository (requires Blender >=4.2)
    Expected folder hierarchy:
    Root
        Addon Source
            blender_manifest.toml
        Tests
            this_file.py
    """
    repos = context.preferences.extensions.repos

    # Disable all other repos.
    for repo in repos:
        repo.enabled = False

    # Add add-on repo.
    repo_dir, addon_name, module_name = get_filepath_info()
    _addon_repo = repos.new(name=addon_name, module=module_name, custom_directory=repo_dir)

    msg = f"{addon_name} installed"

    # Enable the add-on.
    if enable:
        assert bpy.ops.preferences.addon_enable(module=f"bl_ext.{module_name}.{addon_name}") == {'FINISHED'}, f"Failed to install {addon_name}."
        msg += " and enabled!"

    print(msg)

def disable_this():
    _repo_dir, addon_name, module_name = get_filepath_info()
    assert bpy.ops.preferences.addon_disable(module=f"bl_ext.{module_name}.{addon_name}") == {'FINISHED'}, f"Failed to unregister {addon_name}."

def get_filepath_info() -> tuple[str, str, str]:
    filepath = Path(__file__)
    dirpath = filepath.parent.parent
    addon_name = dirpath.name
    module_name = addon_name.lower()
    return dirpath.as_posix(), addon_name, module_name