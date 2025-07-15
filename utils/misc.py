# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, os, time, addon_utils
from bpy.types import Text, Object, PropertyGroup, bpy_prop_collection
from bpy.utils import flip_name
from .. import __package__ as base_package


def get_opposite_obj(obj: Object) -> Object:
    """Return the X-mirrored version of a Blender object by name (and library if linked)."""
    flipped_name = flip_name(obj.name)
    lib = obj.library
    return (
        bpy.data.objects.get((lib, flipped_name)) if lib else
        bpy.data.objects.get(flipped_name)
    ) or obj


def load_script(
    file_path="", file_name="cloudrig.py", datablock=None, execute=True
) -> Text:
    """Load a text file into a text datablock, enable register checkbox and execute it.
    Also run an optional search and replace on the file content.
    """

    if datablock:
        # Allow writing into a passed text datablock.
        text = datablock
    else:
        # Check if a text datablock with this file name already exists.
        text = bpy.data.texts.get(file_name)
        # If not, create it.
        if not text:
            text = bpy.data.texts.new(name=file_name)
            text.use_fake_user = False

    text.clear()
    text.use_module = True

    if file_path == "":
        file_path = os.path.dirname(os.path.realpath(__file__))

    readfile = open(os.path.join(file_path, file_name), 'r')
    for line in readfile:
        text.write(line)
    readfile.close()

    # Run UI script
    if execute:
        exec(text.as_string(), {})

    return text


class Timer:
    def __init__(self):
        self.start_time = self.last_time = time.time()

    def tick(self, string):
        t = time.time()
        print(string + "%.3f" % (t - self.last_time))
        self.last_time = t

    def total(self, string="Total: "):
        t = time.time()
        print(string + "%.3f" % (t - self.start_time))


def assign_to_collection(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def check_addon(context, addon_name: str) -> bool:
    """Same as addon_utils.check() but account for workspace-specific disabling.
    Return whether an addon is enabled in this context.
    """
    addon_enabled_in_userprefs = addon_utils.check(addon_name)[1]
    if addon_enabled_in_userprefs and context.workspace.use_filter_by_owner:
        # Not sure why it's called owner_ids, but it contains a list of enabled addons in this workspace.
        addon_enabled_in_workspace = addon_name in context.workspace.owner_ids
        return addon_enabled_in_workspace

    return addon_enabled_in_userprefs
