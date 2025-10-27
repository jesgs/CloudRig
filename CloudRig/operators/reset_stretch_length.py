import bpy

class POSE_OT_reset_stretch_length(bpy.types.Operator):
    """Set the Original Length of selected bone's Stretch To constraints to the actual original length of the bones"""

    bl_idname = "pose.reset_stretch_length"
    bl_label = "Reset Stretch Length"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.selected_pose_bones:
            return False
        if any([c.type == 'STRETCH_TO' for pb in context.selected_pose_bones for c in pb.constraints]):
            return True
        else:
            cls.poll_message_set("No selected pose bones with Stretch To constraint.")
            return False

    def execute(self, context):
        for pb in context.selected_pose_bones:
            for c in pb.constraints:
                if c.type=='STRETCH_TO':
                    c.rest_length = pb.bone.length

        self.report({'INFO'}, f"Stretch length reset.")
        return {'FINISHED'}

registry = [POSE_OT_reset_stretch_length]