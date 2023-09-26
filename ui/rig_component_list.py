from bpy.types import Panel, UIList
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class CLOUDRIG_UL_rig_components(UIList):
    """CloudRigLogEntry's are displayed under Properties->Armature->Rigify Log,
    when the active object is a CloudRig Metarig.
    """
    def draw_item(self, context, layout, _data, item, _icon_value, _active_data, _active_propname):
        rig = context.object
        rig_component_bone_name = item.name
        addon_prefs = get_addon_prefs(context)

        pb = rig.pose.bones.get(rig_component_bone_name)


        row = layout.row()
        split = row.split(factor=0.4)
        row = split.row()
        row.enabled = False
        if not pb:
            row.prop_search(item, 'name', rig.pose, 'bones', text="", icon='ERROR')
        else:
            rig_component = pb.cloudrig_component
            row.prop_search(rig_component, 'owner_bone', rig.pose, 'bones', text="")
            split2 = split.split(factor=0.3)
            split2.alignment = 'RIGHT'
            split2.label(text="Type:")
        if not pb:
            split.label(text="Bone renamed or deleted. Click to refresh.")
        else:
            split2.prop_search(rig_component, 'component_type', addon_prefs, 'rig_type_list', text="", icon='ARMATURE_DATA')

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation."""
        layout.row().prop(self, "filter_name", text="")

class CLOUDRIG_PT_rig_components(Panel):
    bl_label = "Rig Components"
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
            class_name = 'CLOUDRIG_UL_rig_components',
            list_path = 'object.data.cloudrig.rig_component_bones',
            active_index_path = 'object.data.cloudrig.active_rig_component_index',
            insertion_operators = True,
            move_operators = True,
            unique_id = 'CloudRig Rig Component List'
        )

registry = [
    CLOUDRIG_UL_rig_components,
    CLOUDRIG_PT_rig_components,
]
