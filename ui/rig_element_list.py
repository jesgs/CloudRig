from bpy.types import Panel, UIList, UI_UL_list
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

class CLOUDRIG_PT_rig_element(Panel):
    bl_label = "CloudRig Element"
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
        layout = self.layout
        addon_prefs = get_addon_prefs(context)
        active_bone = context.active_bone
        active_pb = context.object.pose.bones.get(active_bone.name)
        rig_element = active_pb.cloudrig_element
        layout.prop_search(rig_element, 'element_type', addon_prefs, 'rig_type_list', icon='ARMATURE_DATA')

        self.draw_bone_sets_list(layout, context, rig_element)

    def draw_bone_sets_list(self, layout, context, params):
        """Drawing the Bone Sets section of the Rigify Parameters."""
        obj = context.object
        cloudrig = obj.data.cloudrig
        active_pb = context.active_pose_bone
        if not active_pb.cloudrig_element.element_type:
            return
        params = active_pb.cloudrig_element.params

        if (
            len(cloudrig.ui_bone_sets) == 0 or \
            cloudrig.active_bone_set_idx > len(cloudrig.ui_bone_sets)
        ):
            layout.label(text="UI Bone Sets were not yet initialized. This should never happen!")
            return

        active_ui_bone_set = cloudrig.ui_bone_sets[cloudrig.active_bone_set_idx]
        active_bone_set = getattr(params.bone_sets, active_ui_bone_set.name)
        if not active_bone_set:
            layout.label(text="Could not find Bone Set named " + active_ui_bone_set.name)
            return

        list_column = draw_ui_list(
            layout
            ,context
            ,class_name = 'CLOUDRIG_UL_bone_sets'
            ,list_path = 'object.data.cloudrig.ui_bone_sets'
            ,active_index_path = 'object.data.cloudrig.active_bone_set_idx'
            ,insertion_operators = False
            ,move_operators = False
            ,type='GRID' if cloudrig.bone_set_use_grid_layout else 'DEFAULT'
            ,columns=3
        )
        # eye_icon = 'HIDE_OFF' if cloudrig.bone_set_show_advanced else 'HIDE_ON'
        # list_column.prop(cloudrig, 'bone_set_show_advanced', text="", emboss=False, icon=eye_icon)
        # layout_icon = 'MESH_GRID' if cloudrig.bone_set_use_grid_layout else 'COLLAPSEMENU'
        # list_column.prop(cloudrig, 'bone_set_use_grid_layout', text="", emboss=False, icon=layout_icon)

        # elif not CLOUDRIG_UL_bone_sets.flt_flags[cloudrig.active_bone_set_idx]:
        #     # If the active item is not visible
        #     return

        # set_info = cls.bone_set_defs[active_bone_set.name]
        # split = layout.row().split(factor=0.8)
        # cls.draw_prop_search(split.row(), params, set_info['param'], obj.pose, "bone_groups", text="Bone Group")
        # bone_group_name = getattr(params, set_info['param'])
        # bone_group = obj.pose.bone_groups.get(bone_group_name)
        # if bone_group:
        #     row = split.row(align=True)

        #     if bone_group.color_set != 'DEFAULT':
        #         row.prop(bone_group, 'color_set', text="", icon_only=True)
        #         row = row.row(align=True)
        #         row.enabled = bone_group.is_custom_color_set
        #         row.prop(bone_group.colors, "normal", text="")
        #         row.prop(bone_group.colors, "select", text="")
        #         row.prop(bone_group.colors, "active", text="")
        #     else:
        #         row.prop(bone_group, 'color_set', text="", icon='DOWNARROW_HLT')

        # layout.use_property_split=False
        # draw_layers_ui(
        #     layout = layout, 
        #     rig = obj, 
        #     show_unnamed_selected_layers = True,
        #     show_hidden_checkbox = True, 
        #     layer_prop_owner = params, 
        #     layer_prop_name = set_info['layer_param']
        # )


registry = [
    CLOUDRIG_UL_rig_elements,
    CLOUDRIG_PT_rig_elements,
    CLOUDRIG_PT_rig_element
]
