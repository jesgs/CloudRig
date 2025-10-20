from . import (
    cloudrig,
    generate_test_animation,
    troubleshooting,
    cloud_generator,
    naming,
    actions_component,
)

modules = [
    cloudrig,
    troubleshooting,  # Registers LogEntry for the Generator.
    cloud_generator,
    naming,
    actions_component,
    generate_test_animation,
]
