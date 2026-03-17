# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_

from ..utils.maths import project_vector_on_plane
from .cloud_aim import Component_Aim
from .cloud_face_chain import Component_FaceChain


class Component_Eyelid(Component_FaceChain):
    """Extends cloud_face_chain with eyelid functionality. This rig's parent bone must have the cloud_aim component type!"""

    ui_name = "Chain: Eyelid"

    ##############################
    # Inherited functions.

    def fchain__create_and_setup_intersections(self, context):
        # Since the cloud_eyelid rig demands to be parented to a cloud_aim rig,
        # but we obviously don't want to parent the eyelid to the eyeball,
        # parent it to the parent of the eyeball.
        # This is also important for custom root parenting functionality to work.
        self.bones_org[0].parent = self.parent_component.bones_org[0].parent
        self.eyelid__make_sticky_setup()
        super().fchain__create_and_setup_intersections(context)

    ##############################
    # Eyelid functions.

    def eyelid__make_sticky_setup(self):
        """Create ROT helper bones between the aim bone's base and the
        main STR controls of the eyelid. This needs to account for
        intersection controls."""

        # Parent rig must be a cloud_aim type rig!
        parent_component = self.parent_component
        if not parent_component or not isinstance(parent_component, Component_Aim):
            self.raise_generation_error(rpt_('Parent bone of a "Chain: Eyelid" component must be an "Aim" component (ie. the eye bone).'))

        sticky_prop_name = "sticky_eyelids_" + parent_component.params.aim.group.lower().replace(" ", "_")
        self.__create_sticky_property(parent_component, sticky_prop_name)

        main_controls = []
        for str_ctr in self.main_str_bones:
            if hasattr(str_ctr, 'intersection_ctrl'):
                str_ctr = str_ctr.intersection_ctrl
            if str_ctr not in main_controls:
                main_controls.append(str_ctr)

        for str_ctr in main_controls:
            eye_bone = parent_component.ctr_bone
            rot_name = self.naming.prepend_base_name(str_ctr.source, "STR-ROT-")
            rot_ctr = self.generator.find_bone_info(rot_name)
            if rot_ctr:
                continue

            rot_ctr = self.bone_sets['Eyelid Mechanism'].new(
                name=rot_name,
                source=eye_bone,
                tail=str_ctr.head.copy(),
                parent=str_ctr.parent,
            )
            rot_ctr.roll_align_other(eye_bone)
            str_ctr.parent = rot_ctr
            copyrot_x = rot_ctr.add_constraint(
                'COPY_ROTATION',
                name='Copy Rotation X',
                subtarget=eye_bone.name,
                use_xyz=[True, False, False],
            )
            eyelid_width = (
                self.bones_org[0].head - self.bones_org[-1].tail
            ).length * 0.55

            # Reject the ROT bone tail onto the eye bone Z axis
            rejection_z = project_vector_on_plane(
                rot_ctr.vector, parent_component.metarig_base_pbone.z_axis
            )
            # Take the distance between that and the base bone's vector
            # to determine the constraints' influence.
            distance = (eye_bone.vector - rejection_z).length
            sticky_strength = 1 - distance / eyelid_width
            copyrot_x.drivers.append(
                {
                    'prop': 'influence',
                    'expression': f"var*{sticky_strength}*2",
                    'variables': [(parent_component.properties_bone.name, sticky_prop_name)],
                }
            )

            copyrot_z = rot_ctr.add_constraint(
                'COPY_ROTATION',
                name='Copy Rotation Z',
                subtarget=eye_bone.name,
                use_xyz=[False, False, True],
            )

            copyrot_z.drivers.append(
                {
                    'prop': 'influence',
                    'expression': f"var*{sticky_strength*0.5}",
                    'variables': [(parent_component.properties_bone.name, sticky_prop_name)],
                }
            )

    def __create_sticky_property(self, eye_rig: Component_Aim, sticky_prop_name):
        self.rig_ui__add_bone_property(
            prop_bone=eye_rig.properties_bone,
            prop_id=sticky_prop_name,
            panel_name="Face",
            label_name="Sticky Eyelids",
            row_name=eye_rig.params.aim.group,
            slider_name=self.parent_component.bones_org[0].name,
            custom_prop_settings={
                'default': 0.1,
                'description': 'How much the eyelids should follow the movements of the eyeball',
            },
        )

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Eyelid Mechanism"), collections=['Mechanism Bones'], is_advanced=True
        )


RIG_COMPONENT_CLASS = Component_Eyelid
