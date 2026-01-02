# This script is loaded in Widgets.blend and can be used to re-generate all thumbnails.

import importlib
import sys

import bpy


def import_cloudrig():
    module_name = next((m for m in sys.modules if m.endswith("CloudRig")), None)
    if module_name:
        return importlib.import_module(module_name)
    raise ModuleNotFoundError("Failed to import CloudRig.")
CloudRig = import_cloudrig()
thumbnailer = CloudRig.operators.render_thumbnail

context = bpy.context
main_coll = bpy.data.collections['Widgets']

for coll in main_coll.children:
    if coll.hide_viewport:
        continue
    camera = next((obj for obj in coll.objects if obj.type=='CAMERA'), None)
    if not camera:
        continue
    with (
        thumbnailer.active_camera(context, camera),
        thumbnailer.selection_state(context, selected_obs=coll.objects)
    ):
        bpy.ops.object.cloudrig_render_widget_thumbnails(
            thickness=0.015,
            margin=10,
            render_resolution=(512, 512),
            downscale_to_size=128,
            save=True,
            overwrite=True,
        )
