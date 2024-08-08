from ..generation.cloudrig import CloudRig_UIElement
from bpy.types import Operator 

class CLOUDRIG_OT_ui_element_add(Operator):
    """Add a UI element"""
    
    bl_idname = "object.cloudrig_ui_element_add"
    bl_label = "Add Property to UI"
    bl_options = {'REGISTER', 'UNDO'}

    # Copy the definition of a single UIElement, which will be added 
    # by this operator, when the "OK" button is clicked.
    __annotations__ = CloudRig_UIElement.__annotations__

    def execute(self, context):
        return {'FINISHED'}
    
    

registry = [
    CLOUDRIG_OT_ui_element_add
]