from .pie_bone_parenting import GenericBoneOperator
from bpy.types import Menu, EditBone, Object
from ..generation.cloudrig import register_hotkey, CloudRigOperator
from ..utils.misc import get_current_rigs


class POSE_OT_delete_bones(GenericBoneOperator, CloudRigOperator):
    """Delete selected bones"""

    bl_idname = "pose.delete_selected"
    bl_label = "Delete Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        eb.hide = False
        remove_drivers_of_bone(rig, eb.name)
        eb.id_data.edit_bones.remove(eb)
        return True

    def execute(self, context):
        rigs = get_current_rigs(context)
        mirror_states = {}
        for rig in rigs:
            mirror_states[rig] = rig.data.use_mirror_x
        affected = self.affect_bones(context)
        for rig in rigs:
            rig.use_mirror_x = mirror_states[rig]
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Deleted {len(affected)} bone{plural}.")
        return {'FINISHED'}


def remove_drivers_of_bone(
    rig: Object,
    bone_name: str,
):
    datablocks = []

    if rig.animation_data:
        datablocks.append(rig)
    if rig.data.animation_data:
        datablocks.append(rig.data)

    for db in datablocks:
        for fc in db.animation_data.drivers[:]:
            if f'.bones["{bone_name}"]' in fc.data_path:
                db.animation_data.drivers.remove(fc)


class CLOUDRIG_MT_PIE_bone_specials(Menu):
    bl_label = "Bone Specials"

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object
        pie = layout.menu_pie()

        # 1) < Symmetrize Rigging
        pie.operator(
            'pose.symmetrize_rigging',
            text="Symmetrize",
            icon='MOD_MIRROR',
        )

        # 2) > Delete Bones (With Symmetry)
        text_del = "Delete"
        if rig.data.use_mirror_x:
            text_del = "Delete (Symmetrized)"
        pie.operator(
            'pose.delete_selected',
            text=text_del,
            icon='X',
        )

        # 3) V Leave empty.
        pie.separator()

        # 4) ^ Edit Widget.
        pie.separator()

        # 5) <^ Toggle Armature Symmetry.
        pie.prop(
            rig.data,
            'use_mirror_x',
            toggle=True,
            icon='MOD_MIRROR',
            text="Toggle Armature X-Mirror",
        )

        # 6) ^> Also empty.
        pie.separator()

        # 7) <v Toggle Pose Symmetry.
        pie.prop(
            rig.pose,
            'use_mirror_x',
            toggle=True,
            icon='MOD_MIRROR',
            text="Toggle Pose X-Mirror",
        )

        # 8) v> Leave empty.
        pie.separator()


registry = [
    POSE_OT_delete_bones,
    CLOUDRIG_MT_PIE_bone_specials,
]


def register():
    for key_cat, space_type in {
        ('Pose', 'VIEW_3D'),
        ('Weight Paint', 'EMPTY'),
        ('Armature', 'VIEW_3D'),
    }:
        register_hotkey(
            'wm.call_menu_pie',
            hotkey_kwargs={'type': "X", 'value': "PRESS"},
            key_cat=key_cat,
            space_type=space_type,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_bone_specials'},
        )
