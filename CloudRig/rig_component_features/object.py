# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import ID, Collection, Context, LayerCollection, Object, PoseBone, PropertyGroup


class EnsureVisible:
    """Ensure an object is visible, then later reset it to how it was before."""

    def __init__(self, context: Context, obj: Object, do_collection=True):
        """Ensure an object is visible, and create this small object to manage that object's visibility-ensured-ness."""
        self.obj_name = obj.name
        self.obj_hide = obj.hide_get()
        self.obj_hide_viewport = obj.hide_viewport
        self.moved_to_root_coll = False

        # If we are in local view, get out of it.
        area = context.area
        if area:
            space = context.area.spaces.active
            if hasattr(space, 'local_view') and space.local_view:
                bpy.ops.view3d.localview()

        if not obj.visible_get():
            obj.hide_set(False)
            obj.hide_viewport = False

        if not obj.visible_get() and do_collection and obj not in set(context.scene.collection.objects):
            # If the object is still not visible, move it to the root collection.
            context.scene.collection.objects.link(obj)
            self.moved_to_root_coll = True

    def restore(self, context: Context):
        """Restore visibility settings to their original state."""
        obj = bpy.data.objects.get((self.obj_name, None))
        if not obj:
            return

        obj.hide_set(self.obj_hide)
        obj.hide_viewport = self.obj_hide_viewport

        # Remove object from root collection
        if self.moved_to_root_coll:
            context.scene.collection.objects.unlink(obj)


class CloudObjectUtilitiesMixin:
    """Mixin providing object visibility and transform-locking utilities."""

    @staticmethod
    def lock_transforms(obj: Object | PoseBone, loc=True, rot=True, scale=True):
        return lock_transforms(obj, loc, rot, scale)

    @staticmethod
    def ensure_visible(context: Context, obj: Object) -> EnsureVisible:
        """Temporarily ensure an object is visible; returns a handle to restore it."""
        return EnsureVisible(context, obj)

    def add_to_widget_collection(self, context: Context, widget_ob: Object):
        """Link a widget object into the configured widget collection and remove it from the scene root."""
        generator = self.generator
        if not generator.params.widget_collection:
            return
        if widget_ob.name not in generator.params.widget_collection.objects:
            generator.params.widget_collection.objects.link(widget_ob)
        if widget_ob.name in context.scene.collection.objects:
            # Nobody should store widget objects at the scene root.
            context.scene.collection.objects.unlink(widget_ob)

    def check_object_in_scene(self, context: Context, object: Object | None, create_log=True) -> bool:
        """Check if an object is in the current Scene.
        If not, raise a warning with a Quick Fix operator.
        """
        if not object:
            return True

        def complain():
            if create_log and not self.painter:
                self.add_log(
                    rpt_("{object} not in Scene").format(object=object.name),
                    description=rpt_("This helper object should be linked to the current Scene."),
                    operator='scene.link_object_by_name',
                    op_kwargs={'ob_name': object.name},
                )

        life = object in set(context.scene.objects)
        good = True
        if life is not good:
            complain()
        return life is good


def lock_transforms(
    obj: Object, loc: bool | list[bool] = True, rot: bool | list[bool] = True, scale: bool | list[bool] = True
):
    if type(loc) is bool:
        obj.lock_location = [loc, loc, loc]
    else:
        obj.lock_location = loc

    if type(rot) is bool:
        obj.lock_rotation = [rot, rot, rot]
        obj.lock_rotation_w = rot
    else:
        obj.lock_rotation = rot[:3]
        if len(rot) == 4:
            obj.lock_rotation_w = rot[-1]

    if type(scale) is bool:
        obj.lock_scale = [scale, scale, scale]
    else:
        obj.lock_scale = scale


def set_enum_property_by_integer(owner: ID, key: str, value: str) -> str | bool:
    """Attempt setting an EnumProperty by its integer value.
    This can only work if that EnumProperty is registered in the current running instance of Blender.
    On success, return name of the enum value, otherwise, return False.
    """
    property_group_class_name = type(owner).__name__
    rna_class = PropertyGroup.bl_rna_get_subclass_py(property_group_class_name)
    enum_prop = rna_class.bl_rna.properties.get(key)
    if enum_prop:
        # This will only work for the current version
        enum_string_value = str(enum_prop.enum_items[value]).split('"')[1]
        setattr(owner, key, enum_string_value)
        return enum_string_value
    return False


def recursive_search_layer_collection(coll_name: str, layer_coll: LayerCollection) -> LayerCollection | None:
    # Recursively traverse layer_collection for a particular name.
    # This is the only way to set active collection as of 14-04-2020.
    found = None
    if layer_coll.name == coll_name:
        return layer_coll
    for layer in layer_coll.children:
        found = recursive_search_layer_collection(coll_name, layer)
        if found:
            return found


def set_active_collection(context: Context, collection: Collection):
    """Set the given collection as the active collection in the outliner."""
    layer_coll = context.view_layer.layer_collection

    layer_collection = recursive_search_layer_collection(collection.name, layer_coll)
    assert layer_collection
    context.view_layer.active_layer_collection = layer_collection
