# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty
from bpy.types import Bone, EditBone, Object, Operator, PoseBone

from ..bs_utils.hotkeys import register_hotkey
from ..generation.cloudrig import find_cloudrig, find_metarig_of_rig
from ..generation.naming import slice_name
from ..utils.rig import bone_is_visible

# An operator to toggle between the Metarig and the Target Rig.
# The Target Rig does not store a reference to the metarig, so just bruteforce search it.

# This operator should only hide/unhide the objects with the eye icon.
# If the objects are not visible when the eye icon is disabled, the operator should fail gracefully.

# Also in the case of either switch, match the armature collection visibilities.

PREFIX_PRIORITY = ['FK', 'IK', 'DEF', 'STR', 'ORG']


class CLOUDRIG_OT_MetarigToggle(Operator):
    """Toggle visibility and selection between the Metarig and the Target Rig."""

    bl_idname = "object.cloudrig_metarig_toggle"
    bl_label = iface_("Toggle Meta/Generated Rig")
    bl_options = {'REGISTER', 'UNDO'}

    match_collections: BoolProperty(
        name="Match Collections",
        default=True,
        description="Keep the same collections visible between armatures when switching between them",
    )
    match_selection: BoolProperty(
        name="Match Selection",
        default=True,
        description="Try to match bone selection when switching between armatures. Also works with non-exact matches",
    )

    @classmethod
    def poll(cls, context):
        if not context.active_object:
            cls.poll_message_set("No active object.")
            return False
        return True

    def execute(self, context):
        if context.active_object:
            ret = metarig_context_switch(context, self.match_collections, self.match_selection)
        else:
            ret = "No active object."
        if ret:
            self.report({'ERROR'}, ret)
            return {'CANCELLED'}
        return {'FINISHED'}


def metarig_context_switch(context, match_collections=True, match_selection=True) -> str:
    """Switches the context between the metarig and the generated rig.
    May return an error message in case of failure."""
    rig = find_cloudrig(context)
    active = context.active_object
    assert active

    if 'metarig' in active and active['metarig']:
        __focus_rig(context, active['metarig'])
        active.hide_set(True)
        return ""

    if rig and rig != active:
        # If the active object is a mesh deformed by the Target Rig,
        # focus the Target Rig.
        __focus_rig(context, rig)
        return ""
    elif active:
        if active.parent and active.parent.type == 'ARMATURE':
            # If active object is parented to an armature, focus that.
            # (Even non-CloudRig armatures.)
            __focus_rig(context, active.parent)
        for m in active.modifiers:
            if m.type == 'ARMATURE' and m.object:
                # If active object is deformed by an armature, focus that.
                # (Even non-CloudRig armatures.)
                __focus_rig(context, m.object)
                return ""

    if not rig:
        return "No armature found to switch to."

    metarig = None
    if rig and rig.cloudrig.generator.target_rig:
        # If the active object is a Metarig, switch to the Target Rig.
        metarig = rig
        rig = metarig.cloudrig.generator.target_rig
        return __switch_rig_focus(context, metarig, rig, match_collections, match_selection)

    # Otherwise, try to find a metarig that references this rig
    metarig = find_metarig_of_rig(context, rig)
    if not metarig:
        return "No metarig found for this rig."

    # Switch from the rig to the metarig
    return __switch_rig_focus(context, rig, metarig, match_collections, match_selection)


def __focus_rig(context, rig, mode='POSE'):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    rig.hide_set(False)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode=mode)


def __switch_rig_focus(
    context,
    ###
    from_rig: Object,
    to_rig: Object,
    ###
    match_collections=True,
    match_selection=True,
) -> str:
    """Lower-level function, once from_rig and to_rig have been figured out.
    May return an error message in case of failure."""
    org_mode = from_rig.mode

    to_rig.hide_set(False)
    if not to_rig.visible_get():
        return rpt_('Could not make "{rig}" visible. It must be enabled, and in an enabled collection.').format(
            rig=to_rig.name
        )

    if context.mode == 'EDIT':
        selected_bone_names = [eb.name for eb in from_rig.data.edit_bones if eb.select]
    else:
        selected_bone_names = [pb.name for pb in from_rig.pose.bones if pb.select]
    bpy.ops.object.mode_set(mode='OBJECT')
    from_rig.hide_set(True)

    context.view_layer.objects.active = to_rig
    to_rig.select_set(True)
    bpy.ops.object.mode_set(mode=org_mode)

    if match_collections:
        from_colls = from_rig.data.collections
        to_colls_all = to_rig.data.collections_all
        to_rig.cloudrig_prefs.collection_ui_type = from_rig.cloudrig_prefs.collection_ui_type
        if from_colls.active:
            to_rig.cloudrig_prefs.active_collection_index = to_colls_all.find(from_colls.active.name)
        for to_coll in to_colls_all:
            from_coll = from_rig.data.collections_all.get(to_coll.name)
            if from_coll:
                to_coll.is_visible = from_coll.is_visible
                to_coll.is_solo = from_coll.is_solo
        from_active = from_colls.active
        if from_active:
            to_active = to_colls_all.get(from_active.name)
            if to_active:
                to_rig.data.collections.active = to_active

    # When switching between the Metarig and the Target Rig,
    # match the bone selection as much as possible, unless a lot of bones are selected.
    if match_selection and org_mode in ['EDIT', 'POSE'] and len(selected_bone_names) < 10:
        __match_bone_selection(from_rig, to_rig, selected_bone_names)
    return ""


def __match_bone_selection(from_rig: Object, to_rig: Object, selected_bone_names: list[str] = []):
    __deselect_all_bones(to_rig)
    __match_active_bone(from_rig, to_rig)

    # Match selected bones, without affecting bone visibilities, and using a prefix priority system.
    # This means that for each selected bone in the source armature,
    # only one or zero bones are selected in the target armature.
    # Zero if no visible matches are found.

    # If an exact match is found, use that. This is rare, since most bones get prefixes during
    # generation (FK-, DEF-, etc).

    # If multiple matches are found, one is chosen based on its prefix
    # (higher priority prefix wins).
    for bone_name in selected_bone_names:
        bone = __get_visible_bone_with_similar_name(to_rig, bone_name)
        if not bone:
            continue
        if to_rig.mode == 'EDIT_ARMATURE':
            ebone = to_rig.data.edit_bones[bone.name]
            ebone.select = True
        else:
            pbone = to_rig.pose.bones[bone.name]
            pbone.select = True


def __deselect_all_bones(rig: Object):
    if rig.mode == 'EDIT_ARMATURE':
        for eb in rig.data.edit_bones:
            eb.select = False
    else:
        for pb in rig.pose.bones:
            pb.select = False


def __match_active_bone(from_rig: Object, to_rig: Object):
    """Set the active bone to be the closest visible name match."""
    active = from_rig.data.bones.active
    if active:
        to_active = __get_visible_bone_with_similar_name(to_rig, active.name)
        if to_active:
            to_rig.data.bones.active = to_active


def __get_visible_bone_with_similar_name(rig: Object, bone_name: str) -> PoseBone | EditBone | Bone | None:
    armature = rig.data

    def names_match(a, b):
        return (a in b) or (b in a)

    if bone_name in armature.bones and bone_is_visible(armature.bones[bone_name]):
        # If we have an exact match and it's visible, return it.
        # (Just for optimization)
        return armature.bones[bone_name]

    matches = [b.name for b in armature.bones if bone_is_visible(b) and names_match(b.name, bone_name)]
    if len(matches) == 1:
        # If there is only one match and it's visible, return it.
        return armature.bones[matches[0]]
    else:
        for prefix in PREFIX_PRIORITY:
            for match in matches:
                prefixes = slice_name(match)[0]
                if prefix in prefixes:
                    return armature.bones[match]


registry = [CLOUDRIG_OT_MetarigToggle]


def register():
    register_hotkey(
        CLOUDRIG_OT_MetarigToggle.bl_idname,
        hotkey_kwargs={'type': "T", 'value': "PRESS", 'shift': True},
        keymap_name="3D View",
    )
