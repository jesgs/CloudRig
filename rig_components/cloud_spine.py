# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup
from bpy.props import BoolProperty
from mathutils import Vector
from math import pi

from ..rig_component_features.bone_info import BoneInfo
from .cloud_fk_chain import Component_Chain_FK


class Component_Spine_IKFK(Component_Chain_FK):
    """Spine setup with FK, IK-like and stretchy IK controls."""

    ui_name = "Spine: IK/FK"
    forced_params = {
        'chain.segments': 1,
        'fk_chain.double_first': False,
        'fk_chain.hinge': False,
        'fk_chain.display_center': False,
        'fk_chain.root': True,
    }
    always_use_custom_props = True

    def initialize(self):
        """Gather and validate data about the rig."""
        super().initialize()

        if self.params.spine.use_ik and self.bone_count < 3:
            self.raise_generation_error(
                "Spine rig with IK must consist of a chain of at least 3 connected bones!"
            )
        if not self.bone_count > 1:
            self.raise_generation_error(
                "Spine rig must consist of a chain of at least 2 connected bones!"
            )

        self.spine_name = self.naming.slice_name(self.base_bone_name)[1]

        self.ik_prop_name = "ik_" + self.spine_name.lower()
        self.ik_stretch_name = "ik_stretch_" + self.spine_name.lower()

        self.root_torso = None

        # The main chest control.
        self.mstr_chest = None
        # The main hip control.
        self.mstr_hips = None

        # IK Controls for the reverse chain.
        self.ik_ctr_chain = []
        # The Reverse IK Chain, which aims at the controls, and are aimed at by the IK bones.
        self.ik_r_chain = []
        # The lowest level IK mechanism bones, which aim at the reverse bones and own the FK bones.
        self.ik_chain = []

    def make_root_bone(self):
        """Overrides cloud_fk_chain."""

        # Create Torso Master control
        torso_root_bone = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["TORSO"], self.spine_name, [self.side_suffix]),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            custom_shape_name="Torso_Master",
        )
        return torso_root_bone

    def make_fk_chain(self, org_chain) -> list[BoneInfo]:
        """Overrides cloud_fk_chain."""
        fk_chain = super().make_fk_chain(org_chain)

        # Create master hip control
        self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["HIP"], self.spine_name, [self.side_suffix]),
            source=org_chain[0],
            head=org_chain[0].tail,
            tail=org_chain[0].head,
            custom_shape_name="Hyperbola",
            parent=self.root_bone,
        )
        if self.params.spine.world_align:
            self.root_bone.flatten()
            self.mstr_hips.flatten()

        # Parent the first FK control to ROOT.
        self.bone_sets['FK Controls'][0].parent = self.root_bone

        return fk_chain

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        # If we want to parent things to the root bone, we use self.root_torso.
        # However, for spine.double to work, self.root_bone must be the bone
        # returned from create_parent_bone().
        self.root_torso = self.root_bone

        if self.params.spine.use_ik:
            self.make_ik_spine()

        if self.params.spine.double:
            self.root_bone = self.create_parent_bone(
                self.root_torso, self.bone_sets['Spine Parent Controls']
            )

    def make_ik_spine(self):
        ### Create master chest control.
        chest_org = self.bones_org[-2]
        head = chest_org.center
        if self.params.spine.world_align:
            tail = head + Vector((0, 0, self.scale))
        else:
            tail = self.bones_org[-1].tail
        self.mstr_chest = self.bone_sets['Spine IK Controls'].new(
            name=self.naming.add_prefix(self.spine_name, "CHST"),
            source=chest_org,
            head=head,
            tail=tail,
            custom_shape_name="Hyperbola",
            custom_shape_scale_xyz=Vector((0.8, -1.3, 0.8)),
            custom_shape_translation=Vector((0, (tail - head).length * 1.8, 0)),
            parent=self.root_torso,
        )

        if self.params.spine.double:
            self.create_parent_bone(
                self.mstr_chest, self.bone_sets['Spine Parent Controls']
            )

        ### IK Control (IK-CTR) chain. Exposed to animators, although rarely used.
        for i, org_bone in enumerate(self.bones_org):
            ik_ctr_bone = self.bone_sets['Spine IK Secondary'].new(
                name="IK-CTR-" + org_bone.name,
                source=org_bone,
                custom_shape_name='Square',
                custom_shape_rotation_euler=((0, pi / 4, 0)),
                custom_shape_scale_xyz=Vector((1, 1, 0.8)),
            )

            if len(self.bones_org) - 1 > i > 0:
                influence_unit = 1 / (len(self.bones_org) - 1)
                influence = influence_unit * i
                ik_ctr_bone.add_constraint(
                    'COPY_ROTATION',
                    mix_mode='ADD',  # Flips later than Before Original.
                    subtarget=self.mstr_chest,
                    influence=influence,
                    use_xyz=[False, True, False],
                )
                ik_ctr_bone.add_constraint(
                    'COPY_ROTATION',
                    mix_mode='ADD',  # Flips later than Before Original.
                    subtarget=self.mstr_hips,
                    influence=1 - influence,
                    use_xyz=[False, True, False],
                    invert_xyz=[False, True, False],
                )

            if i == 0:
                # First spine control should be parented to the hip control.
                ik_ctr_bone.parent = self.mstr_hips
            elif i == len(self.bones_org) - 1:
                # Last spine control should be parented to the chest control.
                ik_ctr_bone.parent = self.mstr_chest
            else:
                # The rest to the torso root.
                ik_ctr_bone.parent = self.root_torso
            self.ik_ctr_chain.append(ik_ctr_bone)

        # Reverse IK (IK-R) chain. Switch bone direction, and Damped Track to IK-CTR.
        # We iterate in reverse to make the parenting easier.
        next_parent = self.mstr_chest
        for i, ik_ctr_bone in enumerate(reversed(self.ik_ctr_chain)):
            ik_r_name = ik_ctr_bone.name.replace("IK-CTR", "IK-R")
            ik_r_bone = self.bone_sets['Spine Mechanism'].new(
                name=ik_r_name,
                head=ik_ctr_bone.tail,
                tail=ik_ctr_bone.head,
                parent=next_parent,
                custom_shape_name='Arrow',
                use_custom_shape_bone_size=True,
            )
            next_parent = ik_r_bone
            self.ik_r_chain.append(ik_r_bone)
            ik_r_bone.add_constraint(
                'DAMPED_TRACK',
                subtarget=ik_ctr_bone,
            )
            # if i > 0:
            # To give a decent behaviour to scaling mstr_chest, let's not
            # inherit scale for the IK-R bones that aren't stuck to it.
            # ik_r_bone.inherit_scale = 'NONE'
        self.ik_r_chain.reverse()

        # IK chain. Aims at the IK-R bones, and owns the FK bones.
        # Also does the stretching.
        next_parent = self.ik_ctr_chain[0]
        for i, (org_bone, ik_r_bone, ik_ctr_bone) in enumerate(
            zip(self.bones_org, self.ik_r_chain, self.ik_ctr_chain)
        ):
            ik_name = ik_r_bone.name.replace("IK-R", "IK-M")
            ik_bone = self.bone_sets['Spine Mechanism'].new(
                name=ik_name,
                source=org_bone,
                parent=next_parent,
                custom_shape_name='Arrow',
                use_custom_shape_bone_size=True,
            )
            self.ik_chain.append(ik_bone)
            next_parent = ik_bone
            ik_ctr_bone.custom_shape_transform = ik_bone

            if i > 0:
                # IK Stretch Copy Location
                con_name = "Copy Location (Stretchy Spine)"
                str_con = ik_bone.add_constraint(
                    'COPY_LOCATION',
                    space='WORLD',
                    name=con_name,
                    subtarget=ik_r_bone.name,
                    head_tail=1,
                )

                # Influence driver
                influence_unit = 1 / (len(self.bones_org) - 1)
                influence = influence_unit * i

                str_con.drivers.append(
                    {
                        'prop': 'influence',
                        'expression': f"var * {influence}",
                        'variables': [
                            (self.properties_bone.name, self.ik_stretch_name)
                        ],
                    }
                )

                ik_bone.add_constraint(
                    'COPY_ROTATION',
                    space='WORLD',
                    subtarget=ik_ctr_bone,
                )
                ik_bone.add_constraint(
                    'COPY_SCALE',
                    space='WORLD',
                    subtarget=ik_ctr_bone,
                )

            ik_bone.add_constraint('DAMPED_TRACK', subtarget=ik_r_bone)

        # Attach FK to IK
        for fk_bone, ik_bone in zip(self.fk_chain, self.ik_chain):
            con_name = "Copy Transforms IK"
            ct_con = fk_bone.add_constraint(
                'COPY_TRANSFORMS', space='WORLD', name=con_name, subtarget=ik_bone
            )

            ct_con.drivers.append(
                {
                    'prop': 'influence',
                    'variables': [(self.properties_bone.name, self.ik_prop_name)],
                }
            )

        # Store info for UI
        self.add_bone_property_with_ui(
            prop_bone=self.properties_bone,
            prop_id=self.ik_stretch_name,
            panel_name="IK",
            label_name="IK Stretch",
            row_name=self.limb_name,
            slider_name=self.spine_name,
            custom_prop_settings={
                'default': 1.0,
                'description': "Allow the spine to stretch beyond its normal length while in IK mode, for a cartoony effect",
            },
        )

        self.add_bone_property_with_ui(
            prop_bone=self.properties_bone,
            prop_id=self.ik_prop_name,
            panel_name="FK/IK Switch",
            row_name=self.limb_name,
            slider_name=self.spine_name,
            custom_prop_settings={
                'default': 0.0,
                'description': "Switch to an IK-like posing mode. Instead of posing the spine from bottom to top, this lets you control the two end points in an intuitive way"
            },
        )

    def make_main_str_bone(
        self, org_chain: BoneInfo, org_i: int, at_tip=False
    ) -> BoneInfo:
        str_bone = super().make_main_str_bone(org_chain, org_i, at_tip)
        if self.params.chain.smooth_spline:
            # If Smooth Spline is enabled, we don't need to fix the spine's curvature.
            return str_bone

        if org_i == 0 or at_tip:
            # The first STR bone and the tip STR bone don't need corrections.
            return str_bone

        counter_rot = str_bone.add_constraint(
            'COPY_ROTATION',
            name="Counter Rotate IK",
            subtarget=str_bone.parent,
            use_xyz=[True, False, True],
            invert_xyz=[True, False, True],
            influence=0.5,
        )
        counter_rot.drivers.append(
            {
                'prop': 'influence',
                'expression': "var * 0.5",
                'variables': [(self.properties_bone.name, self.ik_prop_name)],
            }
        )

        return str_bone

    def attach_org_to_fk(self, org_bones, fk_bones):
        """Overrides cloud_fk_chain.
        First STR bone should be owned by the hips (via first ORG bone).
        """
        super().attach_org_to_fk(org_bones, fk_bones)
        org_bones[0].parent = self.mstr_hips
        org_bones[0].constraint_infos.pop()

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        """Create parameters for this rig's bone sets."""
        cls.define_bone_set(
            'Spine Main Controls', color_palette='THEME12', collections=['IK Controls', 'FK Controls']
        )
        cls.define_bone_set(
            'Spine IK Controls', color_palette='THEME12', collections=['IK Controls']
        )
        cls.define_bone_set(
            'Spine Parent Controls',
            color_palette='THEME09',
            collections=['IK Controls'],
        )
        cls.define_bone_set(
            'Spine IK Secondary', color_palette='THEME06', collections=['IK Secondary']
        )
        cls.define_bone_set(
            'Spine Mechanism', collections=['Mechanism: Spine IK'], is_advanced=True
        )

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == "spine_ik_secondary":
            return params.spine.use_ik
        if set_name == "spine_parent_controls":
            return params.spine.double

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_control_params(layout, context, params)

        layout.separator()
        cls.draw_control_label(layout, "Spine")
        cls.draw_prop(context, layout, params.spine, 'use_ik')
        cls.draw_prop(context, layout, params.spine, 'double')
        cls.draw_prop(context, layout, params.spine, 'world_align')


class Params(PropertyGroup):
    use_ik: BoolProperty(
        name="Create IK Spine",
        description="If disabled, this spine rig will only have FK controls",
        default=True,
    )
    double: BoolProperty(
        name="Duplicate Controls",
        description="Make duplicates of the main spine controls",
        default=False,
    )
    world_align: BoolProperty(
        name="World-Align Controls",
        description="Flatten the torso and hips to align with the closest world axis",
        default=True,
    )


RIG_COMPONENT_CLASS = Component_Spine_IKFK
