from typing import Dict

import bpy
from bpy.props import StringProperty, BoolVectorProperty, BoolProperty, IntProperty
from bpy.types import PropertyGroup, UIList, UI_UL_list
from rna_prop_ui import rna_idprop_has_properties

from mathutils import Vector, Matrix
from collections import OrderedDict

from ..utils.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs
from .bone import BoneInfo, pose_bone_properties, edit_bone_properties, bone_properties

def driver_from_real(fcurve: bpy.types.FCurve) -> dict:
    driver = fcurve.driver
    """Return a dictionary describing the driver."""
    driver_info = {
        'type' : driver.type
        ,'variables' : []
        ,'index' : fcurve.array_index
    }
    if driver.type=='SCRIPTED':
        driver_info['expression'] = driver.expression
    for var in driver.variables:
        driver_info['variables'].append({
            'name' : var.name
            ,'type' : var.type
            ,'targets' : []
        })
        for t in var.targets:
            target_info = {
                'id' : t.id
            }
            if var.type == 'SINGLE_PROP':
                target_info['id_type'] = t.id_type
                target_info['data_path'] = t.data_path
            else:
                target_info['bone_target'] = t.bone_target
                target_info['transform_type'] = t.transform_type
                target_info['transform_space'] = t.transform_space
                target_info['rotation_mode'] = t.rotation_mode
            driver_info['variables'][-1]['targets'].append(target_info)
    return driver_info

class LinkedList(list):
    """Some very basic doubly linked list functionality to help manage chains of bones."""
    def __init__(self):
        super().__init__()
        self.first = self.last = None

    def remove(self, value):
        super().remove(value)
        if value.prev:
            value.prev.next = value.next
        if value.next:
            value.next.prev = value.prev

    def append(self, value):
        if len(self)>0:
            self[-1].next = value
            value.prev = self[-1]
        super().append(value)

class BoneSet(LinkedList):
    """ Class to create and store lists of BoneInfo instances.
        Also responsible for bone group layer assignment.
    """

    def __init__(self, rig_component, ui_name="Bone Set",
            collection="Collection", color_palette='DEFAULT',
            defaults = {}
        ):
        super().__init__()

        self.rig_component = rig_component

        # kwargs that will be passed to new BoneInfo() instances.
        self.defaults = defaults

        # Name that will be displayed in the Bone Sets UI.
        self.ui_name = ui_name

        # Collection to assign to newly defined BoneInfos.
        self.collection = collection # TODO 4.0 This needs to be a list, and in turn a CollectionProperty...

        # Bone Group name to assign to newly defined BoneInfos.
        self.color_palette = color_palette

    def find(self, name):
        """Find a BoneInfo instance by name, return it if found."""
        for bi in self:
            if bi.name == name:
                return bi
        return None

    def __repr__(self):
        return f"{self.ui_name}: {super().__repr__()}"

    def new(self, name="Bone", source=None, **kwargs):
        """Create and add a new BoneInfo to self."""

        if hasattr(self.rig_component, 'generator'):
            generator = self.rig_component.generator
        else:
            # Since the generator can also be a rig component...
            generator = self.rig_component

        # If a BoneInfo with the passed name already exists, something is very wrong!
        bone_info = generator.find_bone_info(name)
        if bone_info:
            self.raise_metarig_error(f'Bone name "{bone_info.name}" was used twice! Make sure your bone names are unique and do not have trailing zeroes!')

        if 'collection' not in kwargs:
            kwargs['collection'] = self.collection
        if 'color_palette_base' not in kwargs:
            kwargs['color_palette_base'] = self.color_palette
        for key in self.defaults.keys():
            if key not in kwargs:
                kwargs[key] = self.defaults[key]

        bone_info = BoneInfo(self, name, source, **kwargs)
        self.append(bone_info)
        generator.bone_infos.append(bone_info)
        bone_info.owner_rig = self.rig_component

        return bone_info

    def new_from_real(self, rig_ob: bpy.types.Object, edit_bone: bpy.types.EditBone):
        """Load a bpy bone into a BoneInfo class along with its constraints, drivers, custom properties."""
        # NOTE: Parenting should be done outside of this function, 
        # since parent bone info is not guaranteed to exist.

        pose_bone = rig_ob.pose.bones.get(edit_bone.name)
        data_bone = pose_bone.bone
        bone_info = self.new(name=edit_bone.name)

        sources = {
            pose_bone : pose_bone_properties
            ,data_bone : bone_properties
            ,edit_bone : edit_bone_properties
        }

        for source, prop_list in sources.items():
            for key in prop_list:
                value = getattr(source, key)
                if value in [None, ""]: continue
                if key == 'collections':
                    value = [coll.name for coll in value]
                if type(value) in [Vector, Matrix]:
                    value = value.copy()
                setattr(bone_info, key, value)

        # The default value of use_deform in Blender is True, but for CloudRig, False makes a LOT more sense.
        bone_info.use_deform = False

        # Load color palettes (only presets are supported, no custom colors)
        bone_info.color_palette_pose = pose_bone.color.palette
        bone_info.color_palette_base = data_bone.color.palette

        # Load Constraints.
        for c in pose_bone.constraints:
            ci = bone_info.add_constraint_from_real(c)

        # Load Drivers.
        if rig_ob.animation_data:
            driver_map = self.rig_ob.generator.driver_map
            if bone_info.name in driver_map:
                for data_path, array_index in driver_map[bone_info.name]:
                    fcurve = rig_ob.animation_data.drivers.find(data_path, index=array_index)
                    path_from_last = "." + data_path.split('"].')[-1]
                    if path_from_last.endswith('"]'):
                        path_from_last = "[" + path_from_last.split("][")[-1]
                    driver_info = driver_from_real(fcurve)
                    driver_info['prop'] = path_from_last
                    if 'constraints' in fcurve.data_path:
                        con_name = data_path.split('constraints["')[-1].split('"]')[0]
                        constraint_info = bone_info.get_constraint(con_name)
                        if constraint_info:
                            constraint_info.drivers.append(driver_info)
                    else:
                        bone_info.drivers.append(driver_info)
                    rig_ob.animation_data.drivers.remove(fcurve)

        # Load Custom Properties.
        if rna_idprop_has_properties(pose_bone):
            rna_properties = {prop.identifier for prop in pose_bone.bl_rna.properties if prop.is_runtime}
            for prop_name in pose_bone.keys():
                if prop_name in rna_properties:
                    # We don't want to reset addon-defined properties.
                    continue
                if prop_name[0] in "_$": continue
                try:
                    prop_data = pose_bone.id_properties_ui(prop_name).as_dict()
                except TypeError:
                    # This should only happen with python dictionaries, let's just ignore them for now.
                    prop_data = {'default': pose_bone[prop_name]}

                value = pose_bone[prop_name]
                if hasattr(value, 'to_list'):
                    value = value.to_list()
                    prop_data['default'] = value
                elif hasattr(value, 'to_dict'):
                    value = value.to_dict()
                    prop_data['default'] = value

                prop_data['value'] = value
                prop_data['overridable'] = pose_bone.is_property_overridable_library(f'["{prop_name}"]')
                bone_info.custom_props[prop_name] = prop_data

        return bone_info

    def ensure_bone_group(self, rig_ob, overwrite=False):
        """ Create the bone group defined by this bone set on rig_ob. """

        bone_group = rig_ob.pose.bone_groups.get(self.bone_group)
        if bone_group and not overwrite:
            return bone_group

        if not bone_group:
            bone_group = rig_ob.pose.bone_groups.new(name=self.bone_group)

        bone_group.color_set = self.color_set
        bone_group.colors.normal = self.normal[:]
        bone_group.colors.select = self.select[:]
        bone_group.colors.active = self.active[:]

        return bone_group

class BoneSetMixin:
    """Class that provides bone set management to Component_Base."""
    bone_set_defs: Dict[str, str] = OrderedDict()

    def init_bone_set(self, bone_set_name):
        """Take a bone set definition stored in the class and create a single BoneSet for it."""
        rna_name = bone_set_name.lower().replace(" ", "_")
        rna_bone_set = getattr(self.params.bone_sets, rna_name)
        
        assert rna_bone_set, f"Failed to create Bone Set {rna_name}. Couldn't find corresponding RNA bone set."

        new_set = BoneSet(self,
            ui_name = rna_bone_set.name,
            # collection = "",  # TODO 4.0 collections
            # color_palette = rna_bone_set.color_palette,
            defaults = self.defaults
        )

        self.generator.bone_sets.append(new_set)

        return new_set

    def init_bone_sets(self):
        """Instantiate all bone sets based on the class's bone_set_defs dictionary."""
        bone_set_defs = type(self).bone_set_definitions
        for bone_set_name in bone_set_defs.keys():
            ui_name = bone_set_name.replace("_", " ").title()
            self.bone_sets[ui_name] = self.init_bone_set(bone_set_name)

    ##############################
    # UI
    @classmethod
    def draw_bone_sets_list(cls, layout, context, params):
        """Drawing the Bone Sets section of the Rigify Parameters."""
        metarig = context.object
        cloudrig = metarig.data.cloudrig
        active_pb = context.active_pose_bone
        if not active_pb.cloudrig_component.component_type:
            return
        params = active_pb.cloudrig_component.params

        if (
            len(cloudrig.ui_bone_sets) == 0 or \
            cloudrig.active_bone_set_idx > len(cloudrig.ui_bone_sets)
        ):
            layout.label(text="UI Bone Sets were not yet initialized. This should never happen!")
            return

        active_ui_bone_set = cloudrig.ui_bone_sets[cloudrig.active_bone_set_idx]
        active_bone_set = getattr(params.bone_sets, active_ui_bone_set.name)
        if not active_bone_set:
            layout.label(text="Could not find Bone Set named " + active_ui_bone_set.name)
            return

        prefs = get_addon_prefs(context)
        list_column = draw_ui_list(
            layout
            ,context
            ,class_name = 'CLOUDRIG_UL_bone_sets'
            ,list_path = 'object.data.cloudrig.ui_bone_sets'
            ,active_index_path = 'object.data.cloudrig.active_bone_set_idx'
            ,insertion_operators = False
            ,move_operators = False
            ,type='GRID' if prefs.bone_set_use_grid_layout else 'DEFAULT'
            ,columns=3
        )
        eye_icon = 'HIDE_OFF' if prefs.bone_set_show_advanced else 'HIDE_ON'
        list_column.prop(prefs, 'bone_set_show_advanced', text="", emboss=False, icon=eye_icon)
        layout_icon = 'MESH_GRID' if prefs.bone_set_use_grid_layout else 'COLLAPSEMENU'
        list_column.prop(prefs, 'bone_set_use_grid_layout', text="", emboss=False, icon=layout_icon)

        # elif not CLOUDRIG_UL_bone_sets.flt_flags[cloudrig.active_bone_set_idx]:
        #     # If the active item is not visible
        #     return

        # set_info = cls.bone_set_defs[active_bone_set.name]
        # split = layout.row().split(factor=0.8)
        # cls.draw_prop_search(context, split.row(), params, set_info['color_param'], obj.pose, "bone_groups", text="Bone Group")
        # bone_group_name = getattr(params, set_info['color_param'])
        # bone_group = obj.pose.bone_groups.get(bone_group_name)
        # if bone_group:
        #     row = split.row(align=True)

        #     if bone_group.color_set != 'DEFAULT':
        #         row.prop(bone_group, 'color_set', text="", icon_only=True)
        #         row = row.row(align=True)
        #         row.enabled = bone_group.is_custom_color_set
        #         row.prop(bone_group.colors, "normal", text="")
        #         row.prop(bone_group.colors, "select", text="")
        #         row.prop(bone_group.colors, "active", text="")
        #     else:
        #         row.prop(bone_group, 'color_set', text="", icon='DOWNARROW_HLT')

        # layout.use_property_split=False
        # draw_layers_ui(
        #     layout = layout, 
        #     rig = obj, 
        #     show_unnamed_selected_layers = True,
        #     show_hidden_checkbox = True, 
        #     layer_prop_owner = params, 
        #     layer_prop_name = set_info['collection_param']
        # )


    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        """Override in child classes to be able to check for unused bone sets based on current parameters."""
        bone_set = getattr(params.bone_sets, set_name)
        if bone_set.is_advanced:
            prefs = get_addon_prefs(context)
            return prefs.bone_set_show_advanced
        return True

    ##############################
    # Parameters

    @classmethod
    def define_bone_set(cls, params, ui_name, default_group="", default_layers=[0], is_advanced=False, preset=-1):
        """
        A bone set is a set of rig parameters for choosing a bone group and list of bone layers.
        This function is responsible for creating those rig parameters, as well as storing them,
        so they can be referenced easily when implementing the creation of a new bone
        and assigning its bone group and layers.

        For example, all FK chain bones of the FK chain rig are hard-coded to be part of the "FK Main" bone set.
        Then the "FK Main" bone set's bone group and bone layer can be customized via the parameters.
        """
        group_name = ui_name.replace(" ", "_").lower()
        if default_group=="":
            default_group = ui_name

        color_param_name = "BoneSet_Color_" + group_name.replace(" ", "_")
        collection_param_name = "BoneSet_Collection_" + group_name.replace(" ", "_")

        setattr(
            params,
            color_param_name,
            StringProperty( # TODO 4.0 collections: This should be an enumprop, mimicing the bone color preset drop-down.
                default = default_group,
                description = f"Select what group {ui_name} should be assigned to"
            )
        )

        default_layers_bools = [i in default_layers for i in range(32)]
        setattr(
            params,
            collection_param_name,
            BoolVectorProperty( # TODO 4.0 collections: This should be a StringProp... somehow matching to the collections. Ideally in a way where renaming collections is possible, see how Rigify does that.
                size = 32,
                subtype = 'LAYER',
                description = f"Select what layers {ui_name} should be assigned to",
                default = default_layers_bools
            )
        )

        # TODO: Why are we not just creating a class-level BoneSet instance to store here?
        # Even if that's not a good idea, we could make a UIBoneSet class and instance that.
        cls.bone_set_defs[ui_name] = {
            'name'              : ui_name
            ,'preset'           : preset                 # Bone Group color preset to use in case the bone group doesn't already exist.
            ,'color_param'      : color_param_name       # Name of the bone color parameter
            ,'collection_param' : collection_param_name  # Name of the bone collection parameter
            ,'is_advanced'      : is_advanced
        }
        print("Defined bone set: ", ui_name)
        return ui_name

##########################
#### Bone Sets UIList ####
##########################
class UIBoneSet(PropertyGroup):
    """This class is to bridge the data between Blender's UI and the generator."""
    # The reason we can't use this for the actual Bone Set class used during generation is that
    # the properties of the bone set must be defined during registration, and CollectionProperties
    # are not yet ready at that time. (They only become "real" after registration is complete.)
    bone: StringProperty()
    param_name: StringProperty(description="Name of the Rigify Parameter holding the bone group name")
    collection_param: StringProperty(description="Name of the Rigify Parameter holding the bone layer BoolVectorProperty")

class CLOUDRIG_UL_bone_sets(UIList):
    def draw_filter(self, context, layout):
        layout.prop(self, 'filter_name', text="")

    def filter_items(self, context, data, propname):
        flt_flags = []
        flt_neworder = []
        ui_bone_sets = getattr(data, propname)

        helper_funcs = UI_UL_list

        # Always sort alphabetical.
        flt_neworder = helper_funcs.sort_items_by_name(ui_bone_sets, "name")

        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, ui_bone_sets, "pretty_name")

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

        metarig = context.object
        prefs = get_addon_prefs(context)
        component = context.active_pose_bone.cloudrig_component
        rig_class = component.rig_class

        for idx, ui_bone_set in enumerate(ui_bone_sets):
            if ui_bone_set.name not in rig_class.bone_set_definitions:
                flt_flags[idx] = 0
            else:
                bone_set = getattr(component.params.bone_sets, ui_bone_set.name)
                if not prefs.bone_set_show_advanced and bone_set.is_advanced:
                    # Filter advanced bone sets when the user doesn't want to see them.
                    flt_flags[idx] = 0
                    continue
                if not rig_class.is_bone_set_used(context, metarig, component.params, ui_bone_set.name):
                    # Filter bone sets that are not used based on current parameters.
                    flt_flags[idx] = 0

        return flt_flags, flt_neworder

    def draw_item(self, _context, layout, _data, item, _icon_value, _active_data, _active_propname):
        ui_bone_set = item
        pretty_name = ui_bone_set.pretty_name
        # param_layers = getattr(pb.cloudrig_component.params, ui_bone_set.collection_param)
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.label(text=pretty_name)
            # layer_names = ", ".join([layer.name for i, layer in enumerate(rigify_layers) if param_layers[i]])
            # row.label(text=layer_names)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text=pretty_name)

registry = [
    UIBoneSet
    ,CLOUDRIG_UL_bone_sets
]
