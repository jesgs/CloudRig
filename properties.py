# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import (
    StringProperty,
    PointerProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
    IntProperty,
)
from bpy.types import PropertyGroup, Object, PoseBone, ID, BoneColor

from . import rig_components, rig_component_features
from .generation.cloud_generator import GeneratorProperties
from .utils.misc import get_addon_prefs, get_parentless_pbones


def get_param_classes() -> dict:
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
                    for item in BoneColor.bl_rna.properties['palette'].enum_items[:-1]
                ],
                default=bone_set_definition.get('color_palette') or 'DEFAULT',
            ),
            'is_advanced': BoolProperty(
                name="Is Advanced",
                description="If True, this Bone Set will only be displayed in the UI when the 'Show Advanced Bone Sets' toggle is checked",
                default=bone_set_definition.get('is_advanced') or False,
            ),
            'generated_bones': CollectionProperty(  # TODO: Implement this, so bone sets store which bones they generated. Although, might be more useful to store this on the RigComponent instead, actually.
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

    def make_bone_set_property_groups() -> dict[str, type]:
        classes = {}
        for rigcomp_name, rigcomp_module in rig_components.component_modules.items():
            rig_class = getattr(rigcomp_module, 'RIG_COMPONENT_CLASS')
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
    __annotations__ = {
        name: PointerProperty(type=param_class)
        for name, param_class in get_param_classes().items()
    }

    bone_sets: PointerProperty(type=BoneSets)


class RigComponent(PropertyGroup):
    """It is important to store this on the (pose) bone, so that when a bone is duplicated,
    this information is duplicated with it.
    """

    def update_caches(self, context):
        for child_comp in self.children:
            child_comp.enabled_with_parents = (
                self.enabled_toggle
                and self.enabled_with_parents
                and child_comp.enabled_toggle
            )
            child_comp.should_draw = self.show_child_components and self.should_draw
            child_comp.update_caches(context)

    enabled_toggle: BoolProperty(
        name="Enabled",
        description="Whether this rig component and its children should be generated",
        default=True,
        update=update_caches,
    )

    enabled_with_parents: BoolProperty(
        name="Cache: Enabled",
        description="Whether this rig component is enabled, based on the enabled state of its parents. This is cached because calculating it on redraw is expensive",
        default=True,
    )

    @property
    def is_enabled_component(self):
        return self.enabled_toggle and self.enabled_with_parents

    @property
    def base_bone_name(self):
        if not self.component_type:
            return
        return self.owner_pose_bone.name

    @property
    def owner_pose_bone(self):
        metarig = self.id_data
        if not self.component_type:
            return
        # XXX: This causes poor performance when the Components List has lot of bones.
        # Cache solution doesn't work because we can't write to properties during re-draw.
        # And the msgbus API is so terrible that I don't want to use it.
        # So, it is what it is.
        return {
            pb.cloudrig_component: pb
            for pb in metarig.pose.bones
            if pb.cloudrig_component
        }[self]

    @property
    def active_bone_set(self):
        if not self.active_ui_bone_set:
            return
        bone_set_name = self.active_ui_bone_set.name
        if hasattr(self.params.bone_sets, bone_set_name):
            return getattr(self.params.bone_sets, self.active_ui_bone_set.name)
        else:
            return

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
        self.bone_sets_active_index = min(
            self.bone_sets_active_index, len(self.ui_bone_sets) - 1
        )

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

    def component_type_update_callback(self, context):
        # Update component order (used for sorting the UIList as well as generation order).
        self.id_data.cloudrig.refresh_generator_data()
        # Ensure this component has UI bone sets
        self.update_ui_bone_sets()

        # Clear any PointerProperties that are not of the new component type.
        for comp_type_name in list(self.params.keys()):
            if self.component_type.lower().replace(" ", "_") == comp_type_name:
                # Don't reset pointers of the current component type.
                continue
            if "." in comp_type_name:
                # Leftover garbage, from old versions.
                del self.params[comp_type_name]
                continue

            component_type_params = getattr(self.params, comp_type_name)
            for param_key in list(component_type_params.keys()):
                if not hasattr(component_type_params, param_key):
                    # More leftover garbage from old versions.
                    del component_type_params[param_key]
                    continue
                param_value = getattr(component_type_params, param_key)
                if isinstance(param_value, ID):
                    setattr(component_type_params, param_key, None)

    # This could be an EnumProp, but a StringProp allows us to use prop_search,
    # which is better UX.
    component_type: StringProperty(
        name="Component Type",
        description="The type of rig component that should be generated by this bone or bone chain",
        update=component_type_update_callback,
    )

    @property
    def component_module(self) -> 'ModuleType|None':
        prefs = get_addon_prefs()
        component_type_info = prefs.component_types.get(self.component_type)
        if not component_type_info:
            return
        module = rig_components.component_modules.get(component_type_info.module_name)
        assert (
            module
        ), f"Could not get component module: {component_type_info.module_name}"

        return module

    @property
    def rig_class(self) -> type | None:
        if not self.component_module:
            return
        return getattr(self.component_module, 'RIG_COMPONENT_CLASS')

    def instantiate(self, generator, parent_instance=None) -> 'RigComponent|None':
        if not self.rig_class:
            return

        return self.rig_class(
            generator=generator,
            bone_name=self.base_bone_name,
            parent_instance=parent_instance,
        )

    params: PointerProperty(type=ComponentParams)

    sibling_order: IntProperty(
        name="Sibling Order",
        description="Can be affected by the user to tweak the generation order of sibling components",
        default=0,
    )
    order: IntProperty(
        name="Generation order of this component",
        description="Internal value, based on bone hierarchy and sibling_order",
        default=-1,
    )
    depth: IntProperty(
        name="Hierarchy depth, used for UI",
        description="Internal value, based on bone hierarchy",
        default=0,
    )

    @property
    def parent(self) -> 'RigComponent':
        this_bone = self.owner_pose_bone
        if not this_bone:
            return

        bone_parent = this_bone.parent
        parent_component = None
        while bone_parent and not parent_component:
            if bone_parent.cloudrig_component.component_type:
                parent_component = bone_parent.cloudrig_component
            bone_parent = bone_parent.parent

        return parent_component

    @property
    def sibling_components(self) -> list['RigComponent']:
        parent = self.parent
        if not parent:
            return [
                pb.cloudrig_component
                for pb in self.id_data.pose.bones
                if not pb.cloudrig_component.parent
            ]
        return [sibling for sibling in parent.children if sibling != self]

    @property
    def should_draw(self) -> bool:
        """Return False if any parent up the chain has show_children=False"""
        parent = self.parent

        if not parent:
            return True

        if not parent.show_child_components:
            return False

        return parent.should_draw

    show_child_components: BoolProperty(
        name="Show Children",
        description="Show child components in the list",
        default=False,
        update=update_caches,
    )
    should_draw: BoolProperty(
        name="Cache: Draw In List",
        description="Cached flag denoting whether this component should be drawn, updated by the collapse arrows",
        default=True,
    )

    @property
    def children(self) -> list['RigComponent']:
        child_component_pbs = [
            pb for pb in get_direct_child_component_pbones(self.owner_pose_bone)
        ]
        child_component_pbs.sort(key=lambda pb: pb.cloudrig_component.sibling_order)
        return [pb.cloudrig_component for pb in child_component_pbs]

    @property
    def siblings(self) -> list['RigComponent']:
        if self.parent:
            return self.parent.children
        return sorted(
            [pb.cloudrig_component for pb in get_parentless_pbones(self.id_data)],
            key=lambda comp: comp.sibling_order,
        )

    has_children: BoolProperty(
        name="Has Children",
        description="Cache to improve UI drawing performance",
        default=False,
    )

    def __repr__(self):
        return f"{self.base_bone_name}: {self.component_type}"


class Properties_CloudRig(PropertyGroup):
    def active_component_update_callback(self, context=None):
        if self.active_component_index < 0 or len(self.rig_component_bones) == 0:
            return

        # Select the bone of this rig component
        rig = self.id_data
        for bone in rig.data.bones:
            bone.select = False
        rig.data.bones.active = rig.data.bones[self.active_component_index]

        if self.active_component:
            self.active_component.component_type = self.active_component.component_type

    active_component_index: IntProperty(
        description="Active CloudRig Component", update=active_component_update_callback
    )

    @property
    def active_component(self):
        if len(self.rig_component_bones) == 0:
            return

        rig_ob = self.id_data
        return rig_ob.pose.bones[self.active_component_index].cloudrig_component

    def enabled_update_callback(self, context=None):
        if self.enabled:
            self.id_data.cloudrig_prefs.collection_ui_type = 'CLOUDRIG'
            self.id_data.cloudrig_prefs.active_collection_index *= 1
        self.active_component_update_callback()

    enabled: BoolProperty(
        name="CloudRig",
        description="Whether this armature is a CloudRig metarig",
        default=False,
        update=enabled_update_callback,
    )

    metarig_version: IntProperty(
        name="CloudRig MetaRig Version",
        description="For internal use only",
        default=1,
    )

    @property
    def rig_component_bones(self):
        rig = self.id_data
        return [
            pb.cloudrig_component
            for pb in rig.pose.bones
            if pb.cloudrig_component.component_type
        ]

    generator: PointerProperty(type=GeneratorProperties)

    def refresh_generator_data(self):
        self.refresh_generation_order()
        self.id_data.cloudrig_prefs.sync_collection_names()

    def refresh_generation_order(self):
        """Set the `order` and `depth` property of rig components.

        These are used for determining what order to execute rig components in
        during generation, as well as for drawing the component list in the UI.

        This should run when changing rig components, and also before generation,
        just in case.
        """
        metarig_ob = self.id_data

        # Find pbones that have no parents.
        parentless_pbones = get_parentless_pbones(metarig_ob)
        parentless_pbones.sort(key=lambda pb: pb.cloudrig_component.sibling_order)

        # Number them hierarchically
        order_idx = 0
        for i, pbone in enumerate(parentless_pbones):
            pbone.cloudrig_component.sibling_order = i
            order_idx = self.order_components_recursive(
                pbone, order_idx=order_idx, depth=0
            )
            order_idx += 1

    def order_components_recursive(self, pbone, order_idx=0, depth=0):
        component = pbone.cloudrig_component
        component.order = order_idx
        component.depth = depth

        child_component_pbs = get_direct_child_component_pbones(pbone)

        if not child_component_pbs:
            component.has_children = False
            return order_idx
        component.has_children = True

        # Sort the children by their sibling order value,
        # which is controlled by the user with the up/down arrows.
        child_component_pbs.sort(key=lambda pb: pb.cloudrig_component.sibling_order)
        for i, child_pb in enumerate(child_component_pbs):
            order_idx += 1
            order_idx = self.order_components_recursive(child_pb, order_idx, depth + 1)
            child_pb.cloudrig_component.sibling_order = i

        return order_idx

    ui_edit_mode: BoolProperty(
        name="UI Edit Mode",
        description="Reveal Rig UI editing operations",
        default=False,
    )


def get_direct_child_component_pbones(root_pb):
    component_pbs = []
    for child_pb in root_pb.children:
        if child_pb.cloudrig_component.component_type:
            component_pbs.append(child_pb)
        else:
            component_pbs.extend(get_direct_child_component_pbones(child_pb))
    return component_pbs


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
    Object.cloudrig = PointerProperty(type=Properties_CloudRig)
    PoseBone.cloudrig_component = PointerProperty(type=RigComponent)


def unregister():
    del Object.cloudrig
    del PoseBone.cloudrig_component
