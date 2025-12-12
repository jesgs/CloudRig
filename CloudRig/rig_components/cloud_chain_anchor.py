# SPDX-License-Identifier: GPL-3.0-or-later

from .cloud_copy import Component_CopyBone


class Component_FaceChainAnchor(Component_CopyBone):
    """Create a control on the generated rig that serves as an intersection for Face Grid components."""

    ui_name = "Chain Intersection"

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        # Implementation-wise, this class does nothing but assign the cube as a default shape.
        # However, cloud_face_chain has code which checks for this
        # component type and parents itself to this automatically.

        bi = self.bones_org[0]
        meta_bone = self.get_metarig_pbone(bi.name)
        if not meta_bone.custom_shape:
            bi.custom_shape_name = 'Cube'

    ##############################
    # No additional parameters for this component type.


RIG_COMPONENT_CLASS = Component_FaceChainAnchor
