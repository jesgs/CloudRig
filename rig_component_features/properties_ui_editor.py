from ..generation.cloudrig import CloudRig_UIElement, find_cloudrig
from .properties_ui import UIPathProperty
from bpy.types import Operator 
from bpy.props import CollectionProperty, StringProperty, IntProperty, BoolProperty
import bpy

class CLOUDRIG_OT_ui_element_add(Operator):
    """Add a UI element"""
    
    bl_idname = "object.cloudrig_ui_element_add"
    bl_label = "Add Property to UI"
    bl_options = {'REGISTER', 'UNDO'}

    # Copy the definition of a single UIElement, which will be added 
    # by this operator, when the "OK" button is clicked.
    __annotations__ = CloudRig_UIElement.__annotations__

    parent_element: StringProperty(name="Parent Element")

    @classmethod
    def poll(cls, context):
        rig = find_cloudrig(context)
        if not rig:
            return False
        return True

    def invoke(self, context, _event):
        context.scene.cloudrig_ui_parent_selector.clear()

        rig = find_cloudrig(context)

        for ui_element in rig.cloudrig_ui:
            if ui_element.element_type in {'PANEL', 'LABEL', 'ROW'}:
                parent_option = context.scene.cloudrig_ui_parent_selector.add()
                parent_option.name = ui_element.identifier
                parent_option.index = ui_element.index

        return context.window_manager.invoke_props_dialog(self, width=500)
    
    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = True

        layout.prop(self, 'element_type')
        layout.prop(self, 'display_name')
        if self.element_type in {'PANEL', 'LABEL', 'ROW'}:
            layout.prop_search(self, 'parent_element', context.scene, 'cloudrig_ui_parent_selector')

    def execute(self, context):
        rig = find_cloudrig(context)
        new_ui_element = rig.cloudrig_ui.add()
        new_ui_element.display_name = self.display_name
        new_ui_element.element_type = self.element_type
        if self.parent_element:
            new_ui_element.parent_index = context.scene.cloudrig_ui_parent_selector[self.parent_element].index
        return {'FINISHED'}

class CLOUDRIG_OT_ui_element_remove(Operator):
    """Remove this UI element.\n\n""" \
    """Ctrl: Do not remove children"""

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

        if self.recursive:
            for child in element_to_remove.children:
                self.remove_element(rig, child.index)
        else:
            for child in element_to_remove.children:
                child.parent_index = -1

        for element in rig.cloudrig_ui:
            if element.parent_index > index:
                element.parent_index -= 1

        rig.cloudrig_ui.remove(index)


def register():
    bpy.types.Scene.cloudrig_ui_parent_selector = CollectionProperty(
        type=UIPathProperty
    )

registry = [
    CLOUDRIG_OT_ui_element_add,
    CLOUDRIG_OT_ui_element_remove,
]