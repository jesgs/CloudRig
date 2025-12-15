# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi

from bpy.props import BoolProperty
from bpy.types import PropertyGroup

from ..rig_component_features.bone_info import BoneInfo
from .cloud_fk_chain import Component_Chain_FK


class Component_Spine_Toon(Component_Chain_FK):
    """This spine rig must consist of 4 bones, placed to function as the
    hips, lowerback, ribcage, and upperback. Designed for cartoony humanoids.
    """

    ui_name = "Spine: Cartoon"

    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.root': True,
        'fk_chain.create_curl_control': False,
        'fk_chain.counter_rotate_stretch_bones': 0.0,
        'fk_chain.double_first': False,
    }

    ################################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spine_name = self.params.base.base_name or self.naming.slice_name(self.base_bone_name)[1]

    def fk_chain__make_root_bone(self):
        # Create Torso Master control.
        self.torso_ctr = self.bone_sets['FK Controls'].new(
            name=self.naming.add_prefix(self.spine_name, 'TORSO'),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            custom_shape_name=self.params.spine_toon.shape_torso.shape_name,
            custom_shape_scale=1.5,
        )
        if self.params.spine_toon.world_align:
            self.torso_ctr.flatten()
        self.torso_ctr.custom_shape_wire_width += 1.0
        # Also assign to IK collections.
        self.torso_ctr.collections += self.bone_sets['Toon Spine IK'].collections
        return self.torso_ctr

    def fk_chain__make(self, bones_org: list[BoneInfo]) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(bones_org)
        fk_chain[0].parent = self.root_bone

        # Put FK bones at the center.
        prev = None
        for fk_bone in reversed(fk_chain):
            fk_bone.head = fk_bone.center.copy()
            if prev:
                fk_bone.tail = prev.head
            prev = fk_bone

        return fk_chain

    def fk_chain__attach_org_to_fk(self, bones_org, fk_bones):
        """Parent original bones to FK bones.
        The purpose of original bones in this component is just for any child
        components to follow along in an expected way.
        """
        for org_bone, fk_bone in zip(bones_org, fk_bones):
            org_bone.use_connect = False
            org_bone.parent = fk_bone

    def create_bone_infos(self, context):
        """First function called by the generator.
        You should populate your BoneSets with BoneInfo instances here."""
        super().create_bone_infos(context)

        chest = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.spine_name, 'CHST'),
            source=self.fk_chain[-2],
            tail=self.bones_org[-1].tail,
            parent=self.torso_ctr,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
            use_custom_shape_bone_size=True,
            custom_shape_scale_xyz=(1.2, 2.3, 1.2),
            custom_shape_rotation_euler=(0, pi/2, 0)
        )
        hips = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.spine_name, 'HIP'),
            source=self.bones_org[0],
            head=self.fk_chain[1].head,
            tail=self.bones_org[0].head,
            parent=self.torso_ctr,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
        )
        hips.collections += self.bone_sets['FK Controls'].collections
        hips_lower = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.spine_name, 'HipsLower'),
            source=self.bones_org[0],
            head=self.bones_org[0].tail,
            tail=self.bones_org[0].head,
            parent=hips,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
            custom_shape_wire_width=1.5,
            custom_shape_scale_xyz=(1, 0.5, 1),
            custom_shape_along_length=0.33,
        )
        hips_lower.collections += self.bone_sets['FK Controls'].collections

        # Hack the FK parenting a bit.
        self.fk_chain[0].parent = hips_lower
        self.fk_chain[1].parent = self.torso_ctr
        self.bones_org[0].parent = hips_lower
        self.fk_chain[0].collections = self.bone_sets['Mechanism Bones'].collections

        self.__make_ik_setup(self.fk_chain, chest, hips)

        for fk_bone, str_bone in zip(self.fk_chain, self.main_str_bones[1:]):
            str_bone.parent.constraint_infos[0].subtarget = fk_bone
            str_bone.roll_bone = fk_bone
        if self.params.chain.tip_control:
            self.main_str_bones[-1].parent = self.fk_chain[-1]
            self.main_str_bones[-1].roll_bone = self.fk_chain[-1]
        self.main_str_bones[0].roll = 0
        self.main_str_bones[0].roll_bone = None
        self.main_str_bones[0].roll_type = 'VECTOR'
        self.main_str_bones[0].parent.constraint_infos[0].subtarget = hips_lower
        self.main_str_bones[0].add_constraint('COPY_ROTATION', subtarget=hips_lower, influence=0.5, invert_xyz=[False, False, True])

    ##############################
    # Toon spine functions.

    def __make_ik_setup(
        self,
        fk_chain: list[BoneInfo],
        chest: BoneInfo,
        hips: BoneInfo,
    ):
        ikfk_prop_name = f'{self.spine_name}_ik'
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=ikfk_prop_name,
            panel_name='FK/IK Switch',
            slider_name='Spine',
            custom_prop_settings={
                'default' : 1.0,
            }
        )
        ik_chain = self.__make_ik_chain(fk_chain, chest, hips)

        self.__make_ik_str_chain(fk_chain, ik_chain, hips, ikfk_prop_name)

    def __make_ik_chain(self, fk_chain: list[BoneInfo], chest: BoneInfo, hips: BoneInfo) -> list[BoneInfo]:
        ik_chain = []
        def make_ik_bone(name: str, parent: BoneInfo) -> BoneInfo:
            ik_hlp = self.bone_sets['Toon Spine IK Secondary'].new(
                name=name,
                source=fk_bone,
                parent=parent,
                custom_shape_name=self.params.spine_toon.shape_ik_secondary.shape_name,
                lock_rotation=(True, False, True),
                lock_scale=(True, True, True)
            )
            is_last = len(ik_chain)==len(fk_chain)-1
            def_bone = self.bones_def[len(ik_chain)+(0 if is_last else 1)]
            dsp = self.create_dsp_bone(ik_hlp,
                head=def_bone.tail if is_last else def_bone.center,
                vector=def_bone.vector,
                length=def_bone.length/2
            )
            dsp.add_constraint('COPY_TRANSFORMS',
                head_tail=1.0 if is_last else 0.5,
                subtarget=def_bone,
                space='WORLD'
            )
            ik_chain.append(ik_hlp)
            return ik_hlp

        # Make the IK chain.
        next_parent = hips
        for i, fk_bone in enumerate(fk_chain[1:]):
            ik_hlp = make_ik_bone(fk_bone.name.replace("FK", "IK"), next_parent)
            if i == 0:
                ik_hlp.parent = hips
            elif i < len(fk_chain)-3:
                unit = 1 / (len(fk_chain)-3)
                chest_influence = unit*i
                parent_helper = self.create_parent_bone(ik_hlp, bone_set=self.bone_sets['Mechanism Bones'])
                self.constrain_between_bones(parent_helper, hips, chest, chest_influence)

            next_parent = chest

        # One extra at the end.
        ik_hlp = make_ik_bone(self.naming.increment_name(ik_chain[-1]), next_parent)
        ik_hlp.put(fk_bone.tail)

        # The last two should be hidden.
        for i in (1, 2):
            ik_hlp = ik_chain[-i]
            ik_hlp.collections = self.bone_sets['Toon Spine Mechanism'].collections
        return ik_chain

    def __make_ik_str_chain(self, fk_chain: list[BoneInfo], ik_chain: list[BoneInfo], hips: BoneInfo, ikfk_prop_name: str) -> list[BoneInfo]:
        squash_prop_name = f"squash_{self.spine_name}"
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=squash_prop_name,
            panel_name='IK',
            slider_name=f'{self.spine_name} Squash',
            custom_prop_settings={
                'default' : 0.7,
                'soft_max' : 1.0,
                'max': 2.0
            }
        )

        ik_str_chain: list[BoneInfo] = []
        next_parent = hips
        for i, fk_bone in enumerate(fk_chain):
            ik_str = self.bone_sets['Toon Spine Mechanism'].new(
                name=fk_bone.name.replace("FK", "IK-STR"),
                source=fk_bone,
                head=fk_bone.head,
                tail=ik_chain[i].head,
                parent=next_parent
            )
            str_con = ik_str.add_constraint('STRETCH_TO', subtarget=ik_chain[i], use_bulge_min=False, use_bulge_max=True, bulge_max=2.0)
            str_con.drivers.append({
                'prop': 'bulge',
                'variables': [(self.properties_bone.name, squash_prop_name)],
            })
            next_parent = ik_chain[i]
            copycon = fk_bone.add_constraint('COPY_TRANSFORMS',
                name='Copy Transform (IK)',
                subtarget=ik_str,
                space='WORLD',
            )
            copycon.drivers.append(
                {
                    'prop': 'influence',
                    'variables': [(self.properties_bone.name, ikfk_prop_name)],
                }
            )
            ik_str_chain.append(ik_str)
        return ik_str_chain

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        cls.define_bone_set(
            "Toon Spine IK",
            color_palette="THEME13",
            collections=["IK Controls"],
            wire_width=2.5,
        )
        cls.define_bone_set(
            "Toon Spine IK Secondary",
            color_palette="THEME12",
            collections=["IK Secondary"],
            wire_width=1.5,
        )
        cls.define_bone_set(
            "Toon Spine Mechanism",
            collections=["Mechanism Bones"],
            is_advanced=True
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        super().draw_control_params(layout, context, params)

        cls.draw_prop(context, layout, params.spine_toon, 'world_align')

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        super().draw_appearance_params(layout, context, params)
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_torso")
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_ik")
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_ik_secondary")
        return layout


class Params(PropertyGroup):
    """Defines the parameters to be registered in RNA. Must be exactly `Params`."""
    world_align: BoolProperty(
        name="World-Align Torso",
        description="Flatten the torso to align with the closest world axis",
        default=True,
    )

    shape_ik: Component_Chain_FK.make_custom_shape_params(
        identifier="IK",
        default="Saddle"
    )
    shape_ik_secondary: Component_Chain_FK.make_custom_shape_params(
        identifier="IK Secondary",
        default="Square 2"
    )
    shape_torso: Component_Chain_FK.make_custom_shape_params(
        identifier="Torso",
        default="Torso"
    )

RIG_COMPONENT_CLASS = Component_Spine_Toon
