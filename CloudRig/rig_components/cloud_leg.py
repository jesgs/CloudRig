# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi
from math import radians as rad

from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty, StringProperty
from bpy.types import PropertyGroup
from mathutils import Vector
from mathutils.geometry import intersect_point_line

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.bone_set import BoneSet
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_limb import Component_Limb


class Component_Limb_BipedLeg(Component_Limb):
    """Limb rig with extra features for legs, such as foot roll."""

    ui_name = "Limb: Biped Leg"
    forced_params = {
        'chain.tip_control': True,
        'fk_chain.root': True,
        'ik_chain.at_tip': False,
        'chain.sharp': True,
    }

    required_chain_length = 4

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # IK values
        self.ik_pole_direction = -1

        self.ik_pole_offset = 5
        self.pole_side = -1
        self.ik_chain_count -= 1

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.__tweak_org_foot()

        if self.painter:
            return
        # Tweak foot bone's first DEF bone.
        foot_def = self.bones_def[-2]
        for d in foot_def.drivers:
            if d['prop'] == 'bbone_easein':
                foot_def.drivers.remove(d)

    def ik_chain__prevent_straight_chain(self, invert_offset=False):
        # Since legs face the opposite direction, let's flip the offset here.
        super().ik_chain__prevent_straight_chain(invert_offset=True)

    def base__create_properties_bone(self, source: BoneInfo = None) -> BoneInfo:
        """Place the properties bone near where the foot IK will be,
        parented to the 2nd-to-last ORG bone.
        """
        properties_bone = super().base__create_properties_bone()
        head, tail = self.__calc_footroll_headtail()
        properties_bone.head = head
        properties_bone.tail = tail
        properties_bone.roll_align_vector(self.bones_org[-3].head)
        properties_bone.length *= 0.6
        properties_bone.custom_shape_rotation_euler.z = pi / 2
        properties_bone.parent = self.bones_org[-2]
        return properties_bone

    def toon__get_num_segments_of_section(self, org_bone: BoneInfo) -> int:
        """Force 1 segment on the foot and toe."""
        if org_bone in self.bones_org[2:]:
            return 1
        return self.params.chain.segments

    def fk_chain__make(self, org_chain) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(org_chain)
        # Toe FK should be available in the IK collection too.
        fk_chain[-1].collections += self.bone_sets['IK Controls'].collections
        return fk_chain

    def ik_chain__make_ik_setup(self, org_chain: list[BoneInfo], ik_bone_set: BoneSet):
        super().ik_chain__make_ik_setup(org_chain, ik_bone_set)
        if self.params.limb.double_ik:
            self.__create_foot_dsp(self.ik_mstr.parent)
        self.__create_foot_dsp(self.ik_mstr)

        _thigh, knee, foot, toe = org_chain

        # Create forefoot control
        forefoot = None
        if self.params.leg.create_forefoot:
            forefoot = self.bone_sets["IK Controls"].new(
                source=toe,
                name=self.naming.prepend_base_name(foot, "IK-Forefoot-"),
                tail=intersect_point_line(toe.head, knee.head, knee.tail)[0],
                parent=self.ik_mstr,
                custom_shape_name=self.params.leg.shape_forefoot.shape_name,
                custom_shape_rotation_euler=Vector((-pi / 2, 0, 0)),
                custom_shape_wire_width=max(1.5, self.ik_mstr.custom_shape_wire_width / 2),
            )
            forefoot.roll_align_vector(knee.head)

        # IK Foot setup, including Foot Roll.
        if self.params.leg.use_foot_roll:
            self.__make_footroll(self.ik_chain, self.bones_org, forefoot or self.ik_mstr, self.ik_mstr)

            # For FK->IK snapping to work properly when the IK control is world-aligned,
            # we need a world-aligned child of the IK bone.
            if self.params.ik_chain.world_align or self.params.ik_chain.flatten_controls:
                self.foot_snap_bone = self.bone_sets['IK Mechanism'].new(
                    name=self.naming.add_prefix(self.bone_sets['FK Controls'][2], "SNAP"),
                    source=self.bone_sets['FK Controls'][2],
                    parent=self.ik_chain[2],
                    roll=0,
                )
                if self.params.ik_chain.world_align:
                    self.foot_snap_bone.world_align()
                elif self.params.ik_chain.flatten_controls:
                    self.foot_snap_bone.flatten()

        self.__make_ik_toe()

    def ik_chain__make_master_ctr(self, bone_set: BoneSet, source_bone: BoneInfo) -> BoneInfo:
        """Tweak the foot shape."""
        ik_master = super().ik_chain__make_master_ctr(bone_set, source_bone)
        ik_controls = [ik_master]
        if self.params.limb.double_ik:
            ik_controls.append(ik_master.parent)
        for ik_control in ik_controls:
            ik_control.custom_shape_scale = 2.8
            if self.naming.side_is_left(source_bone):
                ik_control.custom_shape_scale_xyz.x *= -1

        return ik_master

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole) -> dict:
        """Toe is not relevant for IK/FK switching."""
        fk_chain = fk_chain[:-1]

        ui_data = super().ik_chain__get_ik_switch_ui_data(fk_chain, ik_chain, ik_mstr, ik_pole)

        if self.params.ik_chain.world_align and self.params.leg.use_foot_roll:
            # In the case of world aligned IK control + footroll, we must
            # snap the FK foot to a specialized helper bone rather than any IK bone.
            ui_data['op_kwargs']['map_fk_to_ik'][-1] = (
                fk_chain[2].name,
                self.foot_snap_bone.name,
            )

        return ui_data

    @no_overlay
    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr):
        """Let leg IK poles follow the IK master by default."""
        super().ik_chain__make_pole_follow_switch(ik_pole, ik_mstr)

    @no_overlay
    def ik_chain__world_align_fk(self):
        """Make 2nd-to-last FK bone (ie. FK Foot) world-aligned."""
        self.ik_chain__world_aligned_helper(self.bones_org[-2].fk_bone)

    ##############################
    # Leg functions.

    def __create_foot_dsp(self, bone: BoneInfo):
        """Create display helper for the foot IK control."""
        knee, foot, toe = self.bones_org[-3:]

        def determine_head() -> Vector:
            if self.params.leg.use_foot_roll:
                if self.heel_pivot_bone:
                    return intersect_point_line(knee.tail, toe.tail, self.heel_pivot_bone.center)[0]
                elif self.painter:
                    # HACK: Fix #343 by grabbing info from the metarig, because the heel bone is not
                    # generated by the overlay since it's not part of this component.
                    # An alternate hack would be to check for this during overlay draw, and include the heel bone in the generation.
                    metarig_pbone = self.get_metarig_pbone(self.params.leg.heel_bone)
                    if metarig_pbone:
                        return metarig_pbone.bone.head_local
            else:
                return intersect_point_line(toe.tail, knee.head, knee.tail)[0]

            return foot.head.copy()

        dsp_bone = self.create_dsp_bone(
            bone,
            head=determine_head(),
            tail=toe.tail.copy(),
        )
        dsp_bone.roll_align_vector(knee.head, axis='-Z')

        bone.custom_shape_along_length = 0.5
        bone.use_custom_shape_bone_size = False
        bone.custom_shape_scale_xyz *= dsp_bone.length * 0.75

        return dsp_bone

    def __calc_footroll_headtail(self) -> tuple[Vector, Vector]:
        knee, foot, toe = self.bones_org[-3:]
        # Project a line along the knee bone, and find the point on that line closest to the toe's tail.
        intersect = intersect_point_line(toe.tail, knee.head, knee.tail)[0]
        if (intersect - knee.head).length < knee.length:
            # If the closest point is actually along the knee, use the end of the knee instead.
            # (We only want to extrapolate the knee if it's necessary,
            # we don't want to pick a position along the knee.)
            intersect = knee.tail
        # Find the direction that points from the toe's tail towards this intersection point.
        intersect_to_toe = (intersect - toe.tail).normalized()

        # Amount we want to offset the point by, away from the foot.
        shift_from_toe = intersect_to_toe * foot.length

        # Calculate final position by adding the offsets to the intersection point.
        head = foot.head + shift_from_toe.normalized() * min(foot.length, toe.length)

        # The tail should point toward the toe bone but stay perpendicular to the knee bone.
        tail = head + -intersect_to_toe * foot.length
        return head, tail

    def __make_footroll(
        self,
        ik_chain: list[BoneInfo],
        org_chain: list[BoneInfo],
        foot_ik: BoneInfo,
        ik_mstr: BoneInfo,
    ):
        ik_foot_chain = ik_chain[-2:]
        _org_thigh, org_knee, org_foot, org_toe = org_chain
        org_toe.roll_align_other(org_foot)

        # Create ROLL control behind the foot.
        head, tail = self.__calc_footroll_headtail()

        TWIST_RANGE = 90
        HEEL_LIMIT = 90
        FOOT_THRESHOLD = 90
        TOE_THRESHOLD = 135

        roll_ctrl = self.bone_sets['IK Controls'].new(
            name=self.naming.add_prefix(org_foot, "ROLL-M"),  # TODO: Swap the name of this with roll_mch
            source=None,
            bbone_width=1 / 18,
            head=head,
            tail=tail,
            parent=foot_ik,
            custom_shape_name=self.params.leg.shape_footroll.shape_name,
            use_custom_shape_bone_size=True,
        )
        roll_ctrl.roll_align_vector(org_knee.head, axis='-Z')
        self.create_dsp_bone(roll_ctrl).parent = ik_foot_chain[0]
        if self.params.custom_props.props_storage == "GENERATED":
            self.properties_bone.parent = roll_ctrl
        # Limit Rotation, lock other transforms.
        self.lock_transforms(roll_ctrl, rot=False)
        roll_ctrl.add_constraint(
            'LIMIT_ROTATION',
            use_limit_x=True,
            min_x=rad(-HEEL_LIMIT),
            max_x=rad(TOE_THRESHOLD),
            use_limit_y=True,
            min_y=rad(-HEEL_LIMIT),
            max_y=rad(HEEL_LIMIT),
            use_limit_z=True,
            min_z=rad(-TWIST_RANGE),
            max_z=rad(TWIST_RANGE),
        )

        # Create bone to use as pivot point when rolling back.
        # This should be placed at the heel of the shoe, with the head and tail
        # defining the width of the foot/shoe.
        heel_pvt_back = self.heel_pivot_bone
        if heel_pvt_back:
            heel_pvt_back.parent = foot_ik
            heel_pvt_back.collections = self.bone_sets['IK Mechanism'].collections
            heel_pvt_back.roll_align_vector(org_toe.tail, axis='+Z')

            heel_pvt_toe = self.bone_sets['IK Mechanism'].new(
                self.naming.add_prefix(org_foot, "FRONT"),
                source=org_toe,
                parent=foot_ik,
                head=org_toe.tail,
                tail=heel_pvt_back.center,
            )
            heel_pvt_toe.roll_align_other(org_toe)
            heel_pvt_toe.add_constraint(
                'TRANSFORM',
                name="Transform (Toe Roll)",
                subtarget=roll_ctrl.name,
                map_from='ROTATION',
                map_to='ROTATION',
                from_min_z_rot=rad(-TWIST_RANGE),
                from_max_z_rot=rad(TWIST_RANGE),
                to_min_z_rot=rad(-TWIST_RANGE * (2 / 3)),
                to_max_z_rot=rad(TWIST_RANGE * (2 / 3)),
            )

            heel_pvt_outer = self.bone_sets['IK Mechanism'].new(
                self.naming.add_prefix(foot_ik, 'OUTER'),
                source=org_toe,
                head=heel_pvt_back.tail,
                tail=heel_pvt_back.tail + heel_pvt_back.z_axis * heel_pvt_back.length,
                parent=heel_pvt_toe,
            )
            outer_con = heel_pvt_outer.add_constraint(
                'TRANSFORM',
                name="Transform (Heel Outer Roll)",
                subtarget=roll_ctrl.name,
                map_from='ROTATION',
                map_to='ROTATION',
            )
            heel_pvt_back.parent = heel_pvt_outer

            back_con = heel_pvt_back.add_constraint(
                'TRANSFORM',
                name="Transform (Heel Roll)",
                subtarget=roll_ctrl.name,
                map_from='ROTATION',
                map_to='ROTATION',
                map_to_z_from='Y',
                map_to_y_from='X',
            )
            # The right side needs some inversion...
            # print("Dot: ", heel_pvt_back.y_axis.dot(roll_ctrl.x_axis), heel_pvt_back.name, roll_ctrl.name)
            if heel_pvt_back.y_axis.dot(roll_ctrl.x_axis) < 0:
                # RIGHT SIDE
                back_con.from_min_x_rot = rad(-HEEL_LIMIT)
                back_con.to_min_y_rot = rad(HEEL_LIMIT)
                back_con.from_min_y_rot = rad(-HEEL_LIMIT)
                back_con.to_min_z_rot = rad(-HEEL_LIMIT)
                outer_con.from_max_y_rot = rad(HEEL_LIMIT)
                outer_con.to_max_y_rot = rad(HEEL_LIMIT)
            else:
                # LEFT SIDE
                back_con.from_min_x_rot = rad(-HEEL_LIMIT)
                back_con.to_min_y_rot = rad(-HEEL_LIMIT)
                back_con.from_max_y_rot = rad(HEEL_LIMIT)
                back_con.to_max_z_rot = rad(HEEL_LIMIT)
                outer_con.from_min_y_rot = rad(-HEEL_LIMIT)
                outer_con.to_min_y_rot = rad(-HEEL_LIMIT)

            roll_mch = ik_mstr
        else:
            roll_mch = self.bone_sets['IK Mechanism'].new(
                name=self.naming.add_prefix(org_foot, "ROLL"),
                source=foot_ik,
                parent=foot_ik,
            )
            roll_mch.roll_align_vector(org_toe.head)
            back_con = roll_mch.add_constraint(
                'TRANSFORM',
                name="Transform (Foot Roll Back)",
                subtarget=roll_ctrl.name,
                map_from='ROTATION',
                map_to='ROTATION',
                from_min_x_rot=-rad(HEEL_LIMIT),
                to_min_x_rot=-rad(HEEL_LIMIT),
            )

        # Create reverse IK bones.
        rik_chain = []
        for i, org_bone in reversed(list(enumerate([org_foot, org_toe]))):
            rik_bone = self.bone_sets['Foot Reverse IK Controls'].new(
                name=self.naming.add_prefix(org_bone, "RIK"),
                source=org_bone,
                head=org_bone.tail.copy(),
                tail=org_bone.head.copy(),
                parent=heel_pvt_back or roll_mch,
                custom_shape_name=self.params.fk_chain.shape_fk.shape_name,
            )
            rik_bone.roll_align_other(org_bone)
            rik_bone.roll_flip()
            rik_chain.append(rik_bone)
            ik_foot_chain[i].parent = rik_bone

            # Calculate angle of rotation necessary to make this bone vertical.
            angle_to_vertical = (org_knee.head - org_knee.tail).angle(rik_bone.vector)

            if i == 0:
                # Foot bone's roll
                rik_bone.add_constraint(
                    'COPY_LOCATION',
                    name="Copy Location (RIK)",
                    space='WORLD',
                    subtarget=rik_chain[-2].name,
                    head_tail=1,
                )

                rik_bone.add_constraint(
                    'TRANSFORM',
                    name="Transformation (Foot Roll)",
                    subtarget=roll_ctrl.name,
                    map_from='ROTATION',
                    map_to='ROTATION',
                    from_max_x_rot=rad(FOOT_THRESHOLD),
                    to_max_x_rot=angle_to_vertical,
                )
            elif i == 1:
                rik_bone.add_constraint(
                    'TRANSFORM',
                    name="Transform (Toe Roll)",
                    subtarget=roll_ctrl.name,
                    map_from='ROTATION',
                    map_to='ROTATION',
                    from_min_x_rot=rad(FOOT_THRESHOLD),
                    from_max_x_rot=rad(TOE_THRESHOLD),
                    to_max_x_rot=angle_to_vertical,
                )

        # IK Toe needs to stick to the end of IK Foot.
        ik_foot, ik_toe = ik_foot_chain
        ik_toe.add_constraint(
            'COPY_LOCATION',
            subtarget=ik_foot,
            head_tail=1,
            space='WORLD',
        )

        # Set properties bone display
        if self.params.custom_props.props_storage == 'GENERATED':
            self.properties_bone.custom_shape_transform = roll_ctrl

    @property
    def heel_pivot_bone(self) -> BoneInfo | None:
        if not hasattr(self, '_heel_pivot_bone'):
            heel_pivot_name = self.params.leg.heel_bone
            heel_pivot = self._heel_pivot_bone = self.find_bone_info(heel_pivot_name)
            if self.params.leg.heel_bone and not heel_pivot:
                self.add_log(
                    rpt_("Heel Pivot Missing"),
                    description=rpt_('Could not find HeelPivot bone in the metarig: "{heel}".').format(
                        heel=heel_pivot_name
                    ),
                )
        return self._heel_pivot_bone

    @no_overlay
    def __make_ik_toe(self):
        """FK Toe bone should be parented between FK Foot and IK Toe."""
        fk_toe = self.fk_chain[-1]
        self.create_driven_armature_constraint(
            fk_toe,
            target_bones=[self.bones_org[-2].fk_bone, self.ik_chain[-1]],
            prop_bone=self.properties_bone,
            prop_name=self.ikfk_name,
            name="Armature (Toe FK/IK)",
        )

    @no_overlay
    def __tweak_org_foot(self):
        """Delete IK constraint and driver from toe bone. It should always use FK."""
        org_toe = self.bones_org[-1]
        org_toe.constraint_infos.pop()
        org_toe.drivers = {}

    ##############################
    # Parameters

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'foot_reverse_ik_control':
            return params.leg.use_foot_roll

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Foot Reverse IK Controls"),
            color_palette='THEME12',
            collections=['IK Secondary'],
            wire_width=1.5,
        )

    @classmethod
    def set_param_defaults(cls, component):
        component.params.ik_chain.shape_ik_master.shape_name = 'Foot'
        component.params.ik_chain.default_ik_pole_follow = 1.0

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        cls.draw_prop(context, layout, params.leg, "use_foot_roll")
        if params.leg.use_foot_roll:
            split = layout.split(factor=0.1)
            split.row()
            row = split.row()
            metarig = context.object
            if params.leg.heel_bone and params.leg.heel_bone not in metarig.pose.bones:
                row.alert = True
            cls.draw_prop_search(
                context,
                row,
                params.leg,
                "heel_bone",
                context.active_object.data,
                "bones",
                text="Heel Pivot",
                alert=row.alert,
            )
        cls.draw_prop(context, layout, params.leg, "create_forefoot")

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        if params.leg.use_foot_roll:
            cls.draw_prop_custom_shape(context, layout, params.leg, 'shape_footroll')
        if params.leg.create_forefoot:
            cls.draw_prop_custom_shape(context, layout, params.leg, 'shape_forefoot')


class Params(PropertyGroup):
    use_foot_roll: BoolProperty(
        name="Foot Roll",
        description="Create a Foot Roll control. When rotated 90 degrees on the X axis, the foot will be fully vertical (ie. on tippy-toes). Rotate it an additional 45 degrees, and the toe will also be vertical (like a ballerina). The angles are calculated based on the rest pose",
        default=True,
    )
    heel_bone: StringProperty(
        name="Heel Pivot Bone",
        description="(Optional.) Bone to use as the heel pivot. This bone should be placed at the heel of the shoe, pointing from the center outward, with its length defining the width of the shoe.",
        default="",
    )
    create_forefoot: BoolProperty(
        name="Forefoot Control",
        description="Create a control at the ball of the foot to pivot from.",
        default=False,
    )

    shape_footroll: Component_Limb.make_custom_shape_params(
        identifier="Foot Roll",
        default="Heel",
    )
    shape_forefoot: Component_Limb.make_custom_shape_params(
        identifier="Forefoot",
        default="Heel",
    )


RIG_COMPONENT_CLASS = Component_Limb_BipedLeg
