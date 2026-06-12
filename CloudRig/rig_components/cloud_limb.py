# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import RigComponent
from math import pow

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.app.translations import pgettext_tip as tip_
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Context, PropertyGroup, UILayout

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.bone_set import BoneSet
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_ik_chain import Component_Chain_IKFK


class Component_Limb(Component_Chain_IKFK):
    """IK chain with extra features such as Auto-Rubberhose for a simple limb like an arm."""

    ui_name = "Limb: Generic"
    forced_params = {
        'chain.sharp': True,
        'fk_chain.root': True,
        'ik_chain.at_tip': False,
    }

    required_chain_length = 3

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.params.chain.smooth_spline:
            self.params.limb.auto_hose = False

        self.ik_pole_direction = 1

    def create_bone_infos(self, context: Context):
        """Build the limb rig, then add rubber hose constraints if enabled."""
        super().create_bone_infos(context)
        segments = self.params.chain.segments
        if self.params.limb.auto_hose and segments > 1:
            upper_section = self.main_str_bones[0].custom_data['sub_bones']
            lower_section = self.main_str_bones[1].custom_data['sub_bones']
            self.__make_rubber_hose(self.bones_org[0], self.bones_org[1], upper_section, lower_section)

    @no_overlay
    def base__apply_parent_switching(
        self,
        *,
        child_bone: BoneInfo | None = None,
        prop_bone: BoneInfo | None = None,
        prop_name="",
        panel_name=n_("IK"),
        row_name="",
        label_name=n_("Parent Switching"),
        entry_name="",
    ):
        """When double IK is enabled and no explicit child is given, use the outer IK master as the switching target."""
        if self.params.limb.double_ik and child_bone in (None, self.ik_mstr):
            child_bone = self.ik_mstr.parent

        super().base__apply_parent_switching(
            child_bone=child_bone,
            prop_bone=prop_bone,
            prop_name=prop_name,
            panel_name=panel_name,
            row_name=row_name,
            label_name=label_name,
            entry_name=entry_name,
        )

    def base__create_properties_bone(self, source: BoneInfo | None = None) -> BoneInfo:
        """Place the properties bone near the end of the limb, parented to the last original bone."""
        if not source:
            source = self.bones_org[0]
            if self.params.custom_props.props_storage == 'GENERATED':
                source = self.bones_org[-1]
        return super().base__create_properties_bone(source=source)

    def toon__get_num_segments_of_section(self, org_bone: BoneInfo) -> int:
        """Force 1 segment on the wrist."""
        if org_bone == self.bones_org[-1]:
            return 1
        return self.params.chain.segments

    def fk_chain__make(self, org_chain: list[BoneInfo]) -> list[BoneInfo]:
        """Build the FK chain, locking the elbow bone's Y/Z axes if the limit parameter is set."""
        fk_chain = super().fk_chain__make(org_chain)
        if self.params.limb.limit_elbow_axes:
            # Locking the FK elbow/knee's Y/Z rotation is necessary for accurate
            # IK/FK snapping. But it might be an annoying limitation for more cartoony
            # characters.
            fk_elbow = fk_chain[1]
            fk_elbow.lock_rotation = [False, True, True]
        return fk_chain

    def ik_chain__make_ik_setup(self, org_chain: list[BoneInfo], ik_bone_set: BoneSet):
        """Extend the parent IK setup with counter-rotation on the first STR bone and optional elbow axis locking."""
        if self.params.limb.double_ik:
            ik_bone_set = self.bone_sets['IK Child Controls']

        super().ik_chain__make_ik_setup(org_chain, ik_bone_set)

        self.__counter_rotate_first_str(self.str_chain[: self.params.chain.segments])

        # Lock IK axes
        if self.params.limb.limit_elbow_axes:
            if self.pole_angle_deg in {180, 0}:
                self.add_log(
                    rpt_("Locked IK must bend on X"),
                    description=rpt_(
                        'To use the "Limit Elbow Axes" parameter, the bone rolls of this limb should '
                        'be rotated 90 degrees, so it bends on X instead of Z axis. '
                        'Currently, this limbn will not bend properly.'
                    ),
                )
            ik_elbow = self.ik_chain[1]
            ik_elbow.lock_ik_z = ik_elbow.lock_ik_y = True

    def ik_chain__make_master_ctr(self, bone_set: BoneSet, source_bone: BoneInfo) -> BoneInfo:
        """Create the IK master control, wrapping it in a parent control when double IK is enabled."""
        ik_mstr = super().ik_chain__make_master_ctr(bone_set, source_bone)

        # Create Duplicate IK Master.
        if self.params.limb.double_ik:
            old_name = ik_mstr.name
            ik_mstr.name = self.naming.add_prefix(ik_mstr, "C")
            double_control = self.create_parent_bone(ik_mstr, self.bone_sets['IK Controls'])
            double_control.name = old_name
            self.ik_controls.append(double_control)

        return ik_mstr

    @no_overlay
    def ik_chain__make_pole_parent_switch(self, ik_pole: BoneInfo, ik_mstr: BoneInfo):
        """When double IK is enabled, use the outer IK master as the pole parent target."""
        if self.params.limb.double_ik:
            ik_mstr = ik_mstr.parent

        super().ik_chain__make_pole_parent_switch(ik_pole, ik_mstr)

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(
        self, fk_chain: list[BoneInfo], ik_chain: list[BoneInfo], ik_mstr: BoneInfo, ik_pole: BoneInfo | None
    ) -> dict:
        """Extend the switch UI data to include the outer IK master when double IK is enabled."""
        ui_data = super().ik_chain__get_ik_switch_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

        if self.params.limb.double_ik:
            # Need to insert IK master parent->last FK bone switching BEFORE IK master parent.
            ui_data['op_kwargs']['map_ik_to_fk'].insert(0, (ik_mstr.parent.name, fk_chain[-1].name))
            ui_data['context_bones'] += [self.ik_mstr.parent]

        return ui_data

    ##############################
    # Limb functions.

    @no_overlay
    def __counter_rotate_first_str(self, str_chain: list[BoneInfo]):
        """Counter-Rotate constraint for the first main STR bone.
        This is so that the twisting fades in starting at the shoulder, towards the elbow.
        """
        str_bone = str_chain[0]
        trans_con = str_bone.add_constraint(
            'TRANSFORM',
            name="Transformation (Counter-Rotate)",
            subtarget=self.fk_chain[0],
            influence=0.9,
            map_to='ROTATION',
        )
        trans_con.drivers.append(
            {
                'prop': 'to_min_y_rot',
                'expression': "-var",
                'variables': [
                    {
                        'type': 'TRANSFORMS',
                        'targets': [
                            {
                                'bone_target': self.bones_org[0].name,
                                'transform_space': 'LOCAL_SPACE',
                                'transform_type': 'ROT_Y',
                                'rotation_mode': 'SWING_TWIST_Y',
                            }
                        ],
                    }
                ],
            }
        )

    def __make_rubber_hose(
        self,
        org_upper: BoneInfo,
        org_lower: BoneInfo,
        str_upper_section: list[BoneInfo],
        str_lower_section: list[BoneInfo],
    ):
        """Add translating Transformation constraints to str_upper_section and
        str_lower_section controls, driven by org_lower, which would be the
        elbow or the knee.
        """

        prop_name = "auto_rubber_hose_" + self.base_name_props

        rubberhose_ctr = None
        if self.params.limb.auto_hose_control:
            # Create control bone
            rubberhose_ctr = self.__make_rubber_hose_control(org_lower)
            if self.painter:
                return
            self.properties_bone.custom_props[prop_name] = {'default': 0.0}
            self.properties_bone.drivers.append(
                {
                    'prop': f'["{prop_name}"]',
                    'expression': "var-1",
                    'variables': [
                        {
                            'type': 'TRANSFORMS',
                            'targets': [
                                {
                                    'bone_target': rubberhose_ctr.name,
                                    'transform_space': 'LOCAL_SPACE',
                                    'transform_type': 'SCALE_Y',
                                }
                            ],
                        }
                    ],
                }
            )
        else:
            if self.painter:
                return
            # Don't create a control bone, instead just add a slider in the UI.
            self.rig_ui__add_bone_property(
                prop_bone=self.properties_bone,
                prop_id=prop_name,
                panel_name=n_("Auto Rubber Hose"),
                custom_prop_settings={
                    'default': 0.0,
                    'description': tip_(
                        "Automatically smoothen the curvature of the limb and avoid sharp angles, for a cartoony effect"
                    ),
                },
                row_name=self.base_name,
                slider_name=self.base_name_ui,
                context_bones=(
                    self.ik_chain
                    + self.fk_chain
                    + self.bone_sets['IK Controls']
                    + self.bone_sets['IK Child Controls']
                    + [rubberhose_ctr, self.root_bone]
                ),
            )

        self.__make_rubber_hose_constraints(
            org_upper,
            org_lower,
            str_upper_section,
            str_lower_section,
            prop_name,
            hose_type=self.params.limb.auto_hose_type,
        )

    def __make_rubber_hose_control(self, org_lower: BoneInfo) -> BoneInfo:
        head = org_lower.head + self.pole_vector.normalized() * org_lower.length * 0.3
        control_bone = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org_lower, "RubberHose"),
            source=org_lower,
            parent=org_lower,
            head=head,
            vector=org_lower.vector * 0.3,
            custom_shape_name=self.params.limb.shape_rubberhose.shape_name,
        )

        control_bone.roll_align_vector(org_lower.head)
        if self.painter:
            return control_bone

        self.lock_transforms(control_bone, scale=[True, False, True])
        control_bone.add_constraint('LIMIT_SCALE', use_max_y=True, max_y=2, use_min_y=True, min_y=1)

        dsp_bone = self.create_dsp_bone(control_bone)
        dsp_bone.add_constraint(
            'ARMATURE',
            use_deform_preserve_volume=True,
            targets=[
                {"subtarget": self.bones_def[self.params.chain.segments - 1].name},
                {"subtarget": self.bones_def[self.params.chain.segments].name},
            ],
        )
        dsp_bone.add_constraint('COPY_SCALE', subtarget=control_bone.name)

        return control_bone

    @no_overlay
    def __make_rubber_hose_constraints(
        self,
        org_upper: BoneInfo,
        org_lower: BoneInfo,
        str_upper_section: list[BoneInfo],
        str_lower_section: list[BoneInfo],
        prop_name: str,
        hose_type: str,
    ):
        # TODO: This function is too big!
        driver_influence = {
            'prop': 'influence',
            'expression': 'var',
            'variables': [
                (self.properties_bone.name, prop_name),
            ],
        }

        for org_bone, str_list in zip([org_upper, org_lower], [str_upper_section, str_lower_section]):
            for str_bone in str_list:
                offset = org_bone.length / 2.5

                # Inverse of distance from center divided by half of bone length
                # This results in 1.0 at the center of the bone and 0.0 at the head or tail of the bone.
                distance_to_org_center = (str_bone.head - org_bone.center).length
                centeredness = 1 - (distance_to_org_center / (org_bone.length / 2))

                total_offset = offset * pow(centeredness, 0.5)

                trans_con = str_bone.add_constraint(
                    'TRANSFORM',
                    name="Transformation (Rubber Hose STR)",
                    subtarget=org_lower.name,
                    map_from='ROTATION',
                    map_to_x_from='Z',
                    map_to_z_from='X',
                )

                # Influence driver
                driver = deepcopy(driver_influence)
                if hose_type == 'ELBOW_IN':
                    # For the alternate auto hose type, the shifting just needs to be reduced by half.
                    driver['expression'] += "/2"

                trans_con.drivers.append(driver)

                # Translation drivers
                driver_to_min_x = {
                    'prop': 'to_min_x',
                    'expression': f"(var/pi) * {total_offset}",
                    'variables': [
                        {
                            'type': 'TRANSFORMS',
                            'targets': [
                                {
                                    'bone_target': org_lower.name,
                                    'transform_space': 'LOCAL_SPACE',
                                    'transform_type': 'ROT_Z',
                                    'rotation_mode': 'SWING_TWIST_Y',
                                }
                            ],
                        }
                    ],
                }

                trans_con.drivers.append(driver_to_min_x)

                driver_to_min_z = deepcopy(driver_to_min_x)
                driver_to_min_z['prop'] = 'to_min_z'
                driver_to_min_z['expression'] += " * -1"
                driver_to_min_z['variables'][0]['targets'][0]['transform_type'] = 'ROT_X'
                trans_con.drivers.append(driver_to_min_z)

        # Scale the main STR bone on local Y to get a smooth curve
        # in spite of Sharp Sections parameter being enabled.
        main_str = str_lower_section[0].prev
        # Scale constraint
        scale_con = main_str.add_constraint(
            'TRANSFORM',
            name="Transformation (Rubber Hose Elbow Scale)",
            subtarget=org_lower.name,
            map_to='SCALE',
        )

        # Influence driver
        scale_con.drivers.append(deepcopy(driver_influence))

        # Scale driver
        scale_con.drivers.append(
            {
                'prop': 'to_min_y_scale',
                'expression': "1 + pow( (abs(rot_x) + abs(rot_z)) / pi, 0.5 ) * 1.5",
                'variables': {
                    'rot_x': {
                        'type': 'TRANSFORMS',
                        'targets': [
                            {
                                'bone_target': org_lower.name,
                                'transform_space': 'LOCAL_SPACE',
                                'transform_type': 'ROT_X',
                                'rotation_mode': 'SWING_TWIST_Y',
                            }
                        ],
                    },
                    'rot_z': {
                        'type': 'TRANSFORMS',
                        'targets': [
                            {
                                'bone_target': org_lower.name,
                                'transform_space': 'LOCAL_SPACE',
                                'transform_type': 'ROT_Z',
                                'rotation_mode': 'SWING_TWIST_Y',
                            }
                        ],
                    },
                },
            }
        )

        if hose_type != 'ELBOW_IN':
            return

        ### Additional constraints for alternate, "Long" rubberhose type
        # Translation constraint
        trans_con = main_str.add_constraint(
            'TRANSFORM',
            name="Transformation (Rubber Hose Elbow Translate)",
            subtarget=org_lower.name,
        )

        # Influence driver
        trans_con.drivers.append(deepcopy(driver_influence))

        # Translation drivers
        var_x = {
            'type': 'TRANSFORMS',
            'targets': [
                {
                    'bone_target': org_lower.name,
                    'transform_space': 'LOCAL_SPACE',
                    'transform_type': 'ROT_X',
                    'rotation_mode': 'SWING_TWIST_Y',
                }
            ],
        }
        var_z = deepcopy(var_x)
        var_z['targets'][0]['transform_type'] = 'ROT_Z'
        driver_to_min_y = {
            'prop': 'to_min_y',
            'expression': f"(abs(x + z)/pi) * {org_lower.length / 4}",
            'variables': {
                'x': var_x,
                'z': var_z,
            },
        }

        trans_con.drivers.append(driver_to_min_y)

        driver_to_min_z = deepcopy(driver_to_min_y)
        driver_to_min_z['prop'] = 'to_min_z'
        driver_to_min_z['expression'] = f"(x/pi) * {org_lower.length / 4}"
        trans_con.drivers.append(driver_to_min_z)

        driver_to_min_x = deepcopy(driver_to_min_y)
        driver_to_min_x['prop'] = 'to_min_x'
        driver_to_min_x['expression'] = f"(-z/pi) * {org_lower.length / 4}"
        trans_con.drivers.append(driver_to_min_x)

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("IK Child Controls"),
            color_palette='THEME09',
            collections=['IK Secondary'],
            wire_width=1.5,
        )

    @classmethod
    def draw_control_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_control_params(layout, context, component)
        params = component.params

        layout.separator()
        cls.draw_control_label(layout, iface_("Limb"))

        cls.draw_prop(context, layout, params.limb, 'double_ik')
        cls.draw_prop(context, layout, params.limb, 'limit_elbow_axes')

        row = cls.draw_prop(context, layout, params.limb, 'auto_hose')
        row.enabled = params.chain.segments > 1 and params.chain.smooth_spline
        if row.enabled and params.limb.auto_hose:
            split = layout.split(factor=0.1)
            split.row()
            cls.draw_prop(context, split.row(), params.limb, 'auto_hose_control')
            split = layout.split(factor=0.1)
            split.row()
            cls.draw_prop(context, split.row(), params.limb, 'auto_hose_type', expand=True)

    @classmethod
    def draw_appearance_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        if params.limb.auto_hose:
            layout.separator()
            cls.draw_prop_custom_shape(context, layout, params.limb, 'shape_rubberhose')


class Params(PropertyGroup):
    auto_hose: BoolProperty(
        name="Rubber Hose",
        description="Add an Auto Rubber Hose setting which can be enabled to automatically add curvature to limbs as they bend. Stretch Segments parameter must be >1 and Smooth Spline must be enabled",
        default=False,
    )
    auto_hose_control: BoolProperty(
        name="With Control",
        description="Instead of controlling the Auto Rubber Hose property from the rig UI, create a control bone on the FK Extras layer",
        default=False,
    )
    auto_hose_type: EnumProperty(
        name="Type",
        description="The rubber hosing effect can be achieved in different ways. This lets you pick which one you prefer",
        items=[
            (
                'MIDDLE_OUT',
                "Long",
                "Shift mid-limb STR bones away from the elbow bending direction. As a result, the limb becomes longer",
            ),
            (
                'ELBOW_IN',
                "Short",
                "Shift the elbow STR bone towards the elbow bending direction, and counter-shift the mid-limb STR bones so they stay roughly in place. As a result, the limb becomes shorter",
            ),
        ],
    )

    limit_elbow_axes: BoolProperty(
        name="Limit Elbow Axes",
        description="Lock the Y and Z rotation of the elbow/knee bone, only allowing realistic rotations. This is limiting for cartoony characters, but it's necessary for accurate FK->IK snapping. For realistic characters, this should be enabled. This also requires that the elbow bends along its local X axis",
        default=True,
    )

    double_ik: BoolProperty(
        name="Duplicate IK Master",
        description="The IK control has a parent control. Having two controls for the same thing can help avoid interpolation issues when the common pose in animation is far from the rest pose",
        default=False,
    )

    shape_rubberhose: Component_Chain_IKFK.make_custom_shape_params(identifier="Rubber Hose", default="Slider")


RIG_COMPONENT_CLASS = Component_Limb
