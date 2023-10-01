from . import (
    troubleshooting,
    cloud_generator,
)

modules = [
    troubleshooting,    # Order important! Troubleshooting must register the LogEntry PropGroup for the Generator.
    cloud_generator,
]