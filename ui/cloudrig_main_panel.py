from bpy.types import Panel, UIList, UI_UL_list
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
            ,class_name = 'CLOUDRIG_UL_bone_set'
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

        # elif not CLOUDRIG_UL_bone_set.flt_flags[cloudrig.active_bone_set_idx]:
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


class CLOUDRIG_UL_bone_set(UIList):
    flt_flags = []

    def draw_filter(self, context, layout):
        layout.prop(self, 'filter_name', text="")

    def filter_items(self, context, data, propname):
        flt_flags = []
        flt_neworder = []
        ui_bone_sets = getattr(data, propname)

        helper_funcs = UI_UL_list

        # Always sort alphabetical.
        flt_neworder = helper_funcs.sort_items_by_name(ui_bone_sets, "name")

        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, ui_bone_sets, "pretty_name")

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

        return flt_flags, flt_neworder

        obj = context.object
        cloudrig = obj.data.cloudrig
        active_pb = context.active_pose_bone
        rig_class = active_pb.cloudrig_element.rig_class

        for idx, ui_bone_set in enumerate(ui_bone_sets):
            # TODO: Filter bone sets not in the class definition of the active bone's assigned rig element.
            if ui_bone_set.name not in rig_class.bone_set_defs:
                flt_flags[idx] = 0
            # else:
            #     bone_set_def = rig_class.bone_set_defs[ui_bone_set.name]
            #     if not rig_class.is_bone_set_used(active_pb.rigify_parameters, bone_set_def):
            #         # Filter bone sets that are not used based on current parameters
            #         flt_flags[idx] = 0

        type(self).flt_flags = flt_flags
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        ui_bone_set = item
        pretty_name = ui_bone_set.pretty_name
        # rig_data = ui_bone_set.id_data
        # rigify_layers = rig_data.rigify_layers
        rig = context.object
        pb = context.active_pose_bone
        # param_layers = getattr(pb.rigify_parameters, ui_bone_set.layer_param)
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.label(text=pretty_name)
            # layer_names = ", ".join([layer.name for i, layer in enumerate(rigify_layers) if param_layers[i]])
            # row.label(text=layer_names)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text=pretty_name)

registry = [
    POSE_PT_CloudRig,
    CLOUDRIG_UL_bone_set,
    CLOUDRIG_UL_rig_elements,
    CLOUDRIG_PT_rig_elements,
    CLOUDRIG_PT_rig_element
]