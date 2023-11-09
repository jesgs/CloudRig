import bpy
from bpy.props import (
    StringProperty,
    PointerProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
    IntProperty,
)
from bpy.types import PropertyGroup, Object
from typing import Dict, Optional
from . import rig_components
from . import rig_component_features
from .generation.cloud_generator import GeneratorProperties
from .utils.misc import get_addon_prefs


def get_param_classes() -> Dict:
    param_classes = {}
    module_dicts = (
        rig_components.component_modules,
        rig_component_features.component_feature_modules,
    )
    for module_dict in module_dicts:
        for module_name, module in module_dict.items():
            if hasattr(module, 'Params'):
                param_classes[module_name.replace("cloud_", "")] = module.Params
    return param_classes


class NameProperty(PropertyGroup):
    name: StringProperty()


class BoneSet_ForUI(PropertyGroup):
    """I want to draw Bone Sets in a UIList, but for that, they need to be a CollectionProperty,
    which I want to avoid for the reasons explained in the docstring of class BoneSets.

    So, we have this layer on top of that, just so we can display Bone Sets in a UIList.
    """

    name: StringProperty()
    ui_name: StringProperty()


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
    def class_from_definition(rna_name: str, bone_set_definition: dict) -> type:
        annotations = {
            'name': StringProperty(
                name="Property Name",
                description="Internal name of the bone set",
                default=bone_set_definition.get('name'),
            ),
            'ui_name': StringProperty(
                name="Bone Set Name",
                description="Name of this Bone Set in the UI. Defined by implementation of component types, should not be modified by user",
                default=bone_set_definition.get('ui_name'),
            ),
            'collections': CollectionProperty(
                name="Bone Collections",
                description="Select a collection",
                type=NameProperty,
            ),
            'collections_active_index': IntProperty(
                name="Bone Set Collection Active Index",
                description="Name of the Bone Collections that bones in this Bone Set will be assigned to during generation",
            ),
            'color_palette': EnumProperty(
                name="Color Palette",
                description="Color palette to use for the Bone Group of this Bone Set. Custom Colors are not supported, only theme color presets",
                items=[
                    (
                        item.identifier,
                        item.name,
                        item.description,
                        item.icon,
                        item.value,
                    )
                    for item in bpy.types.BoneColor.bl_rna.properties[
                        'palette'
                    ].enum_items[:-1]
                ],
                default=bone_set_definition.get('color_palette') or 'DEFAULT',
            ),
            'is_advanced': BoolProperty(
                name="Is Advanced",
                description="If True, this Bone Set will only be displayed in the UI when the 'Show Advanced Bone Sets' toggle is checked",
                default=bone_set_definition.get('is_advanced') or False,
            ),
            'generated_bones': CollectionProperty(  # TODO 4.0: Implement this, so bone sets store which bones they generated. Although, might be more useful to store this on the RigComponent instead, actually.
                name="Generated Bones",
                description="List of bone names generated in this Bone Set during the last time the target rig was generated",
                type=NameProperty,
            ),
        }

        class_name = "BoneSet_" + rna_name
        base_classes = (PropertyGroup,)
        class_attributes = {'__annotations__': annotations}

        bone_set_class = type(class_name, base_classes, class_attributes)

        return bone_set_class

    def make_bone_set_property_groups() -> Dict[str, type]:
        classes = {}
        for rig_type_name, rig_module in rig_components.component_modules.items():
            rig_class = getattr(rig_module, 'RigComponent')
            rig_class.define_bone_sets()
            for bone_set_name, bone_set_definition in rig_class.bone_set_defs.items():
                rna_name = bone_set_name.lower().replace(" ", "_")
                if rna_name in classes:
                    continue
                bone_set_class = BoneSets.class_from_definition(
                    rna_name, bone_set_definition
                )
                classes[rna_name] = bone_set_class
        return classes

    bone_set_property_groups = make_bone_set_property_groups()

    __annotations__ = {
        name: PointerProperty(type=bone_set_class)
        for name, bone_set_class in bone_set_property_groups.items()
    }


class ComponentParams(PropertyGroup):
    # TODO 4.0: Some params need to be grabbed from the rig_component_features package.

    __annotations__ = {
        name: PointerProperty(type=param_class)
        for name, param_class in get_param_classes().items()
    }

    bone_sets: PointerProperty(type=BoneSets)


class RigComponent(PropertyGroup):
    """It is important to store this on the (pose) bone, so that when a bone is duplicated,
    this information is duplicated with it.
    """

    @property
    def base_bone_name(self):
        return self.owner_pose_bone.name

    @property
    def owner_pose_bone(self):
        metarig = self.id_data
        for pb in metarig.pose.bones:
            if pb.cloudrig_component == self:
                return pb

    @property
    def active_bone_set(self):
        if not self.active_ui_bone_set:
            return
        return getattr(self.params.bone_sets, self.active_ui_bone_set.name)

    @property
    def active_ui_bone_set(self):
        if len(self.ui_bone_sets) == 0:
            return
        return self.ui_bone_sets[self.bone_sets_active_index]

    @property
    def bone_set_dict(self):
        return {
            key: getattr(self.params.bone_sets, key)
            for key in self.params.bone_sets.keys()
        }

    def update_ui_bone_sets(self):
        # Update UI Bone Sets, which are the ones displayed under the "Bone Organization"
        # sub-panel of the CloudRig Component.
        self.ui_bone_sets.clear()
        for prop_name in BoneSets.bone_set_property_groups.keys():
            bone_set = getattr(self.params.bone_sets, prop_name)
            if not self.rig_class:
                continue
            if prop_name not in self.rig_class.bone_set_defs:
                continue
            ui_bone_set = self.ui_bone_sets.add()
            ui_bone_set.name = prop_name
            ui_bone_set.ui_name = bone_set.ui_name

            # Also update the collection list of each BoneSet, such that if a BoneSet
            # doesn't have any collections yet, its defaults are assigned.
            if len(bone_set.collections) == 0:
                self.reset_collections_of_bone_set(bone_set)

    def reset_collections_of_bone_set(self, bone_set):
        ui_bone_set = self.ui_bone_sets[bone_set.name]
        bone_set_definitions = self.rig_class.bone_set_defs
        bone_set_definition = bone_set_definitions[ui_bone_set.name]
        bone_set.collections.clear()
        for default_coll in bone_set_definition['collections']:
            coll_entry = bone_set.collections.add()
            coll_entry.name = default_coll

    ui_bone_sets: CollectionProperty(type=BoneSet_ForUI)
    bone_sets_active_index: IntProperty(
        name="Bone Sets",
        description="Bone Sets allow you to assign the collections and colors of bones that will be generated",
    )

    # This could be an EnumProp, but a StringProp allows us to use prop_search,
    # which is better UX.
    def component_type_update_callback(self, context):
        self.id_data.cloudrig.active_component_index = self.id_data.pose.bones.find(
            context.active_bone.name
        )

    component_type: StringProperty(
        name="Component Type",
        description="The type of rig component that should be generated by this bone or bone chain",
        update=component_type_update_callback,
    )

    @property
    def component_module(self) -> Optional['ModuleType']:
        prefs = get_addon_prefs(bpy.context)
        component_type_info = prefs.component_types.get(self.component_type)
        if not component_type_info:
            return
        module = rig_components.component_modules.get(component_type_info.module_name)
        assert (
            module
        ), f"Could not get component module: {component_type_info.module_name}"

        return module

    @property
    def rig_class(self) -> Optional[type]:
        if not self.component_module:
            return
        return getattr(self.component_module, 'RigComponent')

    def instantiate(self, generator, parent_instance=None) -> Optional['RigComponent']:
        if not self.rig_class:
            return

        return self.rig_class(
            generator=generator,
            bone_name=self.base_bone_name,
            parent_instance=parent_instance,
        )

    params: PointerProperty(type=ComponentParams)
    order: IntProperty(
        name="Generation order of this component",
        description="Internal value, based on bone hierarchy",
        default=-1,
    )
    depth: IntProperty(
        name="Hierarchy depth, used for UI",
        description="Internal value, based on bone hierarchy",
        default=0,
    )

    @property
    def parent(self):
        rig_ob = self.id_data
        if not self.base_bone_name:
            return
        this_bone = rig_ob.pose.bones.get(self.base_bone_name)
        bone_parent = this_bone.parent
        parent_component = None
        while bone_parent and not parent_component:
            if bone_parent.cloudrig_component.component_type:
                parent_component = bone_parent.cloudrig_component
            bone_parent = bone_parent.parent

        return parent_component

    @property
    def should_draw(self):
        """Return False if any parent up the chain has show_children=False"""
        if not self.parent:
            return True

        if not self.parent.show_child_components:
            return False

        return self.parent.should_draw

    show_child_components: BoolProperty(
        name="Show Children",
        description="Show child components in the list",
        default=False,
    )

    @property
    def children(self):
        rig_ob = self.id_data
        children = []
        for pb in rig_ob.pose.bones:
            if (
                pb.cloudrig_component.component_type
                and pb.cloudrig_component.parent == self
            ):
                children.append(pb.cloudrig_component)
        return children


class Properties_CloudRig(PropertyGroup):
    def ensure_bone_collections_info(self, context=None):
        rig_ob = self.id_data
        rig_ob.data.collections.active_index = self.active_collection_index
        for coll in rig_ob.data.collections:
            coll.cloudrig_info.name = coll.name

    active_collection_index: IntProperty(
        name="Nested Collections",
        description="Nested Collections",
        update=ensure_bone_collections_info,
    )

    def active_component_update_callback(self, context=None):
        # Update component order (used for sorting the UIList as well as generation order).
        self.refresh_generation_order()
        self.ensure_bone_collections_info()

        if self.active_component_index < 0 or len(self.rig_component_bones) == 0:
            return
        # Select the bone of this rig component
        rig = self.id_data
        for bone in rig.data.bones:
            bone.select = False
        rig.data.bones.active = rig.data.bones[self.active_component_index]

        # Ensure this component has UI bone sets
        self.active_component.update_ui_bone_sets()

    active_component_index: IntProperty(
        description="Active CloudRig Component", update=active_component_update_callback
    )

    @property
    def active_component(self):
        if len(self.rig_component_bones) == 0:
            return

        rig_ob = self.id_data
        return rig_ob.pose.bones[self.active_component_index].cloudrig_component

    enabled: BoolProperty(
        name="CloudRig",
        description="Whether this armature is a CloudRig metarig",
        default=False,
        update=active_component_update_callback,
    )

    metarig_version: IntProperty(
        name="CloudRig MetaRig Version",
        description="For internal use only",
        default=1,
    )

    @property
    def rig_component_bones(self):
        rig = bpy.context.object
        return [
            pb.cloudrig_component
            for pb in rig.pose.bones
            if pb.cloudrig_component.component_type
        ]

    generator: PointerProperty(type=GeneratorProperties)

    def refresh_generation_order(self):
        metarig_ob = self.id_data

        # Find bones that have no parents.
        parentless = [pb for pb in metarig_ob.pose.bones if not pb.bone.parent]
        parentless.sort(key=lambda pb: pb.name)

        # Number them hierarchically
        index = 0
        for pb in parentless:
            index = self.number_rig_components_recursive(
                pb=pb, parent_component=None, index=index
            )

    def number_rig_components_recursive(
        self, pb: bpy.types.PoseBone, parent_component: "RigComponent" = None, index=0
    ):
        if pb.cloudrig_component.component_type:
            pb.cloudrig_component.order = index
            if parent_component:
                pb.cloudrig_component.depth = parent_component.depth + 1
            else:
                pb.cloudrig_component.depth = 0
            index += 1

            # Set parent for the next recursion.
            parent_component = pb.cloudrig_component
        else:
            pb.cloudrig_component.order = -1
            pb.cloudrig_component.depth = 0

        for child_pb in sorted(pb.children, key=lambda pb: pb.name):
            index = self.number_rig_components_recursive(
                pb=child_pb, parent_component=parent_component, index=index
            )

        return index


registry = (
    [NameProperty]
    + list(get_param_classes().values())
    + list(BoneSets.bone_set_property_groups.values())
    + [BoneSet_ForUI, BoneSets, ComponentParams, RigComponent, Properties_CloudRig]
)


def register():
    # Storing CloudRig properties on Object & PoseBone rather than Armature & Bone
    # has these benefits:
    # 1. Can have multi-user Armature datablock with different CloudRig parameters
    # 2. All code dealing with CloudRig can use `.id_data` to access the Object
    bpy.types.Object.cloudrig = PointerProperty(type=Properties_CloudRig)
    bpy.types.PoseBone.cloudrig_component = PointerProperty(type=RigComponent)


def unregister():
    del bpy.types.Object.cloudrig
    del bpy.types.PoseBone.cloudrig_component
