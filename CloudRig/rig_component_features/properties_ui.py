# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, json, sys, os
from bpy.types import (
    Operator,
    ID,
    bpy_struct,
    PoseBone,
    Bone,
    UILayout,
    PropertyGroup,
    BoneCollection,
    Modifier,
)
from typing import Any
from bpy.props import StringProperty, BoolProperty, CollectionProperty, IntProperty
from collections import OrderedDict
from ..generation.cloudrig import (
    unquote_custom_prop_name,
    feed_op_props,
    draw_property,
    read_rig_panels,
    get_rig_and_ui,
    write_rig_panels,
    find_cloudrig,
)
from rna_prop_ui import rna_idprop_ui_create, rna_idprop_value_item_type


def get_data_paths(self, obj) -> tuple[ID, str, str, str, Any]:
    data_path = self.owner_path
    prop_name = self.prop_name

    # In case a data path wasn't provided, the default property owner is the object itself.
    prop_owner = obj

    if data_path and self.use_bone_selector:
        # If user wants to use the bone search selector,
        # we need to help them get the data path to the selected pose bone.
        data_path = f'pose.bones["{data_path}"]'
    elif data_path and self.use_coll_selector:
        data_path = f'data.collections_all["{data_path}"]'

    if data_path:
        prop_owner = path_resolve_safe(obj, data_path)

    if not prop_owner:
        # If a nonsense data path was provided, return empty values.
        return None, "", data_path, prop_name, None

    prop_value = None
    dot = ""
    # Let's figure out if the user wants to specify a custom property or a regular one.
    if prop_name:
        try:
            # If it evaluates with a dot without error, then we keep the dot!
            # We don't want to use the safe path resolve here, we need the error.
            if data_path:
                path_to_resolve = data_path + "." + prop_name
                dot = "."
            else:
                path_to_resolve = prop_name
            prop_value = obj.path_resolve(path_to_resolve)
        except ValueError:
            # If we fail to evaluate to a value with the `.`, use custom property syntax instead.
            prop_name = f'["{prop_name}"]'
            dot = ""

    full_path = data_path + dot + prop_name
    if not prop_value:
        # If we didn't get the property value yet, grab it.
        # Can be useful to re-assure the user that we have the property they intend.
        prop_value = path_resolve_safe(obj, full_path)

    return prop_owner, full_path, data_path, prop_name, prop_value


def update_property_selector(self, context):
    rig = find_cloudrig(context)

    context.scene.cloudrig_property_name_selector.clear()

    prop_owner, full_path, owner_path, brackets_prop_name, prop_value = (
        get_data_paths(self, rig)
    )

    # Populate the property drop-down selector with available custom properties.
    for key in get_drawable_custom_properties(prop_owner):
        name_entry = context.scene.cloudrig_property_name_selector.add()
        name_entry.name = key

    # Also add built-in properties.
    # NOTE: User can mask a built-in property with a custom property. That's on them!
    for key in get_drawable_builtin_properties(prop_owner):
        name_entry = context.scene.cloudrig_property_name_selector.add()
        name_entry.name = key


class CloudRigUIEditOpMixin:
    """Add a property to the rig UI. It can be a built-in property or a custom property. If it doesn't exist, it will be created if possible. It can also have an operator next to it"""

    def update_use_bone_selector(self, context):
        if self.use_bone_selector:
            # If the use_bone_selector was just turned on, extract the bone name from the data path.
            self.use_coll_selector = False
            if self.owner_path.startswith("pose.bones"):
                self.owner_path = self.owner_path.split('["')[1].split('"]')[0]
            else:
                self.owner_path = ""
        elif self.owner_path != '' and not self.use_coll_selector:
            # If the use_bone_selector was just turned off, turn the bone name into a data path.
            self.owner_path = f'pose.bones["{self.owner_path}"]'

    def update_use_coll_selector(self, context):
        if self.use_coll_selector:
            # If the use_coll_selector was just turned on, extract the collection name from the data path.
            self.use_bone_selector = False
            if self.owner_path.startswith("data.collections_all"):
                self.owner_path = self.owner_path.split('["')[1].split('"]')[0]
            else:
                self.owner_path = ""
        elif self.owner_path != '' and not self.use_bone_selector:
            # If the use_coll_selector was just turned off, turn the bone name into a data path.
            self.owner_path = f'data.collections_all["{self.owner_path}"]'

    def update_owner_path(self, context):
        update_property_selector(self, context)

        rig = find_cloudrig(context)
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = (
            get_data_paths(self, rig)
        )

        # Help initialize BoneCollection visibility toggles.
        if type(prop_owner) == BoneCollection:
            if self.prop_name == "":
                self.prop_name = "is_visible"
            if self.slider_name == "":
                self.slider_name = prop_owner.name

    def update_parent_selector(self, context):
        parent_option = context.scene.cloudrig_property_parent_selector.get(
            self.parent_selector
        )
        if parent_option and parent_option.current not in self.parent_value:
            # When user selects a parent property from the drop-down,
            # we want to make life easy by setting the parent value to the current value of the chosen property.
            # But don't do this if the current parent value is `1, 2, 3` and the actual value is eg. 2.
            self.parent_value = parent_option.current

    # We need a separate init_owner_path where UI code can feed us an owner path without triggering the update callback.
    init_owner_path: StringProperty(
        name="Data Path",
        description="Python data path from the rig to the owner of the property. Can be left empty to look for a property directly on the rig object itself",
    )
    owner_path: StringProperty(
        name="Data Path",
        update=update_owner_path,
        description="Python data path from the rig to the owner of the property. Can be left empty to look for a property directly on the rig object itself",
    )
    use_coll_selector: BoolProperty(
        name="Use Collection Selector",
        options={'SKIP_SAVE'},
        description="Display a collection selector. If disabled, you can manually type in a data path",
        default=False,
        update=update_use_coll_selector,
    )
    use_bone_selector: BoolProperty(
        name="Use Bone Selector",
        options={'SKIP_SAVE'},
        description="Display a bone selector. If disabled, you can manually type in a data path",
        default=False,
        update=update_use_bone_selector,
    )
    def update_prop_name(self, context):
        rig = find_cloudrig(context)

        # Help initialize Bone Collection toggles.
        prop_owner, full_path, data_path, prop_name, prop_value = get_data_paths(self, rig)
        if type(prop_owner) == BoneCollection and self.prop_name == 'is_visible':
            if self.icon_true == 'CHECKBOX_HLT':
                self.icon_true = 'HIDE_OFF'
            if self.icon_false == 'CHECKBOX_DEHLT':
                self.icon_false = 'HIDE_ON'
            if self.slider_name in {"", "is_visible"}:
                self.slider_name = prop_owner.name
            if self.panel_name == "Properties":
                self.panel_name = "Bone Collections"

    prop_name: StringProperty(
        name="Property Name",
        description="Name of the property. It can already exist, otherwise it will be created with a value of 1.0",
        update=update_prop_name
    )
    use_manual_prop_name: BoolProperty(
        name="Custom Property",
        default=False,
        description="Enter any custom property name instead of searching existing ones. If it doesn't exist, it will be created",
    )

    panel_name: StringProperty(
        name="Subpanel",
        default="Properties",
        description="Optional: The sub-panel that this property should be displayed in",
    )
    label_name: StringProperty(
        name="Label", description="Optional: Place this property under a text label"
    )
    row_name: StringProperty(
        name="Row ID",
        default="",
        options={'SKIP_SAVE'},
        description="Optional: If two sliders share the same Row ID, they will be drawn in the same row. However, the Row ID itself is not shown in the interface",
    )
    slider_name: StringProperty(
        name="Display Name",
        default="",
        options={'SKIP_SAVE'},
        description="Optional: Override the display text of the property",
    )
    texts: StringProperty(
        name="Value Names",
        options={'SKIP_SAVE'},
        description="Optional: Comma-separated list of strings to display based on the property value. The first string is displayed when the value is 0, and so on",
    )
    use_batch_add: BoolProperty(
        name="Batch Add",
        options={'SKIP_SAVE'},
        default=False,
        description="Add all custom properties of the selected ID to the UI",
    )

    use_parenting: BoolProperty(
        name="Parenting",
        options={'SKIP_SAVE'},
        description="Instead of putting this property in a sub-panel directly, parent it to another property (int/bool), so it's only visible when that parent property has specific values",
    )
    parent_ui_path: StringProperty(
        name="Parent UI Path",
        options={'SKIP_SAVE'},
        default="[]",
        description="Internal. The UI Path of the selected parent element. Used by the Add Child and Edit operators",
    )
    parent_selector: StringProperty(
        name="Parent Element",
        options={'SKIP_SAVE'},
        update=update_parent_selector,
        description="The child will only be visible when this parent element has a certain value, specified below",
    )
    parent_value: StringProperty(
        name="Parent Value",
        default="1",
        description="Display this child property only when the parent property matches one of these comma-separated values",
    )

    show_internals: BoolProperty(
        name="Internals", default=False, description="Show internal data"
    )

    operator: StringProperty(
        name="Operator ID",
        options={'SKIP_SAVE'},
        description="Internal. Only used by the Edit operator, to initialize the temp KeyMapItem",
    )
    op_kwargs: StringProperty(
        name="Operator Arguments",
        default="{}",
        description="Internal. Only used by the Edit operator, to feed kwargs to the temp KeyMapItem",
    )
    op_icon: StringProperty(
        name="Operator Icon", default='BLANK1', description="Operator Icon"
    )
    icon_true: StringProperty(
        name="True Icon",
        default='CHECKBOX_HLT',
        description="Property icon when value is True",
    )
    icon_false: StringProperty(
        name="False Icon",
        default='CHECKBOX_DEHLT',
        description="Property icon when value is False",
    )
    use_expand_enum: BoolProperty(
        name="Expand Enum",
        default=False,
        description="Whether enum should be expanded in the UI",
    )
    use_slider: BoolProperty(
        name="Draw As Slider",
        default=True,
        description="Whether int/float should be drawn as a slider",
    )

    children: StringProperty(
        name="UI Children",
        options={'SKIP_SAVE'},
        default="{}",
        description="Internal. Only used by the Edit operator, to preserve children",
    )

    @classmethod
    def poll(cls, context):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            cls.poll_message_set("No active CloudRig found in this context.")
            return False
        return True

    def invoke(self, context, _event):
        # We create a keymap item to help us draw the operator set-up UI.
        # KeymapItems in the default keymap will not be stored by Blender,
        # so we don't need to worry about making a mess there.
        rig, ui_data = get_rig_and_ui(context)
        self.panels = ui_data
        self.temp_kmi = context.window_manager.keyconfigs.default.keymaps[
            'Info'
        ].keymap_items.new('', 'NUMPAD_5', 'PRESS')
        if self.operator:
            self.temp_kmi.idname = self.operator
            if self.op_kwargs:
                op_props = self.temp_kmi.properties
                feed_op_props(op_props, self.op_kwargs)
        owner_path = self.init_owner_path or self.owner_path
        self.owner_path = owner_path

        if owner_path.startswith('pose.bones') or owner_path.startswith('data.collections_all'):
            prop_owner, full_path, data_path, prop_name, prop_value = get_data_paths(
                self, rig
            )
            if prop_owner and type(prop_owner) in (PoseBone, BoneCollection):
                owner_path = prop_owner.name

        if owner_path == "" or owner_path in rig.pose.bones:
            self.use_bone_selector = True
        elif owner_path in rig.data.collections_all:
            self.use_coll_selector = True

        self.use_parenting = self.parent_ui_path != "[]"
        self.update_property_parent_selector(context)

        if self.parent_ui_path != '[]':
            for entry in context.scene.cloudrig_property_parent_selector:
                if entry.ui_path == self.parent_ui_path:
                    self.parent_selector = entry.name

        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        layout = self.layout.column()

        if not self.draw_owner_box(layout, context):
            return
        error = self.draw_prop_box(layout, context)
        if error:
            return
        self.draw_placement_box(layout, context)
        layout.separator()

        self.draw_op_box(layout, context)
        layout.separator()

        # self.draw_debug_box(layout, context)

    def draw_owner_box(self, layout, context) -> bool:
        """Returns whether a valid property owner is currently specified in the input box."""
        rig = find_cloudrig(context)
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = (
            get_data_paths(self, rig)
        )

        owner_box = layout.box()
        owner_row = owner_box.row(align=True)
        if self.use_bone_selector:
            owner_row.prop_search(
                self, 'owner_path', rig.pose, 'bones', text="Property Bone"
            )
        elif self.use_coll_selector:
            owner_row.prop_search(
                self, 'owner_path', rig.data, 'collections_all', text="Bone Collection"
            )
        else:
            owner_row.prop(self, 'owner_path')
        owner_row.prop(self, 'use_bone_selector', icon='BONE_DATA', text="")
        owner_row.prop(self, 'use_coll_selector', icon='OUTLINER_COLLECTION', text="")

        if self.owner_path and not prop_owner:
            # User tried providing a data path, but it didn't path_resolve() to anything.
            owner_row.alert = True
            alert_row = owner_box.row()
            alert_row.alert = True
            alert_row.label(
                text=f"No property owner at '{self.owner_path}' found.", icon='ERROR'
            )
            return False
        if self.owner_path and not hasattr(prop_owner, 'bl_rna'):
            # User tried providing a full data path to a property in the owner field, 
            # as opposed to a path to a property owner, and then later a property name.
            owner_row.alert = True
            alert_row = owner_box.row()
            alert_row.alert=True
            alert_row.label(text=f'Type "{type(prop_owner).__name__}" cannot have properties.')
            return False

        text = f'{type(prop_owner).__name__}'
        if hasattr(prop_owner, 'name'):
            text += f" ('{prop_owner.name}')"
        else:
            text += str(prop_owner)
        try:
            icon_value = UILayout.icon(prop_owner)
            owner_box.label(text=text, icon_value=icon_value)
        except:
            owner_box.label(text=text, icon='INFO')

        return True

    def draw_prop_box(self, layout, context) -> bool:
        """Returns whether UI drawing should be interrupted after this."""
        rig = find_cloudrig(context)
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = (
            get_data_paths(self, rig)
        )

        prop_box = layout.box().column()
        if not prop_owner:
            prop_box.label(text=f'Data path failed to resolve on {rig.name}.')
            return True

        any_selectable_props = len(context.scene.cloudrig_property_name_selector) > 0
        drawable_props = list(get_drawable_custom_properties(prop_owner))

        prop_row = prop_box.row(align=True)

        if self.use_batch_add:
            prop_row.label(
                text=f"Add all {len(drawable_props)} custom properties to the UI"
            )
            prop_row.prop(self, 'use_batch_add', icon='ALIGN_JUSTIFY', text="")
            return True

        if self.use_manual_prop_name or not any_selectable_props:
            prop_row.prop(self, 'prop_name')
        else:
            prop_row.prop_search(
                self,
                'prop_name',
                context.scene,
                'cloudrig_property_name_selector',
                icon='BLANK1',
            )

        prop_row.prop(self, 'use_manual_prop_name', icon='ADD', text="")

        if drawable_props:
            prop_row.prop(self, 'use_batch_add', icon='ALIGN_JUSTIFY', text="")

        if not self.prop_name:
            # User hasn't typed in a property name yet. Don't overwhelm them with the rest of the UI.
            return True

        prop_settings = None
        if hasattr(prop_owner, 'id_properties_ui'):
            try:
                prop_settings = prop_owner.id_properties_ui(self.prop_name)
            except KeyError:
                pass
            except TypeError:
                # This happens for Python properties.
                pass

            if prop_settings:
                prop_settings = prop_settings.as_dict()

        if prop_value != None or issubclass(type(prop_owner), Modifier) or prop_settings and 'id_type' in prop_settings:
            if (
                prop_value != None
                and isinstance(prop_value, bpy_struct)
                and not isinstance(prop_value, ID)
            ):
                # Checking for prop_value!=None again is deliberate,
                # as modifier inputs are allowed to be None and still be drawn.
                row = prop_box.row()
                row.alert = True
                row.label(text="This is a struct, not a property.", icon='ERROR')
                return True
            else:
                prop_box.label(text=f"Property found.", icon='CHECKMARK')
                draw_property(
                    prop_box.row(),
                    prop_owner,
                    brackets_prop_name,
                    slider_name=self.slider_name,
                    icon_true=self.icon_true,
                    icon_false=self.icon_false,
                    use_expand_enum=self.use_expand_enum,
                    use_slider=self.use_slider,
                    texts=[t.strip() for t in self.texts.split(",")],
                )
        elif hasattr(prop_owner, brackets_prop_name):
            prop_box.prop(prop_owner, brackets_prop_name)
        elif type(prop_owner) in {ID, PoseBone, Bone}:
            prop_box.label(
                text="Property will be created with a value of 1.0.", icon='CHECKMARK'
            )
        else:
            row = prop_box.row()
            row.alert = True
            row.label(text="Property not found: " + brackets_prop_name, icon='ERROR')
            return True

        return False

    def draw_placement_box(self, layout, context):
        rig = find_cloudrig(context)
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = (
            get_data_paths(self, rig)
        )

        panel_box = layout.box().column()
        panel_row = panel_box.row()
        panel_row_left = panel_row.row()
        panel_row_right = panel_row.row()
        panel_row_right.prop(self, 'use_parenting', text="", icon='OUTLINER')
        if self.use_parenting:
            panel_row_left.prop_search(
                self,
                'parent_selector',
                context.scene,
                'cloudrig_property_parent_selector',
                icon='BLANK1',
            )
            # panel_box.label(text=self.parent_selector)
            panel_box.prop(self, 'parent_value')
        else:
            panel_row_left.prop(self, 'panel_name')
        panel_box.prop(self, 'label_name')
        if self.use_batch_add:
            return
        panel_box.prop(self, 'row_name')
        panel_box.prop(self, 'slider_name')
        if type(prop_value) in {bool, int}:
            panel_box.prop(self, 'texts')
        if type(prop_value) == bool:
            icons = UILayout.bl_rna.functions["prop"].parameters["icon"]
            panel_box.prop_search(
                self, 'icon_true', icons, 'enum_items', icon=self.icon_true
            )
            panel_box.prop_search(
                self, 'icon_false', icons, 'enum_items', icon=self.icon_false
            )
        if type(prop_value) in (float, int):
            panel_box.prop(self, 'use_slider')
        if type(prop_value) == str and isinstance(prop_owner.bl_rna.properties.get(brackets_prop_name), bpy.types.EnumProperty):
            panel_box.prop(self, 'use_expand_enum')

    def draw_op_box(self, layout, context):
        if self.use_batch_add:
            return
        op_box = layout.box().column()
        op_box.prop(self.temp_kmi, 'idname', text="Operator")
        self.op_kwargs_dict = {}
        if self.temp_kmi.idname:
            box = None
            op_rna = eval("bpy.ops." + self.temp_kmi.idname).get_rna_type()
            for key, value in op_rna.properties.items():
                if key == 'rna_type':
                    continue
                if not box:
                    box = op_box.box().column(align=True)
                box.prop(self.temp_kmi.properties, key)
                self.op_kwargs_dict[key] = str(getattr(self.temp_kmi.properties, key))
            icons = UILayout.bl_rna.functions["prop"].parameters["icon"]
            op_box.prop_search(self, 'op_icon', icons, 'enum_items', icon=self.op_icon)

    def draw_debug_box(self, layout, context):
        int_box = layout.box().column()
        split = int_box.row().split(factor=0.15, align=True)
        icon = 'TRIA_DOWN' if self.show_internals else 'TRIA_RIGHT'
        split.prop(self, 'show_internals', icon=icon, toggle=False, emboss=False)
        split.prop(
            self, 'show_internals', icon='BLANK1', toggle=False, emboss=False, text=""
        )
        if self.show_internals:
            int_box.prop(self, 'parent_ui_path')
            if hasattr(self, 'ui_path'):
                row = int_box.row()
                row.enabled = False
                row.prop(self, 'ui_path')

    def update_property_parent_selector(self, context):
        rig, ui_data = get_rig_and_ui(context)
        if not rig or not ui_data:
            return
        context.scene.cloudrig_property_parent_selector.clear()

        def add_slider_ui_paths_recursive(
            ui_data: OrderedDict, ui_path: list[str], display_name: str
        ):
            for elem_name, elem_data in ui_data.items():
                new_ui_path = ui_path + [elem_name]
                identifier = json.dumps(new_ui_path)
                if hasattr(self, 'ui_path') and identifier == self.ui_path:
                    # Skip our own child UI elements!
                    return
                new_display_name = display_name or elem_name
                if 'owner_path' in elem_data:
                    # This is a slider, so it is a potential parent, add it to `items`.
                    if elem_name:
                        if 'children' in ui_path and ui_path[-4] == 'children':
                            parent_value = ui_path[-3]
                            new_display_name += f" ({parent_value})"
                        new_display_name += " -> " + elem_name
                    parent_option = (
                        context.scene.cloudrig_property_parent_selector.add()
                    )
                    parent_option.name = new_display_name
                    parent_option.ui_path = identifier
                    parent_option.current = str(
                        path_resolve_safe(
                            rig, elem_data['owner_path'] + elem_data['prop_name']
                        )
                    )

                if type(elem_data) == OrderedDict:
                    add_slider_ui_paths_recursive(
                        elem_data, new_ui_path[:], new_display_name
                    )

        add_slider_ui_paths_recursive(ui_data, ui_path=[], display_name="")

    def execute(self, context):
        rig = find_cloudrig(context)
        owner, full_path, owner_path, brackets_prop_name, prop_value = get_data_paths(
            self, rig
        )

        if self.use_batch_add:
            self.temp_kmi.idname = ""
            self.op_icon = ""
            self.op_kwargs_dict = {}
            self.texts = ""
            for key in get_drawable_custom_properties(owner):
                self.row_name = ""
                self.slider_name = ""
                self.prop_name = key
                ret = self.execute_add_property(context)
                if ret:
                    return ret
            self.report(
                {'INFO'}, f"Added {len(owner.keys())} properties to the rig UI."
            )
        else:
            ret = self.execute_add_property(context)
            if ret:
                return ret
            self.report({'INFO'}, f"Added property {self.slider_name} to the rig UI.")

        redraw_viewport()
        return {'FINISHED'}

    def execute_add_property(self, context):
        if not self.prop_name:
            self.report({'ERROR'}, "You didn't specify a property.")
            return {'CANCELLED'}

        rig = find_cloudrig(context)
        owner, full_path, owner_path, brackets_prop_name, prop_value = get_data_paths(
            self, rig
        )

        if self.prop_name != brackets_prop_name:
            if issubclass(type(owner), ID) or type(owner) in {PoseBone, Bone}:
                # Owner supports custom props.
                if self.prop_name not in owner:
                    # Target is a custom property that doesn't exist yet, so let's create it.
                    ensure_custom_property(owner, self.prop_name)
                # Make the property library overridable.
                owner.property_overridable_library_set(brackets_prop_name, True)
            elif not issubclass(type(owner), Modifier):
                self.report(
                    {'ERROR'}, f'{type(owner)} does not support custom properties.'
                )
                return {'CANCELLED'}

        if not self.slider_name:
            self.slider_name = self.prop_name

        if self.use_parenting:
            parent_option = context.scene.cloudrig_property_parent_selector.get(
                self.parent_selector
            )
            if parent_option:
                ui_path = json.loads(parent_option.ui_path)
            elif self.parent_selector == "" and len(self.parent_ui_path) > 2:
                ui_path = json.loads(self.parent_ui_path)
                self.panel_name = ui_path[0]
                self.label_name = ui_path[1]
                ui_path = []
            else:
                ui_path = json.loads(self.parent_ui_path)
        else:
            # If the parent selector is toggled off, the UI path can be left empty, as only the panel_name will be used.
            ui_path = []

        add_property_to_ui(
            obj=rig,
            owner_path=owner_path,
            prop_name=brackets_prop_name,
            ###
            panel_name=self.panel_name,
            label_name=self.label_name,
            row_name=self.row_name,
            slider_name=self.slider_name,
            texts=[t.strip() for t in self.texts.split(",")],
            icon_true=self.icon_true,
            icon_false=self.icon_false,
            use_expand_enum=self.use_expand_enum,
            use_slider=self.use_slider,
            ###
            children=json.loads(self.children),
            ui_path=ui_path,
            parent_value=self.parent_value,
            ###
            operator=self.temp_kmi.idname,
            op_icon=self.op_icon,
            op_kwargs=self.op_kwargs_dict,
            ###
            panels=self.panels,
        )

        if 'cloudrig_property_parent_selector' in context.scene:
            del context.scene['cloudrig_property_parent_selector']
        if 'cloudrig_property_name_selector' in context.scene:
            del context.scene['cloudrig_property_name_selector']


class CLOUDRIG_OT_add_property_to_ui(CloudRigUIEditOpMixin, Operator):
    """Add a property to the rig UI. It can be a built-in property or a custom property. If it doesn't exist, it will be created if possible. It can also have an operator next to it"""

    bl_idname = "pose.cloudrig_add_property_to_ui"
    bl_label = "Add Property to UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}


class CLOUDRIG_OT_add_child_property_to_ui(CloudRigUIEditOpMixin, Operator):
    """Add a child property to the rig UI"""

    bl_idname = "pose.cloudrig_add_child_property_to_ui"
    bl_label = "Add Child Property to UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}


class CLOUDRIG_OT_edit_property_in_ui(CloudRigUIEditOpMixin, Operator):
    """Edit how a property is displayed in the UI"""

    bl_idname = "pose.cloudrig_edit_property_in_ui"
    bl_label = "Edit Property in UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(
        name="UI Path",
        default="",
        description="Internal. List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the slider name",
    )

    def execute(self, context):
        rig = find_cloudrig(context)
        ui_path = json.loads(self.ui_path)

        _ui_data, parents, index = remove_property_from_ui(
            rig, ui_path=ui_path, panels=self.panels
        )

        if parents:
            parent, parent_name, child_name = parents.pop()
            ui_elem = parent[child_name]
            count = len(list(ui_elem.keys()))

        super().execute_add_property(context)

        if parents:
            ui_elem = parent[child_name]
            new_count = len(list(ui_elem.keys()))

            if new_count == count + 1:
                # When the UI element was added to the same parent element that it was in before,
                # let's preserve its vertical position.
                ordereddict_move_to_index(ui_elem, new_count - 1, index)

        write_rig_panels(rig, self.panels)
        redraw_viewport()

        self.report({'INFO'}, f"Edited property {ui_path[-1]} to the rig UI.")
        return {'FINISHED'}


class CLOUDRIG_OT_remove_property_from_ui(Operator):
    """Remove this property from the interface. Hold Shift to also remove the property itself"""

    bl_idname = "pose.cloudrig_remove_property_from_ui"
    bl_label = "Remove Property from UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(
        name="UI Path",
        default="",
        description="List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the slider name",
    )
    delete_actual_prop: BoolProperty(
        name="Delete Actual Property",
        description="Instead of just removing the property from the interface, actually remove it from its owner. Only for Custom Properties",
    )

    def invoke(self, context, event):
        self.delete_actual_prop = event.shift
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        ui_path = json.loads(self.ui_path)
        ui_data, _parents, _index = remove_property_from_ui(
            rig,
            ui_path=ui_path,
        )

        message = f'Removed "{ui_path[-1]}" from UI'

        if self.delete_actual_prop:
            owner_path = ui_data.get('owner_path')
            prop_name = unquote_custom_prop_name(ui_data.get('prop_name'))
            if owner_path == "":
                owner = rig
            elif owner_path:
                owner = path_resolve_safe(rig, owner_path)

            if supports_custom_props(owner) and prop_name in owner:
                del owner[prop_name]
                message += f' and deleted "{prop_name}" property'
            else:
                message += f' but failed to delete "{prop_name}" property'

        self.report({'INFO'}, message + ".")

        return {'FINISHED'}


class CLOUDRIG_OT_reorder_rows(Operator):
    """Rearrange this UI row by moving the mouse up and down. Left-click to confirm, right-click to cancel"""

    bl_idname = "pose.cloudrig_reorder_rows"
    bl_label = "Reorder UI Rows"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(
        name="UI Path",
        default="",
        description="List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the row name",
    )

    def invoke(self, context, event):
        self.mouse_initial = event.mouse_y
        self.index_offset = 0
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return {'CANCELLED'}
        self.initial_panel_data = ui_data
        self.modified_panel_data = read_rig_panels(rig)

        self.row_data, has_moved = reorder_ui_row(
            obj=rig,
            ui_path=json.loads(self.ui_path),
            index_offset=self.index_offset,
            panels=self.modified_panel_data,
        )
        write_rig_panels(rig, self.modified_panel_data)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rig = find_cloudrig(context)
        self.index_offset = 0
        if (
            event.type in {'W', 'UP_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = -1
        elif (
            event.type in {'S', 'DOWN_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = 1
        elif event.type == 'MOUSEMOVE':
            self.index_offset = int((event.mouse_y - self.mouse_initial) / -20)
        elif event.type in {'LEFTMOUSE', 'NUMPAD_ENTER', 'RET'}:
            if self.row_data and 'is_dragged' in self.row_data:
                del self.row_data['is_dragged']
                write_rig_panels(rig, self.modified_panel_data)
                redraw_viewport()
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            write_rig_panels(rig, self.initial_panel_data)
            redraw_viewport()
            return {'CANCELLED'}

        if self.index_offset != 0:
            ret = self.execute(context)
            if ret == {'FINISHED'}:
                self.mouse_initial = event.mouse_y
                write_rig_panels(rig, self.modified_panel_data)
                redraw_viewport()

        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = find_cloudrig(context)
        ui_path = json.loads(self.ui_path)

        self.row_data, has_moved = reorder_ui_row(
            obj=rig,
            ui_path=ui_path,
            index_offset=self.index_offset,
            panels=self.modified_panel_data,
        )

        if has_moved:
            write_rig_panels(rig, self.modified_panel_data)
            redraw_viewport()

            return {'FINISHED'}
        else:
            return {'CANCELLED'}


def path_resolve_safe(owner, data_path):
    try:
        return owner.path_resolve(data_path)
    except:
        return


def ensure_custom_property(prop_bone, prop_id, default=0.0, overwrite=False, **kwargs):
    if 'BoneInfo' in str(type(prop_bone)):
        kwargs['default'] = default
        # Let this function work for BoneInfo objects during the generation process.
        if prop_id not in prop_bone.custom_props:
            prop_bone.custom_props[prop_id] = kwargs
        elif overwrite:
            prop_bone.custom_props[prop_id].update(kwargs)

    else:
        make_property(prop_bone, prop_id, default, **kwargs)


def make_property(
    owner: bpy_struct,
    name: str,
    default,
    *,
    value=None,
    id_type=None,
    subtype: str | None = None,
    ###
    description: str | None = None,
    overridable=True,
    ###
    min: float = 0,
    max: float = 1,
    soft_min=None,
    soft_max=None,
    ###
    **options,
):
    """
    Creates and initializes a custom property of owner.

    The soft_min and soft_max parameters default to min and max.
    Description defaults to the property name.
    """

    value = value or default

    # Some keyword argument defaults differ
    try:
        rna_idprop_ui_create(
            owner,
            name,
            default=default,
            min=min,
            max=max,
            soft_min=soft_min,
            soft_max=soft_max,
            description=description or name,
            overridable=overridable,
            subtype=subtype,
            id_type=id_type,
            **options,
        )

        owner.property_overridable_library_set(f'["{name}"]', overridable)
    except TypeError:
        # Python custom properties will throw an error when trying to call update() on them, but it doesn't matter.
        pass

    if value and value != default:
        owner[name] = value


def add_property_to_ui(
    *,
    obj,
    owner_path: str,
    prop_name: str,
    ###
    panel_name: str,
    label_name="",
    row_name="",
    slider_name="",
    texts: list[str] = [],
    icon_true='CHECKBOX_HLT',
    icon_false='CHECKBOX_DEHLT',
    use_expand_enum=False,
    use_slider=True,
    ###
    children={},
    ui_path: list[str] = None,
    parent_value: str = None,
    ###
    operator="",
    op_icon='BLANK1',
    op_kwargs={},
    ###
    panels=None,
) -> OrderedDict:
    """Add a UI slider to the object's UI data."""
    if panels == None:
        panels = read_rig_panels(obj)

    if ui_path:
        parents = get_ui_element_chain(panels, ui_path)

        parent, parent_name, child_name = parents.pop()
        slider_data = parent[child_name]
        slider_children = slider_data.setdefault('children', OrderedDict())
        panel = slider_children.setdefault(parent_value, OrderedDict())
    else:
        panel = panels.setdefault(panel_name, OrderedDict())

    label = panel.setdefault(label_name, OrderedDict())

    if not slider_name:
        slider_name = prop_name
    if not row_name:
        row_name = "Row: " + slider_name
    row = label.setdefault(row_name, OrderedDict())

    slider_dict = {
        'owner_path': owner_path,
        'prop_name': prop_name,
    }

    if icon_true != 'CHECKBOX_HLT':
        slider_dict['icon_true'] = icon_true
    if icon_false != 'CHECKBOX_DEHLT':
        slider_dict['icon_false'] = icon_false

    # XXX: Blender doesn't support booleans in very specific Py custom prop structures, such as what we need here...
    if use_expand_enum:
        slider_dict['use_expand_enum'] = "True"
    if not use_slider:
        slider_dict['use_slider'] = ""

    if children:
        slider_dict['children'] = {str(key): value for key, value in children.items()}

    if texts:
        slider_dict['texts'] = json.dumps(texts)

    if operator:
        slider_dict['operator'] = operator
        slider_dict['op_icon'] = op_icon
        op_kwargs = {str(key): str(value) for key, value in op_kwargs.items()}
        slider_dict['op_kwargs'] = op_kwargs

    row[slider_name] = slider_dict

    write_rig_panels(obj, panels)

    return panels


def remove_property_from_ui(
    obj,
    ui_path: list[str],
    panels=None,
) -> tuple[OrderedDict, OrderedDict, int, list[str]]:
    """Remove an element of the rig UI, provided a list of names representing the path of
    nesting to follow in the UI data which is a nested OrderedDict.

    For example, if `ui_path = ['Outfits', 'Headwear', 'Hairpin', 'Hairpin.L']`,
    we will remove the `HairPin.L` slider from the `Hairpin` row of the `Headwear` label of the `Outfits` panel.

    If any of those elements become empty from this removal, the empty element will also be removed.

    Returns the sub-dictionary that was removed from the nested dictionary,
    the UI element chain up to the top-most removed element,
    and the index among its siblings of the highest element that was removed.
    """

    if panels == None:
        panels = read_rig_panels(obj)
    parents = get_ui_element_chain(panels, ui_path)

    # Remove the deepest entry from its parent.
    parent, parent_name, child_name = parents.pop()
    ui_entry_data = parent[child_name]
    index = ordereddict_get_index(parent, child_name)
    del parent[child_name]

    # Now go up the tree, and keep removing elements if they have become empty.
    # So empty row, label, panels, and children data does not get left behind after removing their last elements.
    for parent, parent_name, child_name in reversed(parents):
        child_data = parent[child_name]
        if not any(
            [
                key == 'owner_path' or type(value) != str
                for key, value in child_data.items()
            ]
        ):
            index = ordereddict_get_index(parent, child_name)
            del parent[child_name]
            parents.pop()

    write_rig_panels(obj, panels)
    return ui_entry_data, parents, index


def reorder_ui_row(
    *, obj, ui_path: list[str], index_offset=1, panels=None
) -> tuple[OrderedDict, bool]:
    """Re-order a row of the rig UI, provided a list of names representing the path of
    nesting to follow in the UI data which is a nested OrderedDict.

    For example, if `ui_path = ['Outfits', 'Headwear', 'Hairpin']`,
    we will move the `HairPin` row in the the `Headwear` label of the `Outfits` panel
    by the provided index_offset.

    If the index gets clamped and therefore we don't need to perform any re-ordering, we
    don't.
    Return the row_data of the row that was targetted, and a bool of it was actually moved.
    """

    if panels == None:
        panels = read_rig_panels(obj)
    parents = get_ui_element_chain(panels, ui_path)

    label_data, _label_name, row_name = parents.pop()
    from_idx = ordereddict_get_index(label_data, row_name)

    to_idx = from_idx + index_offset
    to_idx = min(to_idx, len(label_data) - 1)
    to_idx = max(0, to_idx)

    label_data[row_name]['is_dragged'] = "True"

    if from_idx != to_idx:
        ordereddict_move_to_index(label_data, from_idx, to_idx)

        # write_rig_panels(obj, panels)
        return label_data[row_name], True

    return label_data[row_name], False


def get_ui_element_chain(
    root_element: OrderedDict, ui_path: list[str]
) -> list[tuple[OrderedDict, str, str]]:
    """Provided a deeply nested OrderedDict where all keys are strings, and a list of names
    that describe a path down the branches of the tree,
    return a list of (OrderedDict, dict_name, child_name) tuples.

    This is used to uniquely identify and find an element in the rig UI.
    """
    chain = []
    # For debugging, this variable pairs the UI element's data to its name.
    parent_name = "Panels"
    ui_element = root_element
    for child_name in ui_path:
        next_ui = ui_element.get(child_name)
        if not next_ui:
            raise Exception(
                f"Failed to get element chain for UI path:\n{ui_path}\nThis should only happen when internal values are set to non-existent elements."
            )

        chain.append((ui_element, parent_name, child_name))
        ui_element = next_ui
        parent_name = child_name
    return chain


def ordereddict_get_index(od: OrderedDict, key: str) -> int:
    """Return the index of a key in an OrderedDictionary."""
    for i, name in enumerate(od.keys()):
        if name == key:
            return i


def ordereddict_move_to_index(od: OrderedDict, from_idx: int, to_idx: int):
    """Return a new OrderedDictionary, where an element was moved from one index to another."""
    # This function was initially written poorly by me, then written flawlessly by ChatGPT.
    items = list(od.items())

    key, value = items.pop(from_idx)

    items.insert(to_idx, (key, value))

    reordered_dict = OrderedDict(items)

    od.clear()
    od.update(reordered_dict)


def supports_custom_props(prop_owner):
    return isinstance(prop_owner, ID) or type(prop_owner) in {PoseBone, BoneCollection}


def get_drawable_custom_properties(prop_owner):
    if not supports_custom_props(prop_owner):
        return []
    for prop_name in prop_owner.keys():
        try:
            prop_owner.id_properties_ui(prop_name).as_dict()
        except TypeError:
            # This happens for Python properties. There's not much point in drawing them.
            continue
        yield prop_name


def get_drawable_builtin_properties(prop_owner):
    if not hasattr(prop_owner, 'bl_rna'):
        return
    for prop_name, prop_data in prop_owner.bl_rna.properties.items():
        if prop_data.is_runtime:
            continue
        prop_value = getattr(prop_owner, prop_name)
        value_type, is_array = rna_idprop_value_item_type(prop_value)
        if value_type in {bool, int, float, str}:
            yield prop_name


class HiddenPrints:
    def write(*args):
        # This is a workaround to /issues/83 based on
        # https://stackoverflow.com/questions/6735917/redirecting-stdout-to-nothing-in-python
        pass

    def __enter__(self):
        self._original_stdout = sys.stdout
        try:
            sys.stdout = open(os.devnull, 'w')
        except FileNotFoundError:
            # Workaround, relies on this class having a write() method.
            sys.stdout = self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout


def redraw_viewport():
    with HiddenPrints():
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)


class UIPathProperty(PropertyGroup):
    name: StringProperty()
    ui_path: StringProperty()
    current: StringProperty(description="Current value of this property. Used for pre-filling the Parent Values field")
    index: IntProperty()


registry = [
    UIPathProperty,
    CLOUDRIG_OT_add_child_property_to_ui,
    CLOUDRIG_OT_edit_property_in_ui,
    CLOUDRIG_OT_add_property_to_ui,
    CLOUDRIG_OT_remove_property_from_ui,
    CLOUDRIG_OT_reorder_rows,
]


def register():
    bpy.types.Scene.cloudrig_property_parent_selector = CollectionProperty(
        type=UIPathProperty
    )
    bpy.types.Scene.cloudrig_property_name_selector = CollectionProperty(
        type=UIPathProperty
    )
