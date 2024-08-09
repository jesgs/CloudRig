from ..generation.cloudrig import CloudRig_UIElement, find_cloudrig, feed_op_props
from .properties_ui import UIPathProperty
from bpy.types import Operator, UILayout, ID, PoseBone, BoneCollection
from bpy.props import (
    CollectionProperty,
    StringProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
)
from rna_prop_ui import rna_idprop_value_item_type
import bpy, json


def draw_ui_editing(context, layout, ui_element, operator):
    layout.prop(operator, 'element_type', expand=True)

    draw_parent_picking(context, layout, ui_element, operator)

    if operator.element_type == 'PROPERTY':
        draw_prop_editing(context, layout, ui_element, operator)

    if operator.element_type == 'OPERATOR':
        draw_op_editing(context, layout, ui_element, operator)

    # debug
    # layout.prop(ui_element, 'prop_owner_path')
    # layout.prop(ui_element, 'is_custom_prop')


def draw_parent_picking(context, layout, ui_element, operator):
    parent_row = layout.row()
    if operator.create_new_ui:
        parent_row.prop(operator, 'new_panel_name')
        layout.prop(operator, 'new_label_name')
        layout.prop(operator, 'new_row_name')
    else:
        parent_row.prop_search(
            operator, 'parent_element', context.scene, 'cloudrig_ui_parent_selector'
        )
    if context.scene.cloudrig_ui_parent_selector:
        parent_row.prop(operator, 'create_new_ui', text="", icon='ADD')


def draw_prop_editing(context, layout, ui_element, operator):
    rig = find_cloudrig(context)

    owner_row = layout.row()
    if operator.prop_owner_type == 'BONE':
        owner_row.prop_search(operator, 'prop_bone', rig.pose, 'bones')
    elif operator.prop_owner_type == 'COLLECTION':
        owner_row.prop_search(
            operator,
            'prop_coll',
            rig.data,
            'collections_all',
            icon='OUTLINER_COLLECTION',
        )
    elif operator.prop_owner_type == 'DATA_PATH':
        owner_row.prop(operator, 'prop_data_path', icon='RNA')
    owner_row.prop(operator, 'prop_owner_type', expand=True, text="")

    if not ui_element.prop_owner:
        return
    if operator.prop_owner_type == 'COLLECTION' and not operator.prop_coll:
        return
    if operator.prop_owner_type == 'BONE' and not operator.prop_bone:
        return

    if context.scene.cloudrig_ui_prop_selector:
        layout.prop_search(
            ui_element, 'prop_name', context.scene, 'cloudrig_ui_prop_selector'
        )
    else:
        layout.prop(ui_element, 'prop_name')

    if not ui_element.prop_name:
        return

    layout.prop(ui_element, 'display_name')

    value_type, is_array = rna_idprop_value_item_type(ui_element.prop_value)
    if not is_array:
        if value_type in {bool, int}:
            layout.prop(ui_element, 'texts')
        if value_type == bool:
            icons = UILayout.bl_rna.functions["prop"].parameters["icon"]
            layout.prop_search(
                ui_element, 'icon', icons, 'enum_items', icon=ui_element.icon
            )
            layout.prop_search(
                ui_element,
                'icon_false',
                icons,
                'enum_items',
                icon=ui_element.icon_false,
            )


def draw_op_editing(context, layout, ui_element, operator):
    if operator.use_batch_add:
        return
    layout.prop(operator.temp_kmi, 'idname', text="Operator")
    operator.op_kwargs_dict = {}
    if not operator.temp_kmi.idname:
        return

    box = None
    op_rna = eval("bpy.ops." + operator.temp_kmi.idname).get_rna_type()
    for key, value in op_rna.properties.items():
        if key == 'rna_type':
            continue
        if not box:
            box = layout.box().column(align=True)
        box.prop(operator.temp_kmi.properties, key)
        operator.op_kwargs_dict[key] = str(
            getattr(operator.temp_kmi.properties, key)
        )
    icons = UILayout.bl_rna.functions["prop"].parameters["icon"]
    layout.prop_search(
        ui_element, 'icon', icons, 'enum_items', icon=ui_element.icon
    )

    layout.prop(ui_element, 'display_name')


def update_parent_selector(context):
    context.scene.cloudrig_ui_parent_selector.clear()

    rig = find_cloudrig(context)

    for ui_element in rig.cloudrig_ui:
        if ui_element.element_type in {'PANEL', 'LABEL', 'ROW', 'PROPERTY'}:
            parent_option = context.scene.cloudrig_ui_parent_selector.add()
            parent_option.name = ui_element.identifier
            parent_option.index = ui_element.index


def wipe_parent_selector(context):
    if 'cloudrig_ui_parent_selector' in context.scene:
        del context.scene['cloudrig_ui_parent_selector']


def get_new_ui_element(context):
    rig = find_cloudrig(context)
    return rig.cloudrig_ui_new_element


def update_property_selector(self, context):
    context.scene.cloudrig_ui_prop_selector.clear()

    ui_element = get_new_ui_element(context)

    prop_owner = ui_element.prop_owner

    if not prop_owner:
        return

    # Populate the property drop-down selector with available custom properties.
    ui_element.is_custom_prop = True
    for key in get_drawable_custom_properties(prop_owner):
        name_entry = context.scene.cloudrig_ui_prop_selector.add()
        name_entry.name = key

    if len(context.scene.cloudrig_ui_prop_selector) == 0:
        # If that failed, populate it with built-in properties instead.
        ui_element.is_custom_prop = False
        for key in get_drawable_builtin_properties(prop_owner):
            name_entry = context.scene.cloudrig_ui_prop_selector.add()
            name_entry.name = key


class UIElementAddMixin:
    def update_parent_element(self, context):
        ui_element = get_new_ui_element(context)
        ui_element.parent_index = context.scene.cloudrig_ui_parent_selector[
            self.parent_element
        ].index

    parent_element: StringProperty(
        name="Parent Element",
        description="Optional. UI element that this new one should be a part of",
        update=update_parent_element,
    )

    def update_prop_bone(self, context):
        ui_element = get_new_ui_element(context)
        if self.prop_bone:
            ui_element.prop_owner_path = f'pose.bones["{self.prop_bone}"]'
            update_property_selector(self, context)
            if ui_element.prop_name not in ui_element.prop_owner:
                ui_element.prop_name = ""

    prop_bone: StringProperty(name="Bone Name", update=update_prop_bone)

    def update_prop_coll(self, context):
        ui_element = get_new_ui_element(context)
        if self.prop_coll:
            ui_element.prop_owner_path = f'data.collections_all["{self.prop_coll}"]'
            update_property_selector(self, context)
            ui_element.prop_name = 'is_visible'
            ui_element.display_name = self.prop_coll
            ui_element.icon = 'HIDE_OFF'
            ui_element.icon_false = 'HIDE_ON'

    prop_coll: StringProperty(name="Bone Collection", update=update_prop_coll)

    def update_prop_data_path(self, context):
        ui_element = get_new_ui_element(context)
        ui_element.prop_owner_path = self.prop_data_path
        update_property_selector(self, context)

    prop_data_path: StringProperty(name="Data Path", update=update_prop_data_path)

    def update_prop_owner_type(self, context):
        ui_element = get_new_ui_element(context)
        if self.prop_owner_type == 'COLLECTION':
            self.prop_coll = self.prop_coll
        if self.prop_owner_type == 'BONE':
            self.prop_bone = self.prop_bone
        if self.prop_owner_type == 'DATA_PATH':
            self.prop_data_path = ui_element.prop_owner_path

    prop_owner_type: EnumProperty(
        name="Property Owner Type",
        description="How you would like to select the owner of the property which will be added to the UI",
        items=[
            ('BONE', 'Bone', 'Select a bone from the rig', 'BONE_DATA', 0),
            (
                'COLLECTION',
                'Collection',
                'Select a bone collection from the rig',
                'OUTLINER_COLLECTION',
                1,
            ),
            (
                'DATA_PATH',
                'Data Path',
                'Enter a Python Data Path to any property of the rig',
                'RNA',
                2,
            ),
        ],
        update=update_prop_owner_type,
    )

    element_type: EnumProperty(
        name="Element Type",
        items=[
            ('PROPERTY', 'Property', "Property"),
            ('OPERATOR', 'Operator', "Operator"),
        ],
    )
    create_new_ui: BoolProperty(
        name="Create Containers",
        description="Instead of placing this UI element in an existing panel, label, and row, create new ones",
    )
    new_panel_name: StringProperty(
        name="Panel Name",
        description="Optional. Elements parented to this panel can be hidden by collapsing the panel",
    )
    new_label_name: StringProperty(
        name="Label Name",
        description="Optional. Elements parented to this label will be displayed below it",
    )
    new_row_name: StringProperty(
        name="Row Name",
        description="Optional. Elements parented to this row will be displayed side-by-side",
    )

    use_batch_add: BoolProperty(
        name="Batch Add",
        options={'SKIP_SAVE'},
        default=False,
        description="Add all custom properties of the selected ID to the UI",
    )

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context)
        if not rig:
            return False
        return True

    def invoke(self, context, _event):
        update_parent_selector(context)
        if not context.scene.cloudrig_ui_parent_selector:
            self.create_new_ui = True

        self.ui_element = get_new_ui_element(context)
        self.ui_element.reset()

        self.temp_kmi = context.window_manager.keyconfigs.default.keymaps[
            'Info'
        ].keymap_items.new('', 'NUMPAD_5', 'PRESS')
        if self.ui_element.bl_idname:
            self.temp_kmi.idname = self.ui_element.bl_idname
            if self.ui_element.op_kwargs:
                op_props = self.temp_kmi.properties
                feed_op_props(op_props, self.ui_element.op_kwargs)

        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = True

        draw_ui_editing(context, layout, self.ui_element, self)


class CLOUDRIG_OT_ui_element_add(UIElementAddMixin, Operator):
    """Add UI Element"""

    bl_idname = "object.cloudrig_ui_element_add"
    bl_label = "Add UI Element"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = find_cloudrig(context)
        temp_ui_element = get_new_ui_element(context)

        parent = None
        if self.create_new_ui:
            if self.new_panel_name:
                parent = rig.cloudrig_ui.add()
                parent.element_type = 'PANEL'
                parent.display_name = self.new_panel_name
            if self.new_label_name:
                label = rig.cloudrig_ui.add()
                label.parent = parent
                label.element_type = 'LABEL'
                label.display_name = self.new_label_name
                parent = label

            row = rig.cloudrig_ui.add()
            row.parent = parent
            row.element_type = 'ROW'
            row.display_name = self.new_row_name or temp_ui_element.prop_name
            parent = row

        new_ui_element = rig.cloudrig_ui.add()

        for prop_name in new_ui_element.bl_rna.properties.keys():
            if prop_name == 'rna_type':
                continue
            setattr(new_ui_element, prop_name, getattr(temp_ui_element, prop_name))

        if parent:
            new_ui_element.parent = parent
        new_ui_element.element_type = self.element_type

        if self.element_type == 'OPERATOR':
            new_ui_element.bl_idname  = self.temp_kmi.idname

        wipe_parent_selector(context)
        del rig['cloudrig_ui_new_element']

        return {'FINISHED'}


class CLOUDRIG_OT_ui_element_edit(UIElementAddMixin, Operator):
    """Add a UI element"""

    bl_idname = "object.cloudrig_ui_element_edit"
    bl_label = "Edit UI Element"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    element_index: IntProperty()

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = True

        rig = find_cloudrig(context)
        elem_to_edit = rig.cloudrig_ui[self.element_index]

        draw_ui_editing(context, layout, elem_to_edit, self)


class CLOUDRIG_OT_ui_element_remove(Operator):
    """Remove this UI element.\n\n""" """Ctrl: Do not remove children"""

    bl_idname = "object.cloudrig_ui_element_remove"
    bl_label = "Remove UI Element"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    element_index: IntProperty()
    recursive: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context)

    def invoke(self, context, event):
        self.recursive = not event.ctrl
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        self.remove_element(rig, self.element_index)
        return {'FINISHED'}

    def remove_element(self, rig, index):
        element_to_remove = rig.cloudrig_ui[index]
        fallback_parent = element_to_remove.parent

        if self.recursive:
            for child in element_to_remove.children:
                self.remove_element(rig, child.index)
        else:
            for child in element_to_remove.children:
                child.parent = fallback_parent

        for element in rig.cloudrig_ui:
            if element.parent_index > index:
                element.parent_index -= 1

        rig.cloudrig_ui.remove(index)


def supports_custom_props(prop_owner):
    return isinstance(prop_owner, ID) or type(prop_owner) in {PoseBone, BoneCollection}


def has_custom_props(prop_owner) -> bool:
    if not supports_custom_props(prop_owner):
        return False
    return bool(list(get_drawable_custom_properties(prop_owner)))


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


def path_resolve_safe(owner, data_path):
    try:
        return owner.path_resolve(data_path)
    except ValueError:
        # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
        return


def get_drawable_builtin_properties(prop_owner):
    for prop_name, prop_data in prop_owner.bl_rna.properties.items():
        if prop_data.is_runtime:
            continue
        prop_value = getattr(prop_owner, prop_name)
        value_type, is_array = rna_idprop_value_item_type(prop_value)
        if value_type in {bool, int, float, str}:
            yield prop_name


def register():
    bpy.types.Scene.cloudrig_ui_parent_selector = CollectionProperty(
        type=UIPathProperty
    )
    bpy.types.Scene.cloudrig_ui_prop_selector = CollectionProperty(type=UIPathProperty)
    bpy.types.Object.cloudrig_ui_new_element = PointerProperty(type=CloudRig_UIElement)


registry = [
    CLOUDRIG_OT_ui_element_add,
    CLOUDRIG_OT_ui_element_edit,
    CLOUDRIG_OT_ui_element_remove,
]
