# SPDX-License-Identifier: GPL-3.0-or-later

from .cloud_copy import Component_CopyBone


class Component_FaceChainAnchor(Component_CopyBone):
    """Create a control on the Target Rig that serves as an intersection for Face Grid components."""

    ui_name = "Chain Intersection"

    # Implementation-wise, this class does nothing extra.
    # However, cloud_face_chain has code which checks for this
    # component type and parents itself to this automatically.


RIG_COMPONENT_CLASS = Component_FaceChainAnchor
