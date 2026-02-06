# SPDX-License-Identifier: GPL-3.0-or-later

from math import radians

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_ik_chain import Component_Chain_IKFK


class Component_Finger(Component_Chain_IKFK):
    """An IK chain tailored for fingers. The finger bending axis should be +X."""

    ui_name = "Chain: Finger"
    forced_params = {
        'ik_chain.at_tip': True,
        'chain.tip_control': True,
        'fk_chain.root': True,
        'fk_chain.double_first': False,
        'ik_chain.world_aligned': False,
    }

    required_chain_length = 3

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.full_length_ik_name = "finger_ik_full_" + self.limb_name_props

    @no_overlay
    def rig_ui__add_bone_property(
        self,
        prop_bone: BoneInfo,
        prop_id: str,
        panel_name: str,
        label_name="",
        custom_prop_settings={},
        **kwargs
    ):
        # TODO: This should be restructured, we shouldn't be overriding this function.
        if panel_name == "FK/IK Switch":
            label_name = "FK/IK Switch"
            custom_prop_settings['default'] = 0.0

        panel_name = "Fingers"
        if label_name == "IK Pole Follow":
            return

        super().rig_ui__add_bone_property(
            prop_bone=prop_bone,
            prop_id=prop_id,
            panel_name=panel_name,
            label_name=label_name,
            custom_prop_settings=custom_prop_settings,
            **kwargs
        )

    def ik_chain__make_ik_chain(
        self,
        org_chain: list[BoneInfo],
        ik_mstr: BoneInfo,
        pole_target: BoneInfo=None,
    ) -> list[BoneInfo]:
        ik_chain = super().ik_chain__make_ik_chain(org_chain, ik_mstr, pole_target)
        ik_mstr.parent = self.root_bone

        self.ik2_chain = self.__create_two_bone_ik_chain(
            self.bones_org[:-1],
            ik_mstr,
            self.pole_ctrl,
        )

        return ik_chain

    @no_overlay
    def ik_chain__make_ik_stretch(
        self,
        org_chain: list[BoneInfo],
        ik_chain: list[BoneInfo],
        ik_mstr: BoneInfo
    ) -> BoneInfo:
        stretch_bone = super().ik_chain__make_ik_stretch(org_chain, ik_chain, ik_mstr)
        stretch_bone.add_constraint('COPY_ROTATION', subtarget=ik_mstr, index=0, use_xyz=[False, True, False])
        if self.pole_ctrl:
            self.pole_ctrl.parent = stretch_bone
        return stretch_bone

    @no_overlay
    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr, _default=0.0):
        """Avoid creating complex inherited setup. Just parent the pole to the master."""
        ik_pole.parent = ik_mstr

    def ik_chain__make_pole_parent_switch(self, ik_pole, ik_mstr):
        """Disable IK pole parent switching for finger components."""
        pass

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole) -> dict:
        ui_data = super().ik_chain__get_ik_switch_ui_data(
            fk_chain, ik_chain, ik_mstr, ik_pole
        )

        # It's quite strange to be creating an extra helper bone in this function,
        # but we need it for correct snapping in this case.
        tip_str = self.main_str_bones[-1]
        snap_helper = self.bone_sets['Mechanism Bones'].new(
            source=tip_str,
            parent=tip_str,
            name=self.naming.add_prefix(ik_mstr, "SNAP"),
            use_inherit_rotation=False,
        )

        map_on = [(ik_mstr.name, snap_helper.name)]

        ui_data['op_kwargs']['map_on'] = map_on
        return ui_data

    @no_overlay
    def ik_chain__attach_org_to_ik(self, org_chain: list[BoneInfo], ik_chain: list[BoneInfo]):
        # Note: Runs after fk_chain__attach_org_to_fk().

        # Add Copy Transforms constraints to the ORG bones to copy the IK bones.
        # Put driver on the influence to be able to disable IK.
        for org_bone, ik_bone in zip(org_chain, ik_chain):
            # Copy Transforms of IK bone
            ct_ik = org_bone.add_constraint(
                "COPY_TRANSFORMS",
                space="WORLD",
                subtarget=ik_bone.name,
                name="Copy Transforms IK Full",
            )

            ct_ik.drivers.append(
                {
                    "prop": "influence",
                    "variables": {
                        "ik": (self.properties_bone.name, self.ikfk_name),
                        "ik_full": (self.properties_bone.name, self.full_length_ik_name)
                    },
                    "expression": "ik * ik_full"
                }
            )

        for org_bone, ik2_bone in zip(org_chain, self.ik2_chain):
            # Copy Transforms of IK bone
            ct_ik = org_bone.add_constraint(
                "COPY_TRANSFORMS",
                space="WORLD",
                subtarget=ik2_bone.name,
                name="Copy Transforms IK",
            )

            ct_ik.drivers.append(
                {
                    "prop": "influence",
                    "variables": {
                        "ik": (self.properties_bone.name, self.ikfk_name),
                        "ik_full": (self.properties_bone.name, self.full_length_ik_name)
                    },
                    "expression": "ik * (1-ik_full)"
                }
            )

    ##############################
    # Finger functions.

    @no_overlay
    def __create_two_bone_ik_chain(
        self,
        org_chain: list[BoneInfo],
        ik_mstr: BoneInfo,
        pole_target: BoneInfo | None,
    ) -> list[BoneInfo]:
        """We create an additional IK chain (besides what's inherited from cloud_ik_chain)
        for the 2-length IK behaviour.
        """

        ik2_chain = []
        for org_bone in org_chain:
            ik2_bone = self.bone_sets['IK Mechanism'].new(
                name=self.naming.add_prefix(org_bone, "IK2"),
                source=org_bone,
                parent=ik2_chain[-1] if ik2_chain else self.root_bone,
            )
            ik2_chain.append(ik2_bone)

        last_ik2 = ik2_chain[-1]
        # Add the IK constraint to the previous bone, targetting this one.
        last_ik2.parent.add_constraint(
            'IK',
            pole_target=self.target_rig if pole_target else None,
            pole_subtarget=pole_target.name if pole_target else "",
            pole_angle=radians(self.pole_angle_deg),
            subtarget=last_ik2,
            chain_count=2,
        )
        last_ik2.parent = ik_mstr

        # Add UI data for switching between the two IK types

        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.full_length_ik_name,
            panel_name="IK",
            label_name="Full IK",
            row_name=self.base_name,
            slider_name=self.limb_ui_name,
            custom_prop_settings={
                'default': 1.0,
                'description': 'When enabled, the last bone in the chain is also considered part of the IK chain',
            },
        )

        return ik2_chain

    ##############################
    # No additional parameters for this component type.

RIG_COMPONENT_CLASS = Component_Finger
