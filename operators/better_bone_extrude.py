import bpy
from ..generation.naming import uniqify
from ..generation.cloudrig import register_hotkey, CloudRigOperator


class BoneDuplicateOpMixin:
    def bone_operation(self):
        raise NotImplemented

    def execute(self, context):
        rig = context.active_object

        original_bones = set(rig.data.edit_bones[:])
        self.bone_operation()
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


class ARMATURE_OT_better_bone_extrude(BoneDuplicateOpMixin, CloudRigOperator):
    bl_idname = "armature.better_extrude"
    bl_description = "Extrude a bone and increment its name"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Extrude Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            return False
        return [b for b in context.object.data.edit_bones if b.select_tail]

    def bone_operation(self):
        # Extrude it!
        bpy.ops.armature.extrude_move()


class ARMATURE_OT_better_bone_duplicate(BoneDuplicateOpMixin, CloudRigOperator):
    bl_idname = "armature.better_duplicate"
    bl_description = "Duplicate a bone and increment its name"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Duplicate Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            return False
        return [b for b in context.object.data.edit_bones if b.select]

    def bone_operation(self):
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
