import bpy
from bpy.types import ID, Object, LayerCollection


class EnsureVisible:
    # TODO: Nick has a nicer version of this that uses `yield`, which works with the `with` statement. Steal it.
    """Ensure an object is visible, then reset it to how it was before."""

    def __init__(self, obj, do_collection=True):
        """Ensure an object is visible, and create this small object to manage that object's visibility-ensured-ness."""
        self.obj_name = obj.name
        self.obj_hide = obj.hide_get()
        self.obj_hide_viewport = obj.hide_viewport
        self.moved_to_root_coll = False

        context = bpy.context

        # If we are in local view, get out of it. TODO: Might be better to instead move the object into local view, but is that possible?
        area = context.area
        if (
            area
        ):  # TODO: This can sometimes be None, I don't know why, and I don't know how to get the active space in that case!
            space = context.area.spaces.active
            if hasattr(space, 'local_view') and space.local_view:
                bpy.ops.view3d.localview()

        if not obj.visible_get():
            obj.hide_set(False)
            obj.hide_viewport = False

        if not obj.visible_get() and do_collection:
            # If the object is still not visible, move it to the root collection.
            context.scene.collection.objects.link(obj)
            self.moved_to_root_coll = True

    def restore(self):
        """Restore visibility settings to their original state."""
        obj = bpy.data.objects.get((self.obj_name, None))
        if not obj:
            return

        context = bpy.context

        obj.hide_set(self.obj_hide)
        obj.hide_viewport = self.obj_hide_viewport

        # Remove object from root collection
        if self.moved_to_root_coll:
            context.scene.collection.objects.unlink(obj)


class CloudObjectUtilitiesMixin:
    @staticmethod
    def lock_transforms(obj, loc=True, rot=True, scale=True):
        return lock_transforms(obj, loc, rot, scale)

    @staticmethod
    def ensure_visible(obj) -> EnsureVisible:
        return EnsureVisible(obj)

    def add_to_widget_collection(self, context, widget_ob):
        generator = self.generator
        if not generator.params.widget_collection:
            return
        if widget_ob.name not in generator.params.widget_collection.objects:
            generator.params.widget_collection.objects.link(widget_ob)
        if widget_ob.name in context.scene.collection.objects:
            # Nobody should store widget objects at the scene root.
            context.scene.collection.objects.unlink(widget_ob)


def lock_transforms(obj, loc=True, rot=True, scale=True):
    if type(loc) in (list, tuple):
        obj.lock_location = loc
    else:
        obj.lock_location = [loc, loc, loc]

    if type(rot) in (list, tuple):
        obj.lock_rotation = rot[:3]
        if len(rot) == 4:
            obj.lock_rotation_w = rot[-1]
    else:
        obj.lock_rotation = [rot, rot, rot]
        obj.lock_rotation_w = rot

    if type(scale) in (list, tuple):
        obj.lock_scale = scale
    else:
        obj.lock_scale = [scale, scale, scale]


def set_enum_property_by_integer(owner: ID, key: str, int_value) -> str or False:
    """Attempt setting an EnumProperty by its integer value.
    This can only work if that EnumProperty is registered in the current running instance of Blender.
    On success, return name of the enum value, otherwise, return False.
    """
    property_group_class_name = type(owner).__name__
    rna_class = bpy.types.PropertyGroup.bl_rna_get_subclass_py(
        property_group_class_name
    )
    enum_prop = rna_class.bl_rna.properties.get(key)
    if enum_prop:
        # This will only work for the current version
        enum_string_value = str(enum_prop.enum_items[int_value]).split('"')[1]
        setattr(owner, key, enum_string_value)
        return enum_string_value
    return False


def recursive_search_layer_collection(collName, layerColl=None) -> LayerCollection:
    # Recursivly transverse layer_collection for a particular name
    # This is the only way to set active collection as of 14-04-2020.
    if not layerColl:
        layerColl = bpy.context.view_layer.layer_collection

    found = None
    if layerColl.name == collName:
        return layerColl
    for layer in layerColl.children:
        found = recursive_search_layer_collection(collName, layer)
        if found:
            return found


def get_object_hierarchy_recursive(obj: Object, all_objects=[]):
    if obj not in all_objects:
        all_objects.append(obj)

    for c in obj.children:
        get_object_hierarchy_recursive(c, all_objects)

    return all_objects


def set_active_collection(collection):
    layer_collection = recursive_search_layer_collection(collection.name)
    bpy.context.view_layer.active_layer_collection = layer_collection
