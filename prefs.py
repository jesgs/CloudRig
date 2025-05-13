# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, json, os
from bpy.types import PropertyGroup, AddonPreferences
from bpy.props import StringProperty, CollectionProperty, BoolProperty, EnumProperty

from pathlib import Path

from . import rig_components
from .generation import cloudrig
from .utils.misc import get_addon_prefs

from . import __package__ as base_package

def update_prefs_on_file(self=None, context=None):
    prefs = get_addon_prefs(context)
    if prefs:
        if not type(prefs).loading:
            prefs.save_prefs_to_file()
    else:
        print("Couldn't save preferences because the class was already unregistered.")


class PrefsFileSaveLoadMixin:
    """Mix-in class that can be used by any add-on to store their preferences in a file,
    so that they don't get lost when the add-on is disabled.
    To use it, copy this class and the two functions above it, and do this in your code:

    ```
    import bpy, json
    from pathlib import Path

    class MyAddonPrefs(PrefsFileSaveLoadMixin, bpy.types.AddonPreferences):
        some_prop: bpy.props.IntProperty(update=update_prefs_on_file)

    def register():
        bpy.utils.register_class(MyAddonPrefs)
        MyAddonPrefs.register_autoload_from_file()

    def unregister():
        update_prefs_on_file()
    ```

    """

    # List of property names to not write to disk.
    omit_from_disk: list[str] = []

    loading = False

    @staticmethod
    def register_autoload_from_file(delay=0.5):
        def timer_func(_scene=None):
            prefs = get_addon_prefs()
            prefs.load_prefs_from_file()
        bpy.app.timers.register(timer_func, first_interval=delay)

    def prefs_to_dict_recursive(self, propgroup: 'IDPropertyGroup') -> dict:
        """Recursively convert AddonPreferences to a dictionary.
        Note that AddonPreferences don't support PointerProperties,
        so this function doesn't either."""
        from rna_prop_ui import IDPropertyGroup

        ret = {}

        if hasattr(propgroup, 'bl_rna'):
            rna_class = propgroup.bl_rna
        else:
            property_group_class_name = type(propgroup).__name__
            rna_class = bpy.types.PropertyGroup.bl_rna_get_subclass_py(
                property_group_class_name
            )

        for key, value in propgroup.items():
            if key in type(self).omit_from_disk:
                continue
            if type(value) == list:
                ret[key] = [self.prefs_to_dict_recursive(elem) for elem in value]
            elif type(value) == IDPropertyGroup:
                ret[key] = self.prefs_to_dict_recursive(value)
            else:
                if (
                    rna_class
                    and key in rna_class.properties
                    and hasattr(rna_class.properties[key], 'enum_items')
                ):
                    # Save enum values as string, not int.
                    ret[key] = rna_class.properties[key].enum_items[value].identifier
                else:
                    ret[key] = value
        return ret

    def apply_prefs_from_dict_recursive(self, propgroup, data):
        for key, value in data.items():
            if not hasattr(propgroup, key):
                # Property got removed or renamed in the implementation.
                continue
            if type(value) == list:
                for elem in value:
                    collprop = getattr(propgroup, key)
                    entry = collprop.get(elem['name'])
                    if not entry:
                        entry = collprop.add()
                    self.apply_prefs_from_dict_recursive(entry, elem)
            elif type(value) == dict:
                self.apply_prefs_from_dict_recursive(getattr(propgroup, key), value)
            else:
                setattr(propgroup, key, value)

    @staticmethod
    def get_prefs_filepath() -> Path:
        addon_name = __package__.split(".")[-1]
        return Path(bpy.utils.user_resource('CONFIG')) / Path(addon_name + ".json")

    def save_prefs_to_file(self, _context=None):
        data_dict = self.prefs_to_dict_recursive(propgroup=self)

        filepath = self.get_prefs_filepath()

        with open(filepath, "w") as f:
            json.dump(data_dict, f, indent=4)

    def load_prefs_from_file(self) -> bool:
        filepath = self.get_prefs_filepath()
        if not filepath.exists():
            return False

        with open(filepath, "r") as f:
            addon_data = json.load(f)
            self.apply_prefs_from_dict_recursive(self, addon_data)


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
    cloud_metarig_version = 2

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
        name="Widget Library",
        default=get_default_widgets_path(),
        subtype='FILE_PATH',
        description="Path to the widgets library .blend file. If invalid, you can press Backspace while mouse-hovering over this field to reset it to the default path",
        update=update_prefs_on_file,
    )
    widget_import_method: EnumProperty(
        name="Import Method",
        items=[('LINK', 'Link', 'Link'), ('APPEND', 'Append', 'Append')],
        default='APPEND',
        description="Whether widget objects should be linked or appended",
        update=update_prefs_on_file,
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

        hotkey_col = draw_fake_dropdown(main_col, self, 'show_hotkeys', "Hotkeys")
        if self.show_hotkeys:
            bpy.types.CLOUDRIG_PT_hotkeys_panel.draw_all_hotkeys(hotkey_col, context)

        main_col.separator()

        preset_col = draw_fake_dropdown(
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

    def prefs_to_dict_recursive(self, propgroup: 'IDPropertyGroup') -> dict:
        data = super().prefs_to_dict_recursive(self)
        data['hotkeys'] = get_keymap_data_for_saving(bpy.context)
        return data


def get_cloudrig_addon_kmis(context):
    keymap_data = list(bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.values())
    keymap_data += list(bpy.types.POSE_PT_CloudRig.cloudrig_keymap_items.values())
    keymap_data = sorted(keymap_data, key=lambda tup: tup[1].name + tup[2].idname)
    return keymap_data


def get_keymap_data_for_saving(context) -> dict:
    all_keymap_data = []
    for addon_kc, addon_km, addon_kmi in get_cloudrig_addon_kmis(context):
        user_km, user_kmi = cloudrig.find_user_kmi(context, addon_km, addon_kmi)
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

        all_keymap_data.append(data)

    return all_keymap_data


def draw_fake_dropdown(layout, prop_owner, prop_name, dropdown_text):
    row = layout.row(align=True)
    row.use_property_split = False
    prop_value = prop_owner.path_resolve(prop_name)
    icon = 'TRIA_DOWN' if prop_value else 'TRIA_RIGHT'
    sub = row.row(align=True)
    sub.alignment='LEFT'
    sub.prop(prop_owner, prop_name, icon=icon, emboss=False, text=dropdown_text)
    sub = row.row(align=True)
    sub.alignment='LEFT'
    sub.scale_x = 100
    sub.prop(prop_owner, prop_name, icon='BLANK1', emboss=False, text="")
    dropdown_col = layout.column()

    return dropdown_col


registry = [CloudRigComponentTypeInfo, CloudRigPreferences]


def register():
    init_component_module_list()
    CloudRigPreferences.register_autoload_from_file()
