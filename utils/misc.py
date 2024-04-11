# Not a fan of a file called utils/misc.py but man, these functions
# really don't fit anywhere.

import addon_utils
import bpy, os
from typing import Tuple, Optional
from bpy.types import PoseBone
import time

# Written by __init__.py at register time. (No other way to access bl_info)
version_min: Tuple = ()
version_max: Tuple = ()


def is_blender_version_compatible() -> bool:
    """Return whether current Blender version is compatible
    with current CloudRig version."""

    tuple_to_version = lambda v: v[0] * 1000 + v[1] * 100 + v[2]

    ver_blender = tuple_to_version(bpy.app.version)

    ver_min = tuple_to_version(version_min)
    ver_max = tuple_to_version(version_max)

    return ver_max >= ver_blender >= ver_min


def load_script(
    file_path="", file_name="cloudrig.py", datablock=None, execute=True
) -> bpy.types.Text:
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


def get_pbone_of_active(context) -> Optional[PoseBone]:
    """Return the PoseBone of the active bone. Can be None. Useful for drawing
    data stored on the PoseBone, in Edit Mode.
    """
    if not context.active_bone:
        return
    return context.object.pose.bones.get(context.active_bone.name)


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


def get_addon_prefs(context=None):
    if not context:
        context = bpy.context
    return context.preferences.addons[__package__.split(".")[0]].preferences


def copy_attributes(from_thing, to_thing, skip=[""], recursive=False):
    """Copy attributes from one thing to another.
    from_thing: Object to copy values from. (Only if the attribute already exists in to_thing)
    to_thing: Object to copy attributes into (No new attributes are created, only existing are changed).
    skip: List of attribute names in from_thing that should not be attempted to be copied.
    recursive: Copy iterable attributes recursively.
    """

    # print("\nCOPYING FROM: " + str(from_thing))
    # print(".... TO: " + str(to_thing))

    bad_stuff = skip + ['active', 'bl_rna', 'error_location', 'error_rotation']
    for prop in dir(from_thing):
        if "__" in prop:
            continue
        if prop in bad_stuff:
            continue

        if hasattr(to_thing, prop):
            from_value = getattr(from_thing, prop)
            # Iterables should be copied recursively, except str.
            if recursive and type(from_value) != str:
                # NOTE: I think This will infinite loop if a CollectionProperty contains a reference to itself!
                warn = False
                try:
                    # Determine if the property is iterable. Otherwise this throws TypeError.
                    iter(from_value)

                    to_value = getattr(to_thing, prop)
                    # The thing we are copying to must therefore be an iterable as well. If this fails though, we should throw a warning.
                    warn = True
                    iter(to_value)
                    count = min(len(to_value), len(from_value))
                    for i in range(0, count):
                        copy_attributes(from_value[i], to_value[i], skip, recursive)
                except TypeError:  # Not iterable.
                    if warn:
                        print(
                            "WARNING: Could not copy attributes from iterable to non-iterable field: "
                            + prop
                            + "\nFrom object: "
                            + str(from_thing)
                            + "\nTo object: "
                            + str(to_thing)
                        )

            # Copy the attribute.
            try:
                setattr(to_thing, prop, from_value)
                # print(prop + ": " + str(from_value))
            except (
                AttributeError
            ):  # Read-Only properties throw AttributeError. We ignore silently, which is not great.
                continue


def find_or_create_constraint(pb, con_type, name=None):
    """Create a constraint on a bone if it doesn't exist yet.
    If a constraint with the given type already exists, just return that.
    If a name was passed, also make sure the name matches before deeming it a match and returning it.
    pb: Must be a pose bone.
    """
    for con in pb.constraints:
        if con.type == con_type:
            if name:
                if con.name == name:
                    return con
            else:
                return con
    con = pb.constraints.new(type=con_type)
    if name:
        con.name = name
    return con
