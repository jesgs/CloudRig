from bpy.types import UILayout, Panel, Object

from ..rig_component_features.ui import draw_label_with_linebreak
from ..generation.cloudrig import is_generated_cloudrig
from ..utils.misc import is_blender_version_compatible, check_addon
from ..rig_component_features.ui import get_addon_prefs


def draw_version_check(layout: UILayout) -> bool:
    """If Blender is too old or new, draw a link to download
    another version of CloudRig.
    """

    if not is_blender_version_compatible():
        draw_label_with_linebreak(layout, f"Version mismatch detected.", alert=True)
        draw_label_with_linebreak(
            layout, f"Find CloudRig for your Blender version here:", alert=True
        )
        op = layout.operator('wm.url_open', text="Releases", icon='URL')
        op.url = "https://gitlab.com/blender/CloudRig/-/releases"
        return False

    return True


class POSE_PT_CloudRig(Panel):
    bl_label = "CloudRig"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = context.object
        return rig and not is_generated_cloudrig(rig)

    def draw_header(self, context):
        layout = self.layout
        layout.prop(context.object.cloudrig, 'enabled', text="")

    def draw(self, context):
        layout = self.layout

        metarig = context.object
        cloudrig = metarig.cloudrig

        layout.enabled = cloudrig.enabled

        if not draw_version_check(layout):
            return

        text = "Generate CloudRig"
        if metarig.cloudrig.generator.target_rig:
            text = "Re-Generate CloudRig"
        layout.operator("pose.cloudrig_generate", text=text)


class POSE_PT_CloudRig_Generation(Panel):
    bl_label = "Generation"
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
                if 'cloud_fk_chain' in str(rig_component.rig_class.mro()):
                    return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = get_addon_prefs(context)
        metarig = context.object
        generator = metarig.cloudrig.generator

        layout = layout.column()
        layout.prop(generator, 'target_rig')

        layout.row().prop_search(generator, 'ensure_root', metarig.data, 'bones')
        layout.row().prop_search(generator, 'properties_bone', metarig.data, 'bones')
        layout.row().prop(generator, 'custom_script')

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

        if not prefs.advanced_mode:
            return

        if check_addon(context, 'bone_gizmos'):
            layout.prop(generator, 'auto_setup_gizmos')


registry = [POSE_PT_CloudRig, POSE_PT_CloudRig_Generation]
