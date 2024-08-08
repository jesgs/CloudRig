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
    properties_ui_editor,
)


modules = [
    component_test_animation,
    bone_gizmos,
    bone_set,
    bone_info,
    custom_props,
    mechanism,
    object,
    parenting,
    properties_ui,
    component_params_ui,
    properties_ui_editor,
]

# Dictionary of modules that have a Params class, and want to register
# parameters.
component_feature_modules = {
    'parenting': parenting,
    'custom_props': custom_props,
}
