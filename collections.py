from typing import List
import bpy
from bpy.types import PropertyGroup, Operator, Panel, UIList, BoneCollection
from bpy.props import PointerProperty, StringProperty, BoolProperty, IntProperty
from bl_ui.generic_ui_list import draw_ui_list

from .rig_component_features.ui import redraw_viewport


class CloudRigBoneCollection(PropertyGroup):
    def get_collection(self) -> BoneCollection:
        armature = self.id_data
        for coll in armature.collections:
            if coll.cloudrig_info == self:
                return coll

    def update_name(self, context):
        coll = self.get_collection()

        for other_coll in self.id_data.collections:
            if other_coll.cloudrig_info.parent_name == coll.name:
                other_coll.cloudrig_info.parent_name = self.name

        coll.name = self.name

    name: StringProperty(
        name="Name", description="Name of this bone collection", update=update_name
    )
    show_children: BoolProperty()
    parent_name: StringProperty(
        name="Parent",
        description="Parent of this bone collection",
    )

    @property
    def parent_collection(self) -> BoneCollection:
        armature = self.id_data
        return armature.collections.get(self.parent_name)

    @property
    def children(self) -> List[BoneCollection]:
        children = []
        if not self.name:
            return []
        armature = self.id_data
        for coll in armature.collections:
            if self.name == coll.cloudrig_info.parent_name:
                children.append(coll)
        return children

    @property
    def should_draw(self):
        """Return False if any parent up the chain has show_children=False"""
        if not self.parent_collection:
            return True

        if not self.parent_collection.cloudrig_info.show_children:
            return False

        return self.parent_collection.cloudrig_info.should_draw

    @property
    def hierarchy_depth(self):
        """Return number of parents"""

        parent = self.parent_collection
        counter = 0
        while parent:
            counter += 1
            parent = parent.cloudrig_info.parent_collection

        return counter


class CLOUDRIG_OT_collection_parent_set(Operator):
    """Set parent collection"""

    bl_idname = "pose.cloudrig_collection_parent_set"
    bl_label = "Set Parent Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    coll_idx: IntProperty()
    parent_name: StringProperty(
        name="Parent", description="Parent to set as this bone collection's parent"
    )

    def invoke(self, context, _event):
        self.parent_name = context.object.data.collections[
            self.coll_idx
        ].cloudrig_info.parent_name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.prop_search(self, 'parent_name', context.object.data, 'collections')

    def execute(self, context):
        coll_info = context.object.data.collections[self.coll_idx].cloudrig_info
        if coll_info.parent_name == self.parent_name:
            self.report({'INFO'}, "This parent is already set. Nothing was done.")
            return {'CANCELLED'}
        if self.parent_name == coll_info.name:
            self.report({'ERROR'}, "Cannot set a collection's parent to be itself.")
            return {'CANCELLED'}
        coll_info.parent_name = self.parent_name

        # Ensure there's no parent cycle.
        parent = coll_info.parent_collection
        while parent:
            if parent in coll_info.children:
                parent.cloudrig_info.parent_name = ""
                self.report(
                    {'INFO'}, "A collection was un-parented to avoid a parenting loop."
                )
                redraw_viewport()
                return {'FINISHED'}
            parent = parent.cloudrig_info.parent_collection

        redraw_viewport()
        self.report({'INFO'}, "Collection parent set.")
        return {'FINISHED'}


class CLOUDRIG_OT_collection_remove(Operator):
    """Delete active collection"""

    bl_idname = "pose.cloudrig_collection_delete"
    bl_label = "Delete"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object.data.collections.active

    def execute(self, context):
        coll = context.object.data.collections.active
        parent_name = coll.cloudrig_info.parent_name

        for child in coll.cloudrig_info.children:
            child.cloudrig_info.parent_name = parent_name

        context.object.data.collections.remove(coll)

        context.object.cloudrig.active_collection_index = (
            context.object.data.collections.find(parent_name)
        )

        return {'FINISHED'}


class CLOUDRIG_OT_collection_add(Operator):
    """Add bone collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Delete"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        coll = context.object.data.collections.active
        parent_name = ""
        if coll:
            parent_name = coll.cloudrig_info.parent_name

        coll = context.object.data.collections.new(name="Collection")
        coll.cloudrig_info.parent_name = parent_name

        context.object.cloudrig.active_collection_index = (
            context.object.data.collections.find(coll.name)
        )

        return {'FINISHED'}


class CLOUDRIG_UL_bone_collection_nested_list(UIList):
    """Draw bone collections with nesting support provided by CloudRig"""

    def draw_item(
        self, context, layout, data, item, icon_value, _active_data, _active_propname
    ):
        collection = item
        cloudrig_info = collection.cloudrig_info

        row = layout.row(align=True)
        icon = 'TRIA_DOWN' if cloudrig_info.show_children else 'TRIA_RIGHT'
        if cloudrig_info.parent_collection:
            split = row.split(factor=0.02 * cloudrig_info.hierarchy_depth)
            split.row()
            row = split.row(align=True)
        if cloudrig_info.children:
            row.prop(cloudrig_info, 'show_children', text="", icon=icon, emboss=False)
        else:
            row.label(text="", icon='BLANK1')
        row.prop(cloudrig_info, 'name', icon_value=icon_value, text="", emboss=False)
        row.operator(
            CLOUDRIG_OT_collection_parent_set.bl_idname, text="", icon='CON_CHILDOF'
        ).coll_idx = data.collections.find(collection.name)

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation.
        """
        layout.row().prop(self, "filter_name", text="")

    def filter_items(self, context, data, propname):
        collections = getattr(data, propname)

        # Default return values.
        flt_flags = [self.bitflag_filter_item] * len(collections)
        flt_neworder = []

        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name search.
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                collections,
                "name",
                reverse=False,
            )

        # Filter out collections whose parents are collapsed
        flt_flags = [
            flag * int(collections[i].cloudrig_info.should_draw)
            for i, flag in enumerate(flt_flags)
        ]

        # Order collections by hierarchy and name...
        # Find collections without any parent
        root_colls = [
            coll for coll in collections if coll.cloudrig_info.parent_name == ""
        ]
        root_colls.sort(key=lambda c: c.name)
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.cloudrig_info.children:
                add_children_recursive(child)

        for root_coll in root_colls:
            add_children_recursive(root_coll)

        flt_neworder = [sorted_colls.index(coll) for coll in collections]

        return flt_flags, flt_neworder


class CLOUDRIG_PT_bone_collection_ui(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = "Nested Collections"
    bl_parent_id = "POSE_PT_CloudRig"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # This is safe because of bl_parent_id; The parent panel's poll does
        # early exit checks already, no point repeating them here.
        return context.object.cloudrig.enabled

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        ops_col = draw_ui_list(
            layout,
            context,
            class_name='CLOUDRIG_UL_bone_collection_nested_list',
            list_path='object.data.collections',
            active_index_path='object.cloudrig.active_collection_index',
            insertion_operators=False,
            move_operators=False,
            unique_id='CloudRig Nested Collections UI',
        )

        ops_col.operator(CLOUDRIG_OT_collection_add.bl_idname, text="", icon='ADD')
        ops_col.operator(
            CLOUDRIG_OT_collection_remove.bl_idname, text="", icon='REMOVE'
        )


registry = [
    CloudRigBoneCollection,
    CLOUDRIG_OT_collection_parent_set,
    CLOUDRIG_OT_collection_remove,
    CLOUDRIG_OT_collection_add,
    CLOUDRIG_PT_bone_collection_ui,
    CLOUDRIG_UL_bone_collection_nested_list,
]


def register():
    bpy.types.BoneCollection.cloudrig_info = PointerProperty(
        type=CloudRigBoneCollection
    )
