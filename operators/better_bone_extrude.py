import bpy
from bpy.utils import flip_name
from ..generation.naming import increment_name
from ..generation.cloudrig import register_hotkey


class ARMATURE_OT_better_bone_extrude(bpy.types.Operator):
    bl_idname = "armature.better_extrude"
    bl_description = "Extrude a bone and increment its name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Better Extrude Bone"

    hotkeys = []

    @classmethod
    def poll(cls, context):
        b = context.active_bone
        return (
            context.mode == 'EDIT_ARMATURE'
            and b
            and b.select_head != b.select_tail
            and len(context.selected_bones) == 0
        )

    def execute(self, context):
        rig = context.object
        source_bone = context.active_bone

        # Increment LAST number in the name.
        new_name = increment_name(source_bone.name, 1)

        # Extrude it!
        bpy.ops.armature.extrude_move()

        if rig.data.use_mirror_x:
            opp_bone = rig.data.edit_bones.get(flip_name(context.active_bone.name))
            if opp_bone:
                opp_bone.name = flip_name(new_name)

        # Fix the name!
        new_bone = context.active_bone
        new_bone.name = new_name

        # This should happen on its own but it doesn't...?
        new_bone.select_tail = True

        bpy.ops.transform.translate('INVOKE_DEFAULT')

        return {'FINISHED'}


registry = [ARMATURE_OT_better_bone_extrude]


def register():
    register_hotkey(
        ARMATURE_OT_better_bone_extrude.bl_idname,
        hotkey_kwargs={'type': 'E', 'value': 'PRESS'},
        key_cat='Armature',
    )
