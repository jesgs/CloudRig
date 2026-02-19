# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from types import ModuleType
from typing import Callable, get_type_hints

from _bpy_types import _RNAMetaPropGroup
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import ID, BoneColor, Object, PoseBone, PropertyGroup

from . import rig_component_features, rig_components
from .bs_utils.prefs import get_addon_prefs
from .generation.cloud_generator import GeneratorProperties
from .rig_components.cloud_raw_copy import Component_RawCopy


def get_param_classes() -> dict:
    param_classes = {}
    module_dicts = (
        rig_components.ALL_COMPONENT_MODULES,
        rig_component_features.component_feature_modules,
        {"cloud_base": rig_components.cloud_base}
    )
    for module_dict in module_dicts:
        for module_name, module in module_dict.items():
            if hasattr(module, 'Params'):
                param_classes[module_name.replace("cloud_", "").split(".")[-1]] = inject_update_callback(module.Params)
    return param_classes


def mark_overlay_dirty(self):
    for ancestor in self.rna_ancestors():
        if ancestor.__class__.__name__ == 'RigComponent':
            component = ancestor
            component.overlay_is_dirty = True


def inject_update_callback(pg_class) -> dict:
    def wrap_setter(prop_name: str, set_transform: Callable | None):
        def set_transform_wrapper(self, new_value, curr_value, is_set):
            if new_value != curr_value:
                mark_overlay_dirty(self)
                # print(f"Marked overlay as dirty. {prop_name} changed from `{curr_value}` to `{new_value}`.")

            if set_transform:
                # Call the original call-back function.
                return set_transform(self, new_value, curr_value, is_set)
            return new_value

        return set_transform_wrapper

    def wrap_update(prop_name: str, update: Callable | None):
        def update_wrapper(self, context):
            mark_overlay_dirty(self)
            # print(f"Marked overlay as dirty. {prop_name} changed to `{getattr(self, prop_name)}`.")
            if update:
                update(self, context)
        return update_wrapper

    annotations = get_type_hints(pg_class)
    for key, value in annotations.items():
        if 'CollectionProperty' in str(value):
            continue
        # Inject generic component parameter update callback...
        if isinstance(value, _RNAMetaPropGroup):
            inject_update_callback(value)
            continue
        elif isinstance(value, str):
            print("CloudRig Registration Warning: This shouldn't be a String:", value)
            continue
        if not hasattr(value, 'keywords'):
            print("CloudRig Registration Warning: This should have a `keywords` attribute:", value, type(value))
            continue
        if 'PointerProperty' not in str(value):
            value.keywords['set_transform'] = wrap_setter(key, value.keywords.get('set_transform'))
        else:
            value.keywords['update'] = wrap_update(key, value.keywords.get('update'))

    pg_class.__annotations__ = annotations

    return pg_class

class NameProperty(PropertyGroup):
    name: StringProperty()


class BoneSet_ForUI(PropertyGroup):
    """Bone Set UI Data"""
    __longdoc__ = """I want to draw Bone Sets in a UIList, but for that, they need to be a CollectionProperty,
    which I want to avoid for the reasons explained in the docstring of `class BoneSets`.

    So, we have this layer on top of that, just so we can display Bone Sets in a UIList.
    """

    name: StringProperty()
    ui_name: StringProperty()


class BoneSets(PropertyGroup):
    "Bone Set"
    __longdoc__ = """We could've simply created a `class BoneSet(PropertyGroup)`
    and then make a CollectionProperty of that, yes.
    But that would have a lot of downsides:
        1. Every entry in a CollectionProperty has the same default values.
        This would mean that users can't reset Bone Set properties to useful defaults.
        2. Entries of CollectionProperties exist on individual Blender datablocks, which means, they
        cannot be populated during `register()`.
        This could admittedly be worked around by initializing the Bone Sets on some `update()` callback.
        3. Accessing Bone Sets in the rig generation code would have to be done by name,
        eg. `params.bone_sets['FK Chain']`. It's technically possible for user to change the
        Bone Set's name to anything, which would result in errors and workarounds.

    So, what do we do instead?
    We let each BoneSet be its own unique PropertyGroup!
    This way they're created during `register()`, and always exist on every PoseBone.
    1. Unique default values can be defined per Bone Set. User can reset to proper defaults using mouse hover + backspace.
    2. No need for update callback shennanigans to initialize Bone Sets.
    3. Accessing (RNA) Bone Sets is done via symbols instead of strings, eg. `params.bone_sets.fk_chain`

    And how do we do it?
        Python lets us define classes dynamically using the `type()` function.
        Blender's PyAPI just wants a class that subclasses `bpy.types.PropertyGroup`, and
        has annotations whose values are whatever Blender returns from its `bpy.props.WhateverProperty()` functions.
        Python lets us define those annotations dynamically as well, by setting
        a class's `__annotations__` dictionary, which is a built-in Python variable.

    And we actually do this twice here:
    - First, when dynamically defining individual BoneSet PropertyGroup classes, in `class_from_definition()`
    - Second, when assigning a PointerProperty to the BoneSets PropertyGroup for each BoneSet.

    Last important thing: We must store references to the classes that we dynamically defined, in order
    to be able to register them. So, we store those references in the class definition (`bone_set_property_groups`),
    and then add them to `registry`, which gets (un)registered by `__init__.py`.
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
                description="Bone Collections that bones in this Bone Set will be assigned to during generation", # This is displayed when mouse hovering the list.
            ),
            'color_palette': EnumProperty(
                name="Color Palette",
                description="Color palette to assign to bones of this Bone Set. Custom Colors are not supported, only theme color presets",
                items=[
                    (
                        item.identifier,
                        item.name.replace(" - Theme Color Set", "").replace(" Colors", ""),
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
            'wire_width': FloatProperty(
                name="Wire Width",
                description="Wire Width to assign to bones of this Bone Set",
                default=bone_set_definition.get('wire_width') or 1.0,
                min=1, max=10
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
        return inject_update_callback(bone_set_class)

    @staticmethod
    def make_bone_set_property_groups() -> dict[str, type]:
        classes = {}
        for _rig_component_name, rig_component_module in rig_components.ALL_COMPONENT_MODULES.items():
            rig_component_class = getattr(rig_component_module, 'RIG_COMPONENT_CLASS')
            rig_component_class.define_bone_sets()
            for bone_set_name, bone_set_definition in rig_component_class.bone_set_defs.items():
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
    """Rig Component data is stored on PoseBones.
    If a Component Type is assigned by the user via the UI, parameters will appear,
    and this bone (and usually its connected children) will contribute to the Target Rig.
    """
    last_bone_name: StringProperty() #TODO: Reset this as an early generation step.
    bone_name: StringProperty(description="INTERNAL: Stores a cache of the start of this component.")
    overlay_is_dirty: BoolProperty(description="INTERNAL: Flag that gets set to True when a component parameter is changed, and gets set to False when the virtual component is re-generated.")

    def update_caches(self, _context=None):
        # Update pbone chain stuff for the overlay and generation.
        self.last_bone_name = ""
        self.bone_name = ""
        self.component_pbone_chain

        # Update parent UI stuff for the Rig Component List
        if not self.parent:
            self.should_draw = True
            self.enabled_with_parents = True
        for child_comp in self.children:
            child_comp.enabled_with_parents = (
                self.enabled_toggle
                and self.enabled_with_parents
                and child_comp.enabled_toggle
            )
            child_comp.should_draw = self.show_child_components and self.should_draw
            child_comp.update_caches()

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
    def is_enabled_component(self) -> bool:
        if not self.component_type:
            return True
        return self.enabled_toggle and self.enabled_with_parents


    @property
    def base_bone_name(self) -> str:
        return self.owner_pose_bone.name

    @property
    def owner_pose_bone(self) -> PoseBone:
        metarig = self.id_data
        if self.bone_name:
            pb = metarig.pose.bones.get(self.bone_name)
            if pb and pb.cloudrig_component == self:
                return pb
        pb = next((pb for pb in metarig.pose.bones if pb.cloudrig_component == self))
        try:
            self.bone_name = pb.name
        except AttributeError:
            # If we are in UI drawing code, just don't do this.
            pass
        return pb

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
            if not self.component_class:
                continue
            if prop_name not in self.component_class.bone_set_defs:
                continue
            ui_bone_set = self.ui_bone_sets.add()
            ui_bone_set.name = prop_name
            ui_bone_set.ui_name = bone_set.ui_name

            # Also update the collection list of each BoneSet, such that if a BoneSet
            # doesn't have any collections yet, its defaults are assigned.
            if len(bone_set.collections) == 0:
                self.reset_collections_of_bone_set(bone_set)
        self.bone_sets_active_index = min(
            self.bone_sets_active_index,
            len(self.ui_bone_sets) - 1
        )

    def reset_collections_of_bone_set(self, bone_set):
        ui_bone_set = self.ui_bone_sets[bone_set.name]
        bone_set_definitions = self.component_class.bone_set_defs
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
            if not hasattr(self.params, comp_type_name):
                # This can cause an error when a bone set implementation is removed.
                continue

            component_type_params = getattr(self.params, comp_type_name)
            for param_key in list(component_type_params.keys()):
                if not hasattr(component_type_params, param_key):
                    # This can cause an error when a bone set implementation is removed.
                    continue
                param_value = getattr(component_type_params, param_key)
                if isinstance(param_value, ID):
                    setattr(component_type_params, param_key, None)
                elif hasattr(param_value, 'custom_shape'):
                    setattr(param_value, 'custom_shape', None)

    # This could be an EnumProp, but a StringProp allows us to use prop_search,
    # which is better UX.
    def comp_type_get_transform(self, curr_value, is_set) -> str:
        prefs = get_addon_prefs()
        comp_info = next((comp for comp in prefs.component_types if comp.module_name==curr_value), None)
        if not comp_info and curr_value:
            # Backwards compatibility: If the UI name is stored in the property, let this still work.
            # Properties that are kept alive this way will break if the UI name of the component changes,
            # unless the rig is re-generated first, which will fire the necessary updates.
            comp_info = prefs.component_types.get(curr_value)
        if not comp_info:
            return ""
        return comp_info.name
    def comp_type_set_transform(self, new_value, curr_value, is_set) -> str:
        """Convert the artist-friendly component name to the implementation name
        This allows changing the displayed name of component types without breakage.
        """
        prefs = get_addon_prefs()
        comp_info = prefs.component_types.get(new_value)
        if not comp_info:
            if curr_value != new_value:
                # If user un-assigned the component, let's just reset everything to default.
                self.property_unset('params')
            return ""
        return comp_info.module_name
    component_type: StringProperty(
        name="Component Type",
        description=(
            "The type of rig component that should be generated by this bone or bone chain.\n\n"
            "No assignment will fall back to the Raw Copy component behaviour, which copies the "
            "bone to the Target Rig while re-targeting any references from the metarig to the "
            "Target Rig."
        ),
        update=component_type_update_callback,
        get_transform=comp_type_get_transform,
        set_transform=comp_type_set_transform,
    )

    @property
    def component_module(self) -> ModuleType | None:
        prefs = get_addon_prefs()
        comp_info = prefs.component_types.get(self.component_type)
        if not comp_info:
            return
        return rig_components.ALL_COMPONENT_MODULES.get(comp_info.module_name)

    @property
    def component_class(self) -> type:
        if not self.component_module:
            return Component_RawCopy
        return getattr(self.component_module, 'RIG_COMPONENT_CLASS')

    @property
    def component_pbone(self) -> PoseBone | None:
        pb = self.owner_pose_bone

        if self.component_type:
            return pb

        parent = pb.parent if pb.bone and pb.bone.use_connect else None
        while parent:
            if parent.cloudrig_component.component_type:
                return parent
            parent = parent.parent if parent.bone.use_connect else None

    @property
    def inherited_component(self) -> RigComponent | None:
        comp_pbone = self.component_pbone
        if not comp_pbone:
            return
        return comp_pbone.cloudrig_component

    @property
    def component_pbone_chain(self) -> list[PoseBone]:
        metarig = self.id_data
        if self.last_bone_name:
            last_bone = metarig.pose.bones.get(self.last_bone_name)
            if last_bone and (metarig.mode != 'EDIT' or self.last_bone_name in metarig.data.edit_bones):
                chain = [last_bone]
                while chain[0].parent:
                    chain.insert(0, chain[0].parent)
                    if chain[0].cloudrig_component == self:
                        return chain

        if not self.inherited_component:
            # The Raw Copy case.
            self.last_bone_name = self.base_bone_name
            return [self.owner_pose_bone]

        comp_class = self.inherited_component.component_class
        if not comp_class:
            # Class implementation is missing - Maybe it was installed externally and it isn't anymore.
            return []
        component_pbone = self.component_pbone
        if not component_pbone:
            return []
        max_length = comp_class.max_bones_in_chain
        only_connected = comp_class.only_connected_children

        # Go down in the hierarchy from the component pbone, appending connected bones to the list.
        # NOTE: If one bone has multiple connected children and neither of them have
        # a component type, the chain becomes ambiguous. This case is not supported!
        cur_pb = component_pbone
        chain = [cur_pb]
        try:
            while cur_pb and len(cur_pb.children) > 0:
                next_pb = None
                for child_pb in cur_pb.children:
                    if child_pb.cloudrig_component.component_type == "":
                        if only_connected:
                            if  not child_pb.bone.use_connect:
                                continue
                            if next_pb is not None:
                                # TODO: This check should be done during generation, and result in an error or generation log entry.
                                print(
                                    f"""Warning: Branching connected bone chain for {component_pbone.name}: \n
                                    \tChain could continue with either {next_pb.name} or {child_pb.name}. \n
                                    \tPicking the first one arbitrarily! \n
                                    \tDisconnect the bone or assign a component type to make it unambiguous."""
                                )
                            else:
                                next_pb = child_pb
                        else:
                            next_pb = child_pb
                if next_pb and (metarig.mode != 'EDIT' or next_pb.name in metarig.data.edit_bones):
                    chain.append(next_pb)
                cur_pb = next_pb
        except KeyError:
            # Happens on bone deletion.
            return []
        except AttributeError:
            # Happens on bone duplication.
            return []

        if max_length != -1:
            chain = chain[:max_length]

        self.last_bone_name = chain[-1].name
        return chain

    def instantiate(self, generator, parent_component: RigComponent=None) -> RigComponent | None:
        return self.component_class(
            generator=generator,
            bone_name=self.base_bone_name,
            parent_component=parent_component,
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
    def parent(self) -> RigComponent | None:
        this_bone = self.owner_pose_bone
        if not this_bone:
            return

        bone_parent = this_bone.parent
        while bone_parent:
            if bone_parent.cloudrig_component.component_type:
                return bone_parent.cloudrig_component
            bone_parent = bone_parent.parent

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
    def children(self) -> list[RigComponent]:
        child_component_pbs = [
            pb for pb in get_direct_child_component_pbones(self.owner_pose_bone)
        ]
        child_component_pbs.sort(key=lambda pb: pb.cloudrig_component.sibling_order)
        return [pb.cloudrig_component for pb in child_component_pbs]

    @property
    def siblings(self) -> list[RigComponent]:
        if self.parent:
            return self.parent.children
        return sorted([
                pb.cloudrig_component
                for pb in self.id_data.pose.bones
                if pb.cloudrig_component.component_type and not pb.cloudrig_component.parent
            ],
            key=lambda comp: comp.sibling_order,
        )

    has_children: BoolProperty(
        name="Has Children",
        description="Cache to improve UI drawing performance",
        default=False,
    )

    @property
    def appearance_enabled(self) -> bool:
        return not self.id_data.cloudrig.generator.preserve_shapes_properties

    def __str__(self) -> str:
        return f"{self.base_bone_name}: {self.component_type or 'No Component'}"


class Properties_CloudRig(PropertyGroup):
    def active_component_update_callback(self, _context=None):
        if self.active_component_index < 0 or len(self.rig_component_bones) == 0:
            return

        # Select the bone of this rig component
        rig = self.id_data
        active_component = self.active_component
        if self.active_component:
            for pbone in rig.pose.bones:
                pbone.select = pbone.cloudrig_component == active_component
            rig.data.bones.active = rig.data.bones[self.active_component_index]

            self.active_component.component_type = self.active_component.component_type

    active_component_index: IntProperty(
        description="Active CloudRig Component", update=active_component_update_callback
    )

    @property
    def active_component(self) -> RigComponent | None:
        if len(self.rig_component_bones) == 0:
            return
        rig_ob = self.id_data
        if self.active_component_index > len(rig_ob.pose.bones)-1:
            return

        active_comp = rig_ob.pose.bones[self.active_component_index].cloudrig_component
        if not active_comp.should_draw:
            return
        return active_comp

    @active_component.setter
    def active_component(self, comp: RigComponent):
        set_bone = comp.owner_pose_bone
        new_idx = next((i for i, pb in enumerate(self.id_data.pose.bones) if pb==set_bone), self.active_component_index)
        self.active_component_index = new_idx
        parent = comp.parent
        while parent:
            parent.show_child_components = True
            parent = parent.parent

    def enabled_update_callback(self, context=None):
        if self.enabled:
            self.id_data.cloudrig_prefs.collection_ui_type = 'CLOUDRIG'
            self.id_data.cloudrig_prefs.active_collection_index *= 1
        self.refresh_generator_data()
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
    def rig_component_bones(self) -> list[RigComponent]:
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

    def refresh_generation_order(self, pbone_subset: list[PoseBone]=[]):
        """Set the `order` and `depth` property of rig components.

        These are used for determining what order to execute rig components in
        during generation, as well as for drawing the component list in the UI.

        This should run when changing rig components, and also before generation,
        just in case.
        """
        metarig_ob = self.id_data
        if not pbone_subset:
            pbone_subset = metarig_ob.pose.bones
        # Find component bones that have no parent components.
        orphan_comp_pbones = [pb for pb in pbone_subset if not pb.cloudrig_component.parent]
        orphan_comp_pbones.sort(key=lambda pb: pb.cloudrig_component.sibling_order)

        # Number them hierarchically
        order_idx = 0
        for i, pbone in enumerate(orphan_comp_pbones):
            pbone.cloudrig_component.update_caches()
            pbone.cloudrig_component.sibling_order = i
            order_idx = self.order_components_recursive(pbone, order_idx=order_idx, depth=0)
            order_idx += 1

    def order_components_recursive(self, pbone: PoseBone, order_idx=0, depth=0) -> int:
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


def get_direct_child_component_pbones(root_pb: PoseBone) -> list[PoseBone]:
    component_pbs = []
    try:
        for child_pb in root_pb.children:
            if child_pb.cloudrig_component.component_type:
                component_pbs.append(child_pb)
            elif child_pb.cloudrig_component.inherited_component is None:
                # We treat bones with no component as an implicit "Raw Copy" component.
                component_pbs.append(child_pb)
            else:
                component_pbs.extend(get_direct_child_component_pbones(child_pb))
    except (KeyError, AttributeError):
        # Can happen after bone deletion/creation.
        return []
    return component_pbs


def get_param_classes_ordered():
    param_classes = list(get_param_classes().values())
    new_order = []
    for param_class in param_classes:
        for anno_name, anno_value in get_type_hints(param_class).items():
            # NOTE: We must use get_type_hints(), otherwise any class inside a module
            # which has `from __future__ import annotations` will have the annotation
            # values as strings of Python code rather than evaluated Python values.
            if isinstance(anno_value, _RNAMetaPropGroup):
                # We do this for dynamically defined nested PropertyGroups,
                # see make_custom_shape_params().
                new_order.append(anno_value)
                param_class.__annotations__[anno_name] = PointerProperty(type=anno_value)
        new_order.append(param_class)

    return new_order


registry = (
    [NameProperty]
    + get_param_classes_ordered()
    + list(BoneSets.bone_set_property_groups.values())
    + [BoneSet_ForUI, BoneSets, ComponentParams, RigComponent, Properties_CloudRig]
)


def register():
    # Storing CloudRig properties on Object & PoseBone rather than Armature & Bone
    # has these benefits:
    # 1. Can have multi-user Armature datablock with different CloudRig parameters.
    # 2. Component type functions can use `self.id_data` to access the Object.
    Object.cloudrig = PointerProperty(type=Properties_CloudRig)
    PoseBone.cloudrig_component = PointerProperty(type=RigComponent)


def unregister():
    del Object.cloudrig
    del PoseBone.cloudrig_component
