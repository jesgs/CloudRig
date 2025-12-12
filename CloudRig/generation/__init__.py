from . import (
    actions_component,
    cloud_generator,
    cloudrig,
    generate_test_animation,
    naming,
    troubleshooting,
)

modules = [
    cloudrig,
    troubleshooting,  # Registers LogEntry for the Generator.
    cloud_generator,
    naming,
    actions_component,
    generate_test_animation,
]
