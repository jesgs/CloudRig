import bpy
from bpy.types import Object, FCurve
from bpy.props import BoolProperty

from ..generation.naming import uniqify
from ..generation.cloudrig import register_hotkey, CloudRigOperator
from ..utils.misc import get_current_rigs

class BoneDuplicateOpMixin:

    increment_names: BoolProperty(name="Increment Names", description="Whether to increment numbers in bone names. If False, use Blender's .001 naming instead", default=True)

    def bone_operation(self):
        raise NotImplemented

    def execute(self, context):
        original_bones = {}
        rigs = list(get_current_rigs(context))
        for rig in rigs:
            original_bones[rig] = set(rig.data.edit_bones[:])

        self.bone_operation()
        bpy.ops.transform.translate(False, value=(0, 0, 0.1))

        new_drivers = []

        for rig in rigs:
            new_bones = set(rig.data.edit_bones[:]) - original_bones[rig]
            for new_bone in sorted(new_bones, key=lambda b: b.name):
                new_name = new_bone.name
                if self.increment_names:
                    new_name = uniqify(
                        new_bone.name, rig.data.edit_bones, strip_first=True
                    )
                if new_bone.name.endswith(".001"):
                    # Driver duplication is only unambiguous when this is the first duplicate of a bone.
                    # Otherwise we can't tell which bone is the original that got duplicated.
                    old_bone = rig.data.edit_bones[new_bone.name[:-4]]
                    new_drivers.extend(copy_drivers_of_bone(rig, old_bone.name, new_name))
                # Fix the name!
                new_bone.name = new_name

                # This should happen on its own but it doesn't...?
                new_bone.select_tail = True

        # Refresh the copied drivers
        bpy.ops.object.mode_set(False, mode='POSE')
        bpy.ops.object.mode_set(False, mode='EDIT')
        for fc in new_drivers:
            fc.driver.expression = fc.driver.expression

        bpy.ops.transform.translate(False, value=(0, 0, -0.1))
        bpy.ops.transform.translate('INVOKE_DEFAULT', False)

        return {'FINISHED'}

def copy_drivers_of_bone(rig: Object, old_bone_name:str, new_bone_name: str) -> list[FCurve]:
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


class ARMATURE_OT_better_bone_extrude(BoneDuplicateOpMixin, CloudRigOperator):
    bl_idname = "armature.better_extrude"
    bl_description = "Extrude a bone and increment its name"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Extrude Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return [b for b in context.object.data.edit_bones if b.select_tail or b.select_head]

    def bone_operation(self):
        # Extrude it!
        bpy.ops.armature.extrude_move(False)


class ARMATURE_OT_better_bone_duplicate(BoneDuplicateOpMixin, CloudRigOperator):
    bl_idname = "armature.better_duplicate"
    bl_description = "Duplicate a bone and increment its name"
    # Undo flag is omitted, because an Undo step is created by duplicate_move() anyways.
    bl_options = {'REGISTER'}
    bl_label = "Better Duplicate Bone"

    @classmethod
    def poll(cls, context):
        if not context.mode == 'EDIT_ARMATURE':
            cls.poll_message_set("Active Armature must be in edit mode.")
            return False
        return [b for b in context.object.data.edit_bones if b.select]

    def bone_operation(self):
        # Duplicate it!
        bpy.ops.armature.duplicate_move(False)


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
