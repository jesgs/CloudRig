from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty
import os

from . import rig_components
from .generation import cloudrig
from .utils.misc import get_addon_prefs

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
    for rig_file_name, rigcomp_module in rig_components.component_modules.items():
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


class CloudRigPreferences(AddonPreferences):
    bl_idname = __package__

    # This should get a version bump whenever there is a change that affects metarigs.
    # For example, changing names of rig types, splitting an old rig type into multiple,
    # changing names of parameters, etc.
    cloud_metarig_version = 2

    component_types: CollectionProperty(type=CloudRigComponentTypeInfo)

    advanced_mode: BoolProperty(
        name="Advanced Mode",
        description="Reveal advanced options in the Generator and Rig Component interfaces",
        default=False,
    )
    bone_set_show_advanced: BoolProperty(
        name="Show Internal Bone Sets",
        description="Reveal bone sets that are marked as internal, ie. mechanism bones. You would customize these much less frequently than the controls, which are exposed to animators",
        default=False,
    )

    widget_library: StringProperty(
        name="Widget Library",
        default=get_default_widgets_path(),
        subtype='FILE_PATH',
        description="Path to the widgets library .blend file. If invalid, you can press Backspace while mouse-hovering over this field to reset it to the default path",
    )
    widget_import_method: EnumProperty(
        name="Import Method",
        items=[('LINK', 'Link', 'Link'), ('APPEND', 'Append', 'Append')],
        default='APPEND',
        description="Whether widget objects should be linked or appended",
    )

    show_hotkeys: BoolProperty(
        name="Show Hotkeys",
        default=False,
        description="Reveal the hotkey list. You may customize or disable these hotkeys",
    )
    show_widget_prefs: BoolProperty(
        name="Show Widget Preferences",
        default=False,
        description="Reveal the hotkey list. You may customize or disable these hotkeys",
    )
    show_color_presets: BoolProperty(
        name="Show Color Presets",
        default=False,
        description="Reveal the color preset operators",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        main_col = layout.column(align=True)
        main_col.row(align=True).prop(self, 'advanced_mode')
        main_col.separator()

        lib_row = main_col.row(align=True)
        if not os.path.exists(self.widget_library):
            lib_row.alert = True
        lib_row.prop(self, 'widget_library')
        main_col.row(align=True).prop(self, 'widget_import_method', expand=True)
        main_col.separator()

        hotkey_col = self.draw_fake_dropdown(main_col, self, 'show_hotkeys', "Hotkeys")
        if self.show_hotkeys:
            cloudrig.CLOUDRIG_PT_hotkeys_panel.draw_hotkey_list(hotkey_col, context)

        preset_col = self.draw_fake_dropdown(
            main_col, self, 'show_color_presets', "Bone Colors"
        )
        if self.show_color_presets:
            split = preset_col.split(factor=0.4)
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
            preview_row = preset_col.row(align=True)
            split = preview_row.split(factor=0.4)
            split.row()
            row = split.row()
            for i in range(20):
                icon = f"COLORSET_{str(i+1).zfill(2)}_VEC"
                row.label(text="", icon=icon)

    def draw_fake_dropdown(self, layout, prop_owner, prop_name, dropdown_text):
        row = layout.row()
        split = row.split(factor=0.20)
        split.use_property_split = False
        prop_value = prop_owner.path_resolve(prop_name)
        icon = 'TRIA_DOWN' if prop_value else 'TRIA_RIGHT'
        split.prop(prop_owner, prop_name, icon=icon, emboss=False, text=dropdown_text)
        split.prop(prop_owner, prop_name, icon='BLANK1', emboss=False, text="")
        split = layout.split(factor=0.012)
        split.row()
        dropdown_row = split.row()
        dropdown_col = dropdown_row.column()
        row = dropdown_col.row()
        row.use_property_split = False

        return dropdown_col


registry = [CloudRigComponentTypeInfo, CloudRigPreferences]


def register():
    init_component_module_list()
