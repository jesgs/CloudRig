from bpy.types import Operator, ID, bpy_struct
from typing import Optional
from bpy.props import StringProperty, BoolProperty
from collections import OrderedDict
from ..generation.cloudrig import is_active_cloudrig, is_active_cloud_metarig, tuples_to_dict, dict_to_tuples
from rna_prop_ui import rna_idprop_ui_create
from rna_prop_ui import rna_idprop_quote_path as quote_property


class CLOUDRIG_OT_add_property_to_ui(Operator):
    bl_idname = "pose.cloudrig_add_property_to_ui"
    bl_label = "Add Property To UI"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    owner_path: StringProperty(name="Property Owner", description="Python path from the rig to the owner of the property")
    use_bone: BoolProperty(name="Use Bone", description="Display a bone selector", default=True)
    prop_name: StringProperty(name="Property Name", description="Name of the property. It can already exist, otherwise it will be created with a value of 1.0")

    panel_name: StringProperty(name="Panel Name", default="Properties", description="The sub-panel that this property should be displayed in")
    label_name: StringProperty(name="Label Name", description="If provided, the property will be placed below this label")
    row_name: StringProperty(name="Row Name", default="", options={'SKIP_SAVE'}, description="Properties that share a Row Name will be displayed in the same row. If none provided, will use the property name as fallback")
    slider_name: StringProperty(name="Slider Name", description="Override the display name of the property")

    operator: StringProperty(name="Operator Name", description="Draw this operator next to the property")
    op_icon: StringProperty(name="Operator Icon", default='BLANK1', description="Operator Icon")
    op_kwargs: StringProperty(name="Operator Arguments", description="Operator Arguments, provided as a Python dictionary")

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context) or is_active_cloud_metarig(context)

    def get_data_paths(self, obj) -> tuple[ID, str, str, str]:
        data_path = self.owner_path
        prop_name = self.prop_name
        if self.use_bone:
            data_path = f'pose.bones["{data_path}"]'

        try:
            prop_owner = obj.path_resolve(data_path)
        except ValueError:
            return None, "", "", ""

        dot = "."
        if prop_name not in prop_owner.__dir__():
            dot = ""
            prop_name = f'["{prop_name}"]'

        full_path = data_path + dot + prop_name

        return prop_owner, full_path, data_path, prop_name

    def draw(self, context):
        layout = self.layout
        rig = context.active_object
        row = layout.row(align=True)
        if self.use_bone:
            row.prop_search(self, 'owner_path', rig.pose, 'bones')
        else:
            row.prop(self, 'owner_path')
        row.prop(self, 'use_bone', icon='BONE_DATA', text="")
        layout.prop(self, 'prop_name')
        full_path = self.get_data_paths(rig)[1]
        if self.owner_path and self.prop_name:
            if not full_path:
                row = layout.row(alert=True)
                row.label(text=f"Property owner '{self.owner_path}' not found.", icon='ERROR')
            else:
                layout.label(text=full_path)
        layout.separator()
        layout.prop(self, 'panel_name')
        layout.prop(self, 'label_name')
        layout.prop(self, 'row_name')
        layout.prop(self, 'slider_name')
        layout.separator()
        layout.prop(self, 'operator')
        if self.operator:
            layout.prop(self, 'op_icon')
            layout.prop(self, 'op_kwargs')

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=600)

    def execute(self, context):
        owner, _, owner_path, brackets_prop_name = self.get_data_paths(context.active_object)
        
        if self.prop_name not in owner and self.prop_name not in owner.__dir__():
            # Target is a custom property that doesn't exist yet, so let's create it.
            ensure_custom_property(
                owner,
                self.prop_name
            )

        add_property_to_ui(
            context.active_object,
            owner_path=owner_path,
            prop_name=brackets_prop_name,

            panel_name=self.panel_name,
            label_name=self.label_name,
            row_name=self.row_name or self.prop_name,
            slider_name=self.slider_name,

            operator=self.operator,
            op_icon=self.op_icon,
            op_kwargs=self.op_kwargs
        )
        return {'FINISHED'}

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
    obj,
    owner_path: str,
    prop_name: str,
    *,
    texts={},
    children={},

    panel_name: str,
    label_name="",
    row_name="",
    slider_name="",

    operator="",
    op_icon='BLANK1',
    op_kwargs={},

    parent_id="",
) -> OrderedDict:
    # Convert existing UI data to an OrderedDict for easy operations.
    if 'ui_data' not in obj.data:
        obj.data['ui_data'] = {'panels' : []}
    panels = obj.data['ui_data'].to_dict()['panels']
    panels = tuples_to_dict(panels)

    panel = panels.setdefault(panel_name, OrderedDict())
    panel['parent_id'] = parent_id
    header = panel.setdefault(label_name, OrderedDict())
    row = header.setdefault(row_name, OrderedDict())

    if not slider_name:
        slider_name = prop_name

    texts = {str(key): value for key, value in texts.items()}
    children = {str(key): value for key, value in children.items()}
    row[slider_name] = {'owner_path':owner_path, 'prop_name':prop_name, 'texts':texts, 'children':children, 'operator': operator, 'op_icon': op_icon, 'op_kwargs': op_kwargs}

    # Convert back to a list of tuples so Blender can store it without mangling it.
    panels = {'panels' : dict_to_tuples(panels)}
    obj.data['ui_data'] = panels

    return panels


registry = [
    CLOUDRIG_OT_add_property_to_ui
]