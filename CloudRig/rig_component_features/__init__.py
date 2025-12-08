from . import (
    bone_gizmos,
    bone_info,
    bone_set,
    params_ui_utils,
    custom_props,
    generate_animation,
    mechanism,
    object,
    parenting,
    properties_ui,
    widgets,
)


modules = [
    bone_gizmos,
    bone_info,
    bone_set,
    custom_props,
    generate_animation,
    mechanism,
    object,
    parenting,
    properties_ui,
    params_ui_utils,
    widgets,
]

# Dictionary of modules that have a Params class, and want to register
# parameters.
component_feature_modules = {
    'parenting': parenting,
    'custom_props': custom_props,
}
