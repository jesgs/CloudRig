# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup
from bpy.props import BoolProperty

from ...rig_component_features.bone_info import BoneInfo
from ..cloud_base import Component_Base


class MyComponent(Component_Base):
    """Template for implementing rig component types in CloudRig.
    Component types must inherit from Component_Base, and override at least one of the 3 generation functions, most likely `create_bone_infos()`.
    This example just creates a control bone.
    """

    # Name to display in the UI in the component selection list.
    ui_name = "My Component"

    # If an error occurs in your code, users will be presented with a Report Bug button which opens this URL. You can leave it empty.
    bug_report_url = "https://duckduckgo.com/"

    # If you want to force some inherited parameters to specific values and hide them from the UI.
    # Check Component_Base implementation for more inherited functionalities like constraint relinking, parent switching, logging, custom property management, etc.
    forced_params = {'my_component.always_false' : False}

    @classmethod
    def define_bone_sets(cls):
        """Define this component type's bone sets. 
        Runs during add-on registration, to create the necessary RNA properties for bone set customization via the UI.
        Riggers can then customize the colors, collections, and wire widths of a set of bones as defined by the component's implementation.
        BoneSets are necessary to create BoneInfo instances in CloudRig, which will be turned into real bones by the generator.
        """
        super().define_bone_sets()
        cls.define_bone_set('Template Bones', color_palette='THEME02', collections=['IK Controls'], wire_width=1.5)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Draw the UI for the component parameters."""
        cls.draw_prop(context, layout, params.my_component, 'create_control')
        # Since this parameter is found in forced_params, it will not be visible by default.
        # It will be visible when Advanced Mode is enabled, but it will be grayed out.
        # During generation, its value will be set to the forced value.
        # This is useful when wanting to inherit functionality from another class but force it to a specific value.
        cls.draw_prop(context, layout, params.my_component, 'always_false')

    def init_extra(self):
        """Called at the end of super().__init__(). 
        Feel free to override __init__() directly, but it takes some parameters that you probably don't care about."""
        pass

    ################################
    # Generation Steps.
    def create_bone_infos(self, context):
        """First function called by the generator.
        You should populate your BoneSets with BoneInfo instances here."""
        super().create_bone_infos(context)
        if self.params.my_component.create_control: # Parameter defined in `class Params` below. `my_component` is given by the name of this file.
            orig_bone = self.bones_org[0]
            ctr_bone: BoneInfo = self.bone_sets['Template Bones'].new( # You must create BoneInfo instances on a BoneSet. See define_bone_sets() above.
                name="CTR-"+orig_bone.name,
                source=orig_bone,           # Edit Mode transform properties copied from the source: head, tail, roll, radius, width, envelope.
                custom_shape_name='Circle', # See Widgets.blend for available bone shapes.
                parent=orig_bone.parent,
            )
            orig_bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
        else:
            # As the name suggests, this will raise, so any subsequent code won't run.
            # Note that generation errors are NOT BUGS. You should raise a generation error when you detect that the user is doing something illegal.
            # self.raise_generation_error("This component requires that the Create Control param is set to True. (This is a fake error to showcase how to raise errors in the template code!)")
            # print("This will not be printed.")
            assert False, "If this code runs, that IS A BUG! User will still get a stack trace. In the case of any sub-sub-module of rig_components, they will not be prompted with a bug report button, since I don't want to see your bugs."

    def create_component_interactions(self, context):
        """Second function called by the generator.
        Useful to implement features where unrelated rig components might interact, such as parent switching."""
        super().create_component_interactions(context)

    def create_helper_objects(self, context):
        """Third function called by the generator.
        You can create and hook up your helper objects like curves, empties, lattices, physics meshes, etc, here."""
        super().create_helper_objects(context)


class Params(PropertyGroup):
    """This class defines the parameters to be registered in RNA.
    It must be called exactly `Params`.
    """
    create_control: BoolProperty(
        name="Make Control", description="Create a Control bone", default=True
    )
    always_false: BoolProperty(
        name="Forced to False", description="This parameter is forced to be False", default=True
    )


# Un-comment the line below to make this component type appear as an option in Blender.
RIG_COMPONENT_CLASS = MyComponent
