# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import BoolProperty
from bpy.types import PropertyGroup

from ...rig_component_features.bone_info import BoneInfo
from ..cloud_base import Component_Base


class AdvancedComponent(Component_Base):
    """Template for implementing rig component types in CloudRig.

    Component types must inherit from Component_Base, and override at least one
    of the 3 generation functions, most likely `create_bone_infos()`.

    This example creates a single control bone.
    """

    # Name to display in the UI in the component selection list.
    ui_name = "Advanced Component"

    # If an error occurs in your code, users will be presented with a Report Bug
    # button which opens this URL. You can leave it empty.
    bug_report_url = "https://duckduckgo.com/"

    # If you want to force some inherited parameters to specific values and hide
    # them from the UI. Check Component_Base implementation for more inherited
    # functionalities like constraint relinking, parent switching, logging, etc.
    forced_params = {"advanced_component.always_false": False}

    @classmethod
    def define_bone_sets(cls):
        """Define this component type's bone sets.

        Runs during add-on registration, to create the necessary RNA properties
        for bone set customization via the UI. BoneSets are necessary to create
        BoneInfo instances in CloudRig, which will be turned into real bones by
        the generator.

        Riggers can then customize the colors, collections, and wire widths of a
        set of bones as defined by the component's implementation.
        """
        super().define_bone_sets()
        cls.define_bone_set(
            "My Bone Set",
            color_palette="THEME02",
            collections=["IK Controls"],
            wire_width=1.5,
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        """Draw the UI for the component parameters."""
        params = component.params
        cls.draw_prop(context, layout, params.advanced_component, "create_control")

        # Since this param is in forced_params, it will be hidden by default.
        # (Visible and grayed out when Advanced Mode is enabled.)
        cls.draw_prop(context, layout, params.advanced_component, "always_false")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    ################################
    # Generation Steps.
    def create_bone_infos(self, context):
        """First function called by the generator.
        You should populate your BoneSets with BoneInfo instances here."""
        super().create_bone_infos(context)

        # Read the value of the `create_control` parameter.
        # The `advanced_component` part of the path is given by the name of this file.
        if self.params.advanced_component.create_control:
            self.__create_control(self.bones_org[0])
        else:
            # Generation errors are NOT BUGS. You can raise them if user is
            # doing something wrong.
            self.raise_generation_error("Create Control must be True!")
            assert False, "If this were to run, user gets a bug report button."

    def __create_control(self, bone: BoneInfo):
        # We must create BoneInfo instances on a BoneSet.
        # "My Bone Set" was defined in define_bone_sets() above.
        ctr_bone: BoneInfo = self.bone_sets["My Bone Set"].new(
            name="CTR-" + bone.name,
            source=bone,  # head, tail, roll, radius, width, envelope.
            custom_shape_name=self.params.advanced_component.shape_control.shape_name,  # See Widgets.blend for bone shapes.
            parent=bone.parent,
        )
        bone.add_constraint("COPY_TRANSFORMS", subtarget=ctr_bone.name)

    def create_component_interactions(self, context):
        """Second function called by the generator, after most BoneInfos have
        been created.

        Useful to implement features where unrelated rig components might
        interact, such as parent switching.
        """
        super().create_component_interactions(context)

    def create_helper_objects(self, context):
        """Third function called by the generator, after the rig has been generated.

        You can create and hook up your helper objects like curves, empties,
        lattices, physics meshes, etc, here.
        """
        super().create_helper_objects(context)


class Params(PropertyGroup):
    """Defines the parameters to be registered in RNA. Must be exactly `Params`."""

    create_control: BoolProperty(
        name="Make Control", description="Create a Control bone", default=True
    )
    always_false: BoolProperty(
        name="Forced to False",
        description="This parameter is forced to be False",
        default=True,
    )

    shape_control: Component_Base.make_custom_shape_params(
        identifier="Control",
        default="Circle" # See Widgets.blend for bone shapes.
    )

# Un-comment the below line to make this component appear in Blender.
# RIG_COMPONENT_CLASS = AdvancedComponent
