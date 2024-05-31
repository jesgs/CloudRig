import bpy
from bpy.types import Operator, ID, bpy_struct, UILayout
from typing import Optional
from bpy.props import StringProperty, BoolProperty, EnumProperty
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

    op_icon: StringProperty(name="Operator Icon", default='BLANK1', description="Operator Icon")

    @classmethod
    def poll(cls, context):
        return is_active_cloudrig(context) or is_active_cloud_metarig(context)

    @staticmethod
    def path_resolve_safe(owner, data_path):
        try:
            return owner.path_resolve(data_path)
        except:
            return

    def get_data_paths(self, obj) -> tuple[ID, str, str, str, any]:
        data_path = bone_name = self.owner_path
        prop_name = self.prop_name

        # In case a data path wasn't provided, the default property owner is the object itself.
        prop_owner = obj

        if "." in prop_name:
            # If there's a dot in the property name, move the parts before the last dot to the end of the data path instead.
            # Note that this part of the code must come after 
            split = prop_name.split(".")
            data_path += "." + ".".join(split[:-1])
            prop_owner = self.path_resolve_safe(obj, data_path)
            prop_name = split[-1]

        if data_path:
            if self.use_bone:
                # If user wants to use the bone search selector, 
                # we need to help them get the data path to the selected pose bone.
                data_path = f'pose.bones["{bone_name}"]'

            prop_owner = self.path_resolve_safe(obj, data_path)

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
            prop_value = self.path_resolve_safe(obj, full_path)

        return prop_owner, full_path, data_path, prop_name, prop_value

    def invoke(self, context, _event):
        # We create a keymap item to help us draw the operator set-up UI.
        # KeymapItems in the default keymap will not be stored by Blender, 
        # so we don't need to worry about making a mess there.
        self.temp_kmi = context.window_manager.keyconfigs.default.keymaps['Info'].keymap_items.new('', 'NUMPAD_5', 'PRESS')
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        layout = self.layout
        rig = context.active_object
        row = layout.row(align=True)

        prop_owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(rig)

        if not prop_owner:
            row.alert = True

        if self.use_bone:
            row.prop_search(self, 'owner_path', rig.pose, 'bones')
        else:
            row.prop(self, 'owner_path')
        row.prop(self, 'use_bone', icon='BONE_DATA', text="")
        layout.prop(self, 'prop_name')
        if prop_owner:
            text = f'Owner: {type(prop_owner).__name__} '
            if hasattr(prop_owner, 'name'):
                text += prop_owner.name
            else:
                text += str(prop_owner)
            layout.label(text=text)
        else:
            layout.label(text=f'Data path "{self.owner_path}" failed to resolve on {rig.name}.')
            return

        if self.owner_path and not prop_owner:
            row = layout.row(alert=True)
            row.label(text=f"No property owner at '{self.owner_path}' found.", icon='ERROR')

        if not self.prop_name:
            return
        layout.label(text="Data Path: " + full_path)
        if prop_value:
            if type(prop_value) == bpy_struct:
                layout.label(text="Please specify a property name.")
            else:
                layout.label(text=f"Existing property found with a current value of {prop_value}.")
        else:
            layout.label(text="Property will be created with a value of 1.0.")

        layout.separator()
        layout.prop(self, 'panel_name')
        layout.prop(self, 'label_name')
        layout.prop(self, 'row_name')
        layout.prop(self, 'slider_name')
        layout.separator()
        layout.prop(self.temp_kmi, 'idname', text="Operator")
        self.op_kwargs = {}
        if self.temp_kmi.idname:
            box = None
            op_rna = eval("bpy.ops."+self.temp_kmi.idname).get_rna_type()
            for key, value in op_rna.properties.items():
                if key == 'rna_type':
                    continue
                if not box:
                    box = layout.box().column(align=True)
                box.prop(self.temp_kmi.properties, key)
                self.op_kwargs[key] = str(getattr(self.temp_kmi.properties, key))
            icons = UILayout.bl_rna.functions["prop"].parameters["icon"]
            layout.prop_search(self, 'op_icon', icons, 'enum_items', icon=self.op_icon)

    def execute(self, context):
        owner, full_path, owner_path, brackets_prop_name, prop_value = self.get_data_paths(context.active_object)

        if self.prop_name not in owner and self.prop_name not in owner.__dir__():
            # Target is a custom property that doesn't exist yet, so let's create it.
            ensure_custom_property(
                owner,
                self.prop_name
            )

        if not self.slider_name:
            self.slider_name = self.prop_name

        add_property_to_ui(
            context.active_object,
            owner_path=owner_path,
            prop_name=brackets_prop_name,

            panel_name=self.panel_name,
            label_name=self.label_name,
            row_name=self.row_name or self.prop_name,
            slider_name=self.slider_name,

            operator=self.temp_kmi.idname,
            op_icon=self.op_icon,
            op_kwargs=self.op_kwargs
        )

        self.report({'INFO'}, f"Added property {brackets_prop_name} to the rig UI")

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