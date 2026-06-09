# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ..properties import BoneSet_ForUI, ComponentParams, NameProperty, RigComponent
    from ..rig_components.cloud_base import Component_Base

from typing import Any

from bl_ui.generic_ui_list import draw_ui_list
from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import (
    Context,
    Object,
    Operator,
    PoseBone,
    UI_UL_list,
    UILayout,
    UIList,
)

from ..bs_utils.prefs import get_addon_prefs
from ..utils.rig import get_component_in_ui
from .bone_info import BoneInfo


class LinkedList(list):
    """Some very basic doubly linked list functionality to help manage chains of bones."""

    def __init__(self):
        super().__init__()
        self.first = self.last = None

    def remove(self, value: Any):
        """Remove value and relink its neighbours."""
        super().remove(value)
        if value.prev:
            value.prev.next = value.next
        if value.next:
            value.next.prev = value.prev

    def append(self, value: Any):
        """Append value and link it to the previous tail."""
        if len(self) > 0:
            self[-1].next = value
            value.prev = self[-1]
        super().append(value)


class BoneSet(LinkedList):
    """Class to create and store lists of BoneInfo instances.
    Also responsible for Bone Collection/Color/Wire Width assignment.
    """

    def __init__(
        self,
        rig_component: Component_Base,
        ui_name="Bone Set",
        collections=["Collection"],
        color_palette='DEFAULT',
        wire_width=1.0,
        defaults={},
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
        # Wire Width to assign to newly defined BoneInfos.
        self.wire_width = wire_width

    def get(self, name: str) -> BoneInfo | None:
        """Find a BoneInfo instance by name, return it if found."""
        for bi in self:
            if bi.name == name:
                return bi
        return None

    def __repr__(self) -> str:
        return f"{self.ui_name}: {super().__repr__()}"

    def new(
        self,
        name="Bone",
        *,
        source: BoneInfo | PoseBone | None,
        keep_collections=False,
        keep_colors=False,
        keep_wire_width=False,
        **kwargs,
    ) -> BoneInfo:
        """Create and add a new BoneInfo to self.

        The new bone will start out as a copy of `source`, if there is one.
        Passing a `source` is required, but passing None is allowed.
        This is done because caller should need to explicitly specify that
        they don't want this bone to inherit properties.

        `keep_collections/colors/wire_width`: Ignore the Bone Set's relevant
        properties, and preserve whatever is in the source bone instead.
        """

        # Prevent name collision.
        existing = self.rig_component.generator.find_bone_info(name)
        if existing and existing.preserve:
            self.rig_component.raise_generation_error(
                rpt_('"{name}" already exists. May be a bug.').format(name=name),
                trouble_bone=name,
            )

        # Build effective kwargs (explicit > inferred > defaults).
        inferred = {
            "collections": self.collections.copy(),
            "color_palette_base": self.color_palette,
            "custom_shape_wire_width": self.wire_width + self.rig_component.generator.params.base_wire_width,
        }
        if keep_collections:
            if isinstance(source, BoneInfo):
                inferred['collections'] = [coll for coll in source.collections]
            else:
                inferred['collections'] = [coll.name for coll in source.bone.collections]
        if keep_colors:
            if isinstance(source, BoneInfo):
                inferred['color_palette_base'] = source.color_palette_base
            else:
                inferred['color_palette_base'] = source.bone.color.palette
        if keep_wire_width:
            inferred['custom_shape_wire_width'] = source.custom_shape_wire_width

        effective_kwargs = dict(self.defaults)
        effective_kwargs.update(inferred)
        effective_kwargs.update(kwargs)

        # Create and register.
        bone_info = BoneInfo(
            self,
            name,
            source,
            owner_component=self.rig_component,
            keep_collections=keep_collections,
            keep_colors=keep_colors,
            **effective_kwargs,
        )
        self.append(bone_info)

        return bone_info


class BoneSetMixin:
    """Class that provides bone set management to Component_Base."""

    bone_set_defs: OrderedDict[str, str] = OrderedDict()

    @property
    def bone_infos(self) -> Iterator[BoneInfo]:
        """Iterate over all BoneInfo instances across all bone sets."""
        for name, bone_set in self.bone_sets.items():
            for bone_info in bone_set:
                yield bone_info

    def init_bone_set(self, bone_set_prop_name: str) -> BoneSet:
        """Take a bone set definition stored in the class and create a single BoneSet for it."""
        rna_bone_set = getattr(self.params.bone_sets, bone_set_prop_name)

        assert rna_bone_set, (
            f"Failed to create Bone Set {bone_set_prop_name}. Couldn't find corresponding RNA bone set."
        )

        bone_set_def = self.bone_set_defs.get(bone_set_prop_name)
        defaults = self.defaults.copy()
        defaults.update(bone_set_def['defaults'])

        new_set = BoneSet(
            self,
            ui_name=rna_bone_set.name,
            collections=[prop.name for prop in rna_bone_set.collections],
            color_palette=rna_bone_set.color_palette,
            wire_width=rna_bone_set.wire_width,
            defaults=defaults,
        )

        return new_set

    def init_bone_sets(self) -> dict[str, BoneSet]:
        """Instantiate all bone sets based on the class's bone_set_defs dictionary."""
        bone_set_defs = type(self).bone_set_defs
        bone_sets = {}
        for bone_set_prop_name, bone_set_def in bone_set_defs.items():
            bone_sets[bone_set_def['ui_name']] = self.init_bone_set(bone_set_prop_name)
        return bone_sets

    ##############################
    # UI
    @classmethod
    def draw_bone_set_params(cls, layout: UILayout, context: Context, component: RigComponent, only_colors=False):
        """Bone Organization panel of the Component Parameters."""
        if not (component and component.enabled_with_parents):
            return

        params = component.params

        if not component.active_bone_set:
            layout.label(text="UI Bone Sets were not yet initialized. This should never happen!")
            return

        active_ui_bone_set = component.active_ui_bone_set
        active_bone_set = getattr(params.bone_sets, active_ui_bone_set.name)
        if not active_bone_set:
            layout.label(
                text=iface_("Could not find Bone Set named {bone_set}").format(bone_set=active_ui_bone_set.name)
            )
            return

        prefs = get_addon_prefs(context)
        list_column = draw_ui_list(
            layout,
            context,
            class_name='CLOUDRIG_UL_bone_sets',
            list_path=f'object.pose.bones["{component.base_bone_name}"].cloudrig_component.ui_bone_sets',
            active_index_path=f'object.pose.bones["{component.base_bone_name}"].cloudrig_component.bone_sets_active_index',
            insertion_operators=False,
            move_operators=False,
            columns=3,
            unique_id="CloudRig Bone Sets",
        )
        eye_icon = 'HIDE_OFF' if prefs.bone_set_show_advanced else 'HIDE_ON'
        list_column.prop(prefs, 'bone_set_show_advanced', text="", emboss=False, icon=eye_icon)

        col = layout.column(align=True)
        if not any(CLOUDRIG_UL_bone_sets.flt_flags):
            col.label(text="No bone sets to show. Clear the search filter,")
            if not prefs.bone_set_show_advanced:
                col.label(text="enable mechanism collections via the eye icon to the right, ")
            col.label(text="or regenerate the rig.")
            return
        elif not CLOUDRIG_UL_bone_sets.flt_flags[component.bone_sets_active_index]:
            # If the active item is not visible
            return

        metarig = context.object
        generator = metarig.cloudrig.generator
        if not generator.preserve_shapes_properties:
            layout.prop(active_bone_set, 'wire_width')

        if only_colors:
            return

        box = layout.box()
        box.label(text=iface_("Collections of {bone_set}:").format(bone_set=active_bone_set.ui_name))
        row = box.row()
        col = row.column()
        col.template_list(
            'CLOUDRIG_UL_bone_set_collections',
            "CloudRig Bone Set Collections",
            active_bone_set,
            'collections',
            active_bone_set,
            'collections_active_index',
        )
        col = row.column()
        col.operator('pose.cloudrig_bone_set_collection_add', icon='ADD', text="")
        col.operator('pose.cloudrig_bone_set_collection_remove', icon='REMOVE', text="")
        col.separator()
        col.operator('pose.cloudrig_bone_set_collection_reset', icon='FILE_REFRESH', text="")

    @classmethod
    def is_bone_set_used(cls, context: Context, _rig: Object, params: ComponentParams, set_name: str) -> bool:
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
    def define_bone_set(
        cls,
        ui_name: str,
        collections: list[str] = [],
        color_palette='DEFAULT',
        wire_width=1.0,
        is_advanced=False,
        defaults={},
    ):
        """
        A Bone Set contains properties for assigning bone collections, color, and wire width.
        This function is responsible for creating the data which will be used by
        `class BoneSets(PropertyGroup)` to automagically populate itself during add-on registration:
        `PoseBone.cloudrig_component.bone_sets.fk_main.color_palette/collections`.

        Example:
            All FK chain bones of the FK chain rig are created in the "FK Controls" bone set.
            Collections, color, & wire width all "FK Controls" can be customized in the "Bone Organization" panel.

        ui_name:
            Name to display in the Bone Organization panel.
            This cannot be customized by users. It acts as an identifier for the bone set.
        collections:
            List of the DEFAULT Bone Collection names to assign the bones of this bone set to.
            Users can add or change collections, or reset the list.
            Final entry cannot be removed.
        color_palette:
            Default color palette to be used.
            See the enum selector in Blender for possible values; DEFAULT, THEME_01, THEME_02, etc.
            Note that specifying custom colors as the default is not possible.
            You should always use a theme color, or none at all.
        wire_width:
            Default bone shape wire width.
        is_advanced:
            Hidden from the rigger by default. For bone sets of rigging helper bones.
        """

        prop_name = ui_name.replace(" ", "_").lower()
        cls.bone_set_defs[prop_name] = {
            'name': prop_name,
            'ui_name': ui_name,
            'collections': collections or [ui_name],
            'color_palette': color_palette,
            'wire_width': wire_width,
            'is_advanced': is_advanced,
            'defaults': defaults,
        }
        return ui_name

    @classmethod
    def define_bone_sets(cls):
        """Override in subclasses with define_bone_set() calls, always calling super().define_bone_sets() first.
        Resetting the dict here ensures each class gets its own instance instead of sharing the parent's.
        """
        cls.bone_set_defs: OrderedDict[str, str] = OrderedDict()


##########################
#### Bone Sets UIList ####
##########################


class CLOUDRIG_UL_bone_set_collections(UIList):
    def draw_item(
        self,
        _context: Context,
        layout: UILayout,
        _list_owner: BoneSet_ForUI,
        list_element: NameProperty,
        _icon_value: int,
        _active_prop_owner: BoneSet_ForUI,
        _active_prop_name: str,
    ):
        collection = list_element
        metarig_ob = collection.id_data

        row = layout.row()
        split = row.split(factor=0.85)
        row = split.row()
        row.prop_search(
            collection,
            'name',
            metarig_ob.data,
            'collections_all',
            icon='OUTLINER_COLLECTION',
            text="",
        )


class CLOUDRIG_UL_bone_sets(UIList):
    flt_flags = []

    def draw_filter(self, _context: Context, layout: UILayout):
        layout.prop(self, 'filter_name', text="")

    def filter_items(self, context: Context, component: RigComponent, prop_name: str):
        flt_flags = []
        flt_neworder = []
        component = component
        ui_bone_sets = getattr(component, prop_name)

        helper_funcs = UI_UL_list

        # Always sort alphabetical.
        flt_neworder = helper_funcs.sort_items_by_name(ui_bone_sets, "name")

        # Filter by search string.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name, self.bitflag_filter_item, ui_bone_sets, "ui_name"
            )

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

        # Filter to only show bone sets that are relevant to this component type with the current settings.
        metarig = context.object
        prefs = get_addon_prefs(context)
        component_class = component.component_class

        for idx, ui_bone_set in enumerate(ui_bone_sets):
            if ui_bone_set.name not in component_class.bone_set_defs:
                flt_flags[idx] = 0
            else:
                bone_set = getattr(component.params.bone_sets, ui_bone_set.name)
                if not prefs.bone_set_show_advanced and bone_set.is_advanced:
                    # Filter advanced bone sets when the user doesn't want to see them.
                    flt_flags[idx] = 0
                    continue
                if not component_class.is_bone_set_used(context, metarig, component.params, ui_bone_set.name):
                    # Filter bone sets that are not used based on current parameters.
                    flt_flags[idx] = 0

        type(self).flt_flags = flt_flags
        return flt_flags, flt_neworder

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        list_owner: RigComponent,
        list_element: BoneSet_ForUI,
        _icon_value: int,
        _active_prop_owner: RigComponent,
        _active_propname: str,
    ):
        component = list_owner
        ui_bone_set = list_element
        bone_set = getattr(component.params.bone_sets, ui_bone_set.name)

        prefs = get_addon_prefs(context)

        row = layout.row()
        icon = 'BLANK1'
        if bone_set.is_advanced:
            icon = 'SETTINGS'
        split = row.split(factor=0.3, align=True)
        split.prop(bone_set, 'color_palette', text="")
        if prefs.bone_set_show_advanced:
            split.label(text=ui_bone_set.ui_name, icon=icon)
        else:
            split.label(text=ui_bone_set.ui_name)


class CLOUDRIG_OT_bone_set_collection_add(Operator):
    """Add a Bone Collection to this Bone Set"""

    bl_idname = "pose.cloudrig_bone_set_collection_add"
    bl_label = "Add Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context: Context):
        component = get_component_in_ui(context)
        bone_set = component.active_bone_set
        bone_set.collections.add()
        bone_set.collections_active_index = len(bone_set.collections) - 1
        self.report({'INFO'}, iface_("Added collection slot to {bone_set}.").format(bone_set=iface_(bone_set.ui_name)))
        return {'FINISHED'}


class CLOUDRIG_OT_bone_set_collection_remove(Operator):
    """Remove a Bone Collection from this Bone Set"""

    bl_idname = "pose.cloudrig_bone_set_collection_remove"
    bl_label = "Remove Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context: Context):
        component = get_component_in_ui(context)
        bone_set = component.active_bone_set
        if len(bone_set.collections) == 1:
            cls.poll_message_set("Collection list cannot be empty. You can reset it with the button below.")
            return False
        if len(bone_set.collections) - 1 < bone_set.collections_active_index:
            cls.poll_message_set("No active collection slot.")
            return False
        return True

    def execute(self, context: Context):
        component = get_component_in_ui(context)
        bone_set = component.active_bone_set
        coll_name = bone_set.collections[bone_set.collections_active_index].name
        bone_set.collections.remove(bone_set.collections_active_index)
        self.report(
            {'INFO'},
            iface_("{bone_set} will not be assigned to '{collection}' collection.").format(
                bone_set=iface_(bone_set.ui_name), collection=coll_name
            ),
        )
        bone_set.collections_active_index -= 1
        return {'FINISHED'}


class CLOUDRIG_OT_bone_set_collection_reset(Operator):
    """Reset Bone Collections of this Bone Set to the default list"""

    bl_idname = "pose.cloudrig_bone_set_collection_reset"
    bl_label = "Reset Collections"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context: Context):
        component = get_component_in_ui(context)
        component.reset_collections_of_bone_set(component.active_bone_set)
        self.report(
            {'INFO'},
            iface_("{bone_set} collection assignments reset to default.").format(
                bone_set=iface_(component.active_bone_set.ui_name)
            ),
        )
        bone_set = component.active_bone_set
        if bone_set:
            bone_set.collections_active_index = 0
        return {'FINISHED'}


registry = [
    CLOUDRIG_UL_bone_sets,
    CLOUDRIG_OT_bone_set_collection_add,
    CLOUDRIG_OT_bone_set_collection_remove,
    CLOUDRIG_OT_bone_set_collection_reset,
    CLOUDRIG_UL_bone_set_collections,
]
