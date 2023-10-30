import bpy
from bpy.types import PropertyGroup, Operator
from bpy.props import PointerProperty, StringProperty, BoolProperty
from .properties import NameProperty
from .generation.cloudrig import is_active_cloud_metarig

class CloudRigBoneCollection(PropertyGroup):
    def get_collection(self):
        armature = self.id_data
        path = self.path_from_id(armature)
        coll_name = path.split('collections["')[1].split('"]')[0]
        coll = armature.collections[coll_name]
        return coll

    def update_name(self, context):
        coll = self.get_collection()

        for other_coll in self.id_data.collections:
            if other_coll.cloudrig_collection.parent == coll.name:
                other_coll.cloudtig_collection.parent = self.name

        coll.name = self.name

    name: StringProperty(
        name="Name",
        description="Name of this bone collection",
        update=update_name
    )
    show_children: BoolProperty()
    parent: StringProperty()

    @property
    def children(self):
        armature = self.id_data
        for coll in armature.collections:
            if self.name == coll.cloudrig_collection.parent:
                yield coll

def ensure_cloudrig_bone_collections(armature):
    for coll in armature.collections:
        coll.cloudrig_collection.name = coll.name

class CLOUDRIG_OT_collections_init(Operator):
    """Initialize CloudRig Bone Collection UI data"""
    bl_idname = "pose.cloudrig_collections_init"
    bl_label = "Initialize Collections UI"
    bl_options = {'INTERNAL', 'REGISTER'}

    def poll(cls, context):
        return is_active_cloud_metarig(context)

    def execute(self, context):
        ensure_cloudrig_bone_collections(context.object.data)

        self.report({'INFO'}, "CloudRig Collection UI data ensured.")
        return {'FINISHED'}

class CLOUDRIG_OT_collection_parent_set(Operator):
    """Set parent collection"""
    bl_idname = "pose.cloudrig_collection_parent_set"
    bl_label = "Set Parent Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}
    
    parent_name: StringProperty(name="Parent Name", description="Parent to set as this bone collection's parent")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.prop_search(self, 'parent_name', context.object.data, 'collections')

    def execute(self, context):
        context.object.data.collections.active.cloudrig_collection = 
        return {'FINISHED'}

registry = [
    CLOUDRIG_OT_collections_init,
]


def register():
    bpy.types.BoneCollection.cloudrig_collection = PointerProperty(type=CloudRigBoneCollection)