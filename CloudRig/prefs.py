# SPDX-License-Identifier: GPL-3.0-or-later

import os

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, PropertyGroup

from . import rig_components
from .bs_utils.hotkeys import draw_hotkey_list
from .bs_utils.prefs import (
    PrefsFileSaveLoadMixin,
    get_addon_prefs,
    update_prefs_on_file,
)
from .operators.apply_bone_color_preset import draw_bone_color_presets
from .properties import NameProperty
from .rig_component_features.widgets.widgets import (
    refresh_widget_list,
)


def init_component_module_list(context=None):
    prefs = get_addon_prefs()
    prefs.component_types.clear()

    module_infos = []
    for rig_file_name, rigcomp_module in rig_components.ALL_COMPONENT_MODULES.items():
        if not hasattr(rigcomp_module, 'RIG_COMPONENT_CLASS'):
            continue
        component_class = rigcomp_module.RIG_COMPONENT_CLASS

        module_infos.append((component_class.ui_name, rig_file_name))

    module_infos.sort(key=lambda t: t[0])
    for ui_name, file_name in module_infos:
        type_info = prefs.component_types.add()
        type_info.name = ui_name
        type_info.module_name = file_name


class CloudRigComponentTypeInfo(PropertyGroup):
    """Purely for UI purposes, so we can store a list of strings in the RNA that
    represent the list of available rig types. We need that in the RNA so we can use
    prop_search() to draw a nice list that the user can type into to filter and search.
    """

    name: StringProperty(
        name="UI Name",
        description="Pretty, title-case name that will be displayed in the UI",
    )
    module_name: StringProperty(
        name="Rig Module Name",
        description="Name used under the hood for matching the component type to its implementation module (ie. Python file)",
    )


class CloudRigPreferences(PrefsFileSaveLoadMixin, AddonPreferences):
    bl_idname = str(__package__)

    # This should get a version bump whenever there is a change that affects metarigs.
    # For example, changing names of component types, splitting an old component type into multiple,
    # changing names of parameters, etc.
    cloud_metarig_version = 9

    # List of property names to not write to disk.
    omit_from_disk: list[str] = ["component_types", "widget_names"]

    component_types: CollectionProperty(type=CloudRigComponentTypeInfo)

    def on_library_set(self, context):
        refresh_widget_list(force_external=True)

    widget_names: CollectionProperty(type=NameProperty)

    advanced_mode: BoolProperty(
        name="Advanced Mode",
        description="Reveal advanced options in the Generator and Rig Component interfaces",
        default=False,
        update=update_prefs_on_file,
    )
    bone_set_show_advanced: BoolProperty(
        name="Show Internal Bone Sets",
        description="Reveal bone sets that are marked as internal, ie. mechanism bones. You would customize these much less frequently than the controls, which are exposed to animators",
        default=False,
        update=update_prefs_on_file,
    )

    widget_library: StringProperty(
        name="Custom Shape Library .blend",
        default="",
        subtype='FILE_PATH',
        description="Path to your custom shapes library .blend file. This should contain objects prefixed 'WGT-' to show up in CloudRig's various widget selection UI elements, in addition to the built-in set of widgets",
        update=on_library_set,
    )
    widget_popup_size: FloatProperty(
        name="Custom Shape Pop-up Size",
        default=2.0,
        min=1.0,
        max=6.0,
        precision=1,
        step=50,
        description="Size of the custom shape icon selector pop-ups",
    )
    widget_import_method: EnumProperty(
        name="Custom Shape Import Method",
        items=[('LINK', 'Link', 'Link'), ('APPEND', 'Append', 'Append')],
        default='APPEND',
        description="Whether custom shapes should be linked or appended",
        update=update_prefs_on_file,
    )

    overlay_mode: EnumProperty(
        name="Overlay Mode",
        description="Which components should have rig preview rendered. May affect performance when transforming metarig bones",
        items=[
            ('NONE', "None", "No rig preview. No performance cost"),
            ('ACTIVE', "Active", "Preview active bone's component. Minimal performance impact"),
            ('SELECTED', "Selected", "Preview components of selected bones. Performance impact depends on selection"),
            ('CHILDREN', "Selected + Children", "Preview components of selected bones & their children. Performance impact may be noticable"),
            ('VISIBLE', "Visible", "Preview all visible bones' components. Maximum performance impact"),
        ],
        default='SELECTED',
    )
    overlay_use_dashed: BoolProperty(
        name="Dashed",
        default=True,
        description="Dashed lines for the rig preview. Bit more expensive to draw"
    )
    overlay_opacity: FloatProperty(
        name="Opacity",
        description="Opacity of the overlay.",
        default=0.9,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    overlay_dash_length: FloatProperty(
        name="Dash Length",
        description="Length of the dashes.",
        default=1.0,
        min=0.1,
        max=2.0,
        subtype='FACTOR',
    )

    component_overview_mode: EnumProperty(
        name="Overview Mode",
        description="Parameter view mode",
        items=[
            ('ACTIVE', "Active", "Show parameters of the component that the active bone in the 3D View belongs to", 'BONE_DATA', 0),
            ('LIST', "List", "Show a list of all components on this rig, so you don't have to select bones in the 3D View", 'COLLAPSEMENU', 1),
        ],
        default='ACTIVE',
    )
    ui_mode: EnumProperty(
        name="Interface Location",
        items=[
            ('PROPERTIES', "Properties Editor", "Only display CloudRig's UI in the Properties Editor"),
            ('HEADER', "3D View Header", "Display CloudRig's UI in the 3D View's header, next to the Shading pop-over"),
            ('BOTH', "Both", "Display CloudRig's UI in both places"),
        ],
        default='BOTH',
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        main_col = layout.column()
        main_col.operator('wm.cloudrig_report_bug', icon='URL')

        main_col.row(align=True).prop(self, 'ui_mode', expand=True)

        header, panel = layout.panel("CloudRig Custom Shapes")
        header.label(text="Custom Shapes")
        if panel:
            lib_row = panel.row(align=True)
            if self.widget_library and not os.path.exists(self.widget_library):
                lib_row.alert = True
            lib_row.prop(self, 'widget_library', placeholder="A .blend containing objects prefixed 'WGT-'", text="Additional Custom Shapes")
            panel.row(align=True).prop(self, 'widget_import_method', expand=True, text="Import Method")
            panel.row(align=True).prop(self, 'widget_popup_size', text="UI Pop-up Size")

        header, panel = layout.panel("CloudRig Hotkeys")
        header.label(text="Hotkeys")
        if panel:
            panel.operator('window.restore_deleted_hotkeys', icon='BACK')
            draw_hotkey_list(context, panel, sort_mode='BY_OPERATOR')

        draw_bone_color_presets(layout)


registry = [
    CloudRigComponentTypeInfo,
    CloudRigPreferences
]


def register():
    init_component_module_list()
    CloudRigPreferences.register_autoload_from_file()
