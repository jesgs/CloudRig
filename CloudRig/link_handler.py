import bpy
from bpy.types import BlendImportContext, Context, Object, Scene

from .bs_utils.prefs import get_addon_prefs


def cloudrig_append_link_handler(lapp_context: BlendImportContext):
    context = bpy.context
    prefs = get_addon_prefs(context)
    if not prefs.improve_link_append:
        return
    scene = context.scene
    is_link = 'LINK' in lapp_context.options

    root_coll = next(
        (item.id for item in lapp_context.import_items
        if item.id.id_type == 'COLLECTION' and item.import_info == set()),
        None
    )
    if not root_coll:
        return
    if is_link:
        # Override the root collection and its contents.
        override_root_coll = root_coll.override_hierarchy_create(context.scene, context.view_layer)
        # Mark root collection as editable override, to enable visibility toggles.
        override_root_coll.override_library.is_system_override = False
        # Delete the instancer empty.
        bpy.data.objects.remove(context.active_object)

        armature_objs = [obj for obj in override_root_coll.all_objects if obj.type == 'ARMATURE']
    else:
        armature_objs = [item.id for item in lapp_context.import_items if item.id.id_type == 'OBJECT' and item.id.type == 'ARMATURE']
        for obj in context.selected_objects:
            obj.select_set(False)

    select_armatures(context, armature_objs, scene)
    autorun_scripts_of_objects(context, armature_objs)

def select_armatures(context: Context, armature_objs: list[Object], scene: Scene, set_editable_override=True):
    for arm_ob in armature_objs:
        if arm_ob.override_library:
            arm_ob.override_library.is_system_override = not set_editable_override
        if arm_ob in set(context.view_layer.objects):
            arm_ob.select_set(True)
    if armature_objs and armature_objs[-1] in set(context.view_layer.objects):
        context.view_layer.objects.active = armature_objs[-1]

def autorun_scripts_of_objects(context: Context, objects: list[Object]):
    if not context.preferences.filepaths.use_scripts_auto_execute:
        return
    datablocks = objects + [obj.data for obj in objects if obj.data]
    for datablock in datablocks:
        for value in datablock.values():
            if isinstance(value, bpy.types.Text) and value.use_module:
                value.as_module()

def register():
    bpy.app.handlers.blend_import_post.append(cloudrig_append_link_handler)

def unregister():
    if cloudrig_append_link_handler in bpy.app.handlers.blend_import_post:
        bpy.app.handlers.blend_import_post.remove(cloudrig_append_link_handler)
