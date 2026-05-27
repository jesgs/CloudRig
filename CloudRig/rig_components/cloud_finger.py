# SPDX-License-Identifier: GPL-3.0-or-later

from math import radians

from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_tip as tip_

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
        'ik_chain.world_align': False,
        'ik_chain.flatten_controls': False,
    }

    required_chain_length = 3

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.full_length_ik_name = "finger_ik_full_" + self.base_name_props

    @no_overlay
    def rig_ui__add_bone_property(
        self, prop_bone: BoneInfo, prop_id: str, panel_name: str, label_name="", custom_prop_settings={}, **kwargs
    ):
        # TODO: This should be restructured, we shouldn't be overriding this function.
        if panel_name == "FK/IK Switch":
            label_name = n_("FK/IK Switch")
            custom_prop_settings['default'] = 0.0

        panel_name = n_("Fingers")
        if label_name == "IK Pole Follow":
            return

        super().rig_ui__add_bone_property(
            prop_bone=prop_bone,
            prop_id=prop_id,
            panel_name=panel_name,
            label_name=label_name,
            custom_prop_settings=custom_prop_settings,
            **kwargs,
        )

    def ik_chain__make_ik_chain(
        self,
        org_chain: list[BoneInfo],
        ik_mstr: BoneInfo,
        pole_target: BoneInfo = None,
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
    ):
        super().ik_chain__make_ik_stretch(org_chain, ik_chain)
        if self.pole_ctrl:
            self.pole_ctrl.parent = org_chain[-2]

    @no_overlay
    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr, _default=0.0):
        """It's not currently necessary to override this function,
        but just to be safe.
        """
        pass

    @no_overlay
    def ik_chain__make_pole_parent_switch(self, ik_pole, ik_mstr):
        """Avoid creating complex inherited setup. Just parent the pole to the master."""
        ik_pole.parent = ik_mstr

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole) -> dict:
        ui_data = super().ik_chain__get_ik_switch_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

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
        super().ik_chain__attach_org_to_ik(org_chain, ik_chain)

        # The finger has two IK modes, so we need to add a driver to the IK set-up
        # that was inherited from the IK chain implementation.
        for org_bone, ik_bone, ik2_bone in zip(org_chain, ik_chain, self.ik2_chain):
            # Copy Transforms of IK bone
            if not org_bone.constraint_infos:
                continue
            for con_idx, ct_ik in enumerate(org_bone.constraint_infos):
                if ct_ik.type == 'IK':
                    ct_ik.name = "Copy Transforms IK Finger Full"
                    ct_ik.drivers.append(
                        {
                            "prop": "influence",
                            "variables": {
                                "ik": (self.properties_bone.name, self.ikfk_name),
                                "ik_full": (self.properties_bone.name, self.full_length_ik_name),
                            },
                            "expression": "ik * ik_full",
                        }
                    )
                    break

            # The 2nd IK set-up's constraints need to be inserted after the IK constraint of the first.
            ct_ik2 = org_bone.add_constraint(
                "COPY_TRANSFORMS",
                index=con_idx,
                space="WORLD",
                subtarget=ik2_bone.name,
                name="Copy Transforms IK Finger Partial",
            )
            ct_ik2.drivers.append(
                {
                    "prop": "influence",
                    "variables": {
                        "ik": (self.properties_bone.name, self.ikfk_name),
                        "ik_full": (self.properties_bone.name, self.full_length_ik_name),
                    },
                    "expression": "ik * (1-ik_full)",
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
            panel_name=n_("IK"),
            label_name=n_("Full IK"),
            row_name=self.base_name,
            slider_name=self.base_name_ui,
            custom_prop_settings={
                'default': 1.0,
                'description': tip_('When enabled, the last bone in the chain is also considered part of the IK chain'),
            },
            context_bones=[ik_mstr, pole_target],
        )

        for ik_bone in ik2_chain[: self.ik_chain_count]:
            ik_bone.drivers.append(
                {
                    "prop": "ik_stretch",
                    "expression": "var*0.001 if var > 0 else 0",
                    "variables": [(self.properties_bone.name, self.ik_stretch_name)],
                }
            )

        return ik2_chain

    ##############################
    # No additional parameters for this component type.


RIG_COMPONENT_CLASS = Component_Finger
