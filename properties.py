import bpy
from bpy.props import (
    StringProperty, PointerProperty, BoolProperty, BoolVectorProperty, 
    CollectionProperty, IntProperty
)
from bpy.types import PropertyGroup, Object
from typing import Dict
from . import rig_components
from . import rig_component_features
from .generation.cloud_generator import GeneratorProperties

def get_param_classes() -> Dict:
    param_classes = {}
    module_dicts = (rig_components.rig_modules, rig_component_features.component_feature_modules)
    for module_dict in module_dicts:
        for module_name, module in module_dict.items():
            if hasattr(module, 'Params'):
                param_classes[module_name.replace("cloud_", "")] = module.Params
    return param_classes

class GeneratedBone(PropertyGroup):
    name: StringProperty()

class BoneSet_ForUI(PropertyGroup):
    """I want to draw Bone Sets in a UIList, but for that, they need to be a CollectionProperty,
    which I want to avoid for the reasons explained in the docstring of class BoneSets.

    So, we have this layer on top of that, just so we can display Bone Sets in a UIList.
    """
    name: StringProperty()

    @property
    def pretty_name(self) -> str:
        return self.name.replace("_", " ").title().replace("Fk", "FK").replace("Ik", "IK")

class BoneSets(PropertyGroup):
    """
        We could've simply created a class BoneSet(PropertyGroup) and then make a CollectionProperty of that, yes.
        But that would have a lot of downsides:
            1. Every entry in a CollectionProperty has the same default values. 
            This would mean that users can't reset Bone Set properties to useful defaults.
            2. Entries of CollectionProperties exist on individual Blender datablocks, which means, they
            cannot be populated during register().
            This could admittedly be worked around by initializing the Bone Sets on some update() callback.
            3. Accessing Bone Sets in the rig generation code would have to be done by name, 
            eg. `params.bone_sets['FK Chain']`. It's technically possible for user to change the 
            Bone Set's name to anything, which would result in errors and workarounds.

        So, what do we do instead? 
        We let each BoneSet be its own unique PropertyGroup!
        This way they're created during register(), and always exist on every PoseBone.
        1. Unique default values can be defined per Bone Set. User can reset to proper defaults using mouse hover + backspace.
        2. No need for update callback shennanigans to initialize Bone Sets.
        3. Accessing Bone Sets is done via symbols instead of strings, eg. `params.bone_sets.fk_chain`

        And how do we do it?
            Python lets us define classes dynamically using the type() function.
            Blender's PyAPI just wants a class that subclasses bpy.types.PropertyGroup, and
            has annotations whose values are whatever Blender returns from its bpy.props.WhateverProperty() functions.
            Python lets us define those annotations dynamically as well, by setting 
            a class's `__annotations__` dictionary, which is a built-in Python variable.

        And we actually do this twice here:
        - Once, when dynamically defining individual BoneSet PropertyGroup classes, in class_from_definition
        - Again, when assigning a PointerProperty to the BoneSets PropertyGroup for each BoneSet.

        Last important thing: We must store references to the classes that we dynamically defined, in order
        to be able to register them. So, we store those references in the class definition, and then add them to
        `registry`. All classes in the `registry` list will get registered and unregistered by the root level
        __init__.py.
    """

    @staticmethod
    def class_from_definition(bone_set_name: str, bone_set_definition: dict) -> type:
        pretty_name = bone_set_name.replace("_", " ").title()
        annotations = {
            'name' : StringProperty(
                name = "Bone Set Name",
                description = "Name of this Bone Set in the UI. Defined by rig type implementation, should not be modified by user",    # Although it technically shouldn't break anything if user changes this name, it's not used for anything other than UI display.
                default = bone_set_definition.get('name') or pretty_name
            ),
            'bone_group' : StringProperty(
                name = "Bone Group",
                description = "Name of the Bone Group that bones in this Bone Set will be assigned to during generation",
                default = bone_set_definition.get('bone_group') or pretty_name,
            ),
            'layers': BoolVectorProperty(
                name = 'Armature Layers',
                description = "Armature layers that bones in this Bone Set will be assigned to during generation",
                size = 32,
                subtype = 'LAYER',
                default = [i in ([bone_set_definition.get('default_layer')] or [0]) for i in range(32)]
            ),
            'color_preset' : IntProperty(
                name = "Color Preset",
                description = "Index of the built-in color preset to use for the Bone Group of this Bone Set",
                default = bone_set_definition.get('preset') or 1
            ),
            'is_advanced': BoolProperty(
                name = "Is Advanced",
                description = "If True, this Bone Set will only be displayed in the UI when the 'Show Advanced Bone Sets' toggle is checked",
                default = bone_set_definition.get('is_advanced') or False
            ),
            'generated_bones': CollectionProperty(
                name = "Generated Bones",
                description = "List of bone names generated in this Bone Set during the last time the target rig was generated",
                type=GeneratedBone
            )
        }

        class_name = "BoneSet_" + bone_set_name
        base_classes = (PropertyGroup, )
        class_attributes = {
            '__annotations__' : annotations
        }

        bone_set_class = type(class_name, base_classes, class_attributes)

        return bone_set_class

    def make_bone_set_property_groups() -> Dict[str, type]:
        classes = {}
        for rig_type_name, rig_module in rig_components.rig_modules.items():
            rig_class = getattr(rig_module, 'RigComponent')
            if not hasattr(rig_class, 'bone_set_definitions'):
                continue
            for bone_set_name, bone_set_definition in rig_class.bone_set_definitions.items():
                if bone_set_name in classes:
                    continue
                bone_set_class = BoneSets.class_from_definition(bone_set_name, bone_set_definition)
                classes[bone_set_name] = bone_set_class
        return classes

    bone_set_property_groups = make_bone_set_property_groups()

    __annotations__ = {
        name : PointerProperty(type=bone_set_class)
        for name, bone_set_class in bone_set_property_groups.items()
    }

class ComponentParams(PropertyGroup):
    # TODO: Some params would have to be grabbed from the rig_component_features package.

    __annotations__ = {
        name : PointerProperty(type=param_class)
        for name, param_class in get_param_classes().items()
    }
    
    bone_sets: PointerProperty(type=BoneSets)

def refresh_component_bones_list(context):
    addon_prefs = context.preferences.addons[__package__].preferences
    
    rig_ob = context.object
    cloudrig = rig_ob.data.cloudrig
    components = rig_ob.data.cloudrig.rig_component_bones
    active_comp = cloudrig.active_component

    owner_pb = None
    if active_comp and active_comp.bone:
        owner_pb = active_comp.owner_pose_bone

    components.clear()
    for pb in rig_ob.pose.bones:
        elem_type = pb.cloudrig_component.component_type
        if elem_type:
            rig_component_bone = cloudrig.rig_component_bones.add()
            rig_component_bone.name = pb.name
            module_name = addon_prefs.rig_type_list[elem_type].module_name
            pb.cloudrig_component.component_module_name = module_name
            pb.cloudrig_component.owner_bone_name = pb.name

    # Initialize UI Bone Sets, if not already done.
    for rig_type_name, rig_module in rig_components.rig_modules.items():
        rig_class = getattr(rig_module, 'RigComponent')
        if not hasattr(rig_class, 'bone_set_definitions'):
            continue

        for bone_set_name, bone_set_definition in rig_class.bone_set_definitions.items():
            ui_bone_sets = rig_ob.data.cloudrig.ui_bone_sets
            if bone_set_name in ui_bone_sets:
                continue
            ui_bone_set = ui_bone_sets.add()
            ui_bone_set.name = bone_set_name

    # Reset the active element to the one belonging to the same PoseBone as before.
    if owner_pb:
        for i, comp in enumerate(components):
            if comp.owner_pb == owner_pb:
                cloudrig.active_rig_component_index = i

class RigComponent(PropertyGroup):
    """This PropertyGroup lives on PoseBones, so it cannot be used in the UIList.
    Still, it is important to store it on the bone, so that when a bone is duplicated,
    this information is duplicated with it.
    """
    owner_bone_name: StringProperty(
        name="Owner Bone",
        description="Name of the bone this RigComponent is on. This is updated by interacting with the list UI, since it can fall out of sync by bone renaming or bone duplication"
    )
    @property
    def owner_pose_bone(self):
        return self.id_data.pose.bones.get(self.owner_bone_name)

    component_type: StringProperty(
        name="Component Type", 
    )
    component_module_name: StringProperty()

    @property
    def component_module(self):
        return rig_components.rig_modules.get(self.component_module_name)

    @property
    def rig_class(self) -> type:
        if not self.component_module:
            return
        return getattr(self.component_module, 'RigComponent')

    def instantiate(self, generator) -> 'RigComponent':
        return self.rig_class(generator=generator, bone_name=self.owner_bone_name)

    params: PointerProperty(type=ComponentParams)


class Properties_CloudRig(PropertyGroup):
    enabled: BoolProperty(
        name="CloudRig",
        description="Whether this armature is a CloudRig metarig",
        default=False
    )

    version: IntProperty(
        name         = "CloudRig MetaRig Version"
        ,description = "For internal use only"
        ,default     = -1
    )

    @property
    def rig_component_bones(self):
        rig = bpy.context.object
        return [pb.cloudrig_component for pb in rig.pose.bones if pb.cloudrig_component.component_type]

    def select_bone_of_component(self, context):
        rig = context.object
        for bone in rig.data.bones:
            bone.select = False
        rig.data.bones.active = rig.data.bones[self.active_component_index]

    active_component_index: IntProperty(description="Active CloudRig Component", update=select_bone_of_component)

    @property
    def active_component(self):
        if len(self.rig_component_bones) == 0:
            return

        # TODO 4.0: Unsafe index-based access here, but figure out how to keep that index clamped.
        return self.rig_component_bones[self.active_rig_component_index]

    generator: PointerProperty(type=GeneratorProperties)

    metarig_version: IntProperty()

    ui_bone_sets: CollectionProperty(type=BoneSet_ForUI)
    active_bone_set_idx: IntProperty()


registry = [GeneratedBone] + list(get_param_classes().values()) + list(BoneSets.bone_set_property_groups.values()) + [
    BoneSet_ForUI,
    BoneSets,
    ComponentParams,
    RigComponent,
    Properties_CloudRig
]

def register():
    # It might make sense to store things on Bone instead of PoseBone,
    # but PoseBone, being stored on Object, has access to the Object via id_data,
    # which can be handy.
    bpy.types.PoseBone.cloudrig_component = PointerProperty(type=RigComponent)

    # TODO: For the same reason as above, we should probably store this on Object.
    bpy.types.Armature.cloudrig = PointerProperty(type=Properties_CloudRig)

def unregister():
    del bpy.types.Armature.cloudrig
