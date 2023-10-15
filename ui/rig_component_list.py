import bpy
from bpy.props import StringProperty
from bpy.types import Panel, UIList
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs
from ..rig_component_features.ui import redraw_viewport
from ..generation.cloudrig import is_cloud_metarig

class CLOUDRIG_UL_rig_components(UIList):
    """The Rig Component list is actually a list of all pose bones on the object, 
    filtered to only show the ones that have a CloudRig component type assigned.
    """
    def draw_item(self, context, layout, data, item, icon_value, _active_data, _active_propname):
        pose_bone = item
        rig_component = pose_bone.cloudrig_component

        addon_prefs = get_addon_prefs(context)

        row = layout.row()
        split = row.split(factor=0.4)
        row = split.row()
        row.label(text=">" * rig_component.depth + pose_bone.name, icon_value=icon_value)
        split2 = split.split(factor=0.3)
        split2.alignment = 'RIGHT'
        split2.label(text="")
        split2.prop_search(rig_component, 'component_type', addon_prefs, 'component_types', text="", icon='ARMATURE_DATA')

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation."""
        layout.row().prop(self, "filter_name", text="")

    def filter_items(self, context, data, propname):
        pbones = getattr(data, propname)

        # Default return values.
        flt_flags = [self.bitflag_filter_item] * len(pbones)
        flt_neworder = []

        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name search.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, pbones, "name",
                                                          reverse=False)

        # Filter out bones that don't have a rig component.
        flt_flags = [flag * int(pbones[i].cloudrig_component.component_type!="") for i, flag in enumerate(flt_flags)]

        flt_neworder = [i for i, _pb in enumerate(sorted(pbones, key=lambda pb: pb.cloudrig_component.order))]

        return flt_flags, flt_neworder


class CLOUDRIG_OT_add_rig_component(bpy.types.Operator):
    """Assign a CloudRig Component Type to a bone"""
    bl_idname = "pose.cloudrig_assign_component_type"
    bl_label = "Add Component"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    bone_name: StringProperty(
        name="Bone Name",
        description = "Name of the bone to assign a component type to"
    )
    component_type: StringProperty(
        name="Component Type",
        description = "Component type to assign"
    )

    @classmethod
    def poll(cls, context):
        return is_cloud_metarig(context.object)
    
    def invoke(self, context, _event):
        if context.active_pose_bone:
            self.bone_name = context.active_pose_bone.name
        elif context.active_bone:
            self.bone_name = context.active_bone.name
        
        selected_pb = context.object.pose.bones.get(self.bone_name)
        if selected_pb:
            self.component_type = selected_pb.cloudrig_component.component_type

        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split=True
        layout.use_property_decorate=False

        rig = context.object
        row = layout.row()
        row.prop_search(self, 'bone_name', rig.data, 'bones', text="")
        selected_pb = rig.pose.bones.get(self.bone_name)
        if not selected_pb:
            return
        prefs = get_addon_prefs(context)
        row.prop_search(self, 'component_type', prefs, 'component_types', text="", icon='ARMATURE_DATA')

    def execute(self, context):
        rig = context.object
        if not self.bone_name:
            self.report({'ERROR'}, "Cancelled: No bone selected.")
            return {'CANCELLED'}
        if not self.component_type:
            self.report({'ERROR'}, "Cancelled: No component type selected.")
            return {'CANCELLED'}
        if self.bone_name not in rig.pose.bones:
            self.report({'ERROR'}, "Bone not found in rig: " + self.bone_name)
            return {'CANCELLED'}
        selected_pb = rig.pose.bones[self.bone_name]

        selected_pb.cloudrig_component.component_type = self.component_type
        selected_pb.cloudrig_component.base_bone_name = selected_pb.name
        rig.cloudrig.active_component_index = rig.pose.bones.find(self.bone_name)

        # Need to re-draw UI, otherwise the changes don't always show up...
        redraw_viewport()

        return {'FINISHED'}


class CLOUDRIG_OT_remove_rig_component(bpy.types.Operator):
    """Remove active rig component"""
    bl_idname = "pose.cloudrig_remove_component_type"
    bl_label = "Remove Component"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return is_cloud_metarig(context.object)
    
    def execute(self, context):
        rig = context.object
        selected_pb = rig.pose.bones[rig.cloudrig.active_component_index]

        selected_pb.cloudrig_component.component_type = ""
        
        # Set active index to previous bone that has a component.
        last = 0
        for i, pb in enumerate(rig.pose.bones):
            if pb.cloudrig_component.component_type:
                last = i
            if pb == selected_pb:
                break
        
        rig.cloudrig.active_component_index = last

        return {'FINISHED'}

class CLOUDRIG_PT_rig_components(Panel):
    bl_label = "Rig Components"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_parent_id = 'POSE_PT_CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # This is safe because of bl_parent_id; The parent panel's poll does
        # early exit checks already, no point repeating them here.
        return context.object.cloudrig.enabled

    def draw(self, context):
        layout = self.layout
        ops_col = draw_ui_list(
            layout,
            context,
            class_name = 'CLOUDRIG_UL_rig_components',
            list_path = 'object.pose.bones',
            active_index_path = 'object.cloudrig.active_component_index',
            insertion_operators = False,
            move_operators = False,
            unique_id = 'CloudRig Rig Component List'
        )
        ops_col.operator(CLOUDRIG_OT_add_rig_component.bl_idname, text="", icon='ADD')
        ops_col.operator(CLOUDRIG_OT_remove_rig_component.bl_idname, text="", icon='REMOVE')

registry = [
    CLOUDRIG_UL_rig_components,
    CLOUDRIG_OT_add_rig_component,
    CLOUDRIG_OT_remove_rig_component,
    CLOUDRIG_PT_rig_components,
]
