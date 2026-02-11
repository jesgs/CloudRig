# SPDX-License-Identifier: GPL-3.0-or-later

from bl_ui.generic_ui_list import draw_ui_list
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, UI_UL_list, UIList

from ..bs_utils.prefs import get_addon_prefs
from ..generation.cloudrig import is_cloud_metarig
from ..rig_component_features.properties_ui import redraw_viewport
from ..utils.rig import get_component_in_ui, get_pbone_of_active
from .component_param_panels import draw_params_subpanels


class CLOUDRIG_UL_rig_components(UIList):
    """The Rig Component list is actually a list of all pose bones on the object,
    filtered to only show the ones that have a CloudRig component type assigned.
    """

    def draw_item(
        self, context, layout, data, item, icon_value, _active_data, _active_propname
    ):
        pose_bone = item
        rig_component = pose_bone.cloudrig_component
        if not rig_component.component_type:
            return

        row = layout.row(align=True)
        main_split = row.split(factor=0.5)
        row = main_split.row(align=True)
        icon = 'TRIA_DOWN' if rig_component.show_child_components else 'TRIA_RIGHT'
        if rig_component.parent:
            split = row.split(factor=0.02 * rig_component.depth)
            split.row()
            row = split.row(align=True)
        if rig_component.has_children:
            row.prop(rig_component, 'show_child_components', text="", icon=icon, emboss=False)
        else:
            row.label(text="", icon='BLANK1')
        row = row.row()
        row.enabled = rig_component.is_enabled_component
        row.label(text=pose_bone.name, icon='BONE_DATA')

        icon = 'ARMATURE_DATA'
        if not rig_component.component_class:
            icon = 'ERROR'
        main_row = main_split.row()
        row = main_row.row()
        row.enabled = rig_component.enabled_with_parents
        icon = 'ARMATURE_DATA'
        if not rig_component.component_class:
            icon = 'ERROR'
            row.alert = True
        row.label(text=rig_component.component_type, icon=icon)
        row = main_row.row()
        icon = 'CHECKBOX_HLT' if rig_component.enabled_toggle else 'CHECKBOX_DEHLT'
        row.prop(rig_component, 'enabled_toggle', text="", emboss=False, icon=icon)

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation.
        """
        layout.row().prop(self, "filter_name", text="")

    def filter_items(self, context, data, propname):
        pbones = getattr(data, propname)

        # Default return values.
        flt_flags = [self.bitflag_filter_item] * len(pbones)
        flt_neworder = []

        helper_funcs = UI_UL_list

        # Filtering by name search.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                pbones,
                "name",
                reverse=False,
            )
            filter_map = {pb: flt_flags[i] for i, pb in enumerate(pbones)}
            # Allow collections that contain any collections that match the filter.
            for i, pbone in enumerate(pbones):
                if any([filter_map[child] for child in pbone.children_recursive]):
                    flt_flags[i] = 1073741824

        # Filter out bones that don't have a rig component.
        flt_flags = [
            flag * int(pbones[i].cloudrig_component.component_type != "")
            for i, flag in enumerate(flt_flags)
        ]

        # Filter out components whose parents are collapsed
        flt_flags = [
            flag * int(pbones[i].cloudrig_component.should_draw)
            for i, flag in enumerate(flt_flags)
        ]

        sorted_pbones = sorted(pbones, key=lambda pb: pb.cloudrig_component.order)
        # NOTE: THIS MUST BE BOMBPROOF, OR BLENDER WILL CRASH!
        flt_neworder = [sorted_pbones.index(pb) for pb in pbones]
        return flt_flags, flt_neworder


class CLOUDRIG_OT_add_rig_component(Operator):
    """Assign a CloudRig Component Type to a bone"""

    bl_idname = "pose.cloudrig_assign_component_type"
    bl_label = "Add Component"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    bone_name: StringProperty(
        name="Bone Name", description="Name of the bone to assign a component type to"
    )
    component_type: StringProperty(
        name="Component Type", description="Component type to assign"
    )
    remove_active_log: BoolProperty(
        name="Remove Active Log",
        description="If True, remove the active generation log entry",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        if not is_cloud_metarig(context.object):
            cls.poll_message_set(
                "This button should only be visible on CloudRig metarigs!"
            )
            return False
        return True

    def invoke(self, context, _event):
        if not self.bone_name:
            active_pb = get_pbone_of_active(context)
            if active_pb:
                self.bone_name = active_pb.name
            elif context.active_bone:
                self.bone_name = context.active_bone.name

            selected_pb = context.object.pose.bones.get(self.bone_name)
            if selected_pb:
                self.component_type = selected_pb.cloudrig_component.component_type

        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        rig = context.object
        row = layout.row()
        row.prop_search(self, 'bone_name', rig.data, 'bones', text="")
        selected_pb = rig.pose.bones.get(self.bone_name)
        if not selected_pb:
            return
        draw_component_type_selector(context, row, self)

    def execute(self, context):
        rig = context.object
        if not self.bone_name:
            self.report({'ERROR'}, "A bone must be selected.")
            return {'CANCELLED'}
        if not self.component_type:
            self.report({'ERROR'}, "A component type must be selected.")
            return {'CANCELLED'}
        if self.bone_name not in rig.pose.bones:
            self.report({'ERROR'}, "Bone not found in rig: " + self.bone_name)
            return {'CANCELLED'}
        selected_pb = rig.pose.bones[self.bone_name]

        selected_pb.cloudrig_component.component_type = self.component_type
        rig.cloudrig.active_component_index = rig.pose.bones.find(self.bone_name)
        self.report(
            {'INFO'},
            'Added "{comp_type}" component to "{bone}".'.format(comp_type=selected_pb.cloudrig_component.component_type, bone=selected_pb.name),
        )

        if self.remove_active_log:
            rig.cloudrig.generator.remove_active_log()

        # Need to re-draw UI, otherwise the changes don't always show up...
        redraw_viewport()

        return {'FINISHED'}


class CLOUDRIG_OT_remove_rig_component(Operator):
    """Remove active rig component"""

    bl_idname = "pose.cloudrig_remove_component_type"
    bl_label = "Remove Component"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if (
            not is_cloud_metarig(context.object)
            and context.object.cloudrig.active_component
        ):
            cls.poll_message_set("Select a component.")
            return False
        return True

    def execute(self, context):
        rig = context.object
        selected_pb = rig.pose.bones[rig.cloudrig.active_component_index]

        self.report(
            {'INFO'},
            'Removed "{comp_type}" component from "{bone}".'.format(comp_type=selected_pb.cloudrig_component.component_type, bone=selected_pb.name),
        )
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


class CLOUDRIG_OT_reorder_rig_component(Operator):
    """Reorder Component"""

    bl_idname = "pose.cloudrig_reorder_component"
    bl_label = "Reorder Component"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    direction: EnumProperty(
        name="Direction", items=[('UP', "Up", "Up"), ('DOWN', "Down", "Down")]
    )

    @classmethod
    def poll(cls, context):
        rig = context.object
        if not is_cloud_metarig(rig):
            cls.poll_message_set("Must be a CloudRig metarig.")
            return False
        comp = rig.cloudrig.active_component
        if not comp:
            cls.poll_message_set("Select a component.")
            return False
        if len(comp.siblings) == 1:
            cls.poll_message_set("Active component has no siblings.")
            return False
        return True

    def execute(self, context):
        rig = context.object
        component = rig.cloudrig.active_component

        delta = -1 if self.direction == 'UP' else 1
        sibling_idx = component.sibling_order + delta
        if sibling_idx < 0:
            self.report(
                {'ERROR'},
                "This component is already the first among its siblings. It cannot be moved higher in the generation order.",
            )
            return {'CANCELLED'}
        if sibling_idx > len(component.siblings) - 1:
            self.report(
                {'ERROR'},
                "This component is already the last among its siblings. It cannot be moved lower in the generation order.",
            )
            return {'CANCELLED'}

        # Swap the sibling order of the two siblings.
        sibling = component.siblings[sibling_idx]
        sibling.sibling_order -= delta
        component.sibling_order += delta

        rig.cloudrig.refresh_generation_order()

        return {'FINISHED'}


def draw_component_type_selector(context, layout, prop_owner, icon='ARMATURE_DATA'):
    prefs = get_addon_prefs(context)
    layout.prop_search(
        prop_owner,
        'component_type',
        prefs,
        'component_types',
        text="",
        icon=icon,
    )


def draw_rig_component_list(context, layout, default_closed=True):
    header, panel = layout.panel("CloudRig Rig Components", default_closed=default_closed)
    header.label(text="Components")
    if not panel:
        return

    layout = panel
    prefs = get_addon_prefs(context)
    layout.row().prop(prefs, 'component_overview_mode', expand=True)
    if prefs.component_overview_mode == 'LIST':
        ops_col = draw_ui_list(
            layout,
            context,
            class_name='CLOUDRIG_UL_rig_components',
            list_path='object.pose.bones',
            active_index_path='object.cloudrig.active_component_index',
            insertion_operators=False,
            move_operators=False,
            unique_id='CloudRig Rig Component List',
        )
        ops_col.operator(CLOUDRIG_OT_add_rig_component.bl_idname, text="", icon='ADD')
        ops_col.operator(
            CLOUDRIG_OT_remove_rig_component.bl_idname, text="", icon='REMOVE'
        )
        ops_col.separator()
        ops_col.operator(
            CLOUDRIG_OT_reorder_rig_component.bl_idname, text="", icon='TRIA_UP'
        ).direction = 'UP'
        ops_col.operator(
            CLOUDRIG_OT_reorder_rig_component.bl_idname, text="", icon='TRIA_DOWN'
        ).direction = 'DOWN'

    active_component = get_component_in_ui(context)
    if not active_component or not active_component.component_pbone:
        return

    header, panel = layout.panel("CloudRig Component In List", default_closed=False)
    row = header.row()
    row.label(text=f"{active_component.component_pbone.name}", icon='BONE_DATA')
    icon = 'ARMATURE_DATA'
    if not active_component.component_class:
        icon = 'ERROR'
    draw_component_type_selector(context, row, active_component, icon=icon)
    row.label(text="", icon='BLANK1')
    if panel:
        box = panel.box()
        box.use_property_split = True
        box.use_property_decorate = False
        draw_params_subpanels(context, active_component, box.column())

registry = [
    CLOUDRIG_UL_rig_components,
    CLOUDRIG_OT_add_rig_component,
    CLOUDRIG_OT_remove_rig_component,
    CLOUDRIG_OT_reorder_rig_component,
]
