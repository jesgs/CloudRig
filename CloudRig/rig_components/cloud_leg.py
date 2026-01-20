# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi
from math import radians as rad

from bpy.props import BoolProperty, StringProperty
from bpy.types import PoseBone, PropertyGroup
from mathutils import Vector
from mathutils.geometry import intersect_point_line

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.maths import flat
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
        self.chain_count -= 1

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

    def ik_chain__prevent_straight_chain(self, y_offset=0.001):
        # Since legs face the opposite direction, let's flip the offset here.
        super().ik_chain__prevent_straight_chain(y_offset=-y_offset)

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

    def ik_chain__make_ik_setup(self):
        super().ik_chain__make_ik_setup()

        if self.params.limb.double_ik:
            self.__create_foot_dsp(self.ik_mstr.parent)
        self.__create_foot_dsp(self.ik_mstr)

        # IK Foot setup, including Foot Roll.
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
                    roll=0,
                )

        self.__make_ik_toe()

    def ik_chain__make_master_ctr(self, bone_set, source_bone, bone_name="", shape_name=""):
        """Tweak the foot shape."""
        if shape_name == "":
            shape_name = "Foot"
        ik_master = super().ik_chain__make_master_ctr(
            bone_set, source_bone, bone_name, shape_name
        )
        ik_master.custom_shape_scale = 2.8
        if self.side_suffix == 'L':
            ik_master.custom_shape_scale_xyz.x *= -1

        return ik_master

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole) -> dict:
        """Toe is not relevant for IK/FK switching."""
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

    @no_overlay
    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr, stretch_bone, default=0.0):
        """Let leg IK poles follow the IK master by default."""
        super().ik_chain__make_pole_follow_switch(ik_pole, ik_mstr, stretch_bone, 1.0)

    @no_overlay
    def ik_chain__world_align_fk(self):
        """Make 2nd-to-last FK bone (ie. FK Foot) world-aligned."""
        self.ik_chain__world_aligned_helper(self.bones_org[-2].fk_bone)

    ##############################
    # Leg functions.

    def __create_foot_dsp(self, bone: BoneInfo):
        """Create display helper for the foot IK control."""
        knee, foot, toe = self.bones_org[-3:]

        dsp_bone = self.create_dsp_bone(
            bone,
            head=intersect_point_line(toe.tail, knee.head, knee.tail)[0],
            tail=toe.tail.copy(),
        )
        dsp_bone.roll_align_vector(foot.head, axis='-Z')

        bone.custom_shape_along_length = 0.5
        bone.use_custom_shape_bone_size = False
        bone.custom_shape_scale_xyz *= dsp_bone.length * 0.75

        return dsp_bone

    def __calc_footroll_headtail(self) -> tuple[Vector, Vector]:
        knee, foot, toe = self.bones_org[-3:]
        # Project a line along the knee bone, and find the point on that line closest to the toe's tail.
        intersect = intersect_point_line(toe.tail, knee.head, knee.tail)[0]
        # Find the direction that points from the toe's tail towards this intersection point.
        intersect_to_toe = (intersect - toe.tail).normalized()

        # Amount we want to offset the point by, away from the foot.
        shift_from_toe = intersect_to_toe * foot.length
        # Amount we want to offset the point by, up along the knee.
        shift_along_knee = knee.vector.normalized() * -foot.length

        # Calculate final position by adding the offsets to the intersection point.
        head = intersect + shift_from_toe + shift_along_knee

        # The tail should point toward the toe bone but stay perpendicular to the knee bone.
        tail = head + -intersect_to_toe * foot.length
        return head, tail

    def __make_footroll(self, ik_chain, org_chain):
        ik_foot_chain = ik_chain[-2:]
        org_thigh, org_knee, org_foot, org_toe = org_chain

        rolly_stretchy = self.bone_sets['IK Mechanism'].new(
            name=self.naming.add_prefix(org_thigh, "IK-STR-ROLL"),
            source=org_thigh,
            tail=self.ik_mstr.head.copy(),
            parent=ik_chain[0],
        )
        rolly_stretchy.scale_width(0.4)
        rolly_stretchy.add_constraint('STRETCH_TO', subtarget=ik_chain[-2].name)

        _prefixes, base_name, suffixes = self.naming.slice_name(org_foot.name)
        master_name = self.naming.make_name(["ROLL"], base_name, suffixes)

        # Create ROLL control behind the foot.
        head, tail = self.__calc_footroll_headtail()

        TWIST_RANGE = 90
        HEEL_LIMIT = 60
        FOOT_THRESHOLD = 90
        TOE_THRESHOLD = 135

        roll_ctrl = self.bone_sets['IK Controls'].new(
            name=self.naming.make_name(["ROLL-M"], base_name, suffixes),
            bbone_width=1 / 18,
            head=head,
            tail=tail,
            parent=self.ik_mstr,
            custom_shape_name=self.params.leg.shape_footroll.shape_name,
            use_custom_shape_bone_size=True,
        )
        roll_ctrl.roll_align_vector(org_toe.head)
        if self.params.custom_props.props_storage == "GENERATED":
            self.properties_bone.parent = roll_ctrl
        # Limit Rotation, lock other transforms.
        self.lock_transforms(roll_ctrl, rot=[False, True, False])
        roll_ctrl.add_constraint(
            'LIMIT_ROTATION',
            use_limit_x=True,
            min_x=rad(-HEEL_LIMIT),
            max_x=rad(TOE_THRESHOLD),
            use_limit_y=True,
            use_limit_z=True,
            min_z=rad(-TWIST_RANGE),
            max_z=rad(TWIST_RANGE),
        )

        roll_master = None
        roll_master = self.bone_sets['IK Mechanism'].new(
            name=master_name, source=self.ik_mstr, parent=self.ik_mstr
        )
        if not self.painter:
            roll_master.constraint_infos.append(self.ik_tgt_bone.constraint_infos[0])
            self.ik_tgt_bone.clear_constraints()

        # Create bone to use as pivot point when rolling back.
        # This is read from the metarig and should be placed at
        # the heel of the shoe, pointing forward.
        heel_pivot_bone = self.__get_heel_pivot_meta_bone()

        # Take the bone shape size of the foot controls from the heel pivot bone b-bone scale.
        self.ik_mstr._bbone_x = heel_pivot_bone.bone.bbone_x
        self.ik_mstr._bbone_z = heel_pivot_bone.bone.bbone_z
        if self.params.limb.double_ik:
            self.ik_mstr.parent._bbone_x = heel_pivot_bone.bone.bbone_x
            self.ik_mstr.parent._bbone_z = heel_pivot_bone.bone.bbone_z

        heel_pivot = self.bone_sets['IK Mechanism'].new(
            name="IK-RollBack"
            + base_name
            + self.naming.SUFFIX_SEPARATOR
            + self.side_suffix,
            bbone_width=org_toe.bbone_width,
            head=heel_pivot_bone.head,
            tail=heel_pivot_bone.tail,
            parent=roll_master,
        )
        heel_pivot.roll_align_vector(org_knee.head, axis='-Z')

        heel_pivot.add_constraint(
            'TRANSFORM',
            name="Transform (Heel Roll)",
            subtarget=roll_ctrl.name,
            map_from='ROTATION',
            map_to='ROTATION',
            from_min_x_rot=rad(-HEEL_LIMIT),
            to_min_x_rot=rad(-HEEL_LIMIT),
        )

        # Create reverse IK bones.
        rik_chain = []
        for i, org_bone in reversed(list(enumerate([org_foot, org_toe]))):
            rik_bone = self.bone_sets['Foot Reverse IK Controls'].new(
                name=self.naming.add_prefix(org_bone, "RIK"),
                source=org_bone,
                head=org_bone.tail.copy(),
                tail=org_bone.head.copy(),
                parent=heel_pivot,
                custom_shape_name=self.params.fk_chain.shape_fk.shape_name,
            )
            rik_bone.roll_align_other(org_bone)
            rik_bone.roll_flip()
            rik_chain.append(rik_bone)
            ik_foot_chain[i].parent = rik_bone

            # Calculate angle of rotation necessary to make this bone vertical.
            angle_to_vertical = (org_knee.head-org_knee.tail).angle(rik_bone.vector)

            if i == 0:
                # Foot bone's roll
                rik_bone.add_constraint(
                    'COPY_LOCATION',
                    name = "Copy Location (RIK)",
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
                    from_min_z_rot=rad(-TWIST_RANGE),
                    from_max_z_rot=rad(TWIST_RANGE),

                    to_max_x_rot=angle_to_vertical,
                    to_max_z_rot=rad(-TWIST_RANGE/2),
                    to_min_z_rot=rad(TWIST_RANGE/2),
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
                    from_min_z_rot=rad(-TWIST_RANGE),
                    from_max_z_rot=rad(TWIST_RANGE),
                    to_min_z_rot=rad(TWIST_RANGE*(2/3)),
                    to_max_z_rot=rad(-TWIST_RANGE*(2/3)),
                )

        # Change the subtarget of the constraints on main_str_bones from the old stretchy bone to the new one, that accounts for footroll.
        for main_str_bone in self.main_str_bones:
            ci = main_str_bone.parent.get_constraint('CopyLoc_IK_Stretch')
            if ci:
                ci.subtarget = rolly_stretchy.name

        # Set properties bone display
        if self.params.custom_props.props_storage == 'GENERATED':
            self.properties_bone.custom_shape_transform = roll_ctrl

    def __get_heel_pivot_meta_bone(self) -> PoseBone:
        heel_pivot_name = self.params.leg.heel_bone
        if heel_pivot_name == "":
            heel_pivot_name = self.bones_org[-2].name.replace("ORG-", "")
        heel_pivot_pb = self.get_metarig_pbone(heel_pivot_name)
        if not heel_pivot_pb:
            self.raise_generation_error(
                f'Could not find HeelPivot bone in the metarig: "{heel_pivot_name}".'
            )

        return heel_pivot_pb

    @no_overlay
    def __make_ik_toe(self):
        """FK Toe bone should be parented between FK Foot and IK Toe."""
        fk_toe = self.fk_chain[-1]
        self.create_driven_armature_constraint(
            fk_toe,
            target_bones=[self.bones_org[-2].fk_bone, self.ik_chain[-1]],
            prop_bone=self.properties_bone,
            prop_name=self.ikfk_name,
            name="Armature (Toe FK/IK)"
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
            'Foot Reverse IK Controls',
            color_palette='THEME12',
            collections=['IK Secondary'],
            wire_width=1.5,
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

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

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        if params.leg.use_foot_roll:
            cls.draw_prop_custom_shape(context, layout, params.leg, 'shape_footroll')


class Params(PropertyGroup):
    use_foot_roll: BoolProperty(
        name="Foot Roll", description="Create a Foot Roll control. When rotated 90 degrees on the X axis, the foot will be fully vertical (ie. on tippy-toes). Rotate it an additional 45 degrees, and the toe will also be vertical (like a ballerina). The angles are calculated based on the rest pose", default=True
    )
    heel_bone: StringProperty(
        name="Heel Pivot Bone",
        description="Bone to use as the heel pivot. This bone should be placed at the heel of the shoe, pointing forward. If unspecified, fall back to the foot bone",
        default="",
    )

    shape_footroll: Component_Limb.make_custom_shape_params(
        identifier="Foot Roll",
        default="Roll 2"
    )


RIG_COMPONENT_CLASS = Component_Limb_BipedLeg
