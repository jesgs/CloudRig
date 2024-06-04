from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty
import bpy
import os

from . import rig_components
from .generation import cloudrig


def get_default_widgets_path():
    filedir = os.path.dirname(os.path.realpath(__file__))
    blend_path = os.sep.join(
        filedir.split(os.sep) + ['rig_component_features', 'widgets', 'Widgets.blend']
    )
    return blend_path


def init_component_module_list(context=None):
    if not context:
        context = bpy.context
    prefs = context.preferences.addons[__package__].preferences
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
        description="Reveal the hotkey list. You may customize or disable these hotkeys"
    )
    show_widget_prefs: BoolProperty(
        name="Show Widget Preferences",
        default=False,
        description="Reveal the hotkey list. You may customize or disable these hotkeys"
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

        icon = 'TRIA_DOWN' if self.show_hotkeys else 'TRIA_RIGHT'
        main_col.label(text=str(context.area.width))
        width = context.area.width
        row = main_col.row()
        split = row.split(factor=0.12)
        split.use_property_split=False
        split.prop(self, 'show_hotkeys', icon=icon, emboss=False, text="Hotkeys")
        split.prop(self, 'show_hotkeys', icon='BLANK1', emboss=False, text="")
        split = main_col.split(factor=0.012)
        split.row()
        hotkey_row = split.row()
        hotkey_col = hotkey_row.column()
        row = hotkey_col.row()
        row.use_property_split=False
        if self.show_hotkeys:
            cloudrig.CLOUDRIG_PT_hotkeys_panel.draw_hotkey_list(hotkey_col, context)



registry = [CloudRigComponentTypeInfo, CloudRigPreferences]


def register():
    init_component_module_list()
