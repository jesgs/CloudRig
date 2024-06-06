from ..rig_component_features.bone import BoneInfo
from .cloud_ik_chain import Component_Chain_IKFK


class Component_Finger(Component_Chain_IKFK):
    """An IK chain tailored for fingers. The finger bending axis should be +X."""

    ui_name = "Chain: Finger"
    forced_params = {
        'ik_chain.at_tip': True,
        'chain.tip_control': True,
        'fk_chain.root': True,
        'fk_chain.double_first': False,
    }

    required_chain_length = 3

    def initialize(self):
        super().initialize()

        self.full_length_ik_name = "finger_ik_full_" + self.limb_name_props

    def setup_ik_pole_follow_slider(
        self, ik_pole, ik_mstr, _stretch_bone, _default=0.0
    ):
        """Overrides cloud_ik_chain to avoid creating this complex set-up.
        Just parent the pole to the master."""
        ik_pole.parent = ik_mstr
        pass

    def add_bone_property_with_ui(
        self,
        prop_bone: BoneInfo,
        prop_id: str,
        panel_name: str,
        label_name="",
        custom_prop_settings={},
        **kwargs
    ):
        if panel_name == "FK/IK Switch":
            label_name = "FK/IK Switch"
            custom_prop_settings['default'] = 0.0

        panel_name = "Fingers"
        if label_name == "IK Pole Follow":
            return

        super().add_bone_property_with_ui(
            prop_bone=prop_bone,
            prop_id=prop_id,
            panel_name=panel_name,
            label_name=label_name,
            parent_id='CLOUDRIG_PT_custom_ik',
            **kwargs
        )

    def setup_ik_pole_parent_switch(self, ik_pole, ik_mstr):
        # We don't want IK pole parent switching for finger components.
        pass

    def world_align_last_fk(self):
        # Don't world align last FK, only IK.
        pass

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        self.ik_mstr.parent = self.root_bone

        if self.params.ik_chain.use_pole:
            # Parent the pole target to the stretch bone
            self.pole_ctrl.parent = self.stretch_bone

        self.create_two_bone_ik_chain(
            self.bones_org[:-1], self.ik_chain, self.pole_ctrl
        )

    def create_two_bone_ik_chain(
        self,
        org_chain: list[BoneInfo],
        ik_chain: list[BoneInfo],
        pole_target: BoneInfo,
    ) -> list[BoneInfo]:
        """We create an additional IK chain (besides what's inherited from cloud_ik_chain)
        for the 2-length IK behaviour.
        """

        ik2_chain = []
        for org_bone in org_chain:
            ik2_bone = self.bone_sets['IK Mechanism'].new(
                name=self.naming.add_prefix(org_bone.name, "IK2"),
                source=org_bone,
                parent=ik2_chain[-1] if ik2_chain else self.root_bone,
            )
            ik2_chain.append(ik2_bone)
            # Change ORG bone copy transform targets from IK to IK2.
            org_bone.constraint_infos[-1].subtarget = ik2_bone

        ik2_dt = self.bone_sets['IK Mechanism'].new(
            name=self.naming.add_prefix(org_bone, "IK2-DT"),
            source=self.ik_mstr,
            parent=self.ik_tgt_bone,
        )
        dt_con = ik2_dt.add_constraint(
            'DAMPED_TRACK', subtarget=ik_chain[-2], track_axis='TRACK_NEGATIVE_Y'
        )

        ik2_rot = self.bone_sets['IK Mechanism'].new(
            name=self.naming.add_prefix(org_bone.name, "IK2-ROT"),
            source=self.ik_mstr,
            parent=ik2_dt,
        )
        copyrot_con = ik2_rot.add_constraint('COPY_ROTATION', subtarget=self.ik_mstr)

        last_ik2 = ik2_chain[-1]
        # Add the IK constraint to the previous bone, targetting this one.
        last_ik2.parent.add_constraint(
            'IK',
            pole_target=self.target_rig if pole_target else None,
            pole_subtarget=pole_target.name if pole_target else "",
            pole_angle=self.pole_angle,
            subtarget=last_ik2,
            chain_count=2,
        )
        last_ik2.parent = ik2_rot

        # Add UI data for switching between the two IK types

        self.add_bone_property_with_ui(
            prop_bone=self.properties_bone,
            prop_id=self.full_length_ik_name,
            panel_name="IK",
            label_name="Full IK",
            row_name=self.limb_name,
            slider_name=self.limb_ui_name,
            custom_prop_settings={
                'default': 1.0,
            },
        )

        # Add driver to switch between the two IK types
        driver = {
            'prop': 'influence',
            'expression': "var",
            'variables': [(self.properties_bone.name, self.full_length_ik_name)],
        }
        copyrot_con.drivers.append(driver.copy())
        dt_con.drivers.append(driver)

        return ik2_chain

    def create_fkik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
        """Overrides cloud_ik_chain"""
        ui_data = super().create_fkik_switch_ui_data(
            fk_chain, ik_chain, ik_mstr, ik_pole
        )

        # It's quite strange to be creating an extra helper bone in this function,
        # but we need it for correct snapping in this case.
        tip_str = self.main_str_bones[-1]
        snap_helper = self.bone_sets['Mechanism Bones'].new(
            source=tip_str,
            parent=tip_str,
            name="SNAP-" + ik_mstr.name,
            use_inherit_rotation=False,
        )

        map_on = [(ik_mstr.name, snap_helper.name)]

        ui_data['op_kwargs']['map_on'] = map_on
        return ui_data


RIG_COMPONENT_CLASS = Component_Finger
