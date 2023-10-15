from typing import Dict

import bpy
from bpy.props import StringProperty, BoolVectorProperty, BoolProperty, IntProperty
from bpy.types import PropertyGroup, UIList, UI_UL_list, Operator
from rna_prop_ui import rna_idprop_has_properties

from mathutils import Vector, Matrix
from collections import OrderedDict

from bl_ui.generic_ui_list import draw_ui_list
from ..utils.misc import get_addon_prefs
from .bone import BoneInfo, pose_bone_properties, edit_bone_properties, bone_properties

def driver_from_real(fcurve: bpy.types.FCurve) -> dict:
    """Return a dictionary describing the driver."""
    driver = fcurve.driver
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
            collections=["Collection"], color_palette='DEFAULT',
            defaults = {}
        ):
        super().__init__()

        self.rig_component = rig_component

        # kwargs that will be passed to new BoneInfo() instances.
        self.defaults = defaults

        # Name that will be displayed in the Bone Sets UI.
        self.ui_name = ui_name

        # Collection to assign to newly defined BoneInfos.
        self.collections = collections

        # Bone Group name to assign to newly defined BoneInfos.
        self.color_palette = color_palette

    def get(self, name):
        """Find a BoneInfo instance by name, return it if found."""
        for bi in self:
            if bi.name == name:
                return bi
        return None

    def __repr__(self):
        return f"{self.ui_name}: {super().__repr__()}"

    def new(self, name="Bone", source=None, **kwargs):
        """Create and add a new BoneInfo to self."""

        generator = self.rig_component.generator

        # If a BoneInfo with the passed name already exists, something is very wrong!
        # This could be a bug, or not.
        bone_info = generator.find_bone_info(name)
        if bone_info:
            self.rig_component.raise_generation_error(
                description=f"`{name}` was already defined. This could be a bug, but it could also be caused by bones not being named uniquely enough."
            )

        if 'collections' not in kwargs:
            kwargs['collections'] = self.collections
        if 'color_palette_base' not in kwargs:
            kwargs['color_palette_base'] = self.color_palette
        for key in self.defaults.keys():
            if key not in kwargs:
                kwargs[key] = self.defaults[key]

        bone_info = BoneInfo(self, name, source, owner_component=self.rig_component, **kwargs)
        self.append(bone_info)

        return bone_info

    def new_from_real(
            self, 
            rig_ob: bpy.types.Object, 
            edit_bone: bpy.types.EditBone, 
            keep_collections=False, 
            keep_colors=False
        ):
        """Load a bpy bone into a BoneInfo instance along with its constraints, drivers, custom properties."""
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
        if keep_colors:
            if pose_bone.color.palette == 'CUSTOM':
                self.rig_component.add_log("Custom Colors must not be used.")
            else:
                bone_info.color_palette_pose = pose_bone.color.palette
            if data_bone.color.palette == 'CUSTOM':
                self.rig_component.add_log("Custom Colors must not be used.")
            else:
                bone_info.color_palette_base = data_bone.color.palette
        else:
            bone_info.color_palette_base = self.color_palette

        # Load collections
        if keep_collections:
            bone_info.collections = [coll.name for coll in data_bone.collections]
        else:
            bone_info.collections = self.collections

        # Load Constraints.
        for c in pose_bone.constraints:
            ci = bone_info.add_constraint_from_real(c)

        # Load Drivers.
        if rig_ob.animation_data:
            driver_map = self.rig_component.generator.driver_map
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
                    # This should only happen with python dictionaries, let's just ignore them for now. TODO.
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

class BoneSetMixin:
    """Class that provides bone set management to Component_Base."""

    @property
    def bone_infos(self):
        for name, bone_set in self.bone_sets.items():
            for bone_info in bone_set:
                yield bone_info

    def init_bone_set(self, bone_set_prop_name):
        """Take a bone set definition stored in the class and create a single BoneSet for it."""
        rna_bone_set = getattr(self.params.bone_sets, bone_set_prop_name)
        
        assert rna_bone_set, f"Failed to create Bone Set {bone_set_prop_name}. Couldn't find corresponding RNA bone set."

        new_set = BoneSet(self,
            ui_name = rna_bone_set.name,
            collections = [prop.name for prop in rna_bone_set.collections],
            color_palette = rna_bone_set.color_palette,
            defaults = self.defaults
        )

        return new_set

    def init_bone_sets(self):
        """Instantiate all bone sets based on the class's bone_set_defs dictionary."""
        bone_set_defs = type(self).bone_set_defs
        for bone_set_prop_name, bone_set_def in bone_set_defs.items():
            self.bone_sets[bone_set_def['ui_name']] = self.init_bone_set(bone_set_prop_name)

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

        component = active_pb.cloudrig_component
        params = component.params

        if not component.active_bone_set:
            layout.label(text="UI Bone Sets were not yet initialized. This should never happen!")
            return

        active_ui_bone_set = component.active_ui_bone_set
        active_bone_set = getattr(params.bone_sets, active_ui_bone_set.name)
        if not active_bone_set:
            layout.label(text="Could not find Bone Set named " + active_ui_bone_set.name)
            return

        prefs = get_addon_prefs(context)
        list_column = draw_ui_list(
            layout
            ,context
            ,class_name = 'CLOUDRIG_UL_bone_sets'
            ,list_path = f'object.pose.bones["{component.base_bone_name}"].cloudrig_component.ui_bone_sets'
            ,active_index_path = f'object.pose.bones["{component.base_bone_name}"].cloudrig_component.bone_sets_active_index'
            ,insertion_operators = False
            ,move_operators = False
            ,columns=3
            ,unique_id="CloudRig Bone Sets"
        )
        eye_icon = 'HIDE_OFF' if prefs.bone_set_show_advanced else 'HIDE_ON'
        list_column.prop(prefs, 'bone_set_show_advanced', text="", emboss=False, icon=eye_icon)

        if not any(CLOUDRIG_UL_bone_sets.flt_flags):
            layout.label(text="No bone sets to show. Clear the search filter or regenerate the rig.")
            return
        elif not CLOUDRIG_UL_bone_sets.flt_flags[component.bone_sets_active_index]:
            # If the active item is not visible
            return

        box = layout.box()
        box.label(text=f"Collections of {active_bone_set.ui_name}:")
        row = box.row()
        col = row.column()
        col.template_list(
            'CLOUDRIG_UL_bone_set_collections',
            "CloudRig Bone Set Collections",
            active_bone_set,
            'collections',
            active_bone_set,
            'collections_active_index'
        )
        col = row.column()
        col.operator('pose.cloudrig_bone_set_collection_add', icon='ADD', text="")
        col.operator('pose.cloudrig_bone_set_collection_remove', icon='REMOVE', text="")
        col.separator()
        col.operator('pose.cloudrig_bone_set_collection_reset', icon='FILE_REFRESH', text="")

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        """Override in child classes to be able to check for unused bone sets based on current parameters."""
        set_name = set_name.replace(" ", "_").lower()
        bone_set = getattr(params.bone_sets, set_name)
        if bone_set.is_advanced:
            prefs = get_addon_prefs(context)
            return prefs.bone_set_show_advanced
        return True

    ##############################
    # Parameters

    @classmethod
    def define_bone_set(cls, ui_name, collections=[], color_palette='DEFAULT', is_advanced=False):
        """
        A bone set is an RNA PropertyGroup containing properties for choosing bone collections and color.
        This function is responsible for creating the data, which will be used by
        class BoneSets(PropertyGroup) to automagically populate itself during add-on registration.

        For example, all FK chain bones of the FK chain rig are hard-coded to be part of the "FK Main" bone set.
        The "FK Main" bone set's collections and color can be customized via the parameters under
        my_pose_bone.cloudrig_component.bone_sets.fk_main.color_palette/collections.
        """

        prop_name = ui_name.replace(" ", "_").lower()
        cls.bone_set_defs[prop_name] = {
            'name'           : prop_name,
            'ui_name'        : ui_name,
            'collections'    : collections or [ui_name],
            'color_palette'  : color_palette,
            'is_advanced'    : is_advanced,
        }
        return ui_name
    
    @classmethod
    def define_bone_sets(cls):
        # Each class should override this with their define_bone_set() calls.
        # As well as a super().define_bone_sets().

        # This needs to be defined in a function, otherwise every class shares a single instance of this dict.
        # We want each class to have its own instance, so they only store the bone sets they actually define.
        cls.bone_set_defs: Dict[str, str] = OrderedDict()
        pass

##########################
#### Bone Sets UIList ####
##########################

class CLOUDRIG_UL_bone_set_collections(UIList):
    def draw_item(self, context, layout, data, item, icon_value, active_data, active_propname):
        collection = item
        metarig_ob = item.id_data

        row = layout.row()
        split = row.split(factor=0.85)
        split.row().prop_search(collection, 'name', metarig_ob.data, 'collections', icon='OUTLINER_COLLECTION', text="")

class CLOUDRIG_UL_bone_sets(UIList):
    flt_flags = []

    def draw_filter(self, context, layout):
        layout.prop(self, 'filter_name', text="")

    def filter_items(self, context, data, propname):
        flt_flags = []
        flt_neworder = []
        ui_bone_sets = getattr(data, propname)

        helper_funcs = UI_UL_list

        # Always sort alphabetical.
        flt_neworder = helper_funcs.sort_items_by_name(ui_bone_sets, "name")

        # Filter by search string.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, ui_bone_sets, "ui_name")

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

        # Filter to only show bone sets that are relevant to this component type with the current settings.
        metarig = context.object
        prefs = get_addon_prefs(context)
        component = context.active_pose_bone.cloudrig_component
        rig_class = component.rig_class

        for idx, ui_bone_set in enumerate(ui_bone_sets):
            if ui_bone_set.name not in rig_class.bone_set_defs:
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

        type(self).flt_flags = flt_flags
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, _data, item, _icon_value, _active_data, _active_propname):
        ui_bone_set = item
        component = _data
        bone_set = getattr(component.params.bone_sets, ui_bone_set.name)

        row = layout.row()
        row.label(text=ui_bone_set.ui_name)
        row.prop(bone_set, 'color_palette', text="")

class CLOUDRIG_OT_bone_set_collection_add(Operator):
    """Add bone set collection"""
    bl_idname = "pose.cloudrig_bone_set_collection_add"
    bl_label = "Add Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        bone_set = context.active_pose_bone.cloudrig_component.active_bone_set
        bone_set.collections.add()
        self.report({'INFO'}, f"Added collection slot to {bone_set.ui_name}.")
        return {'FINISHED'}

class CLOUDRIG_OT_bone_set_collection_remove(Operator):
    """Remove bone set collection"""
    bl_idname = "pose.cloudrig_bone_set_collection_remove"
    bl_label = "Remove Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        component = context.active_pose_bone.cloudrig_component
        bone_set = component.active_bone_set
        if len(bone_set.collections) == 1:
            cls.poll_message_set("Collection list cannot be empty. You can reset it with the button below.")
            return False
        return True

    def execute(self, context):
        component = context.active_pose_bone.cloudrig_component
        bone_set = component.active_bone_set
        coll_name = bone_set.collections[bone_set.collections_active_index].name
        bone_set.collections.remove(bone_set.collections_active_index)
        self.report({'INFO'}, f"{bone_set.ui_name} will not be assigned to '{coll_name}' collection.")
        return {'FINISHED'}

class CLOUDRIG_OT_bone_set_collection_reset(Operator):
    """Reset collection assignments of this Bone Set to the default list"""
    bl_idname = "pose.cloudrig_bone_set_collection_reset"
    bl_label = "Reset Collections"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        component = context.active_pose_bone.cloudrig_component
        component.reset_collections_of_bone_set(component.active_bone_set)
        self.report({'INFO'}, f"{component.active_bone_set.ui_name} collection assignments reset to default.")
        return {'FINISHED'}

registry = [
    CLOUDRIG_UL_bone_sets,
    CLOUDRIG_OT_bone_set_collection_add,
    CLOUDRIG_OT_bone_set_collection_remove,
    CLOUDRIG_OT_bone_set_collection_reset,
    CLOUDRIG_UL_bone_set_collections
]
