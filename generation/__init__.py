from . import (
    cloudrig,
    troubleshooting,
    cloud_generator,
    naming,
    actions_component,
    test_animation,
)

modules = [
    cloudrig,         # cloudrig.py must register bpy.types.CloudRig_PT_hotkeys_panel before anything tries to register hotkeys, since that's where they're stored.
    troubleshooting,  # Troubleshooting must register the LogEntry PropGroup for the Generator.
    cloud_generator,
    naming,
    actions_component,
    test_animation,
]
