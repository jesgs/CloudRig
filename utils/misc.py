# Not a fan of a file called utils/misc.py but man, these functions
# really don't fit anywhere.

import bpy, os, time, addon_utils
from bpy.types import PoseBone, Text, Object, EditBone, Bone

# Written by __init__.py at register time. (No other way to access bl_info)
version_min: tuple = ()
version_max: tuple = ()


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


def get_pbone_of_active(context) -> PoseBone | None:
    """Return the PoseBone of the active bone. Can be None. Useful for drawing
    data stored on the PoseBone, in Edit Mode.
    """
    if not context.active_bone:
        return
    return context.object.pose.bones.get(context.active_bone.name)


def get_selected_bones(
    context, exclude_active=False
) -> list[tuple[Object, Bone | EditBone]]:
    """Return a list of Bones or EditBones depending on context."""
    bones = []
    if context.mode == 'POSE':
        bones = [(pb.id_data, pb.bone) for pb in context.selected_pose_bones]
    elif context.mode == 'EDIT_ARMATURE':
        for rig in get_current_rigs(context):
            # We can't use context.selected_editable_bones because
            # it actually includes non-selected bones when use_mirror_x==True.
            bones += [(rig, eb) for eb in rig.data.edit_bones if eb.select]

    if exclude_active:
        active_rig = context.pose_object or context.active_object
        bones.remove((active_rig, get_active_bone(context)))

    return bones


def get_current_rigs(context):
    objs = set(context.selected_objects)
    objs.add(context.active_object)

    for obj in objs:
        if context.mode in {'POSE', 'EDIT_ARMATURE'} and obj.type == 'ARMATURE':
            yield obj


def get_active_bone(context):
    """Return active PoseBone or EditBone, depending on context."""
    if context.mode == 'EDIT_ARMATURE':
        return context.active_bone
    else:
        return get_pbone_of_active(context)


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
