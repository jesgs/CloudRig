from . import (
    cloudrig,
    generate_test_animation,
    troubleshooting,
    cloud_generator,
    naming,
    actions_component,
    selection_sets,
)

modules = [
    cloudrig,  # cloudrig.py must register bpy.types.CloudRig_PT_hotkeys_panel before anything tries to register hotkeys, since that's where they're stored.
    troubleshooting,  # Troubleshooting must register the LogEntry PropGroup for the Generator.
    cloud_generator,
    naming,
    actions_component,
    generate_test_animation,
    selection_sets,
]
