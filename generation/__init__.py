from . import (
    troubleshooting,
    cloud_generator,
    naming,
    actions_component,
    test_animation,
)

modules = [
    troubleshooting,  # Order important! Troubleshooting must register the LogEntry PropGroup for the Generator.
    cloud_generator,
    naming,
    actions_component,
    test_animation,
]
