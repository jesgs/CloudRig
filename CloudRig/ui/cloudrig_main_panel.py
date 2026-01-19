# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Object, Panel

from ..bs_utils.prefs import get_addon_prefs
from ..generation.cloudrig import is_cloud_metarig, is_generated_cloudrig
from ..generation.troubleshooting import draw_log_panel
from ..utils.misc import check_addon
from .actions_ui import draw_action_setup_list
from .component_list import draw_rig_component_list


class CloudRig_MainPanel:
    bl_label = "CloudRig"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = context.object
        if not rig or rig.type != 'ARMATURE':
            return False
        return rig and not is_generated_cloudrig(rig)

    def draw_header(self, context):
        layout = self.layout
        layout.prop(context.object.cloudrig, 'enabled', text="")

    def draw(self, context):
        layout = self.layout

        metarig = context.object
        cloudrig = metarig.cloudrig

        layout.enabled = cloudrig.enabled

        text = "Generate CloudRig"
        if metarig.cloudrig.generator.target_rig:
            text = "Re-Generate CloudRig"
        layout.operator("pose.cloudrig_generate", text=text)

        prefs = get_addon_prefs(context)
        if metarig.cloudrig.generator.metarig_version > prefs.cloud_metarig_version:
            warning_col = layout.column(align=True)
            warning_col.alert = True
            warning_col.label(text="Metarig authored with a newer version of CloudRig.", icon='ERROR')
            warning_col.label(text="You should update CloudRig.")
            warning_col.operator('object.cloudrig_dismiss_warning')

        if not context.object.cloudrig.enabled:
            return
        draw_general_panel(context, layout)

        draw_log_panel(context, layout)

        prefs = get_addon_prefs(context)
        if prefs.advanced_mode:
            draw_custom_shapes_panel(context, layout)

        draw_action_setup_list(context, layout)

        draw_rig_component_list(context, layout, default_closed=False)


class POSE_PT_CloudRig_Popover(CloudRig_MainPanel, Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 20

    @classmethod
    def poll(cls, context):
        prefs = get_addon_prefs(context)
        if not prefs:
            return False
        if prefs.ui_mode == 'HEADER':
            arm_ob = context.active_object
            return arm_ob and arm_ob.type == 'ARMATURE' and not is_generated_cloudrig(arm_ob)
        return super().poll(context)

    def draw_header(self, context):
        prefs = get_addon_prefs(context)
        if prefs.ui_mode != 'HEADER':
            return
        super().draw_header(context)


class POST_PT_CloudRig_Properties(CloudRig_MainPanel, Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'

    @classmethod
    def poll(cls, context):
        prefs = get_addon_prefs(context)
        if not prefs:
            return False
        if prefs.ui_mode == 'HEADER':
            return False
        return super().poll(context)


def metarig_contains_fk_chain(metarig: Object) -> bool:
    """Return whether or not a metarig contains an FK rig. Used to determine
    whether animation generation checkbox should appear or not."""
    for pb in metarig.pose.bones:
        rig_component = pb.cloudrig_component
        if rig_component.component_type != '':
            # This is a bit nasty but importing Component_Chain_FK and using issubclass() breaks parameter registering (don't ask me why!)
            if 'cloud_fk_chain' in str(rig_component.component_class.mro()):
                return True
    return False


def draw_general_panel(context, layout):
    header, panel = layout.panel("CloudRig General", default_closed=True)
    header.label(text="General")
    if not panel:
        return

    layout = panel
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout = layout.column(align=True)

    prefs = get_addon_prefs(context)
    metarig = context.object
    generator = metarig.cloudrig.generator

    layout.prop(prefs, 'advanced_mode')

    layout = layout.column()
    layout.prop(generator, 'target_rig')
    if not prefs.advanced_mode:
        return

    script_row = layout.row(align=True)
    script_row.prop(generator, 'custom_script')
    if not generator.custom_script:
        script_row.operator('wm.cloudrig_template_script_create', icon='FILE_NEW', text="")

    # Test Animation Parameters
    if metarig_contains_fk_chain(metarig):
        heading = "Generate Action"
        if generator.test_action:
            heading = "Update Action"
        act_row = layout.row(heading=heading)
        act_row.prop(generator, 'generate_test_action', text="")
        act_col = act_row.column()
        act_col.prop(generator, 'test_action', text="")
        act_col.enabled = generator.generate_test_action

    if check_addon(context, 'bone_gizmos'):
        layout.prop(generator, 'auto_setup_gizmos')

    layout.separator()

    layout.prop(generator, 'ensure_root', icon='BONE_DATA')
    layout.prop_search(generator, 'properties_bone', metarig.data, 'bones')


def draw_custom_shapes_panel(context, layout):
    header, panel = layout.panel("CloudRig Custom Shapes", default_closed=True)
    header.label(text="Custom Shapes")
    if not panel:
        return

    layout = panel
    layout.use_property_split = True
    layout.use_property_decorate = False
    generator = context.object.cloudrig.generator

    # Widgets
    col = layout.column(align=True)
    row = col.row(align=True)
    row.prop(generator, 'widget_collection', text="Collection")
    row.prop(generator, 'reload_widgets', text="", icon='FILE_REFRESH')

    layout.separator()

    # Custom Shapes
    col.prop(generator, 'preserve_shapes_properties', text="Preserve Properties")
    if generator.preserve_shapes_properties:
        split = col.split(factor=0.04)
        split.row()
        split.row().prop(generator, 'preserve_custom_shapes', text="With Shapes")


def draw_cloudrig_popover(self, context):
    prefs = get_addon_prefs(context)
    if not prefs:
        return
    if prefs.ui_mode == 'PROPERTIES':
        return
    if not is_cloud_metarig(context.active_object) and prefs.ui_mode != 'HEADER':
        return
    layout = self.layout
    layout.popover(
        panel="POSE_PT_CloudRig_Popover",
        icon='OUTLINER_DATA_ARMATURE',
        text="",
    )


def register():
    bpy.types.VIEW3D_HT_header.append(draw_cloudrig_popover)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_cloudrig_popover)


registry = [
    POSE_PT_CloudRig_Popover,
    POST_PT_CloudRig_Properties,
]
