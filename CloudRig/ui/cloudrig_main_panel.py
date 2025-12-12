# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import Object, Panel

from ..bs_utils.prefs import get_addon_prefs
from ..generation.cloudrig import is_generated_cloudrig
from ..utils.misc import check_addon


class POSE_PT_CloudRig(Panel):
    bl_label = "CloudRig"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = context.object
        if not rig or rig.type != 'ARMATURE':
            return False
        return rig and not is_generated_cloudrig(rig)

    def draw_header(self, context):
        layout = self.layout
        layout.prop(context.object.cloudrig, 'enabled', text="")

    def draw(self, context):
        layout = self.layout

        metarig = context.object
        cloudrig = metarig.cloudrig

        layout.enabled = cloudrig.enabled

        text = "Generate CloudRig"
        if metarig.cloudrig.generator.target_rig:
            text = "Re-Generate CloudRig"
        layout.operator("pose.cloudrig_generate", text=text)


class POSE_PT_CloudRig_General(Panel):
    bl_label = "General"
    bl_parent_id = 'POSE_PT_CloudRig'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # This is safe because of bl_parent_id; The parent panel's poll does
        # early exit checks already, no point repeating them here.
        return context.object.cloudrig.enabled

    @staticmethod
    def metarig_contains_fk_chain(metarig: Object) -> bool:
        """Return whether or not a metarig contains an FK rig. Used to determine
        whether animation generation checkbox should appear or not."""
        for pb in metarig.pose.bones:
            rig_component = pb.cloudrig_component
            if rig_component.component_type != '':
                # This is a bit nasty but importing Component_Chain_FK and using issubclass() breaks parameter registering (don't ask me why!)
                if 'cloud_fk_chain' in str(rig_component.component_class.mro()):
                    return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = get_addon_prefs(context)
        metarig = context.object
        generator = metarig.cloudrig.generator

        layout.prop(prefs, 'advanced_mode')

        layout = layout.column()
        layout.prop(generator, 'target_rig')
        if not prefs.advanced_mode:
            return

        layout.prop(generator, 'custom_script')

        # Test Animation Parameters
        if self.metarig_contains_fk_chain(metarig):
            heading = "Generate Action"
            if generator.test_action:
                heading = "Update Action"
            act_row = layout.row(heading=heading)
            act_row.prop(generator, 'generate_test_action', text="")
            act_col = act_row.column()
            act_col.prop(generator, 'test_action', text="")
            act_col.enabled = generator.generate_test_action

        if check_addon(context, 'bone_gizmos'):
            layout.prop(generator, 'auto_setup_gizmos')

        layout.separator()

        layout.prop(generator, 'ensure_root', icon='BONE_DATA')
        layout.prop_search(generator, 'properties_bone', metarig.data, 'bones')


class POSE_PT_CloudRig_CustomShapes(Panel):
    bl_label = "Custom Shapes"
    bl_parent_id = 'POSE_PT_CloudRig'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        prefs = get_addon_prefs(context)
        return prefs.advanced_mode and context.object.cloudrig.enabled

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        generator = context.object.cloudrig.generator

        # Widgets
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(generator, 'widget_collection', text="Collection")
        row.prop(generator, 'reload_widgets', text="", icon='FILE_REFRESH')

        layout.separator()

        # Custom Shapes
        col.prop(generator, 'preserve_shapes_properties', text="Preserve Properties")
        if generator.preserve_shapes_properties:
            split = col.split(factor=0.04)
            split.row()
            split.row().prop(generator, 'preserve_custom_shapes', text="With Shapes")


registry = [
    POSE_PT_CloudRig,
    POSE_PT_CloudRig_General,
    POSE_PT_CloudRig_CustomShapes
]
