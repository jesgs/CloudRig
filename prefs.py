# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, json, os
from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty

from pathlib import Path

from . import rig_components
from .generation import cloudrig
from .utils.misc import get_addon_prefs
from .utils.hotkeys import find_matching_km_and_kmi
from .generation.cloudrig import find_user_kmi
from .prefs_save_load import PrefsFileSaveLoadMixin, load_prefs_from_file, update_prefs_on_file


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


class CloudRigPreferences(PrefsFileSaveLoadMixin, AddonPreferences):
    bl_idname = __package__

    # This should get a version bump whenever there is a change that affects metarigs.
    # For example, changing names of rig types, splitting an old rig type into multiple,
    # changing names of parameters, etc.
    cloud_metarig_version = 3

    # List of property names to not write to disk.
    omit_from_disk: list[str] = ["component_types"]

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
        name="Widget Library Blend",
        default=get_default_widgets_path(),
        subtype='FILE_PATH',
        description="Path to the widgets library .blend file. If invalid, you can press Backspace while mouse-hovering over this field to reset it to the default path",
        update=update_prefs_on_file,
    )
    widget_import_method: EnumProperty(
        name="Widget Import Method",
        items=[('LINK', 'Link', 'Link'), ('APPEND', 'Append', 'Append')],
        default='APPEND',
        description="Whether widget objects should be linked or appended",
        update=update_prefs_on_file,
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
            bpy.types.CLOUDRIG_PT_hotkeys_panel.draw_all_hotkeys(panel, context)

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

    def prefs_to_dict_recursive(self, propgroup: 'IDPropertyGroup') -> dict:
        data = super().prefs_to_dict_recursive(self)
        data['hotkeys'] = get_keymap_data_for_saving(bpy.context)
        return data


from .generation.cloudrig import find_user_kmi
from .utils.hotkeys import find_matching_km_and_kmi
def apply_stored_hotkeys():
    for storage_class in (bpy.types.CLOUDRIG_PT_hotkeys_panel, bpy.types.POSE_PT_CloudRig):
        for kmi_hash, (kc_addon, addon_km, addon_kmi) in storage_class.cloudrig_keymap_items.items():
            if bpy.app.version < (4, 5, 0):
                user_km, user_kmi = find_user_kmi(bpy.context, addon_km, addon_kmi, kmi_hash)
            else:
                kc_user = bpy.context.window_manager.keyconfigs.user
                user_km, user_kmi = find_matching_km_and_kmi(bpy.context, kc_user, addon_km, addon_kmi)

            hotkey_user_data = get_hotkey_on_file(kmi_hash)
            if hotkey_user_data and user_kmi:
                op_kwargs = hotkey_user_data['op_kwargs']
                key_kwargs = hotkey_user_data['key_kwargs']

                for key, value in key_kwargs.items():
                    if bpy.app.version < (4, 5, 0) and key == 'hyper':
                        continue
                    cur_value = getattr(user_kmi, key)
                    if cur_value != value:
                        setattr(user_kmi, key, value)

                for key, value in op_kwargs.items():
                    cur_value = getattr(user_kmi.properties, key)
                    if cur_value != value:
                        setattr(user_kmi.properties, key, value)
            elif not hotkey_user_data:
                print("No hotkey user data for ", user_kmi.to_string(), kmi_hash)
            elif not user_kmi:
                print("No user_kmi for ", hotkey_user_data['operator'], kmi_hash)


def get_hotkey_on_file(kmi_hash) -> dict:
    data = load_prefs_from_file()
    if not data:
        return {}
    hotkeys = data.get('hotkeys')
    if hotkeys:
        return hotkeys.get(kmi_hash, {})
    return {}


def get_keymap_data_for_saving(context) -> dict:
    all_keymap_data = {}
    for kmi_hash, (addon_kc, addon_km, addon_kmi) in get_cloudrig_addon_kmis(context):
        user_km, user_kmi = find_user_kmi(context, addon_km, addon_kmi, kmi_hash)
        if not user_km or not user_kmi:
            continue
        data = {}
        data['keymap'] = user_km.name
        data['operator'] = user_kmi.idname

        NO_SAVE_OP_KWARGS = ()

        op_kwargs = {}
        if user_kmi.properties:
            op_kwargs = {
                key: getattr(user_kmi.properties, key)
                for key in user_kmi.properties.keys()
                if hasattr(user_kmi.properties, key) and key not in NO_SAVE_OP_KWARGS
            }

        data['op_kwargs'] = op_kwargs

        data['key_kwargs'] = {
            'type' : user_kmi.type,
            'value' : user_kmi.value,
            'ctrl' : bool(user_kmi.ctrl),
            'shift' : bool(user_kmi.shift),
            'alt' : bool(user_kmi.alt),
            'any' : bool(user_kmi.any),
            'oskey' : bool(user_kmi.oskey),
            'key_modifier' : user_kmi.key_modifier,
            'active' : user_kmi.active
        }
        if bpy.app.version >= (4, 5, 0):
            data['key_kwargs']['hyper'] = bool(user_kmi.hyper)

        all_keymap_data[kmi_hash] = data
    return all_keymap_data


def get_cloudrig_addon_kmis(context):
    keymap_data = list(bpy.types.POSE_PT_CloudRig.cloudrig_keymap_items.items())
    keymap_data += list(bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.items())
    keymap_data = sorted(keymap_data, key=lambda tup: tup[1][1].name + tup[1][2].idname)
    return keymap_data


registry = [CloudRigComponentTypeInfo, CloudRigPreferences]


def register():
    init_component_module_list()
    CloudRigPreferences.register_autoload_from_file()
