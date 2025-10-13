# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup
from bpy.props import BoolProperty

from ...rig_component_features.bone_info import BoneInfo
from ..cloud_base import Component_Base


class MyComponent(Component_Base):
    """Template for implementing rig component types in CloudRig. Just creates a control bone."""

    ui_name = "My Component"

    def init_extra(self):
        pass

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        if self.params.my_component.use_control:
            self.make_ctr_bone(self.bones_org[0])

    def make_ctr_bone(self, bone) -> BoneInfo:
        """Simple control bone that owns the ORG bone."""
        ctr_bone = self.bone_sets['Template Bones'].new(
            name="CTR-"+bone.name,
            source=bone,
            custom_shape_name='Circle',
            parent=bone.parent,
        )
        bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
        return ctr_bone

    ##############################
    # Parameters
    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this component's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            'Template Bones', color_palette='THEME02', collections=['IK Controls']
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the component parameters."""

        cls.draw_prop(context, layout, params.my_component, 'use_control')


class Params(PropertyGroup):
    use_control: BoolProperty(
        name="Make Control", description="Create a Control bone", default=True
    )


# Un-comment this to make it show up in the UI.
# RIG_COMPONENT_CLASS = MyComponent
