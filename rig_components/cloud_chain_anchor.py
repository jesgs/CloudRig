from bpy.props import BoolProperty

from .cloud_copy import Component_CopyBone
from .cloud_base import Component_Base


class Component_FaceChainAnchor(Component_CopyBone):
    """Create a control on the generated rig that serves as an intersection for cloud_face_chain components."""

    ui_name = "Chain Intersection"

    def initialize(self):
        super().initialize()
        self.create_deform_bone = False

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        bi = self.bones_org[0]
        meta_bone = self.get_metarig_pbone(bi.name)

        if not meta_bone.custom_shape:
            bi.custom_shape_name = 'Cube'

    ##############################
    # No parameters for this rig type.


RIG_COMPONENT_CLASS = Component_FaceChainAnchor
