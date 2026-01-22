# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty
from bpy.types import FCurve, Object, Operator

from ..bs_utils.hotkeys import register_hotkey
from ..generation.naming import uniqify
from ..utils.rig import get_current_rigs


class BoneDuplicateOpMixin:
    increment_names: BoolProperty(
        name="Increment Names",
        description="Whether to increment numbers in bone names. If False, use Blender's .001 naming instead",
        default=True,
        options={'SKIP_SAVE'},
    )

    def bone_operation(self):
        raise NotImplementedError

    def invoke(self, context, event):
        self.original_ebones = {}
        self.original_active = {}

        rigs = list(get_current_rigs(context))
        for rig in rigs:
            self.original_ebones[rig] = set(rig.data.edit_bones[:])
            self.original_active[rig] = rig.data.edit_bones.active

        self.bone_operation()
        if hasattr(self, 'is_executing'):
            bpy.ops.transform.translate()
            return {'FINISHED'}
        else:
            bpy.ops.transform.translate('INVOKE_DEFAULT', False)

        self.translate_done = False

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        self.increment_name = not event.shift

        if event.type in {'LEFTMOUSE', 'NUMPAD_ENTER', 'RET', 'RIGHTMOUSE', 'ESC'}:
            if not self.translate_done:
                self.translate_done = True
                return {'PASS_THROUGH'}
            elif self.increment_name:
                return self.execute(context)
            else:
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        new_drivers = []
        if not hasattr(self, 'original_ebones'):
            # This code path lets this operator run when called via Python.
            # Useful for testing.
            self.is_executing = True
            self.invoke(context, None)

        rigs = list(get_current_rigs(context))
        new_bones_names = []
        for rig in rigs:
            new_ebones = set(rig.data.edit_bones[:]) - self.original_ebones[rig]
            original_active = self.original_active[rig]
            for new_ebone in sorted(new_ebones, key=lambda b: b.name):
                new_name = new_ebone.name
                if self.increment_names:
                    new_name = uniqify(new_ebone, strip_first=True)
                if new_ebone.name.endswith(".001"):
                    # Driver duplication is only unambiguous when this is the first duplicate of a bone.
                    # Otherwise we can't tell which bone is the original that got duplicated.
                    old_ebone = rig.data.edit_bones[new_ebone.name[:-4]]
                    if old_ebone == original_active:
                        rig.data.edit_bones.active = new_ebone
                    new_drivers.extend(
                        copy_drivers_of_bone(rig, old_ebone.name, new_name)
                    )
                # Fix the name!
                new_ebone.name = new_name
                new_bones_names.append(new_ebone.name)

        # Refresh PoseBones &  copied drivers
        try:
            bpy.ops.object.mode_set(False, mode='POSE')
            bpy.ops.object.mode_set(False, mode='EDIT')
            for rig in rigs:
                rig.cloudrig.refresh_generation_order()
            for fc in new_drivers:
                fc.driver.expression = fc.driver.expression
        except RuntimeError:
            # This can happen when user keeps the mouse button held while pressing E again.
            # Easiest to get by trying to spam-extrude.
            # I'm just gonna ignore it, this is a silly edge case, and it's only the driver copying that fails.
            return {'FINISHED'}

        new_ebones = [rig.data.edit_bones[bone_name] for bone_name in new_bones_names]
        self.post_execute(new_ebones)

        return {'FINISHED'}

    def post_execute(self, new_ebones):
        pass

def copy_drivers_of_bone(
        rig: Object,
        old_bone_name: str,
        new_ebone_name: str
    ) -> list[FCurve]:
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
                new_fc.data_path = new_fc.data_path.replace(
                    old_bone_name, new_ebone_name
                )
                new_fc.driver.expression = new_fc.driver.expression
                new_drivers.append(new_fc)

    return new_drivers


class ARMATURE_OT_better_bone_extrude(BoneDuplicateOpMixin, Operator):
    bl_idname = "armature.better_bone_extrude"
    bl_description = "Extrude a bone and increment its name. Hold Shift when confirming the extrusion to leave the name as it is"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Extrude Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return [
            ebone
            for ebone in context.active_object.data.edit_bones
            if ebone.select_tail or ebone.select_head
        ]

    def bone_operation(self):
        # Extrude it!
        bpy.ops.armature.extrude_move()

    def post_execute(self, new_ebones):
        for new_eb in new_ebones:
            new_eb.select_head = False
            new_eb.select = False
            if new_eb.parent and new_eb.use_connect:
                new_eb.parent.select_tail = False


class ARMATURE_OT_better_bone_duplicate(BoneDuplicateOpMixin, Operator):
    bl_idname = "armature.better_bone_duplicate"
    bl_description = "Duplicate a bone and increment its name. Hold Shift to leave the name as it is"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Duplicate Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return [ebone for ebone in context.active_object.data.edit_bones if ebone.select]

    def bone_operation(self):
        # Duplicate it!
        bpy.ops.armature.duplicate_move()

    def post_execute(self, new_ebones):
        pass

registry = [ARMATURE_OT_better_bone_extrude, ARMATURE_OT_better_bone_duplicate]


def register():
    register_hotkey(
        ARMATURE_OT_better_bone_extrude.bl_idname,
        hotkey_kwargs={
            'type': 'E',
            'value': 'PRESS'
        },
        keymap_name='Armature',
    )

    register_hotkey(
        ARMATURE_OT_better_bone_duplicate.bl_idname,
        hotkey_kwargs={
            'type': 'D',
            'value': 'PRESS',
            'shift': True
        },
        keymap_name='Armature',
    )
