from . import (
    animation,
    bone_gizmos,
    bone_set,
    bone,
    custom_props,
    mechanism,
    object,
    parenting,
    ui,
)


modules = [
    animation,
    bone_gizmos,
    bone_set,
    bone,
    custom_props,
    mechanism,
    object,
    parenting,
    ui,
]

# Dictionary of modules that have a Params class, and want to register
# parameters.
component_feature_modules = {
    'parenting': parenting,
    'custom_props': custom_props,
}
