from bpy.types import PropertyGroup
from bpy.props import BoolProperty

from ..rig_component_features.bone import BoneInfo
from .cloud_base import Component_Base


class Component_Template(Component_Base):
    """Template for implementing rig types in CloudRig. Just creates a control bone."""

    def initialize(self):
        pass

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        if self.params.template.use_control:
            self.make_ctr_bone(self.bones_org[0])

    def make_ctr_bone(self, bone) -> BoneInfo:
        """Simple control bone that owns the ORG bone."""
        ctr_bone = self.bone_sets['Template Bones'].new(
            name=bone.name.replace('ORG', "CTR"),
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
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            'Template Bones', color_palette='THEME02', collections=['IK Controls']
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""

        cls.draw_prop(context, layout, params.template, 'use_control')


class Params(PropertyGroup):
    use_control: BoolProperty(
        name="Make Control", description="Create a Control bone", default=True
    )


# Un-comment this to make it show up in the UI.
# RIG_COMPONENT_CLASS = Component_Template
