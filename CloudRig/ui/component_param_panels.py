# SPDX-License-Identifier: GPL-3.0-or-later

from collections import OrderedDict
from dataclasses import dataclass

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import Panel

from ..bs_utils.prefs import get_addon_prefs
from ..bs_utils.ui import aligned_label, label_split
from ..utils.rig import get_component_in_ui, get_pbone_of_active


class CLOUDRIG_PT_rig_component(Panel):
    bl_label = "CloudRig Component"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'bone'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        prefs = get_addon_prefs(context)
        if not prefs:
            return False
        if prefs.ui_mode == 'HEADER':
            return False
        if not context.object or context.object.type != 'ARMATURE':
            return False
        if not context.object.cloudrig.enabled:
            return False
        active_pb = get_pbone_of_active(context)
        if not active_pb:
            return False
        return True

    def draw(self, context):
        draw_rig_component_panel(context, self.layout)

def draw_rig_component_panel(context, layout):
    layout = layout.column()
    layout.use_property_split = True
    layout.use_property_decorate = False

    prefs = get_addon_prefs(context)
    active_pb = get_pbone_of_active(context)
    if not active_pb:
        layout.label(text="No active bone.")
        return
    rig_component = active_pb.cloudrig_component
    draw_inherited_component(layout, rig_component)
    layout.alert = rig_component.component_type!="" and not bool(rig_component.component_class)
    row = layout.row()
    text = "Component Type"
    if row.alert:
        text += " (Not Found!)"
    row.prop_search(
        rig_component,
        'component_type',
        prefs,
        'component_types',
        icon='ARMATURE_DATA' if not row.alert else 'ERROR',
        text=text,
    )
    if rig_component.component_type == 'Spine: Squashy':
        # TODO 5.1: Remove Spine: Cartoon.
        aligned_label(layout, text=rpt_("DEPRECATED! Please use Spine: Cartoon!"), alert=True, icon='ERROR')
    if rig_component.component_type in ("", "Raw Copy") or row.alert:
        return

    layout.prop(prefs, 'advanced_mode')
    draw_params_subpanels(context, rig_component, layout)

def draw_inherited_component(layout, rig_component):
    if rig_component.component_type == "":
        comp_pb = rig_component.component_pbone
        if comp_pb:
            # Display inherited component type and a button to jump to it.
            split = label_split(layout, text="Inherited:")
            row = split.row(align=True)
            sub0 = row.row()
            sub0.enabled = False
            sub0.prop(comp_pb, 'name', icon='BONE_DATA', text="")
            sub_1 = row.row()
            sub_2 = row.row()
            sub_1.enabled = False
            sub_1.prop(comp_pb.cloudrig_component, 'component_type', text="")
            op = sub_2.operator("armature.jump_to_bone", text="", icon='LOOP_FORWARDS')
            op.use_target_rig = False
            op.target_bone = comp_pb.name

@dataclass
class CloudRigPanel:
    ui_name: str
    func_name: str
    is_advanced: bool = False

    def poll(self, context):
        comp = get_component_in_ui(context)
        component_class = comp.component_class
        if hasattr(component_class, 'poll_'+self.func_name):
            poll_func = getattr(component_class, 'poll_'+self.func_name)
            if poll_func:
                return poll_func(context, comp)
        return True

    def draw_header(self, context, layout):
        pass

class AnimPanel(CloudRigPanel):
    def poll(self, context):
        return context.object.cloudrig.generator.generate_test_action

    def draw_header(self, context, layout):
        comp = get_component_in_ui(context)
        params = comp.params
        layout.use_property_split = False
        layout.prop(params.fk_chain, 'test_animation_generate', text="")

class BoneSetPanel(CloudRigPanel):
    def poll(self, context):
        if not super().poll(context):
            return False

        comp = get_component_in_ui(context)
        component_class = comp.component_class

        # If no bone sets are visible, don't draw the panel.
        for prop_name, bone_set_def in component_class.bone_set_defs.items():
            if component_class.is_bone_set_used(
                context,
                context.object,
                comp.params,
                bone_set_def['name'],
            ):
                return True

        return False

PANEL_DATAS = OrderedDict(
    (data.ui_name, data) for data in
    [
        CloudRigPanel(iface_("Parenting"), "draw_parenting_params"),
        CloudRigPanel(iface_("Controls"), "draw_control_params"),
        AnimPanel(iface_("Test Animation"), "draw_anim_params"),
        CloudRigPanel(iface_("Bendy Bones"), "draw_bendy_params"),
        CloudRigPanel(iface_("Appearance"), "draw_appearance_params"),
        CloudRigPanel(iface_("Custom Properties"), "draw_custom_prop_params", True),
        BoneSetPanel(iface_("Bone Organization"), "draw_bone_set_params", True),
    ]
)

def draw_params_subpanels(context, rig_component, layout):
    for panel_name in PANEL_DATAS:
        draw_params_subpanel_single(context, rig_component, layout, panel_name)

def draw_params_subpanel_single(context, rig_component, layout, panel_name: str):
    panel_data = PANEL_DATAS.get(panel_name)
    if not panel_data:
        return
    if not rig_component:
        return
    comp_class = rig_component.component_class
    advanced_mode = get_addon_prefs(context).advanced_mode
    if panel_data.is_advanced and not advanced_mode:
        return
    if not panel_data.poll(context):
        return
    if not hasattr(comp_class, panel_data.func_name):
        return
    poll_func_name = "poll_"+panel_data.func_name
    if (
        hasattr(comp_class, poll_func_name) and
        not getattr(comp_class, poll_func_name)(context, rig_component)
    ):
        return
    header, panel = layout.panel(f"CloudRig {panel_data.ui_name}", default_closed=True)
    panel_data.draw_header(context, header)
    header.label(text=panel_data.ui_name)
    if panel:
        draw_component_params(context, panel.column(), rig_component, panel_data.func_name)

def draw_component_params(context, layout, rig_component, func_name: str):
    component_class = rig_component.component_class
    draw_func = getattr(component_class, func_name)
    draw_func(layout, context, rig_component)

registry = [
    CLOUDRIG_PT_rig_component
]
