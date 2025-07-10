# SPDX-License-Identifier: GPL-3.0-or-later

# Not a fan of a file called utils/misc.py but man, these functions
# really don't fit anywhere.

import bpy, os, time, addon_utils
from bpy.types import PoseBone, Text, Object, EditBone, Bone, PropertyGroup, bpy_prop_collection
from .. import __package__ as base_package
from bpy.utils import flip_name


def copy_property_group(src_pg: PropertyGroup, dst_pg: PropertyGroup, x_mirror=False):
    """
    Copy the values from one PropertyGroup into another of the same type.
    Optionally, X-mirror names (e.g., ".L" <-> ".R") in strings and Object references.
    """
    assert isinstance(dst_pg, PropertyGroup) and isinstance(src_pg, PropertyGroup)
    assert dst_pg.__class__ == src_pg.__class__

    for key in src_pg.bl_rna.properties.keys():
        if key in ('rna_type', 'bl_rna'):
            continue
        if not src_pg.is_property_set(key):
            dst_pg.property_unset(key)
            continue
        value = getattr(src_pg, key)
        if isinstance(value, bpy_prop_collection):
            dst_coll = getattr(dst_pg, key)
            dst_coll.clear()
            for src_entry in value:
                if isinstance(src_entry, PropertyGroup):
                    dst_entry = dst_coll.add()
                    copy_property_group(src_entry, dst_entry, x_mirror)
        elif isinstance(value, PropertyGroup):
            copy_property_group(value, getattr(dst_pg, key), x_mirror)
        elif src_pg.is_property_readonly(key):
            # This has to come after CollectionProperty and PropertyGroup checks, 
            # since they are technically read-only.
            continue
        elif isinstance(value, str):
            setattr(dst_pg, key, flip_name(value) if x_mirror else value)
        elif isinstance(value, Object):
            setattr(dst_pg, key, get_opposite_obj(value) if x_mirror else value)
        else:
            setattr(dst_pg, key, value)


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


def get_pbone_of_active(context) -> PoseBone | None:
    """Return the PoseBone of the active bone. Can be None. Useful for drawing
    data stored on the PoseBone, in Edit Mode.
    """
    bone = context.active_pose_bone or context.active_bone
    if not bone:
        return
    rig = context.pose_object or context.active_object
    return rig.pose.bones.get(bone.name)


def get_selected_bone_tuples(
    context, exclude_active=False
) -> list[tuple[Object, Bone | EditBone]]:
    """Return a list of Bones or EditBones depending on context."""
    bone_tuples = []
    if context.mode == 'POSE':
        bone_tuples = [(pb.id_data, pb.bone) for pb in context.selected_pose_bones]
    elif context.mode == 'EDIT_ARMATURE':
        for rig in get_current_rigs(context):
            # We can't use context.selected_editable_bones because
            # it actually includes non-selected bones when use_mirror_x==True.
            bone_tuples += [(rig, eb) for eb in rig.data.edit_bones if eb.select]

    if exclude_active:
        active_rig = context.pose_object or context.active_object
        active_bone = get_active_bone(context)
        if type(active_bone) == PoseBone:
            active_bone = active_bone.bone
        active_tup = (active_rig, active_bone)
        if active_tup in bone_tuples:
            bone_tuples.remove(active_tup)

    return bone_tuples


def get_current_rigs(context):
    objs = set(context.selected_objects)
    objs.add(context.active_object)

    for obj in objs:
        if context.mode in {'POSE', 'EDIT_ARMATURE'} and obj.type == 'ARMATURE':
            yield obj


def get_parentless_pbones(rig: Object) -> list[PoseBone]:
    return [pb for pb in rig.pose.bones if not pb.bone.parent]


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
    from .. import __package__ as base_package
    if base_package.startswith('bl_ext'):
        # 4.2
        return context.preferences.addons[base_package].preferences
    else:
        return context.preferences.addons[base_package.split(".")[0]].preferences
