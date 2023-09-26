from bpy.types import Panel, UIList, UI_UL_list
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class CLOUDRIG_PT_rig_component(Panel):
    bl_label = "CloudRig Component"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'bone'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if not context.object or context.object.type != 'ARMATURE':
            return False
        if context.object.mode not in {'POSE', 'OBJECT'}:
            return False
        if not context.active_bone and not context.active_pose_bone:
            return False
        return True

    def draw(self, context):
        layout = self.layout.column()
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = get_addon_prefs(context)
        active_bone = context.active_bone
        active_pb = context.object.pose.bones.get(active_bone.name)
        rig_component = active_pb.cloudrig_component
        layout.prop_search(rig_component, 'component_type', prefs, 'rig_type_list', icon='ARMATURE_DATA')
        layout.prop(prefs, 'advanced_mode')

registry = [
    CLOUDRIG_PT_rig_component
]
