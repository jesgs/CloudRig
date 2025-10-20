import bpy
from ..cloud_base import Component_Base

class MinimalComponentExample(Component_Base):
    """Fairly minimal example for implementing a rig component type in CloudRig.
    This example creates a single control bone.
    To see it in Blender, un-comment the last line of code in this file.
    """

    ui_name = "Minimal Component"
    bug_report_url = "https://duckduckgo.com/"

    def create_bone_infos(self, context):
        if self.params.minimal_component.create_control:
            original_bone = self.bones_org[0]
            control_bone = self.bone_sets["My Bone Set"].new(
                name="CTR-" + original_bone.name,
                source=original_bone,
                custom_shape_name="Circle",
                parent=original_bone.parent,
            )
            original_bone.add_constraint("COPY_TRANSFORMS", subtarget=control_bone)

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        cls.define_bone_set(
            "My Bone Set",
            color_palette="THEME02",
            collections=["My Controls"],
            wire_width=1.5,
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        cls.draw_prop(context, layout, params.minimal_component, "create_control")


class Params(bpy.types.PropertyGroup):
    create_control: bpy.props.BoolProperty(
        name="Create Control", description="Create a Control bone", default=True
    )

# Un-comment the below line to make this component appear in Blender.
# RIG_COMPONENT_CLASS = MinimalComponentExample
