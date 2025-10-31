# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup, Bone
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector
from mathutils.geometry import intersect_point_line
from math import radians as rad
from math import pi

from ..rig_component_features.bone_info import BoneInfo
from ..utils.maths import flat
from ..rig_component_features.component_params_ui import ensure_custom_property
from .cloud_limb import Component_Limb


class Component_Limb_BipedLeg(Component_Limb):
    """Limb rig with extra features for legs, such as foot roll."""

    ui_name = "Limb: Biped Leg"
    forced_params = {
        'chain.tip_control': True,
        'fk_chain.root': True,
        'fk_chain.position_along_bone': 0,
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
        self.chain_count -= 1

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.__tweak_org_foot()

        # Tweak foot bone's first DEF bone
        foot_def = self.bones_def[-2]
        for d in foot_def.drivers:
            if d['prop'] == 'bbone_easein':
                foot_def.drivers.remove(d)

    def base__create_properties_bone(self) -> BoneInfo:
        """Overrides cloud_limb.
        Place the properties bone near where the foot IK will be,
        parented to the 2nd-to-last ORG bone.
        """
        properties_bone = super().base__create_properties_bone()
        head, tail = self.__calc_footroll_headtail(
            self.bones_org[1], self.bones_org[-1], self.scale
        )
        properties_bone.head = head
        properties_bone.tail = tail
        properties_bone.length *= 0.6
        properties_bone.roll_type = 'ALIGN'
        properties_bone.roll_bone = self.bones_org[-2]
        properties_bone.roll = 0
        properties_bone.custom_shape_name = 'Cogwheel'
        properties_bone.custom_shape_rotation_euler.z = pi / 2
        properties_bone.parent = self.bones_org[-2]
        return properties_bone

    def toon__get_num_segments_of_section(self, org_bone: BoneInfo) -> int:
        """Override cloud_leg, force 1 segment on the foot and toe."""
        if org_bone in self.bones_org[2:]:
            return 1
        return self.params.chain.segments

    def fk_chain__make(self, org_chain) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(org_chain)
        self.fk_toe = org_chain[-1].fk_bone
        # Toe FK should be available in the IK collection too.
        fk_chain[-1].collections += self.bone_sets['IK Controls'].collections
        return fk_chain

    def ik_chain__make_ik_setup(self):
        super().ik_chain__make_ik_setup()

        if self.params.limb.double_ik:
            self.__create_foot_dsp(self.ik_mstr.parent)
        self.__create_foot_dsp(self.ik_mstr)

        # IK Foot setup, including Foot Roll
        if self.params.leg.use_foot_roll:
            self.__make_footroll(self.ik_chain, self.bones_org)

            # For FK->IK snapping to work properly when the IK control is world-aligned,
            # we need a world-aligned child of the IK bone.
            if self.params.ik_chain.world_aligned:
                self.foot_snap_bone = self.bone_sets['IK Mechanism'].new(
                    name=self.naming.add_prefix(self.bone_sets['FK Controls'][2], "SNAP"),
                    source=self.bone_sets['FK Controls'][2],
                    vector=flat(self.bone_sets['FK Controls'][2].vector),
                    parent=self.ik_chain[2],
                )

        self.__make_ik_toe()

    def ik_chain__make_master_ctr(self, bone_set, source_bone, bone_name="", shape_name=""):
        """Override."""
        if shape_name == "":
            shape_name = "Foot"
        ik_master = super().ik_chain__make_master_ctr(
            bone_set, source_bone, bone_name, shape_name
        )
        ik_master.custom_shape_scale = 2.8

        return ik_master

    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole):
        """Overrides cloud_limb."""
        # Toe is not relevant for IK/FK switching.
        fk_chain = fk_chain[:-1]

        ui_data = super().ik_chain__get_ik_switch_ui_data(
            fk_chain, ik_chain, ik_mstr, ik_pole
        )

        if self.params.ik_chain.world_aligned and self.params.leg.use_foot_roll:
            # In the case of world aligned IK control + footroll, we must
            # snap the FK foot to a specialized helper bone rather than any IK bone.
            ui_data['op_kwargs']['map_fk_to_ik'][-1] = (
                fk_chain[2].name,
                self.foot_snap_bone.name,
            )

        return ui_data

    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr, stretch_bone, default=0.0):
        """Let leg IK poles follow the IK master by default."""
        super().ik_chain__make_pole_follow_switch(ik_pole, ik_mstr, stretch_bone, 1.0)

    def ik_chain__world_align_fk(self):
        """Overrides cloud_ik_chain.
        Make SECOND TO last FK bone world-aligned.
        """
        self.ik_chain__world_aligned_helper(self.bones_org[-2].fk_bone)

    ##############################
    # Leg functions.

    def __create_foot_dsp(self, bone):
        """Create display helper for the foot IK control."""
        dsp_bone = self.create_dsp_bone(bone)

        # To get the position of the foot bone display helper,
        # project a line out of the knee bone, then find the point on that line
        # which is closest the toe bone's tail, lowered to the Z position of the
        # heel bone if there is one and it is lower.
        knee = self.bones_org[1]
        toe = self.bones_org[-1]
        shoe_tip = toe.tail.copy()
        heel_pivot_bone = self.__get_heel_pivot_meta_bone()
        if heel_pivot_bone.tail_local.z < shoe_tip.z:
            shoe_tip.z = heel_pivot_bone.tail_local.z
        intersect = intersect_point_line(shoe_tip, knee.head, knee.tail)[0]

        dsp_bone.head = intersect
        dsp_bone.tail = shoe_tip
        dsp_bone.head.z = dsp_bone.tail.z
        dsp_bone.length = 0.1 * self.scale
        dsp_bone.roll_type = 'VECTOR'
        dsp_bone.roll_vector = toe.z_axis
        dsp_bone.roll = pi if self.side_suffix == 'L' else 0

        return dsp_bone

    @staticmethod
    def __calc_footroll_headtail(
        knee: BoneInfo, toe: BoneInfo, scale: float
    ) -> tuple[Vector, Vector]:
        scalar = knee.bbone_width * scale

        # Project a line along the knee bone, and find the point on that line closest to the toe tail
        intersect = intersect_point_line(toe.tail, knee.head, knee.tail)[0]
        # Find the direction that points from the toe tail towards the intersection point
        intersect_to_toe = (intersect - toe.tail).normalized()

        # Amount we want to offset the point by, away from the toe
        shift_from_toe = intersect_to_toe * scalar * 8
        # Amount we want to offset the point by, up along the knee
        shift_along_knee = (knee.tail - intersect).normalized() * scalar * 2

        # Calculate final position by adding the offsets to the intersection point.
        head = intersect + shift_from_toe + shift_along_knee

        # The tail should point toward the toe bone but stay perpendicular to the knee bone.
        tail = head + intersect_to_toe * scalar * -4
        return head, tail

    def __make_footroll(self, ik_chain, org_chain):
        ik_foot_chain = ik_chain[-2:]
        thigh, knee, foot, toe = org_chain

        rolly_stretchy = self.bone_sets['IK Mechanism'].new(
            name=self.naming.add_prefix(thigh, "IK-STR-ROLL"),
            source=thigh,
            tail=self.ik_mstr.head.copy(),
            parent=ik_chain[0],
        )
        rolly_stretchy.scale_width(0.4)
        rolly_stretchy.add_constraint('STRETCH_TO', subtarget=ik_chain[-2].name)

        _prefixes, base_name, suffixes = self.naming.slice_name(foot.name)
        master_name = self.naming.make_name(["ROLL"], base_name, suffixes)
        roll_master = self.bone_sets['IK Mechanism'].new(
            name=master_name, source=self.ik_mstr, parent=self.ik_mstr
        )
        roll_master.constraint_infos.append(self.ik_tgt_bone.constraint_infos[0])
        self.ik_tgt_bone.clear_constraints()

        # Create ROLL control behind the foot
        head, tail = self.__calc_footroll_headtail(knee, toe, self.scale)

        roll_ctrl = self.bone_sets['IK Controls'].new(
            name=self.naming.make_name(["ROLL-M"], base_name, suffixes),
            bbone_width=1 / 18,
            head=head,
            tail=tail,
            roll_type='VECTOR',
            roll_vector=toe.z_axis,
            parent=self.ik_mstr,
            custom_shape_name='Roll_Flat',
            use_custom_shape_bone_size=True,
        )
        if self.params.custom_props.props_storage == "GENERATED":
            self.properties_bone.parent = roll_ctrl
        # Limit Rotation, lock other transforms
        self.lock_transforms(roll_ctrl, rot=False)
        roll_ctrl.add_constraint(
            'LIMIT_ROTATION',
            use_limit_x=True,
            min_x=rad(-90),
            max_x=rad(130),
            use_limit_y=True,
            use_limit_z=True,
            min_z=rad(-90),
            max_z=rad(90),
        )

        # Create bone to use as pivot point when rolling back. This is read from the metarig and should be placed at the heel of the shoe, pointing forward.
        heel_pivot_bone = self.__get_heel_pivot_meta_bone()

        # Take the bone shape size of the foot controls from the heel pivot bone b-bone scale.
        self.ik_mstr._bbone_x = heel_pivot_bone.bbone_x
        self.ik_mstr._bbone_z = heel_pivot_bone.bbone_z
        if self.params.limb.double_ik:
            self.ik_mstr.parent._bbone_x = heel_pivot_bone.bbone_x
            self.ik_mstr.parent._bbone_z = heel_pivot_bone.bbone_z

        heel_pivot = self.bone_sets['IK Mechanism'].new(
            name="IK-RollBack"
            + base_name
            + self.naming.SUFFIX_SEPARATOR
            + self.side_suffix,
            bbone_width=toe.bbone_width,
            head=heel_pivot_bone.head_local,
            tail=heel_pivot_bone.head_local + Vector((0, -self.scale * 0.1, 0)),
            roll_type='VECTOR',
            roll_vector=toe.z_axis,
            parent=roll_master,
        )

        heel_pivot.add_constraint(
            'TRANSFORM',
            subtarget=roll_ctrl.name,
            map_from='ROTATION',
            map_to='ROTATION',
            from_min_x_rot=rad(-90),
            to_min_x_rot=rad(-60),
        )

        # Create reverse bones
        rik_chain = []
        for i, b in reversed(list(enumerate([foot, toe]))):
            rik_bone = self.bone_sets['Foot Reverse IK Controls'].new(
                name=self.naming.add_prefix(b, "RIK"),
                source=b,
                head=b.tail.copy(),
                tail=b.head.copy(),
                roll=pi,
                roll_type='VECTOR',
                roll_vector=-b.z_axis,
                parent=heel_pivot,
                custom_shape_name="Circle_Spiked_2",
            )
            rik_chain.append(rik_bone)
            ik_foot_chain[i].parent = rik_bone

            if i == 1:
                # Toe bone's roll
                toe_roll_con = rik_bone.add_constraint(
                    'TRANSFORM',
                    subtarget=roll_ctrl.name,
                    map_from='ROTATION',
                    map_to='ROTATION',
                    from_min_x_rot=rad(90),
                    from_max_x_rot=rad(166),
                    to_min_x_rot=rad(0),
                    to_max_x_rot=rad(-169),
                    from_min_z_rot=rad(-60),
                    from_max_z_rot=rad(60),
                    to_min_z_rot=rad(-10),
                    to_max_z_rot=rad(10),
                )
                toe_roll_prop_name = "Toe Roll Threshold"
                ensure_custom_property(
                    roll_ctrl, toe_roll_prop_name, default=rad(90), min=0, max=rad(180)
                )
                toe_roll_con.drivers.append(
                    {
                        'prop': 'from_min_x_rot',
                        'variables': [(roll_ctrl.name, toe_roll_prop_name)],
                    }
                )

            if i == 0:
                # Foot bone's roll
                rik_bone.add_constraint(
                    'COPY_LOCATION',
                    space='WORLD',
                    subtarget=rik_chain[-2].name,
                    head_tail=1,
                )

                rik_bone.add_constraint(
                    'TRANSFORM',
                    name="Transformation Roll",
                    subtarget=roll_ctrl.name,
                    map_from='ROTATION',
                    map_to='ROTATION',
                    from_min_x_rot=rad(0),
                    from_max_x_rot=rad(135),
                    to_min_x_rot=rad(0),
                    to_max_x_rot=rad(-118),
                    from_min_z_rot=rad(-45),
                    from_max_z_rot=rad(45),
                    to_min_z_rot=rad(-25),
                    to_max_z_rot=rad(25),
                )
                rik_bone.add_constraint(
                    'TRANSFORM',
                    name="Transformation CounterRoll",
                    subtarget=roll_ctrl.name,
                    map_from='ROTATION',
                    map_to='ROTATION',
                    from_min_x_rot=rad(90),
                    from_max_x_rot=rad(135),
                    to_min_x_rot=rad(0),
                    to_max_x_rot=rad(31.8),
                )

        # Change the subtarget of the constraints on main_str_bones from the old stretchy bone to the new one, that accounts for footroll.
        for main_str_bone in self.main_str_bones:
            ci = main_str_bone.parent.get_constraint('CopyLoc_IK_Stretch')
            if ci:
                ci.subtarget = rolly_stretchy.name

        # Set properties bone display
        if self.params.custom_props.props_storage == 'GENERATED':
            self.properties_bone.custom_shape_transform = roll_ctrl

    def __get_heel_pivot_meta_bone(self) -> Bone:
        heel_pivot_name = self.params.leg.heel_bone
        if heel_pivot_name == "":
            heel_pivot_name = self.bones_org[-2].name.replace("ORG-", "")
        heel_pivot_pb = self.get_metarig_pbone(heel_pivot_name)
        if not heel_pivot_pb:
            self.raise_generation_error(
                f'Could not find HeelPivot bone in the metarig: "{heel_pivot_name}".'
            )

        return heel_pivot_pb.bone

    def __make_ik_toe(self):
        # FK Toe bone should be parented between FK Foot and IK Toe.
        fk_toe = self.fk_toe
        fk_toe.parent = None
        self.create_driven_armature_constraint(
            fk_toe,
            target_bones=[self.bones_org[-2].fk_bone, self.ik_chain[-1]],
            prop_bone=self.properties_bone,
            prop_name=self.ikfk_name,
            name="Armature (Toe FK/IK)"
        )

    def __tweak_org_foot(self):
        # Delete IK constraint and driver from toe bone. It should always use FK.
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
            'Foot Reverse IK Controls',
            color_palette='THEME12',
            collections=['IK Secondary'],
            wire_width=2,
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_control_params(layout, context, params)

        cls.draw_prop(context, layout, params.leg, "use_foot_roll")
        if params.leg.use_foot_roll:
            split = layout.split(factor=0.1)
            split.row()
            cls.draw_prop_search(
                context,
                split.row(),
                params.leg,
                "heel_bone",
                context.active_object.data,
                "bones",
                text="Heel Pivot",
            )


class Params(PropertyGroup):
    use_foot_roll: BoolProperty(
        name="Foot Roll", description="Create Foot roll controls", default=True
    )
    heel_bone: StringProperty(
        name="Heel Pivot Bone",
        description="Bone to use as the heel pivot. This bone should be placed at the heel of the shoe, pointing forward. If unspecified, fall back to the foot bone",
        default="",
    )


RIG_COMPONENT_CLASS = Component_Limb_BipedLeg
