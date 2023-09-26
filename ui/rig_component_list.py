import bpy
from bpy.types import Panel, UIList
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class CLOUDRIG_UL_rig_components(UIList):
    """The Rig Component list is actually a list of all pose bones on the object, 
    filtered to only show the ones that have a CloudRig component type assigned.
    """
    # TODO 4.0: Make sure this list has functional filtering, hierarchical sorting, and ideally, hierarchical indentation.
    def draw_item(self, context, layout, data, item, icon_value, _active_data, _active_propname):
        pose_bone = item
        rig_component = pose_bone.cloudrig_component

        addon_prefs = get_addon_prefs(context)

        row = layout.row()
        split = row.split(factor=0.4)
        row = split.row()
        row.label(text=pose_bone.name, icon_value=icon_value)
        split2 = split.split(factor=0.3)
        split2.alignment = 'RIGHT'
        split2.label(text="")
        split2.prop_search(rig_component, 'component_type', addon_prefs, 'rig_type_list', text="", icon='ARMATURE_DATA')

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

        return flt_flags, flt_neworder
    

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
        return context.object.data.cloudrig.enabled

    def draw(self, context):
        layout = self.layout
        draw_ui_list(
            layout,
            context,
            class_name = 'CLOUDRIG_UL_rig_components',
            list_path = 'object.pose.bones',
            active_index_path = 'object.active_material_index', # I mean, Blender won't be needing it? (TODO 4.0 This is funny but just make a property)
            insertion_operators = True,
            move_operators = False,
            unique_id = 'CloudRig Rig Component List'
        )

registry = [
    CLOUDRIG_UL_rig_components,
    CLOUDRIG_PT_rig_components,
]
