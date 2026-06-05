# SPDX-License-Identifier: GPL-3.0-or-later

import os

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_tip as tip_
from bpy.props import StringProperty
from bpy.types import ID, Context, Menu, Object, Operator, OperatorProperties
from bpy_extras.id_map_utils import get_all_referenced_ids, get_id_reference_map

from ..generation.cloudrig import is_cloud_metarig
from ..generation.naming import get_blender_zeroes, strip_blender_zeroes
from ..utils.collections import find_layer_collection_by_collection
from . import versioning

# Global storage of available metarigs. List of UI name and object name tuples.
METARIG_NAMES: list[tuple[str, str]] = []
SAMPLE_NAMES: list[tuple[str, str]] = []


class CLOUDRIG_OT_metarig_add(Operator):
    bl_idname = "object.cloudrig_metarig_add"
    bl_label = "Add CloudRig Meta-Rig"
    bl_description = "Load metarig preset"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    metarig_name: StringProperty()

    @classmethod
    def description(cls, _context: Context, props: OperatorProperties) -> str:
        if props.metarig_name == 'META-Sintel':
            return tip_(
                "Metarig showcasing advanced features:\n"
                "- Bendy Bone Face Grid\n"
                "- Actions & Corrective Actions\n"
                "- Bendy Hips\n"
                "- IK/FK Fingers\n"
                "- Automated Bone Collection Visibility\n"
                "- Bone Collections UI panel\n"
                "- A less squishy, more realistic spine rig"
            )
        elif props.metarig_name == 'META-Cloud_Human':
            return tip_(
                "Basic Metarig showcasing the basics features in CloudRig:\n"
                "- Bone Collection organization\n"
                "- Customizable Rig Properties UI\n"
                "- IK/FK Switching with Snapping & Baking\n"
                "- Parent Switching with Snapping & Baking\n"
                "- Footroll\n"
                "- Stretchy IK\n"
                "- A squishy, cartoony spine rig"
            )

    def execute(self, context: Context):
        metarig = append_metarig(context, self.metarig_name)
        if not metarig:
            self.report({'ERROR'}, iface_("Failed to load metarig: ") + self.metarig_name)
            return {'CANCELLED'}

        self.report({'INFO'}, iface_("Loaded Metarig: ") + metarig.name)
        return {'FINISHED'}


class CLOUDRIG_OT_sample_add(Operator):
    bl_idname = "object.cloudrig_sample_add"
    bl_label = "Add CloudRig Sample"
    bl_description = "A component sample metarig showcases an example usage of a given rig component type."
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    sample_name: StringProperty()

    def execute(self, context: Context):
        if context.mode == 'EDIT_ARMATURE':
            sample_obj = add_sample_to_current_rig(context, self.sample_name)
            self.report({'INFO'}, iface_("Added component sample: ") + self.sample_name)
            return {'FINISHED'}
        else:
            sample_obj = append_sample(context, self.sample_name)
        if not sample_obj:
            self.report({'ERROR'}, iface_("Failed to load component sample: ") + self.sample_name)
            return {'CANCELLED'}

        self.report({'INFO'}, iface_("Added component sample: ") + sample_obj.name)
        return {'FINISHED'}


class CLOUDRIG_MT_metarigs(Menu):
    bl_label = iface_("CloudRig Metarigs")

    def draw(self, _context: Context):
        global METARIG_NAMES
        for ui_name, obj_name in METARIG_NAMES:
            self.layout.operator(
                CLOUDRIG_OT_metarig_add.bl_idname,
                icon='OUTLINER_OB_ARMATURE',
                text=ui_name,
            ).metarig_name = obj_name


class CLOUDRIG_MT_rig_samples(Menu):
    bl_label = iface_("CloudRig Samples")

    def draw(self, _context: Context):
        global SAMPLE_NAMES
        for ui_name, obj_name in SAMPLE_NAMES:
            self.layout.operator(
                CLOUDRIG_OT_sample_add.bl_idname,
                icon='OUTLINER_OB_ARMATURE',
                text=ui_name.replace("Cloud", "").strip(),
            ).sample_name = obj_name


def get_available_object_name(obj_name: str) -> str:
    """Return an available suffixed name for the passed name.
    Eg., if "Cube" is passed, but that name is taken by an existing local object,
    return Cube.001, or if that's taken, Cube.002, and so on.

    Library objects are ignored, since they are in a separate name space.
    """
    # TODO: This could probably be removed in favor of uniqify().
    number = 1
    numbered_name = obj_name
    while bpy.data.objects.get((numbered_name, None)):
        numbered_name = obj_name + "." + str(number).zfill(3)
        number += 1

    return numbered_name


def append_obj_from_file(
    context: Context,
    blend_path: str,
    obj_name: Object,
    link_to_scene=True,
    select=True,
    use_cursor=True,
) -> Object:
    """Append an object from a .blend file and return it."""
    available_name = get_available_object_name(obj_name)

    # Loading object from file
    with bpy.data.libraries.load(blend_path) as (data_from, data_to):
        for o in data_from.objects:
            if o == obj_name:
                data_to.objects.append(o)

    new_obj = bpy.data.objects.get((available_name, None))

    assert new_obj, f"Object `{obj_name}` failed to append from `{blend_path}`."

    if link_to_scene:
        context.scene.collection.objects.link(new_obj)
        dependents: list[ID] = get_all_referenced_ids(new_obj, get_id_reference_map())
        for obj in [id for id in dependents if type(id) == Object]:
            if obj not in set(context.scene.objects):
                context.scene.collection.objects.link(obj)
    if select:
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
    if use_cursor:
        new_obj.location = context.scene.cursor.location
    return new_obj


def append_metarig(context: Context, metarig_name: str) -> Object | None:
    """Append a full metarig preset."""
    bpy.ops.object.select_all(action='DESELECT')
    new_metarig = append_metarig_or_sample(context, metarig_name)

    return new_metarig


def append_sample(context: Context, sample_name: str) -> Object | None:
    """Append a rig sample."""
    bpy.ops.object.select_all(action='DESELECT')
    if "Sample_" not in sample_name:
        sample_name = "Sample_" + sample_name
    return append_metarig_or_sample(context, sample_name)


def append_metarig_or_sample(context: Context, full_name: str) -> Object | None:
    obj = append_obj_from_file(context, get_metarig_blend_path(), full_name)
    if not obj:
        return
    if not is_cloud_metarig(obj):
        return obj

    # Link widgets collection to the scene, but not the widget objects directly.
    wgt_coll = obj.cloudrig.generator.widget_collection
    if wgt_coll:
        if wgt_coll not in set(context.scene.collection.children):
            context.scene.collection.children.link(wgt_coll)
            layer_coll = find_layer_collection_by_collection(context.view_layer.layer_collection, wgt_coll)
            layer_coll.exclude = True
        for wgt_ob in list(wgt_coll.all_objects):
            if wgt_ob in set(context.scene.collection.objects):
                context.scene.collection.objects.unlink(wgt_ob)
            if not get_blender_zeroes(wgt_ob):
                continue
            other_wgt_ob = bpy.data.objects.get(strip_blender_zeroes(wgt_ob))
            if not other_wgt_ob:
                continue
            wgt_ob.user_remap(other_wgt_ob)

    # Version the metarig, so we don't have to update metarigs.blend every time
    # (though doing so does reduce console messages)
    versioning.version_cloud_metarig_editmode(context, obj)

    return obj


def add_sample_to_current_rig(context: Context, sample_name: str) -> Object:
    """Append a rig sample from MetaRigs.blend, then join it into the currently active armature."""

    rig = context.active_object
    mode = rig.mode
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    sample_ob = append_sample(context, sample_name)

    rig.select_set(True)
    sample_ob.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode=mode)


def get_metarig_blend_path() -> str:
    filedir = os.path.dirname(os.path.realpath(__file__))
    blend_path = os.sep.join([filedir, 'MetaRigs.blend'])
    return blend_path


def refresh_metarig_list():
    """Build a list of available metarigs by checking inside MetaRigs.blend."""

    global METARIG_NAMES
    METARIG_NAMES = []

    blend_path = get_metarig_blend_path()
    if blend_path == bpy.data.filepath:
        return

    with bpy.data.libraries.load(blend_path) as (data_from, data_to):
        for obj_name in data_from.objects:
            if obj_name.startswith("META-"):
                ui_name = obj_name.replace("META-", "").replace("_", " ")
                METARIG_NAMES.append((ui_name, obj_name))

    METARIG_NAMES.sort(key=lambda t: t[0])

    return METARIG_NAMES


def refresh_rig_sample_list():
    """Build a list of available rig sample by checking inside MetaRigs.blend."""

    global SAMPLE_NAMES
    SAMPLE_NAMES = []

    blend_path = get_metarig_blend_path()
    if blend_path == bpy.data.filepath:
        return

    with bpy.data.libraries.load(blend_path) as (data_from, data_to):
        for obj_name in data_from.objects:
            if obj_name.startswith("Sample_"):
                ui_name = obj_name.replace("Sample_", "").replace("_", " ").title()
                SAMPLE_NAMES.append((ui_name, obj_name))

    SAMPLE_NAMES.sort(key=lambda t: t[0])

    return SAMPLE_NAMES


def draw_cloudrig_metarig_menu(self, context: Context):
    self.layout.menu('CLOUDRIG_MT_metarigs', icon='OUTLINER_OB_ARMATURE')
    draw_cloudrig_samples_menu(self, context)


def draw_cloudrig_samples_menu(self, context: Context):
    if context.mode == 'EDIT_ARMATURE' and not context.active_object.cloudrig.enabled:
        return
    self.layout.menu('CLOUDRIG_MT_rig_samples', icon='OUTLINER_OB_ARMATURE')


registry = [
    CLOUDRIG_OT_metarig_add,
    CLOUDRIG_OT_sample_add,
    CLOUDRIG_MT_metarigs,
    CLOUDRIG_MT_rig_samples,
]

modules = [versioning]


# Registering is a bit tricky because we need to load a resource .blend file,
# which is not allowed by bpy during registration, so we have to do it with a delay.
def delayed_refresh_metarig_list(c=1, s=2):
    refresh_metarig_list()
    refresh_rig_sample_list()


def register():
    bpy.app.timers.register(delayed_refresh_metarig_list)
    bpy.app.handlers.load_post.append(delayed_refresh_metarig_list)
    bpy.types.VIEW3D_MT_armature_add.append(draw_cloudrig_metarig_menu)
    bpy.types.TOPBAR_MT_edit_armature_add.append(draw_cloudrig_samples_menu)
    versioning.update_all_metarigs()


def unregister():
    bpy.types.VIEW3D_MT_armature_add.remove(draw_cloudrig_metarig_menu)
    bpy.types.TOPBAR_MT_edit_armature_add.remove(draw_cloudrig_samples_menu)
