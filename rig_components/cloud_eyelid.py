# SPDX-License-Identifier: GPL-2.0-or-later

from ..utils.maths import project_vector_on_plane
from .cloud_face_chain import Component_FaceChain
from .cloud_aim import Component_Aim


class Component_Eyelid(Component_FaceChain):
    """Extends cloud_face_chain with eyelid functionality. This rig's parent bone must have the cloud_aim rig type!"""

    ui_name = "Chain: Eyelid"

    def initialize(self):
        super().initialize()

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        if not self.parent_component or type(self.parent_component) != Component_Aim:
            self.raise_generation_error("Must have a cloud_aim parent bone!")

        # Since the cloud_eyelid rig demands to be parented to a cloud_aim rig,
        # but we obviously don't want to parent the eyelid to the eyeball,
        # parent it to the parent of the eyeball.
        # This is also important for custom root parenting functionality to work.
        self.bones_org[0].parent = self.parent_component.bones_org[0].parent
        self.make_sticky_eyelid()

    def make_sticky_eyelid(self):
        """Create ROT helper bones between the aim bone's base and the
        main STR controls of the eyelid. Since this needs to account for
        intersection controls, it must be called from execute_final_face_chain()."""

        # Parent rig must be a cloud_aim type rig!
        parent_rig = self.parent_component
        if not isinstance(parent_rig, Component_Aim):
            self.raise_generation_error(
                f'Parent of eyelid rig MUST be a "cloud_aim" rig type, not "{type(parent_rig)}"!'
            )

        sticky_prop_name = (
            "sticky_eyelids_" + parent_rig.params.aim.group.lower().replace(" ", "_")
        )
        self.create_sticky_property(parent_rig, sticky_prop_name)

        main_controls = []
        for str_ctr in self.main_str_bones:
            if hasattr(str_ctr, 'intersection_ctrl'):
                str_ctr = str_ctr.intersection_ctrl
            if str_ctr not in main_controls:
                main_controls.append(str_ctr)

        for str_ctr in main_controls:
            eye_bone = parent_rig.ctr_bone
            prefixes, base, suffixes = self.naming.slice_name(str_ctr)
            rot_name = self.naming.make_name(prefixes + ["ROT"], base, suffixes)
            rot_ctr = self.generator.find_bone_info(rot_name)
            if rot_ctr:
                continue

            rot_ctr = self.bone_sets['Eyelid Mechanism'].new(
                name=rot_name,
                source=eye_bone,
                tail=str_ctr.head.copy(),
                parent=self.root_bone,
                roll_type='ALIGN',
                roll_bone=eye_bone,
                roll=0,
            )
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
                rot_ctr.vector, parent_rig.metarig_base_pbone.z_axis
            )
            # Take the distance between that and the base bone's vector
            # to determine the constraints' influence.
            distance = (eye_bone.vector - rejection_z).length
            sticky_strength = 1 - distance / eyelid_width
            copyrot_x.drivers.append(
                {
                    'prop': 'influence',
                    'expression': f"var*{sticky_strength}*2",
                    'variables': [(parent_rig.properties_bone.name, sticky_prop_name)],
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
                    'variables': [(parent_rig.properties_bone.name, sticky_prop_name)],
                }
            )
            str_ctr.parent = rot_ctr

    def create_sticky_property(self, eye_rig: Component_Aim, sticky_prop_name):
        info = {'prop_bone': eye_rig.properties_bone, 'prop_id': sticky_prop_name}

        self.add_bone_property_with_ui(
            prop_bone=eye_rig.properties_bone,
            prop_id=sticky_prop_name,
            panel_name="Face",
            label_name="Sticky Eyelids",
            row_name=eye_rig.params.aim.group,
            slider_name=self.parent_component.bones_org[0].name,
            custom_prop_settings={
                'default': 0.1,
            },
        )

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            'Eyelid Mechanism', collections=['Mechanism Bones'], is_advanced=True
        )


RIG_COMPONENT_CLASS = Component_Eyelid
