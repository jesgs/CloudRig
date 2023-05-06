from bpy.types import Panel, UIList, UI_UL_list
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

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
    CLOUDRIG_PT_rig_element
]
