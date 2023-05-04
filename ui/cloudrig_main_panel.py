from bpy.types import Panel, UIList
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class POSE_PT_CloudRig(Panel):
    bl_label = "CloudRig"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

class CLOUDRIG_UL_rig_elements(UIList):
    """CloudRigLogEntry's are displayed under Properties->Armature->Rigify Log,
    when the active object is a CloudRig Metarig.
    """
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        rig = context.object
        cloudrig = data
        rig_element = item
        addon_prefs = get_addon_prefs(context)

        row = layout.row()
        split = row.split(factor=0.4)
        icon = 'BONE_DATA'
        if rig_element.owner_bone not in rig.pose.bones:
            icon = 'ERROR'
        split.prop_search(rig_element, 'owner_bone', rig.pose, 'bones', text="", icon=icon)
        split2 = split.split(factor=0.3)
        split2.label(text="")
        split2.prop_search(rig_element, 'element_type', addon_prefs, 'rig_type_list', text="", icon='ARMATURE_DATA')

class CLOUDRIG_PT_rig_elements(Panel):
    bl_label = "Rig Elements"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_parent_id = 'POSE_PT_CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        draw_ui_list(
            layout,
            context,
            class_name = 'CLOUDRIG_UL_rig_elements',
            list_path = 'object.data.cloudrig.rig_elements',
            active_index_path = 'object.data.cloudrig.active_rig_element_index',
            insertion_operators = True,
            move_operators = True,
        )


registry = [
    POSE_PT_CloudRig,
    CLOUDRIG_UL_rig_elements,
    CLOUDRIG_PT_rig_elements
]