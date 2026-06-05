# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import BoolProperty
from bpy.types import Context, Event, FCurve, Macro, Object, Operator

from ..bs_utils.hotkeys import register_hotkey
from ..generation.cloudrig import is_cloud_metarig
from ..generation.naming import uniqify
from ..utils.rig import get_current_rigs


class ARMATURE_OT_post_process_new_bones(Operator):
    """Rename the duplicated bones with a more sane number incrementation logic"""

    bl_idname = "armature.post_process_new_bones"
    bl_label = "Post-Process New Bones"
    bl_options = {'REGISTER', 'INTERNAL'}

    is_extrude: BoolProperty(default=False)

    def invoke(self, context: Context, event: Event):
        if event.alt:
            return {'FINISHED'}
        return self.execute(context)

    def execute(self, context: Context):
        rigs = list(get_current_rigs(context))
        driver_renames = {}

        for rig in rigs:
            driver_renames[rig] = {}
            bones_to_rename = []

            for ebone in rig.data.edit_bones:
                if not (ebone.select or ebone.select_head or ebone.select_tail):
                    continue
                # Driver duplication is only unambiguous when this is the first duplicate of a bone.
                # Otherwise we can't tell which bone is the original that got duplicated.
                if not ebone.name.endswith('.001'):
                    continue
                if ebone.name[:-4] not in rig.data.edit_bones:
                    continue
                bones_to_rename.append(ebone)
                if self.is_extrude:
                    # Weird Blender behaviour workaround:
                    # When mirror is enabled and a bone body is selected, the opposite bone is also considered selected,
                    # even if it isn't actually.
                    # But during extrude, the body is not selected, so we can't rely on that.
                    flipped = bpy.utils.flip_name(ebone.name)
                    if (
                        flipped != ebone.name
                        and flipped in rig.data.edit_bones
                        and flipped.endswith('.001')
                        and flipped[:-4] in rig.data.edit_bones
                    ):
                        bones_to_rename.append(rig.data.edit_bones[flipped])

            for ebone in bones_to_rename:
                old_name = ebone.name[:-4]
                new_name = uniqify(ebone, strip_first=True)
                if bone_has_drivers(rig, old_name):
                    driver_renames[rig][old_name] = new_name
                if self.is_extrude:
                    ebone.select_head = False
                    ebone.select = False
                    if ebone.parent and ebone.use_connect:
                        ebone.parent.select_tail = False
                ebone.name = new_name

        # Weird Blender behaviour workaround:
        # On extrude with mirror, the active bone flips for no reason. So we unflip it.
        if self.is_extrude:
            arm = context.active_object.data
            if arm.use_mirror_x and arm.edit_bones.active:
                flipped = bpy.utils.flip_name(arm.edit_bones.active.name)
                if flipped != arm.edit_bones.active.name and flipped in arm.edit_bones:
                    flipped_bone = arm.edit_bones[flipped]
                    saved_selection = flipped_bone.select, flipped_bone.select_head, flipped_bone.select_tail
                    arm.edit_bones.active = flipped_bone
                    # For some reason, setting active state affects selection state, so, to fix that...
                    flipped_bone.select, flipped_bone.select_head, flipped_bone.select_tail = saved_selection

        if not any(driver_renames.values()) or self.is_extrude:
            return {'FINISHED'}

        new_drivers = []
        bpy.ops.object.mode_set(mode='POSE')
        for rig in rigs:
            for old_name, new_name in driver_renames[rig].items():
                new_drivers.extend(copy_drivers_of_bone(rig, old_name, new_name))
        bpy.ops.object.mode_set(mode='EDIT')
        for rig in rigs:
            if is_cloud_metarig(rig):
                # Refresh for sake of overlay drawing.
                rig.cloudrig.refresh_generation_order()
        for fc in new_drivers:
            fc.driver.expression = fc.driver.expression

        return {'FINISHED'}


class ARMATURE_OT_better_bone_extrude(Macro):
    bl_idname = "armature.better_bone_extrude"
    bl_label = iface_("Better Extrude Bone")
    bl_description = "Extrude a bone and increment its name"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: Context):
        if context.mode != 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return any(
            eb.select_tail or eb.select_head
            for eb in context.active_object.data.edit_bones
        )


class ARMATURE_OT_better_bone_duplicate(Macro):
    bl_idname = "armature.better_bone_duplicate"
    bl_label = iface_("Better Duplicate Bone")
    bl_description = "Duplicate a bone and increment its name"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: Context):
        if context.mode != 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return any(eb.select for eb in context.active_object.data.edit_bones)


def bone_has_drivers(rig: Object, bone_name: str) -> bool:
    """Return True if the rig or its data has any drivers referencing the given bone name."""
    for db in (rig, rig.data):
        if db.animation_data:
            for fc in db.animation_data.drivers:
                if f'bones["{bone_name}"]' in fc.data_path:
                    return True
    return False


def copy_drivers_of_bone(
    rig: Object,
    old_bone_name: str,
    new_bone_name: str,
) -> list[FCurve]:
    """Copy all drivers referencing old_bone_name and remap them to new_bone_name."""
    datablocks = []
    if rig.animation_data:
        datablocks.append(rig)
    if rig.data.animation_data:
        datablocks.append(rig.data)

    new_drivers = []
    for db in datablocks:
        for fc in db.animation_data.drivers:
            if f'bones["{old_bone_name}"]' in fc.data_path:
                new_fc = db.animation_data.drivers.from_existing(src_driver=fc)
                new_fc.data_path = new_fc.data_path.replace(old_bone_name, new_bone_name)
                new_fc.driver.expression = new_fc.driver.expression
                new_drivers.append(new_fc)
    return new_drivers


registry = [
    ARMATURE_OT_post_process_new_bones,
    ARMATURE_OT_better_bone_extrude,
    ARMATURE_OT_better_bone_duplicate,
]


def register():
    # Macros allow us to combine these undo steps into one.
    ARMATURE_OT_better_bone_extrude.define("ARMATURE_OT_extrude").properties.forked = False
    ARMATURE_OT_better_bone_extrude.define("TRANSFORM_OT_translate")
    ARMATURE_OT_better_bone_extrude.define("ARMATURE_OT_post_process_new_bones").properties.is_extrude = True

    ARMATURE_OT_better_bone_duplicate.define("ARMATURE_OT_duplicate")
    ARMATURE_OT_better_bone_duplicate.define("TRANSFORM_OT_translate")
    ARMATURE_OT_better_bone_duplicate.define("ARMATURE_OT_post_process_new_bones")

    register_hotkey(
        ARMATURE_OT_better_bone_extrude.bl_idname,
        hotkey_kwargs={'type': 'E', 'value': 'PRESS'},
        keymap_name='Armature',
    )
    register_hotkey(
        ARMATURE_OT_better_bone_duplicate.bl_idname,
        hotkey_kwargs={'type': 'D', 'value': 'PRESS', 'shift': True},
        keymap_name='Armature',
    )
