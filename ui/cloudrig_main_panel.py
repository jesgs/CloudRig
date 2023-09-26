from bpy.types import UILayout, Panel

from ..rig_component_features.ui import draw_label_with_linebreak, is_cloud_metarig
from ..utils.misc import is_blender_version_compatible

def draw_version_check(layout: UILayout) -> bool:
    """ If Blender is too old or new, draw a link to download
        another version of CloudRig.
    """

    if not is_blender_version_compatible():
        draw_label_with_linebreak(layout, f"Version mismatch detected.", alert=True)
        draw_label_with_linebreak(layout, f"Find CloudRig for your Blender version here:", alert=True)
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
        return context.object and context.object.type == 'ARMATURE' and is_cloud_metarig(context.object)

    def draw(self, context):
        layout = self.layout
        metarig = context.object

        if not draw_version_check(layout):
            return

        text = "Generate CloudRig"
        if metarig.data.cloudrig.generator.target_rig:
            text = "Re-Generate CloudRig"
        layout.operator("pose.cloudrig_generate", text=text)


class POSE_PT_CloudRig_Generation(Panel):
    bl_label = "Generation"
    bl_parent_id = 'POSE_PT_CloudRig'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        metarig = context.object
        layout.prop(metarig.data.cloudrig.generator, 'target_rig')

registry = [
    POSE_PT_CloudRig,
    POSE_PT_CloudRig_Generation
]