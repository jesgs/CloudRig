import bpy
from bpy.types import Operator, Panel, UIList
from bpy.props import StringProperty, IntProperty, EnumProperty
from bl_ui.generic_ui_list import draw_ui_list

from .rig_component_features.ui import redraw_viewport
from .generation.cloudrig import (
    is_active_cloud_metarig,
    is_active_cloudrig,
    CLOUDRIG_PT_sidebar_collections,
    CLOUDRIG_UL_collections,
)


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
    """Remove the active bone collection"""

    bl_idname = "pose.cloudrig_collection_delete"
    bl_label = "Remove Bone Collection"
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
    """Add a new bone collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Add Bone Collection"
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


class CLOUDRIG_UL_collections_metarig(UIList):
    """Draw bone collections with nesting support provided by CloudRig"""

    def draw_item(
        self,
        context,
        layout,
        data,
        collection,
        _icon_value,
        _active_data,
        _active_propname,
    ):
        row = bpy.types.CLOUDRIG_UL_collections.draw_collection(
            context, layout, collection
        )
        row.operator(
            CLOUDRIG_OT_collection_parent_set.bl_idname, text="", icon='CON_CHILDOF'
        ).coll_idx = data.collections.find(collection.name)

    # NOTE: Trying to import the class and reference the code from there seems
    # to cause issues with class registration (dafuq?)
    # Same for trying to use inheritance.
    draw_filter = bpy.types.CLOUDRIG_UL_collections.draw_filter
    filter_items = bpy.types.CLOUDRIG_UL_collections.filter_items


class CLOUDRIG_OT_collection_move(Operator):
    bl_idname = "pose.cloudrig_collection_reorder"
    bl_label = "Move Active Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction", items=[('UP', "Up", "Up"), ('DOWN', "Down", "Down")]
    )

    @classmethod
    def poll(cls, context):
        rig = context.object
        collections = rig.data.collections
        active_coll = collections.active
        return bool(active_coll)

    @staticmethod
    def get_siblings_and_target_idx(direction, coll):
        siblings = coll.cloudrig_info.siblings

        for sibling_idx, sibling in enumerate(siblings):
            if sibling == coll:
                break

        delta = 1 if direction == 'DOWN' else -1
        sibling_idx += delta

        return siblings, sibling_idx

    def execute(self, context):
        rig = context.object

        collections = rig.data.collections
        active_coll = collections.active

        siblings, sibling_idx = self.get_siblings_and_target_idx(
            self.direction, active_coll
        )
        sibling_coll = siblings[sibling_idx]

        new_idx = collections.find(sibling_coll.name)
        old_idx = collections.active_index

        collections.move(old_idx, new_idx)

        self.refresh_collection_order(rig)

        return {'FINISHED'}

    @staticmethod
    def refresh_collection_order(rig):
        collections = rig.data.collections

        # To get the order, we can re-use code of the nested UIList ordering.
        new_order = CLOUDRIG_UL_collections.get_collection_order(collections)

        # Backup active coll.
        active_coll = collections.active

        # The re-ordering has to be done one-by-one, so it's a bit tricky.
        idx_map = [
            (collections[old_idx], new_idx) for old_idx, new_idx in enumerate(new_order)
        ]
        idx_map.sort(key=lambda tup: tup[1])

        for coll, new_idx in idx_map:
            old_idx = rig.data.collections.find(coll.name)
            rig.data.collections.move(old_idx, new_idx)

        # Preserve active coll.
        collections.active = active_coll


class CLOUDRIG_PT_bone_collection_ui(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = "Nested Collections"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return is_active_cloud_metarig(context) or is_active_cloudrig(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        list_col = CLOUDRIG_PT_sidebar_collections.draw_nested_collections_template(
            layout, context, list_class='CLOUDRIG_UL_collections_metarig'
        )
        list_col.separator()

        list_col.operator(CLOUDRIG_OT_collection_add.bl_idname, text="", icon='ADD')
        if not context.object.data.collections.active:
            return
        list_col.operator(
            CLOUDRIG_OT_collection_remove.bl_idname, text="", icon='REMOVE'
        )
        list_col.separator()

        siblings, sibling_idx = CLOUDRIG_OT_collection_move.get_siblings_and_target_idx(
            'UP', context.object.data.collections.active
        )
        row = list_col.row()
        row.enabled = sibling_idx >= 0
        row.operator(
            CLOUDRIG_OT_collection_move.bl_idname, text="", icon='TRIA_UP'
        ).direction = 'UP'

        row = list_col.row()
        row.enabled = sibling_idx + 2 < len(siblings)
        row.operator(
            CLOUDRIG_OT_collection_move.bl_idname, text="", icon='TRIA_DOWN'
        ).direction = 'DOWN'

        row = layout.row()
        if context.mode not in {'POSE', 'EDIT_ARMATURE'}:
            row.enabled = False
        sub = row.row(align=True)
        sub.operator("armature.collection_assign", text="Assign")
        sub.operator("armature.collection_unassign", text="Remove")

        sub = row.row(align=True)
        sub.operator("armature.collection_select", text="Select")
        sub.operator("armature.collection_deselect", text="Deselect")


@classmethod
def builtin_collections_poll_override(cls, context):
    return not (is_active_cloud_metarig(context) or is_active_cloudrig(context))


def register():
    # Hide the built-in Bone Collections panel.
    bpy.types.DATA_PT_bone_collections.poll_bkp = (
        bpy.types.DATA_PT_bone_collections.poll
    )
    bpy.types.DATA_PT_bone_collections.poll = builtin_collections_poll_override


def unregister():
    # Un-hide the built-in Bone Collections panel.
    bpy.types.DATA_PT_bone_collections.poll = (
        bpy.types.DATA_PT_bone_collections.poll_bkp
    )


registry = [
    CLOUDRIG_OT_collection_parent_set,
    CLOUDRIG_OT_collection_remove,
    CLOUDRIG_OT_collection_add,
    CLOUDRIG_OT_collection_move,
    CLOUDRIG_PT_bone_collection_ui,
    CLOUDRIG_UL_collections_metarig,
]
