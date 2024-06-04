import bpy, json, sys, os
from bpy.types import Operator, ID, bpy_struct, PoseBone, Bone, UILayout
from typing import Optional
from bpy.props import StringProperty, BoolProperty, EnumProperty
from collections import OrderedDict
from ..generation.cloudrig import (
    is_active_cloudrig,
    is_active_cloud_metarig,
    unquote_custom_prop_name,
    ensure_custom_panels,
    feed_op_props,
    draw_property,
    read_rig_panels,
    write_rig_panels,
    tuples_to_dict,
    dict_to_tuples,
)
from rna_prop_ui import rna_idprop_ui_create
from rna_prop_ui import rna_idprop_quote_path as quote_property

class CLOUDRIG_OT_add_property_to_ui(Operator):
    """Add a property to the rig UI. It can be a built-in property or a custom property. If it doesn't exist, it will be created if possible. It can also have an operator next to it"""
    bl_idname = "pose.cloudrig_add_property_to_ui"
    bl_label = "Add Property to UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def update_use_bone_selector(self, context):
        if self.use_bone_selector:
            if self.owner_path.startswith("pose.bones"):
                self.owner_path = self.owner_path.split('["')[1].split('"]')[0]
            else:
                self.owner_path = ""
        elif self.owner_path != '' and not self.owner_path.startswith('pose.bones'):
            self.owner_path = f'pose.bones["{self.owner_path}"]'

    owner_path: StringProperty(name="Data Path", description="Python data path from the rig to the owner of the property. Can be left empty to look for a property directly on the rig object itself")
    use_bone_selector: BoolProperty(name="Use Bone Selector", options={'SKIP_SAVE'}, description="Display a bone selector. If disabled, you can manually type in a data path", default=True, update=update_use_bone_selector)
    prop_name: StringProperty(name="Property Name", description="Name of the property. It can already exist, otherwise it will be created with a value of 1.0")

    panel_name: StringProperty(name="Subpanel", default="Properties", description="Optional: The sub-panel that this property should be displayed in")
    label_name: StringProperty(name="Label", description="Optional: Place this property under a text label")
    row_name: StringProperty(name="Row ID", default="", options={'SKIP_SAVE'}, description="Optional: If two sliders share the same Row ID, they will be drawn in the same row. However, the Row ID itself is not shown in the interface")
    slider_name: StringProperty(name="Display Name", default="", options={'SKIP_SAVE'}, description="Optional: Override the display text of the property")
    texts: StringProperty(name="Value Names", options={'SKIP_SAVE'}, description="Optional: Comma-separated list of strings to display based on the property value. The first string is displayed when the value is 0, and so on")

    parent_ui_path: StringProperty(name="Parent UI Path", options={'SKIP_SAVE'}, default="[]", description="Internal. Used only by the Add Child operator, to identify the parent")

    def get_sliders(self, context):
        ui_data = read_rig_panels(context.active_object)
        items = []

        def add_slider_ui_paths_recursive(ui_data: OrderedDict, ui_path: list[str], display_name: str):
            for elem_name, elem_data in ui_data.items():
                if type(elem_data) == str:
                    continue
                new_ui_path = ui_path + [elem_name]
                identifier = json.dumps(new_ui_path)
                if hasattr(self, 'ui_path') and identifier == self.ui_path:
                    return
                new_display_name = display_name or elem_name
                if 'owner_path' in elem_data:
                    # This is a slider, so it is a potential parent, add it to `items`.
                    if elem_name:
                        new_display_name += " -> " + elem_name
                    items.append((identifier, new_display_name, ""))

                add_slider_ui_paths_recursive(elem_data, new_ui_path[:], new_display_name)

        add_slider_ui_paths_recursive(ui_data, ui_path=[], display_name="")
        return items

    parent_selector: EnumProperty(name="Parent Slider", options={'SKIP_SAVE'}, items=get_sliders)
    parent_value: StringProperty(name="Parent Value", default="1", description="Display this child property only when the parent property matches this value")
    show_internals: BoolProperty(name="Internals", default=False, description="Show internal data")

    operator: StringProperty(name="Operator ID", description="Internal. Only used by the Edit operator, to initialize the temp KeyMapItem")
    op_kwargs: StringProperty(name="Operator Arguments", default="{}", description="Internal. Only used by the Edit operator, to feed kwargs to the temp KeyMapItem")
    op_icon: StringProperty(name="Operator Icon", default='BLANK1', description="Operator Icon")

    children: StringProperty(name="UI Children", options={'SKIP_SAVE'}, default="{}", description="Internal. Only used by the Edit operator, to preserve children")

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context) or is_active_cloud_metarig(context)

    def get_data_paths(self, obj) -> tuple[ID, str, str, str, any]:
        data_path = bone_name = self.owner_path
        prop_name = self.prop_name

        # In case a data path wasn't provided, the default property owner is the object itself.
        prop_owner = obj

        if data_path and self.use_bone_selector:
            # If user wants to use the bone search selector, 
            # we need to help them get the data path to the selected pose bone.
            data_path = f'pose.bones["{bone_name}"]'

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
                prop_value = obj.path_resolve(data_path + "." + prop_name)
                dot = "."
            except ValueError:
                # If we fail to evaluate to a value with the `.`, use custom property syntax instead.
                prop_name = f'["{prop_name}"]'
                dot = ""

        full_path = data_path + dot + prop_name
        if not prop_value:
            # If we didn't get the property value yet, grab it. 
            # Can be useful to re-assure the user that we have the property they intend.
            prop_value = path_resolve_safe(obj, full_path)

        if prop_name and not prop_value:
            prop_value = path_resolve_safe(obj, full_path)

        return prop_owner, full_path, data_path, prop_name, prop_value

    def invoke(self, context, _event):
        # We create a keymap item to help us draw the operator set-up UI.
        # KeymapItems in the default keymap will not be stored by Blender, 
        # so we don't need to worry about making a mess there.
        self.panels = read_rig_panels(context.active_object)
        self.temp_kmi = context.window_manager.keyconfigs.default.keymaps['Info'].keymap_items.new('', 'NUMPAD_5', 'PRESS')
        if self.operator:
            self.temp_kmi.idname = self.operator
            if self.op_kwargs:
                op_props = self.temp_kmi.properties
                feed_op_props(op_props, self.op_kwargs)
        if self.owner_path:
            self.use_bone_selector = self.owner_path.startswith('pose.bones')

        if self.parent_ui_path != '[]':
            self.parent_selector = self.parent_ui_path

        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        layout = self.layout.column()
        rig = context.active_object

        self.draw_owner_box(layout, context)
        self.draw_prop_box(layout, context)
        self.draw_placement_box(layout, context)
        layout.separator()

        self.draw_op_box(layout, context)
        layout.separator()

        # self.draw_debug_box(layout, context)

    def draw_owner_box(self, layout, context):
        rig = context.active_object
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(rig)

        owner_box = layout.box()
        owner_row = owner_box.row(align=True)
        if self.use_bone_selector:
            owner_row.prop_search(self, 'owner_path', rig.pose, 'bones', text="Property Bone")
        else:
            owner_row.prop(self, 'owner_path')
        owner_row.prop(self, 'use_bone_selector', icon='BONE_DATA', text="")

        if self.owner_path and not prop_owner:
            # User tried providing a data path, but it didn't path_resolve() to anything.
            owner_row.alert = True
            alert_row = owner_box.row()
            alert_row.alert=True
            alert_row.label(text=f"No property owner at '{self.owner_path}' found.", icon='ERROR')
            return

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

    def draw_prop_box(self, layout, context):
        rig = context.active_object
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(rig)

        prop_box = layout.box()
        prop_box.prop(self, 'prop_name')

        if not prop_owner:
            prop_box.label(text=f'Data path failed to resolve on {rig.name}.')
            return

        if not self.prop_name:
            # User hasn't typed in a property name yet. Don't overwhelm them with the rest of the UI.
            return

        if prop_value != None:
            if isinstance(prop_value, bpy_struct):
                row = prop_box.row()
                row.alert=True
                row.label(text="This is a struct, not a property.", icon='ERROR')
                return
            else:
                prop_box.label(text=f"Property found.", icon='CHECKMARK')
                draw_property(prop_box, prop_owner, brackets_prop_name, slider_name=self.slider_name, texts=[t.strip() for t in self.texts.split(",")])
        elif type(prop_owner) in {ID, PoseBone, Bone}:
            prop_box.label(text="Property will be created with a value of 1.0.", icon='CHECKMARK')
        else:
            row = prop_box.row()
            row.alert = True
            row.label(text="Property not found.", icon='ERROR')
            return

    def draw_placement_box(self, layout, context):
        rig = context.active_object
        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(rig)

        panel_box = layout.box()
        if self.parent_ui_path != "[]":
            panel_box.prop(self, 'parent_selector')
            # panel_box.label(text=self.parent_selector)
            panel_box.prop(self, 'parent_value')
        else:
            panel_box.prop(self, 'panel_name')
        panel_box.prop(self, 'label_name')
        panel_box.prop(self, 'row_name')
        panel_box.prop(self, 'slider_name')
        if type(prop_value) in {bool, int}:
            panel_box.prop(self, 'texts')

    def draw_op_box(self, layout, context):
        op_box = layout.box().column()
        op_box.prop(self.temp_kmi, 'idname', text="Operator")
        self.op_kwargs_dict = {}
        if self.temp_kmi.idname:
            box = None
            op_rna = eval("bpy.ops."+self.temp_kmi.idname).get_rna_type()
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
        split.prop(self, 'show_internals', icon='BLANK1', toggle=False, emboss=False, text="")
        if self.show_internals:
            int_box.prop(self, 'parent_ui_path')
            if hasattr(self, 'ui_path'):
                row = int_box.row()
                row.enabled=False
                row.prop(self, 'ui_path')

    def execute(self, context):
        ret = self.execute_add_property(context)
        if ret:
            return ret
        self.report({'INFO'}, f"Added property {self.slider_name} to the rig UI")
        redraw_viewport()
        return {'FINISHED'}

    def execute_add_property(self, context):
        rig = context.active_object
        owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(rig)

        if self.prop_name != brackets_prop_name:
            if issubclass(type(owner), ID) or type(owner) in {PoseBone, Bone}:
                # Owner supports custom props.
                if self.prop_name not in owner:
                    # Target is a custom property that doesn't exist yet, so let's create it.
                    ensure_custom_property(
                        owner,
                        self.prop_name
                    )
                # Make the property library overridable.
                owner.property_overridable_library_set(brackets_prop_name, True)
            else:
                self.report({'ERROR'}, f'{type(owner)} does not support custom properties.')
                return {'CANCELLED'}

        if not self.slider_name:
            self.slider_name = self.prop_name

        add_property_to_ui(
            obj=rig,
            owner_path=owner_path,
            prop_name=brackets_prop_name,

            panel_name=self.panel_name,
            label_name=self.label_name,
            row_name=self.row_name,
            slider_name=self.slider_name,

            texts=[t.strip() for t in self.texts.split(",")],
            children=json.loads(self.children),

            ui_path=json.loads(self.parent_selector),
            parent_value = self.parent_value,

            operator=self.temp_kmi.idname,
            op_icon=self.op_icon,
            op_kwargs=self.op_kwargs_dict,

            panels=self.panels,
        )

        ensure_custom_panels(None, None)

class CLOUDRIG_OT_add_child_property_to_ui(CLOUDRIG_OT_add_property_to_ui):
    """Add a child property to the rig UI"""
    bl_idname = "pose.cloudrig_add_child_property_to_ui"
    bl_label = "Add Child Property to UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

class CLOUDRIG_OT_edit_property_in_ui(CLOUDRIG_OT_add_property_to_ui):
    """Edit how a property is displayed in the UI"""
    bl_idname = "pose.cloudrig_edit_property_in_ui"
    bl_label = "Edit Property in UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(name="UI Path", default="", description="Internal. List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the slider name")

    def execute(self, context):
        rig = context.active_object
        ui_path = json.loads(self.ui_path)

        _ui_data, parents, index = remove_property_from_ui(
            rig,
            ui_path=ui_path,
            panels=self.panels
        )

        if parents:
            parent, parent_name, child_name = parents.pop()
            ui_elem = parent[child_name]
            count = len(list(ui_elem.keys()))

        super().execute_add_property(context)

        if parents:
            ui_elem = parent[child_name]
            new_count = len(list(ui_elem.keys()))

            if new_count == count+1:
                # When the UI element was added to the same parent element that it was in before, 
                # let's preserve its vertical position.
                ordereddict_move_to_index(ui_elem, new_count-1, index)

        write_rig_panels(rig, self.panels)
        redraw_viewport()

        self.report({'INFO'}, f"Edited property {ui_path[-1]} to the rig UI")
        return {'FINISHED'}

class CLOUDRIG_OT_remove_property_from_ui(Operator):
    """Remove this property from the interface. Hold Shift to also remove the property itself"""
    bl_idname = "pose.cloudrig_remove_property_from_ui"
    bl_label = "Remove Property from UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(name="UI Path", default="", description="List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the slider name")
    delete_actual_prop: BoolProperty(name="Delete Actual Property", description="Instead of just removing the property from the interface, actually remove it from its owner. Only for Custom Properties")

    def invoke(self, context, event):
        self.delete_actual_prop = event.shift
        return self.execute(context)

    def execute(self, context):
        rig = context.active_object
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
            
            if prop_name in owner:
                del owner[prop_name]
                message += f' and deleted "{prop_name}" property'
            else:
                message += f' but failed to delete "{prop_name}" property'

        self.report({'INFO'}, message+".")

        return {'FINISHED'}

class CLOUDRIG_OT_reorder_rows(Operator):
    """Rearrange this UI row by moving the mouse up and down. Left-click to confirm, right-click to cancel"""
    bl_idname = "pose.cloudrig_reorder_rows"
    bl_label = "Reorder UI Rows"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    ui_path: StringProperty(name="UI Path", default="", description="List of entry names to follow the nesting of the UIData dictionary, starting with the panel name and ending with the row name")
    reset_panels: BoolProperty(name="Reset Panels", default=False, options={'SKIP_SAVE'}, description="Internal. When re-ordering panels, they need to be re-registered. Set this to True when this operator is re-ordering panels")

    def invoke(self, context, event):
        self.mouse_initial = event.mouse_y
        self.index_offset = 0
        self.initial_panel_data = read_rig_panels(context.active_object)
        self.modified_panel_data = read_rig_panels(context.active_object)

        self.row_data, has_moved = reorder_ui_row(
            obj=context.active_object, 
            ui_path=json.loads(self.ui_path), 
            index_offset=self.index_offset,

            panels=self.modified_panel_data
        )
        write_rig_panels(context.active_object, self.modified_panel_data)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.index_offset = int((event.mouse_y - self.mouse_initial) / -20)
            if self.index_offset != 0:
                ret = self.execute(context)
                if ret == {'FINISHED'}:
                    redraw_viewport()
                    self.mouse_initial = event.mouse_y
                    self.update_ui_data(context, self.modified_panel_data)
        elif event.type == 'LEFTMOUSE':
            if self.row_data and 'is_dragged' in self.row_data:
                del self.row_data['is_dragged']
                write_rig_panels(context.active_object, self.modified_panel_data)
                redraw_viewport()
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.update_ui_data(context, self.initial_panel_data)
            write_rig_panels(context.active_object, self.initial_panel_data)
            redraw_viewport()
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def update_ui_data(self, context, ui_data):
        rig = context.active_object
        if not self.reset_panels:
            write_rig_panels(rig, ui_data)
            return
        bpy.types.CLOUDRIG_PT_settings.unregister_subpanels()
        redraw_viewport()
        write_rig_panels(rig, ui_data)
        bpy.types.CLOUDRIG_PT_settings.ensure_custom_panels(context)
        redraw_viewport()

    def execute(self, context):
        ui_path = json.loads(self.ui_path)

        self.row_data, has_moved = reorder_ui_row(
            obj=context.active_object, 
            ui_path=ui_path, 
            index_offset=self.index_offset,

            panels=self.modified_panel_data
        )

        if has_moved:
            write_rig_panels(context.active_object, self.modified_panel_data)
            redraw_viewport()

            return {'FINISHED'}
        else:
            return {'CANCELLED'}

def path_resolve_safe(owner, data_path):
    try:
        return owner.path_resolve(data_path)
    except:
        return

def ensure_custom_property(prop_bone, prop_id, default=0.0, **kwargs):
    if 'BoneInfo' in str(type(prop_bone)):
        kwargs['default'] = default
        # Let this function work for BoneInfo objects during the generation process.
        if prop_id not in prop_bone.custom_props:
            prop_bone.custom_props[prop_id] = kwargs
        else:
            prop_bone.custom_props[prop_id].update(kwargs)

    else:
        make_property(prop_bone, prop_id, default, **kwargs)

def make_property(
        owner: bpy_struct, name: str, default, *,
        min: float = 0, max: float = 1, soft_min=None, soft_max=None,
        description: Optional[str] = None, overridable=True, 
        subtype: Optional[str] = None, id_type=None,
        value=None,
        **options):
    """
    Creates and initializes a custom property of owner.

    The soft_min and soft_max parameters default to min and max.
    Description defaults to the property name.
    """

    value = value or default

    # Some keyword argument defaults differ
    try:
        rna_idprop_ui_create(
            owner, name, default=default,
            min=min, max=max, soft_min=soft_min, soft_max=soft_max,
            description=description or name,
            overridable=overridable,
            subtype=subtype,
            id_type=id_type,
            **options
        )

        owner.property_overridable_library_set(
            f'["{name}"]', overridable
        )
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

    panel_name: str,
    label_name="",
    row_name="",
    slider_name="",

    texts: list[str]=[],
    children={},

    ui_path: list[str] = None,
    parent_value: str = None,

    operator="",
    op_icon='BLANK1',
    op_kwargs={},

    parent_id="",

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
        panel['parent_id'] = parent_id

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

    if not panels:
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
        if (not any([key=='owner_path' or type(value)!=str for key, value in child_data.items()])):
            index = ordereddict_get_index(parent, child_name)
            del parent[child_name]
            parents.pop()

    write_rig_panels(obj, panels)
    return ui_entry_data, parents, index

def reorder_ui_row(
    *,
    obj,
    ui_path: list[str],
    index_offset = 1,

    panels=None
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

    if not panels:
        panels = read_rig_panels(obj)
    parents = get_ui_element_chain(panels, ui_path)

    label_data, _label_name, row_name = parents.pop()
    from_idx = ordereddict_get_index(label_data, row_name)

    to_idx = from_idx + index_offset
    to_idx = min(to_idx, len(label_data)-1)
    to_idx = max(0, to_idx)

    label_data[row_name]['is_dragged'] = "True"

    if from_idx != to_idx:
        ordereddict_move_to_index(label_data, from_idx, to_idx)

        # write_rig_panels(obj, panels)
        return label_data[row_name], True

    return label_data[row_name], False

def get_ui_element_chain(
    root_element: OrderedDict,
    ui_path: list[str]
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
            raise Exception(f"Failed to get element chain for UI path:\n{ui_path}\nThis should only happen when internal values are set to non-existent elements.")

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


registry = [
    CLOUDRIG_OT_add_child_property_to_ui,
    CLOUDRIG_OT_edit_property_in_ui,
    CLOUDRIG_OT_add_property_to_ui,
    CLOUDRIG_OT_remove_property_from_ui,
    CLOUDRIG_OT_reorder_rows,
]