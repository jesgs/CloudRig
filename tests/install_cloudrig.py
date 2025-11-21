import bpy, os

def install_cloudrig(context):
    repos = context.preferences.extensions.repos

    # Disable all other repos.
    for repo in repos:
        repo.enabled = False

    # Add CloudRig repo.
    dirpath = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("DIRPATH: ", dirpath)
    cloudrig_repo = repos.new(name="CloudRig", module="cloudrig", custom_directory=dirpath)
    assert bpy.ops.preferences.addon_enable(module="bl_ext.cloudrig.CloudRig") == {'FINISHED'}, "Failed to install CloudRig."
    assert hasattr(bpy.types.Object, 'cloudrig')
    print("CloudRig installed!")
