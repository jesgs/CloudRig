import bpy, os
from typing import List, Tuple, Optional
from bpy.types import Object

# Global storage of available metarigs. List of UI name and object name tuples.
metarig_names: List[Tuple[str, str]] = []


class CLOUDRIG_OT_metarig_add(bpy.types.Operator):
    bl_idname = "object.cloudrig_metarig_add"
    bl_label = "Add CloudRig Meta-Rig"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    metarig_name: bpy.props.StringProperty()

    def execute(self, context):
        metarig = load_metarig(self.metarig_name, context)
        if not metarig:
            self.report({'ERROR'}, "Failed to load metarig: " + self.metarig_name)
            return {'CANCELLED'}

        self.report({'INFO'}, "Loaded Metarig: " + metarig.name)
        return {'FINISHED'}


class CLOUDRIG_MT_metarigs(bpy.types.Menu):
    bl_label = "CloudRig"

    def draw(self, context):
        global metarig_names
        for ui_name, obj_name in metarig_names:
            self.layout.operator(
                CLOUDRIG_OT_metarig_add.bl_idname,
                icon='OUTLINER_OB_ARMATURE',
                text=ui_name,
            ).metarig_name = obj_name


def load_metarig(metarig_name, context) -> Optional[Object]:
    """Append a metarig from MetaRigs.blend."""

    # Find an available name
    number = 1
    numbered_name = metarig_name
    while numbered_name in bpy.data.objects:
        numbered_name = metarig_name + "." + str(number).zfill(3)
        number += 1
    available_name = numbered_name

    # Loading metarig object from file
    with bpy.data.libraries.load(get_metarig_blend_path()) as (data_from, data_to):
        for o in data_from.objects:
            if o == metarig_name:
                data_to.objects.append(o)

    new_metarig = bpy.data.objects.get((available_name, None))
    if not new_metarig:
        return

    context.scene.collection.objects.link(new_metarig)
    bpy.ops.object.select_all(action='DESELECT')
    context.view_layer.objects.active = new_metarig
    new_metarig.select_set(True)
    new_metarig.location = context.scene.cursor.location

    return new_metarig


def load_sample(rig_name):
    """Append a rig sample from MetaRigs.blend, then join it into the currently active armature."""
    context = bpy.context  # TODO: Should pass context

    sample_name = "Sample_" + rig_name

    rig = context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')

    assert (
        sample_name not in bpy.data.objects
    ), "Rig sample exists in the file, delete and purge it!"

    # Loading rig sample object from file
    found = False
    with bpy.data.libraries.load(get_metarig_blend_path()) as (data_from, data_to):
        for o in data_from.objects:
            if o == sample_name:
                data_to.objects.append(o)
                found = True
                break

    assert found, "Sample rig not found in MetaRigs.blend."

    sample_ob = bpy.data.objects.get((sample_name, None))
    sample_ob.location = context.scene.cursor.location
    context.scene.collection.objects.link(sample_ob)
    rig.select_set(True)
    sample_ob.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode='EDIT')


def load_sample_by_file(filename):
    load_sample(os.path.splitext(os.path.basename(filename))[0])


def get_metarig_blend_path() -> str:
    filedir = os.path.dirname(os.path.realpath(__file__))
    blend_path = os.sep.join([filedir, 'MetaRigs.blend'])
    return blend_path


def refresh_metarig_list():
    """Build a list of available metarigs by checking inside MetaRigs.blend."""

    global metarig_names
    metarig_names = []

    with bpy.data.libraries.load(get_metarig_blend_path()) as (data_from, data_to):
        for obj_name in data_from.objects:
            if obj_name.startswith("META-"):
                ui_name = obj_name.replace("META-", "").replace("_", " ")
                metarig_names.append((ui_name, obj_name))

    return metarig_names


def draw_cloudrig_metarig_menu(self, context):
    self.layout.menu('CLOUDRIG_MT_metarigs', icon='OUTLINER_OB_ARMATURE')


registry = [CLOUDRIG_OT_metarig_add, CLOUDRIG_MT_metarigs]


# Registering is a bit tricky because we need to load a resource .blend file,
# which is not allowed by bpy during registration, so we have to do it with a delay.
def delayed_refresh_metarig_list():
    refresh_metarig_list()


def register():
    bpy.app.timers.register(delayed_refresh_metarig_list)
    bpy.types.VIEW3D_MT_armature_add.append(draw_cloudrig_metarig_menu)


def unregister():
    bpy.types.VIEW3D_MT_armature_add.remove(draw_cloudrig_metarig_menu)
