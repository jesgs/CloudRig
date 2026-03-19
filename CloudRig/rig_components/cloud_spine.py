# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.app.translations import pgettext_tip as tip_
from bpy.props import BoolProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_fk_chain import Component_Chain_FK


class Component_Spine_IKFK(Component_Chain_FK):
    """Spine setup with FK, IK-like and stretchy IK controls."""

    ui_name = "Spine: IK/FK"
    forced_params = {
        'chain.segments': 1,
        'fk_chain.double_first': False,
        'fk_chain.hinge': False,
        'fk_chain.create_curl_control': False,
        'fk_chain.counter_rotate_stretch_bones': 0.5,
        'fk_chain.root': True,
    }
    always_use_custom_props = True

    ################################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.params.spine.use_ik and self.bone_count < 3:
            self.raise_generation_error(
                rpt_("Spine component with IK must consist of a chain of at least 3 connected bones!")
            )
        if not self.bone_count > 1:
            self.raise_generation_error(
                rpt_("Spine component must consist of a chain of at least 2 connected bones!")
            )

        self.ik_prop_name = "ik_" + self.base_name.lower()
        self.ik_stretch_name = "ik_stretch_" + self.base_name.lower()

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

    def fk_chain__make_root_bone(self):
        # Create Torso Master control
        self.torso_ctr = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.add_prefix(self.base_name, 'TORSO'),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            length=self.bones_org[0].length+self.bones_org[1].length/2,
            custom_shape_name=self.params.spine.shape_torso.shape_name,
        )
        if self.params.spine.world_align:
            self.torso_ctr.world_align()
            self.torso_ctr.custom_shape_rotation_euler.x = pi/2
        return self.torso_ctr

    def fk_chain__make(self, org_chain) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(org_chain)

        fk_chain[1].parent = self.torso_ctr

        # Create master hip control.
        self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.add_prefix(self.base_name, "HIP"),
            source=org_chain[0],
            head=org_chain[0].tail,
            tail=org_chain[0].head,
            custom_shape_name=self.params.spine.shape_hip.shape_name,
            parent=self.torso_ctr,
        )
        self.mstr_hips.roll_align_other(org_chain[0], axis='-Z')
        self.mstr_hips.custom_shape_translation *= Vector((1, -1, -1))
        self.mstr_hips.custom_shape_scale_xyz = self.mstr_hips.custom_shape_scale_xyz.zyx
        self.mstr_hips.custom_shape_rotation_euler.y *= -1
        self.mstr_hips.custom_shape_rotation_euler.y += pi/2
        self.mstr_hips.custom_shape_rotation_euler.z *= -1
        fk_chain[0].parent = self.mstr_hips
        fk_chain[0].collections = self.bones_mch.collections

        # TODO: Flatten will be deprecated in 6.0
        spine_params = self.params.spine
        if spine_params.world_align:
            self.root_bone.world_align()
            self.mstr_hips.world_align()
            self.mstr_hips.custom_shape_rotation_euler = (-pi/2, 0, pi/2)

        elif spine_params.flatten_controls:
            self.root_bone.flatten()
            self.mstr_hips.flatten()

        return fk_chain

    @no_overlay
    def fk_chain__counter_rotate_str_bones(self, fk_chain: list[BoneInfo], main_str_bones: list[BoneInfo], influence=0.85):
        super().fk_chain__counter_rotate_str_bones(self.bones_org[1:], main_str_bones[1:], influence)
        arm_con = main_str_bones[1].parent_armature_constraint
        if arm_con:
            arm_con.targets = [self.mstr_hips.name]
        main_str_bones[1].constraint_infos[-1].invert_xyz = (False, False, False)
        main_str_bones[1].constraint_infos[-1].influence = 0.75

    @no_overlay
    def fk_chain__attach_org_to_fk(self, org_bones, fk_bones):
        """First ORG bone should be owned by the hips."""
        super().fk_chain__attach_org_to_fk(org_bones[1:], fk_bones[1:])
        org_bones[0].parent = self.mstr_hips

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        # If we want to parent things to the root bone, we use self.root_torso.
        # However, for spine.double to work, self.root_bone must be the bone
        # returned from create_parent_bone().
        self.root_torso = self.root_bone

        if self.params.spine.use_ik:
            self.__make_ik_spine()

        if self.params.spine.double:
            self.root_bone = self.create_parent_bone(
                self.root_torso, self.bone_sets['Spine Parent Controls']
            )

    ################################
    # IK/FK spine functions.

    def __make_ik_spine(self):
        ### Create master chest control.
        chest_org = self.bones_org[-1]
        chest = self.bone_sets['Spine IK Controls'].new(
            name=self.naming.add_prefix(self.base_name, "CHST"),
            source=chest_org,
            head=self.bones_org[-2].center,
            length=chest_org.length,
            parent=self.root_torso,
            custom_shape_name=self.params.spine.shape_chest.shape_name,
        )
        if self.params.spine.world_align:
            chest.world_align()
        elif self.params.spine.flatten_controls:
            chest.flatten()
        chest.custom_shape_scale_xyz = chest.custom_shape_scale_xyz.zyx
        chest.custom_shape_scale_xyz.y *= 2
        chest.custom_shape_rotation_euler.y += pi/2
        self.mstr_chest = chest

        if self.params.spine.double:
            self.create_parent_bone(
                self.mstr_chest, self.bone_sets['Spine Parent Controls']
            )

        ### IK Control (IK-CTR) chain. Exposed to animators, although rarely used.
        for i, org_bone in enumerate(self.bones_org):
            ik_ctr_bone = self.bone_sets['Spine IK Secondary'].new(
                name=self.naming.add_prefix(org_bone, "IK-CTR"),
                source=org_bone,
                custom_shape_name=self.params.spine.shape_ik.shape_name,
                rotation_mode='YZX',
                lock_rotation=[True, False, True],
            )
            ik_ctr_bone.custom_shape_rotation_euler.x = 0
            ik_ctr_bone.custom_shape_rotation_euler.y += pi/4
            ik_ctr_bone.custom_shape_rotation_euler.z = 0

            ik_ctr_bone.custom_shape_translation = Vector((0, 0, 0))

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

        if self.painter:
            return

        # Reverse IK (IK-R) chain. Switch bone direction, and Damped Track to IK-CTR.
        # We iterate in reverse to make the parenting easier.
        next_parent = self.mstr_chest
        for i, ik_ctr_bone in enumerate(reversed(self.ik_ctr_chain)):
            ik_r_bone = self.bone_sets['Spine Mechanism'].new(
                name=self.naming.add_prefix(ik_ctr_bone.source, "IK-R"),
                source=ik_ctr_bone,
                head=ik_ctr_bone.tail,
                tail=ik_ctr_bone.head,
                parent=next_parent,
                custom_shape_name='Arrow',
                use_custom_shape_bone_size=True,
                custom_shape_translation=Vector((0, 0, 0)),
                custom_shape_scale_xyz=Vector((1, 1, 1)),
                custom_shape_rotation_euler=Vector((0, 0, 0)),
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
            ik_bone = self.bone_sets['Spine Mechanism'].new(
                name=self.naming.add_prefix(ik_r_bone.source, "IK-M"),
                source=org_bone,
                parent=next_parent,
                custom_shape_name='Arrow',
                use_custom_shape_bone_size=True,
                custom_shape_translation=Vector((0, 0, 0)),
                custom_shape_scale_xyz=Vector((1, 1, 1)),
                custom_shape_rotation_euler=Vector((0, 0, 0)),
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

        # Attach ORG to IK
        for i, (fk_bone, ik_bone) in enumerate(zip(self.fk_chain, self.ik_chain)):
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
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.ik_stretch_name,
            panel_name=n_("IK"),
            label_name=n_("IK Stretch"),
            row_name=self.base_name,
            slider_name=self.base_name,
            custom_prop_settings={
                'default': 1.0,
                'description': tip_("Allow the spine to stretch beyond its normal length "
                "while in IK mode, for a cartoony effect"),
            },
            context_bones=self.ik_ctr_chain + [self.mstr_chest, self.torso_ctr, self.mstr_hips],
        )

        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.ik_prop_name,
            panel_name=n_("FK/IK Switch"),
            row_name=self.base_name,
            slider_name=self.base_name,
            custom_prop_settings={
                'default': 0.0,
                'description': tip_("Switch to an IK-like posing mode. Instead of posing the spine "
                "from bottom to top, this lets you control the two end points in an intuitive way")
            },
            context_bones=self.fk_chain + self.ik_ctr_chain + [self.mstr_chest, self.torso_ctr, self.mstr_hips],
        )

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        """Create parameters for this rig's bone sets."""
        cls.define_bone_set(
            n_("Spine Main Controls"),
            color_palette='THEME12',
            collections=['IK Controls', 'FK Controls'],
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Spine IK Controls"),
            color_palette='THEME12',
            collections=['IK Controls'],
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Spine Parent Controls"),
            color_palette='THEME09',
            collections=['IK Controls'],
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Spine IK Secondary"),
            color_palette='THEME06',
            collections=['IK Secondary'],
            wire_width=1.0,
        )
        cls.define_bone_set(
            n_("Spine Mechanism"),
            collections=['Mechanism: Spine IK'],
            is_advanced=True,
        )

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == "spine_ik_secondary":
            return params.spine.use_ik
        if set_name == "spine_parent_controls":
            return params.spine.double

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        layout.separator()
        cls.draw_control_label(layout, iface_("Spine"))
        cls.draw_prop(context, layout, params.spine, 'use_ik')
        cls.draw_prop(context, layout, params.spine, 'double')

        cls.draw_prop(context, layout, params.spine, "world_align", enabled=(not params.spine.flatten_controls))
        cls.draw_prop(context, layout, params.spine, "flatten_controls", enabled=(not params.spine.world_align))

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.spine, "shape_torso")
        cls.draw_prop_custom_shape(context, layout, params.spine, "shape_chest")
        cls.draw_prop_custom_shape(context, layout, params.spine, "shape_hip")
        cls.draw_prop_custom_shape(context, layout, params.spine, "shape_ik")


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
        description="Align the torso and hip controls with the world axes",
        default=True,
    )
    flatten_controls: BoolProperty(
        name="Flatten Controls (Deprecated)",
        description="Align torso and hip controls with the closest world axis. This option is deprecated and will be removed in Blender 6.0 in favor of 'World Align Controls'.",
        default=False,
    )

    shape_hip: Component_Chain_FK.make_custom_shape_params(
        identifier="Hip",
        default="Saddle"
    )
    shape_chest: Component_Chain_FK.make_custom_shape_params(
        identifier="Chest",
        default="Saddle"
    )
    shape_torso: Component_Chain_FK.make_custom_shape_params(
        identifier="Torso",
        default="Torso"
    )
    shape_ik: Component_Chain_FK.make_custom_shape_params(
        identifier="IK",
        default="Square"
    )


RIG_COMPONENT_CLASS = Component_Spine_IKFK
