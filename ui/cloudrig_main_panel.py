from bpy.types import Panel

class POSE_PT_CloudRig(Panel):
    bl_label = "CloudRig"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

registry = [
    POSE_PT_CloudRig,
]