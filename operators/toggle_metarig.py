# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Armature, Bone, Object, Operator
from bpy.props import BoolProperty

from ..generation.cloudrig import find_metarig_of_rig, find_cloudrig
from ..generation.naming import slice_name
from ..bs_utils.hotkeys import register_hotkey

# An operator to toggle between the metarig and the generated rig.
# The generated rig does not store a reference to the metarig, so just bruteforce search it.

# This operator should only hide/unhide the objects with the eye icon.
# If the objects are not visible when the eye icon is disabled, the operator should fail gracefully.

# Also in the case of either switch, match the armature collection visibilities.

PREFIX_PRIORITY = ['FK', 'IK', 'DEF', 'STR', 'ORG']


class CLOUDRIG_OT_MetarigToggle(Operator):
    """Switch the active object between the generated rig and the metarig"""

    bl_idname = "object.cloudrig_metarig_toggle"
    bl_label = "Toggle Meta/Generated Rig"
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
        rig = find_cloudrig(context)
        active = context.active_object

        if 'metarig' in active and active['metarig']:
            self.focus_rig(context, active['metarig'])
            return {'FINISHED'}

        if rig and rig != active:
            # If the active object is a mesh deformed by the generated rig,
            # focus the generated rig.
            self.focus_rig(context, rig)
            return {'FINISHED'}
        elif active:
            if active.parent and active.parent.type == 'ARMATURE':
                # If active object is parented to an armature, focus that.
                # (Even non-CloudRig armatures.)
                self.focus_rig(context, active.parent)
            for m in active.modifiers:
                if m.type == 'ARMATURE' and m.object:
                    # If active object is deformed by an armature, focus that.
                    # (Even non-CloudRig armatures.)
                    self.focus_rig(context, m.object)
                    return {'FINISHED'}

        if not rig:
            self.report({'ERROR'}, "No armature found to switch to.")
            return {'CANCELLED'}

        metarig = None
        if rig and rig.cloudrig.generator.target_rig:
            # If the active object is a metarig, switch to the generated rig.
            metarig = rig
            rig = metarig.cloudrig.generator.target_rig
            self.switch_rig_focus(
                context, metarig, rig, self.match_collections, self.match_selection
            )
            return {'FINISHED'}

        # Otherwise, try to find a metarig that references this rig
        metarig = find_metarig_of_rig(context, rig)
        if not metarig:
            self.report({'ERROR'}, "No metarig found for this rig.")
            return {'CANCELLED'}

        # Switch from the rig to the metarig
        self.switch_rig_focus(
            context, rig, metarig, self.match_collections, self.match_selection
        )
        return {'FINISHED'}

    def focus_rig(self, context, rig, mode='POSE'):
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        rig.hide_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode=mode)

    def switch_rig_focus(
        self,
        context,
        ###
        from_rig: Object,
        to_rig: Object,
        ###
        match_collections=True,
        match_selection=True,
    ):
        org_mode = from_rig.mode

        to_rig.hide_set(False)
        if not to_rig.visible_get():
            self.report(
                {'ERROR'},
                f'Could not make "{to_rig.name}" visible. It must be enabled, and in an enabled collection.',
            )
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        from_rig.hide_set(True)

        context.view_layer.objects.active = to_rig
        to_rig.select_set(True)
        bpy.ops.object.mode_set(mode=org_mode)

        if match_collections:
            for to_coll in to_rig.data.collections_all:
                from_coll = from_rig.data.collections_all.get(to_coll.name)
                if from_coll:
                    to_coll.is_visible = from_coll.is_visible
                    to_coll.is_solo = from_coll.is_solo
            from_active = from_rig.data.collections.active
            if from_active:
                to_active = to_rig.data.collections_all.get(from_active.name)
                if to_active:
                    to_rig.data.collections.active = to_active

        # When switching between the metarig and the generated rig,
        # match the bone selection as much as possible, unless a lot of bones are selected.
        selected = [b for b in from_rig.data.bones if b.select]
        if match_selection and org_mode in ['EDIT', 'POSE'] and len(selected) < 10:
            self.match_bone_selection(from_rig, to_rig)

    def match_bone_selection(self, from_rig: Object, to_rig: Object):
        self.deselect_all_bones(to_rig)
        self.match_active_bone(from_rig, to_rig)

        # Match selected bones, without affecting bone visibilities, and using a prefix priority system.
        # This means that for each selected bone in the source armature,
        # only one or zero bones are selected in the target armature.
        # Zero if no visible matches are found.

        # If an exact match is found, use that. This is rare, since most bones get prefixes during generation (FK-, DEF-, etc).

        # If multiple matches are found, one is chosen based on its prefix
        # (higher priority prefix wins).
        selected_names = [b.name for b in from_rig.data.bones if b.select]
        for bone_name in selected_names:
            bone = self.get_visible_bone_with_similar_name(to_rig.data, bone_name)
            if bone:
                bone.select = True

    def deselect_all_bones(self, armature: Object):
        for b in armature.data.bones:
            b.select = False

    def match_active_bone(self, from_rig: Object, to_rig: Object):
        """If there is an exact match for the active bone, make the matching bone active."""
        active = from_rig.data.bones.active
        if active:
            to_active = to_rig.data.bones.get(active.name)
            if to_active:
                to_rig.data.bones.active = to_active

    def get_visible_bone_with_similar_name(
        self, armature: Armature, bone_name: str
    ) -> Bone | None:

        def bone_is_visible(bone):
            return not bone.hide and any([coll.is_visible_effectively for coll in bone.collections])

        def names_match(a, b):
            return (a in b) or (b in a)

        if bone_name in armature.bones and bone_is_visible(armature.bones[bone_name]):
            # If we have an exact match and it's visible, return it.
            # (Just for optimization)
            return armature.bones[bone_name]

        matches = [
            b.name
            for b in armature.bones
            if bone_is_visible(b) and names_match(b.name, bone_name)
        ]
        if len(matches) == 1:
            # If there is only one match and it's visible return it.
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
