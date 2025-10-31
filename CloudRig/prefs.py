# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, os
from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty

from . import rig_components
from .properties import NameProperty
from .rig_component_features.widgets.widgets import get_widgets_enum_items
from .bs_utils.prefs import PrefsFileSaveLoadMixin, update_prefs_on_file, get_addon_prefs
from .bs_utils.hotkeys import HotkeyDrawMixin

def get_default_widgets_path():
    filedir = os.path.dirname(os.path.realpath(__file__))
    blend_path = os.sep.join(
        filedir.split(os.sep) + ['rig_component_features', 'widgets', 'Widgets.blend']
    )
    return blend_path


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


class CloudRigPreferences(PrefsFileSaveLoadMixin, HotkeyDrawMixin, AddonPreferences):
    bl_idname = __package__

    # This should get a version bump whenever there is a change that affects metarigs.
    # For example, changing names of component types, splitting an old component type into multiple,
    # changing names of parameters, etc.
    cloud_metarig_version = 4

    # List of property names to not write to disk.
    omit_from_disk: list[str] = ["component_types"]

    # Function that returns a list of CloudRig add-on KeyMapItems
    component_types: CollectionProperty(type=CloudRigComponentTypeInfo)

    def update_widget_names(self, context):
        self.widget_names.clear()
        widget_items = get_widgets_enum_items()
        if not widget_items:
            return
        for identifier, name, description in [w for w in widget_items if w]:
            widget_entry = self.widget_names.add()
            widget_entry.name = name
        update_prefs_on_file()

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
        default=get_default_widgets_path(),
        subtype='FILE_PATH',
        description="Path to the custom shapes library .blend file. If invalid, you can press Backspace while mouse-hovering over this field to reset it to the default path",
        update=update_widget_names,
    )
    widget_import_method: EnumProperty(
        name="Custom Shape Import Method",
        items=[('LINK', 'Link', 'Link'), ('APPEND', 'Append', 'Append')],
        default='APPEND',
        description="Whether custom shapes should be linked or appended",
        update=update_widget_names,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        main_col = layout.column(align=True)

        lib_row = main_col.row(align=True)
        if not os.path.exists(self.widget_library):
            lib_row.alert = True
        lib_row.prop(self, 'widget_library')
        main_col.row(align=True).prop(self, 'widget_import_method', expand=True)
        main_col.row(align=True).prop(self, 'advanced_mode')

        layout.operator('wm.cloudrig_report_bug', icon='URL')

        header, panel = layout.panel("CloudRig Hotkeys")
        header.label(text="Hotkeys")
        if panel:
            panel.operator('window.restore_deleted_hotkeys', icon='BACK')
            self.draw_hotkey_list(context, panel, sort_mode='BY_OPERATOR')

        header, panel = layout.panel("CloudRig Bone Colors")
        header.label(text="Bone Colors")
        if panel:
            split = panel.split(factor=0.4)
            row = split.row()
            row.alignment = 'RIGHT'
            row.label(text="Apply Color Presets: ")
            row = split.row()
            row.operator(
                'preferences.set_bone_color_presets',
                text='Blender',
                icon='RESTRICT_COLOR_OFF',
            ).preset = 'BLENDER'
            row.operator(
                'preferences.set_bone_color_presets',
                text='CloudRig',
                icon='RESTRICT_COLOR_ON',
            ).preset = 'CLOUDRIG'
            preview_row = panel.row(align=True)
            split = preview_row.split(factor=0.4)
            split.row()
            row = split.row()
            for i in range(20):
                icon = f"COLORSET_{str(i+1).zfill(2)}_VEC"
                row.label(text="", icon=icon)


registry = [CloudRigComponentTypeInfo, CloudRigPreferences]


def delayed_refresh_widget_list():
    prefs = get_addon_prefs()
    prefs.update_widget_names(bpy.context)


def register():
    init_component_module_list()
    # NOTE: Updating widget list will result in saving preferences, so this should have a GREATER delay
    # than the initial loading of the preferences.
    bpy.app.timers.register(delayed_refresh_widget_list, first_interval=2.0)
    CloudRigPreferences.register_autoload_from_file()
