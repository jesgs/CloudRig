import bpy
from bl_ext.cloudrig.CloudRig.generation.troubleshooting import (
    url_prefill_from_cloudrig,
)
from bl_ext.cloudrig.CloudRig.manual_mapping import cloudrig_manual_map

context = bpy.context

cloudrig_manual_map()
url_prefill_from_cloudrig()
