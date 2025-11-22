import bpy
from pathlib import Path

def install_this(context):
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

    # Add CloudRig repo.
    filepath = Path(__file__)
    dirpath = filepath.parent.parent
    addon_name = dirpath.name
    module_name = addon_name.lower()
    addon_repo = repos.new(name=addon_name, module=module_name, custom_directory=dirpath.as_posix())
    assert bpy.ops.preferences.addon_enable(module=f"bl_ext.{module_name}.{addon_name}") == {'FINISHED'}, f"Failed to install {addon_name}."
    print(f"{addon_name} installed!")
