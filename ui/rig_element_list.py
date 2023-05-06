from bpy.types import Panel, UIList
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class CLOUDRIG_UL_rig_elements(UIList):
    """CloudRigLogEntry's are displayed under Properties->Armature->Rigify Log,
    when the active object is a CloudRig Metarig.
    """
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        rig = context.object
        cloudrig = data
        rig_element_bone_name = item.name
        addon_prefs = get_addon_prefs(context)

        pb = rig.pose.bones.get(rig_element_bone_name)


        row = layout.row()
        split = row.split(factor=0.4)
        row = split.row()
        row.enabled = False
        if not pb:
            row.prop_search(item, 'name', rig.pose, 'bones', text="", icon='ERROR')
        else:
            rig_element = pb.cloudrig_element
            row.prop_search(rig_element, 'owner_bone', rig.pose, 'bones', text="")
            split2 = split.split(factor=0.3)
            split2.alignment = 'RIGHT'
            split2.label(text="Type:")
        if not pb:
            split.label(text="Bone renamed or deleted. Click to refresh.")
        else:
            split2.prop_search(rig_element, 'element_type', addon_prefs, 'rig_type_list', text="", icon='ARMATURE_DATA')

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig elements will be executed during generation."""
        layout.row().prop(self, "filter_name", text="")

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
            list_path = 'object.data.cloudrig.rig_element_bones',
            active_index_path = 'object.data.cloudrig.active_rig_element_index',
            insertion_operators = True,
            move_operators = True,
        )

registry = [
    CLOUDRIG_UL_rig_elements,
    CLOUDRIG_PT_rig_elements,
]
