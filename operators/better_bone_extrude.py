import bpy
from bpy.utils import flip_name
from ..generation.naming import increment_name, uniqify
from ..generation.cloudrig import register_hotkey


class BoneDuplicateOperatorBase:
    def bone_operation(self, context):
        # Extrude it!
        bpy.ops.armature.extrude_move()

    def execute(self, context):
        rig = context.active_object

        original_bones = set(rig.data.edit_bones[:])
        self.bone_operation(context)
        new_bones = set(rig.data.edit_bones[:]) - original_bones

        for new_bone in sorted(new_bones, key=lambda b: b.name):
            # Fix the name!
            new_bone.name = uniqify(
                new_bone.name, rig.data.edit_bones, strip_first=True
            )

        # This should happen on its own but it doesn't...?
        new_bone.select_tail = True

        bpy.ops.transform.translate('INVOKE_DEFAULT')

        return {'FINISHED'}


class ARMATURE_OT_better_bone_extrude(BoneDuplicateOperatorBase, bpy.types.Operator):
    bl_idname = "armature.better_extrude"
    bl_description = "Extrude a bone and increment its name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Better Extrude Bone"

    @classmethod
    def poll(cls, context):
        selected_tails = [b for b in context.object.data.edit_bones if b.select_tail]
        return context.mode == 'EDIT_ARMATURE' and selected_tails


class ARMATURE_OT_better_bone_duplicate(BoneDuplicateOperatorBase, bpy.types.Operator):
    bl_idname = "armature.better_duplicate"
    bl_description = "Duplicate a bone and increment its name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Better Duplicate Bone"

    @classmethod
    def poll(cls, context):
        selected_bones = [b for b in context.object.data.edit_bones if b.select]
        return context.mode == 'EDIT_ARMATURE' and selected_bones

    def bone_operation(self, context):
        # Duplicate it!
        bpy.ops.armature.duplicate_move()


registry = [ARMATURE_OT_better_bone_extrude, ARMATURE_OT_better_bone_duplicate]


def register():
    register_hotkey(
        ARMATURE_OT_better_bone_extrude.bl_idname,
        hotkey_kwargs={'type': 'E', 'value': 'PRESS'},
        key_cat='Armature',
    )

    register_hotkey(
        ARMATURE_OT_better_bone_duplicate.bl_idname,
        hotkey_kwargs={'type': 'D', 'value': 'PRESS', 'shift': True},
        key_cat='Armature',
    )
