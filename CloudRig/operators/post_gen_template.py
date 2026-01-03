########################################
### Import CloudRig's utility functions

import importlib
import sys

import bpy


def import_cloudrig():
    # Importing add-on code from a text datablock is tricky because the name of the
    # extension repository ends up in the module name.
    module_name = next((m for m in sys.modules if m.endswith("CloudRig")), None)
    if module_name:
        return importlib.import_module(module_name)
    raise ModuleNotFoundError("Failed to import CloudRig.")
CloudRig = import_cloudrig()
post_gen = CloudRig.utils.post_gen

# Grab a reference to the rig that was just generated.
rig = bpy.context.active_object

#########################################
### Examples (You can delete everything below!)

print(f"Post-Generation Running for {rig.name}")

# Loop over the PoseBones.
for pbone in rig.pose.bones:
    print(pbone.name)
    # Loop over every constraint
    for con in pbone.constraints:
        # Do nothing.
        pass

# Changing a bone's rest position requries entering Edit Mode.
from math import degrees

from mathutils import Vector

bpy.ops.object.mode_set(mode='EDIT')
for ebone in rig.data.edit_bones:
    ebone.head += Vector((0, 0, 0))
    ebone.tail += Vector((0, 0, 0))
    ebone.roll += degrees(0)

# You must absolutely use this function if you want to rename bones.
# This is because bone names are also present in the rig's UI data,
# as well as in driver variable data paths.
post_gen.rename_bone(rig, "from_name", "to_name")

# Same exact situation with renaming custom properties.
post_gen.rename_custom_property(rig, "bone_name", "old_prop_name", "new_prop_name")

# You can change the default value of a custom property.
post_gen.set_custom_property_default(rig, "bone_name", "prop_name", value=1.0)

# For more functions, see the source code:
# https://projects.blender.org/Mets/CloudRig/src/branch/master/CloudRig/utils/post_gen.py
