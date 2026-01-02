# SPDX-License-Identifier: GPL-3.0-or-later

from collections import OrderedDict

from bl_ui.generic_ui_list import draw_ui_list
from bpy.types import (
    Operator,
    PoseBone,
    UI_UL_list,
    UIList,
)

from ..bs_utils.prefs import get_addon_prefs
from ..utils.rig import get_pbone_of_active
from .bone_info import BoneInfo


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
        rig_component,
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

    def get(self, name):
        """Find a BoneInfo instance by name, return it if found."""
        for bi in self:
            if bi.name == name:
                return bi
        return None

    def __repr__(self):
        return f"{self.ui_name}: {super().__repr__()}"

    def new(self, name="Bone", source: BoneInfo | PoseBone | None=None, **kwargs) -> BoneInfo:
        """Create and add a new BoneInfo to self."""

        # Prevent name collision.
        existing = self.rig_component.generator.find_bone_info(name)
        if existing and existing.preserve:
            self.rig_component.raise_generation_error(
                f'"{name}" already exists. May be a bug.',
                trouble_bone=name,
            )

        # Build effective kwargs (explicit > inferred > defaults).
        inferred = {
            "collections": self.collections.copy(),
            "color_palette_base": self.color_palette,
            "custom_shape_wire_width": self.wire_width + (source.custom_shape_wire_width-1 if source else 0),
        }
        effective_kwargs = dict(self.defaults)
        effective_kwargs.update(inferred)
        effective_kwargs.update(kwargs)

        # Create and register.
        bone_info = BoneInfo(
            self,
            name,
            source,
            owner_component=self.rig_component,
            **effective_kwargs,
        )
        self.append(bone_info)

        return bone_info


class BoneSetMixin:
    """Class that provides bone set management to Component_Base."""

    bone_set_defs: OrderedDict[str, str] = OrderedDict()

    @property
    def bone_infos(self):
        for name, bone_set in self.bone_sets.items():
            for bone_info in bone_set:
                yield bone_info

    def init_bone_set(self, bone_set_prop_name) -> BoneSet:
        """Take a bone set definition stored in the class and create a single BoneSet for it."""
        rna_bone_set = getattr(self.params.bone_sets, bone_set_prop_name)

        assert (
            rna_bone_set
        ), f"Failed to create Bone Set {bone_set_prop_name}. Couldn't find corresponding RNA bone set."

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
            bone_sets[bone_set_def['ui_name']] = self.init_bone_set(
                bone_set_prop_name
            )
        return bone_sets

    ##############################
    # UI
    @classmethod
    def draw_bone_set_params(cls, layout, context, params, only_colors=False):
        """Bone Organization panel of the Component Parameters."""
        active_pb = get_pbone_of_active(context)
        if not active_pb:
            return
        component = active_pb.cloudrig_component.inherited_component
        if not (component and component.enabled_with_parents):
            return

        params = component.params

        if not component.active_bone_set:
            layout.label(
                text="UI Bone Sets were not yet initialized. This should never happen!"
            )
            return

        active_ui_bone_set = component.active_ui_bone_set
        active_bone_set = getattr(params.bone_sets, active_ui_bone_set.name)
        if not active_bone_set:
            layout.label(
                text="Could not find Bone Set named " + active_ui_bone_set.name
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
        list_column.prop(
            prefs, 'bone_set_show_advanced', text="", emboss=False, icon=eye_icon
        )

        if not any(CLOUDRIG_UL_bone_sets.flt_flags):
            layout.label(text="No bone sets to show. Clear the search filter,")
            if not prefs.bone_set_show_advanced:
                layout.label(text="enable mechanism collections via the eye icon to the right, ")
            layout.label(text="or regenerate the rig.")
            return
        elif not CLOUDRIG_UL_bone_sets.flt_flags[component.bone_sets_active_index]:
            # If the active item is not visible
            return

        layout.prop(active_bone_set, 'wire_width')

        if only_colors:
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
            'collections_active_index',
        )
        col = row.column()
        col.operator('pose.cloudrig_bone_set_collection_add', icon='ADD', text="")
        col.operator('pose.cloudrig_bone_set_collection_remove', icon='REMOVE', text="")
        col.separator()
        col.operator(
            'pose.cloudrig_bone_set_collection_reset', icon='FILE_REFRESH', text=""
        )

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
    def define_bone_set(
        cls, ui_name, collections: list[str]=[], color_palette='DEFAULT', wire_width=1.5, is_advanced=False, defaults={}
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
            List of the DEFAULT bone collection names to assign the bones of this bone set to.
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
        # Each class should override this with their define_bone_set() calls.
        # As well as a super().define_bone_sets().

        # This needs to be defined in a function, otherwise every class shares a single instance of this dict.
        # We want each class to have its own instance, so they only store the bone sets they actually define.
        cls.bone_set_defs: OrderedDict[str, str] = OrderedDict()
        pass


##########################
#### Bone Sets UIList ####
##########################


class CLOUDRIG_UL_bone_set_collections(UIList):
    def draw_item(
        self, context, layout, data, item, icon_value, active_data, active_propname
    ):
        collection = item
        metarig_ob = item.id_data

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
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name, self.bitflag_filter_item, ui_bone_sets, "ui_name"
            )

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

        # Filter to only show bone sets that are relevant to this component type with the current settings.
        metarig = context.object
        prefs = get_addon_prefs(context)
        active_pb = get_pbone_of_active(context)
        component = active_pb.cloudrig_component.inherited_component
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
                if not component_class.is_bone_set_used(
                    context, metarig, component.params, ui_bone_set.name
                ):
                    # Filter bone sets that are not used based on current parameters.
                    flt_flags[idx] = 0

        type(self).flt_flags = flt_flags
        return flt_flags, flt_neworder

    def draw_item(
        self, context, layout, _data, item, _icon_value, _active_data, _active_propname
    ):
        ui_bone_set = item
        component = _data
        bone_set = getattr(component.params.bone_sets, ui_bone_set.name)

        row = layout.row()
        icon = 'BLANK1'
        if bone_set.is_advanced:
            icon='SETTINGS'
        row.label(text=ui_bone_set.ui_name, icon=icon)
        row.prop(bone_set, 'color_palette', text="")


class CLOUDRIG_OT_bone_set_collection_add(Operator):
    """Add bone set collection"""

    bl_idname = "pose.cloudrig_bone_set_collection_add"
    bl_label = "Add Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        active_pb = get_pbone_of_active(context)
        component = active_pb.cloudrig_component.inherited_component
        bone_set = component.active_bone_set
        bone_set.collections.add()
        bone_set.collections_active_index = len(bone_set.collections)-1
        self.report({'INFO'}, f"Added collection slot to {bone_set.ui_name}.")
        return {'FINISHED'}


class CLOUDRIG_OT_bone_set_collection_remove(Operator):
    """Remove bone set collection"""

    bl_idname = "pose.cloudrig_bone_set_collection_remove"
    bl_label = "Remove Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        active_pb = get_pbone_of_active(context)
        component = active_pb.cloudrig_component
        bone_set = component.active_bone_set
        if len(bone_set.collections) == 1:
            cls.poll_message_set(
                "Collection list cannot be empty. You can reset it with the button below."
            )
            return False
        if len(bone_set.collections)-1 < bone_set.collections_active_index:
            cls.poll_message_set("No active collection slot.")
            return False
        return True

    def execute(self, context):
        active_pb = get_pbone_of_active(context)
        component = active_pb.cloudrig_component
        bone_set = component.active_bone_set
        coll_name = bone_set.collections[bone_set.collections_active_index].name
        bone_set.collections.remove(bone_set.collections_active_index)
        self.report(
            {'INFO'},
            f"{bone_set.ui_name} will not be assigned to '{coll_name}' collection.",
        )
        bone_set.collections_active_index -= 1
        return {'FINISHED'}


class CLOUDRIG_OT_bone_set_collection_reset(Operator):
    """Reset collection assignments of this Bone Set to the default list"""

    bl_idname = "pose.cloudrig_bone_set_collection_reset"
    bl_label = "Reset Collections"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        active_pb = get_pbone_of_active(context)
        component = active_pb.cloudrig_component
        component.reset_collections_of_bone_set(component.active_bone_set)
        self.report(
            {'INFO'},
            f"{component.active_bone_set.ui_name} collection assignments reset to default.",
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
