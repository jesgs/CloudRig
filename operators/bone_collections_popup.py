# TODO: Move to cloudrig.py so animators can have access to this as well.

import bpy
from ..generation.cloudrig import register_hotkey

class CLOUDRIG_OT_bone_collections_popup(bpy.types.Operator):
    """Bone Collections pop-up"""
    bl_idname = "armature.bone_collections_popup"
    bl_label = "Bone Collections"
    bl_options = {'REGISTER'} # Undo step is omitted, since this is just a UI pop-up.

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout

        if context.pose_object:
            rig = context.pose_object
        else:
            rig = context.active_object

        layout.row().template_list(
            'CLOUDRIG_UL_collections',
            'Bone Collections Popover List',
            rig.data, 'collections_all',
            rig.cloudrig_prefs, 'active_collection_index',
            rows=15 if rig.data.collections_all else 1,
        )

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=500)

    def execute(self, context):
        return {'FINISHED'}

registry = [
    CLOUDRIG_OT_bone_collections_popup
]


def register():
    for key_cat, space_type in {
        ('Pose', 'VIEW_3D'),
        ('Weight Paint', 'EMPTY'),
        ('Armature', 'VIEW_3D'),
    }:
        register_hotkey(
            'armature.bone_collections_popup',
            hotkey_kwargs={'type': "M", 'value': "PRESS", 'shift': True},
            key_cat=key_cat,
            space_type=space_type,
        )
