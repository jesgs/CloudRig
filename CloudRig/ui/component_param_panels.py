# SPDX-License-Identifier: GPL-3.0-or-later

from collections import OrderedDict
from dataclasses import dataclass

from bpy.types import Panel

from ..bs_utils.prefs import get_addon_prefs
from ..bs_utils.ui import aligned_label, label_split
from ..utils.rig import get_pbone_of_active


class CLOUDRIG_PT_rig_component(Panel):
    bl_label = "CloudRig Component"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'bone'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if not context.object or context.object.type != 'ARMATURE':
            return False
        if not context.object.cloudrig.enabled:
            return False
        active_pb = get_pbone_of_active(context)
        if not active_pb:
            return False
        if not hasattr(active_pb, 'cloudrig_component'):
            # This would only happen if CloudRig fails to register (hopefully never.)
            return False
        return True

    def draw(self, context):
        layout = self.layout.column()
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = get_addon_prefs(context)
        active_pb = get_pbone_of_active(context)
        rig_component = active_pb.cloudrig_component
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
            text=text
        )
        if rig_component.component_type == 'Spine: Squashy':
            # TODO 5.1: Remove Spine: Cartoon.
            aligned_label(layout, text="DEPRECATED! Please use Spine: Cartoon!", alert=True, icon='ERROR')
        if not rig_component.component_type or row.alert:
            return

        layout.prop(prefs, 'advanced_mode')
        draw_params_subpanels(context, layout)

@dataclass
class CloudRigPanel:
    ui_name: str
    func_name: str
    is_advanced: bool = False

    @classmethod
    def poll(cls, context):
        return True

    def draw_header(self, context, layout):
        pass

class AnimPanel(CloudRigPanel):
    @classmethod
    def poll(cls, context):
        return context.object.cloudrig.generator.generate_test_action

    def draw_header(self, context, layout):
        active_pb = get_pbone_of_active(context)
        params = active_pb.cloudrig_component.params
        layout.use_property_split = False
        layout.prop(params.fk_chain, 'test_animation_generate', text="")

class CustomPropPanel(CloudRigPanel):
    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        pb = get_pbone_of_active(context)
        component_class = pb.cloudrig_component.component_class
        return component_class.base__is_using_custom_props(context, pb.cloudrig_component.params)

class BoneSetPanel(CloudRigPanel):
    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False

        pb = get_pbone_of_active(context)
        component_class = pb.cloudrig_component.component_class

        # If no bone sets are visible, don't draw the panel.
        for prop_name, bone_set_def in component_class.bone_set_defs.items():
            if component_class.is_bone_set_used(
                context,
                context.object,
                pb.cloudrig_component.params,
                bone_set_def['name'],
            ):
                return True

        return False

PANEL_DATAS = OrderedDict(
    (data.ui_name, data) for data in
    [
        CloudRigPanel("Parenting", "draw_parenting_params"),
        CloudRigPanel("Controls", "draw_control_params"),
        AnimPanel("Test Animation", "draw_anim_params"),
        CloudRigPanel("Bendy Bones", "draw_bendy_params"),
        CloudRigPanel("Appearance", "draw_appearance_params"),
        CustomPropPanel("Custom Properties", "draw_custom_prop_params", True),
        BoneSetPanel("Bone Organization", "draw_bone_set_params", True),
    ]
)

def draw_params_subpanels(context, layout):
    for panel_name in PANEL_DATAS:
        draw_params_subpanel_single(context, layout, panel_name)

def draw_params_subpanel_single(context, layout, panel_name: str):
    panel_data = PANEL_DATAS.get(panel_name)
    if not panel_data:
        return
    active_pb = get_pbone_of_active(context)
    rig_component = active_pb.cloudrig_component.inherited_component
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
        not getattr(comp_class, poll_func_name)(context, active_pb.cloudrig_component.params)
    ):
        return
    header, panel = layout.panel(f"CloudRig {panel_data.ui_name}", default_closed=True)
    panel_data.draw_header(context, header)
    header.label(text=panel_data.ui_name)
    if panel:
        draw_component_params(context, layout, panel_data.func_name)

def draw_component_params(context, layout, func_name: str):
    pb = get_pbone_of_active(context)
    component_class = pb.cloudrig_component.component_class
    draw_func = getattr(component_class, func_name)
    draw_func(layout, context, pb.cloudrig_component.params)

registry = [
    CLOUDRIG_PT_rig_component
]
