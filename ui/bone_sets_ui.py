from bpy.types import Panel, UIList, UI_UL_list
from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs

class CLOUDRIG_UL_bone_sets(UIList):
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

        obj = context.object
        cloudrig = obj.data.cloudrig
        active_pb = context.active_pose_bone
        rig_class = active_pb.cloudrig_component.rig_class

        for idx, ui_bone_set in enumerate(ui_bone_sets):
            if ui_bone_set.name not in rig_class.bone_set_definitions:
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
    CLOUDRIG_UL_bone_sets,
]