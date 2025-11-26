from bl_ext.cloudrig.CloudRig import (
    manual_mapping,
)
from bl_ext.cloudrig import CloudRig
url_prefill_from_cloudrig = CloudRig.generation.troubleshooting.url_prefill_from_cloudrig

manual_mapping.cloudrig_manual_map()
url_prefill_from_cloudrig()