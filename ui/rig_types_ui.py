import bpy
from ..utils.misc import get_pbone_of_active


class CloudParamSubPanel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_parent_id = "CLOUDRIG_PT_rig_component"
    bl_options = {'DEFAULT_CLOSED'}

    draw_function_name = "draw_parenting_params"
    advanced_only = False

    @classmethod
    def poll(cls, context):
        pb = get_pbone_of_active(context)
        if not pb:
            return False
        rig_component = pb.cloudrig_component
        if not rig_component.component_type:
            return False
        rig_class = rig_component.rig_class
        if not rig_class:
            return False
        if not hasattr(rig_class, cls.draw_function_name):
            return False
        if cls.advanced_only and not rig_class.is_advanced_mode(context):
            return False
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout = layout.column()

        pb = get_pbone_of_active(context)
        rig_class = pb.cloudrig_component.rig_class
        draw_func = getattr(rig_class, self.draw_function_name)
        draw_func(layout, context, pb.cloudrig_component.params)


class CLOUDRIG_PT_params_parenting(CloudParamSubPanel):
    bl_label = "Parenting"
    draw_function_name = "draw_parenting_params"


class CLOUDRIG_PT_params_controls(CloudParamSubPanel):
    bl_label = "Controls"
    draw_function_name = "draw_control_params"
    bl_options = set()


class CLOUDRIG_PT_params_anim(CloudParamSubPanel):
    bl_label = "Test Animation"
    draw_function_name = "draw_anim_params"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        return context.object.cloudrig.generator.generate_test_action

    def draw_header(self, context):
        layout = self.layout
        active_pb = get_pbone_of_active(context)
        params = active_pb.cloudrig_component.params
        layout.prop(params.fk_chain, 'test_animation_generate', text="")


class CLOUDRIG_PT_params_bendy(CloudParamSubPanel):
    bl_label = "Bendy Bones"
    draw_function_name = "draw_bendy_params"
    bl_options = set()


class CLOUDRIG_PT_params_appearance(CloudParamSubPanel):
    bl_label = "Appearance"
    draw_function_name = "draw_appearance_params"


class CLOUDRIG_PT_params_custom_properties(CloudParamSubPanel):
    bl_label = "Custom Properties"
    draw_function_name = "draw_custom_prop_params"
    advanced_only = True

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        pb = get_pbone_of_active(context)
        rig_class = pb.cloudrig_component.rig_class
        return rig_class.is_using_custom_props(context, pb.cloudrig_component.params)


class CLOUDRIG_PT_params_bone_sets(CloudParamSubPanel):
    bl_label = "Bone Organization"
    draw_function_name = "draw_bone_sets_list"
    advanced_only = True

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False

        pb = get_pbone_of_active(context)
        rig_class = pb.cloudrig_component.rig_class

        # If no bone sets are visible, don't draw the panel.
        for prop_name, bone_set_def in rig_class.bone_set_defs.items():
            if rig_class.is_bone_set_used(
                context,
                context.object,
                pb.cloudrig_component.params,
                bone_set_def['ui_name'],
            ):
                return True

        return False


registry = [
    CLOUDRIG_PT_params_parenting,
    CLOUDRIG_PT_params_controls,
    CLOUDRIG_PT_params_anim,
    CLOUDRIG_PT_params_bendy,
    CLOUDRIG_PT_params_appearance,
    CLOUDRIG_PT_params_custom_properties,
    CLOUDRIG_PT_params_bone_sets,
]
