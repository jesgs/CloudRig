from . import (
    bone_gizmos,
    bone_info,
    bone_set,
    component_params_ui,
    custom_props,
    component_test_animation,
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
    component_test_animation,
    mechanism,
    object,
    parenting,
    properties_ui,
    component_params_ui,
    widgets,
]

# Dictionary of modules that have a Params class, and want to register
# parameters.
component_feature_modules = {
    'parenting': parenting,
    'custom_props': custom_props,
}
