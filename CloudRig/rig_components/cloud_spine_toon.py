# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi

from bpy.app.translations import pgettext_n as n_
from bpy.props import BoolProperty, FloatProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
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
        'fk_chain.display_center': False,
    }

    always_use_custom_props = True

    ################################
    # Inherited functions.

    def fk_chain__make_root_bone(self):
        # Create Torso Master control.
        self.torso_ctr = self.bone_sets['FK Controls'].new(
            name=self.naming.add_prefix(self.base_name, 'TORSO'),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            length=self.bones_org[0].length+self.bones_org[1].length/2,
            custom_shape_name=self.params.spine_toon.shape_torso.shape_name,
        )
        spine_toon_params = self.params.spine_toon
        if spine_toon_params.world_align:
            self.torso_ctr.world_align()
            self.torso_ctr.custom_shape_rotation_euler.x = pi/2
        elif spine_toon_params.flatten_controls:
            self.torso_ctr.flatten()
        self.torso_ctr.custom_shape_wire_width += 1.0
        # Also assign to IK collections.
        self.torso_ctr.collections += self.bone_sets['Toon Spine IK'].collections
        return self.torso_ctr

    def fk_chain__make(self, org_chain: list[BoneInfo]) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(org_chain)
        fk_chain[0].parent = self.root_bone

        # Put FK bones at the center.
        prev = None
        for fk_bone in reversed(fk_chain):
            fk_bone.head = fk_bone.center.copy()
            if prev:
                fk_bone.tail = prev.head
            prev = fk_bone
            fk_bone.custom_shape_scale_xyz *= fk_bone.source.length / fk_bone.length

        return fk_chain

    @no_overlay
    def fk_chain__attach_org_to_fk(self, org_bones, fk_bones):
        """Parent original bones to FK bones.
        The purpose of original bones in this component is just for any child
        components to follow along in an expected way.
        """
        for org_bone, fk_bone in zip(org_bones, fk_bones):
            org_bone.use_connect = False
            org_bone.parent = fk_bone

    def create_bone_infos(self, context):
        """First function called by the generator.
        You should populate your BoneSets with BoneInfo instances here."""
        super().create_bone_infos(context)

        chest = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.base_name, 'CHST'),
            source=self.fk_chain[-2],
            tail=self.bones_org[-1].tail,
            parent=self.torso_ctr,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
            use_custom_shape_bone_size=False,
            custom_shape_rotation_euler=Vector((0, pi/2, 0)),
        )
        chest.custom_shape_scale_xyz = self.fk_chain[-1].custom_shape_scale_xyz.zyx * self.fk_chain[-1].length
        chest.custom_shape_scale_xyz.y *= chest.length / self.fk_chain[-1].length
        chest.custom_shape_translation += self.bones_org[-1].custom_shape_translation

        hips = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.base_name, 'HIP'),
            source=self.bones_org[0],
            head=self.fk_chain[1].head,
            tail=self.bones_org[0].head,
            parent=self.torso_ctr,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
            use_custom_shape_bone_size=False,
            custom_shape_rotation_euler=Vector((0, pi/2, 0)),
        )
        hips.roll_align_other(self.bones_org[0], axis='-Z')
        hips_fwd = self.bone_sets['Mechanism Bones'].new(
            name=self.naming.add_prefix(self.base_name, "HIP-FWD"),
            source=self.bones_org[0],
            tail=self.fk_chain[1].head,
            parent=hips,
        )
        hips_fwd.roll_align_other(chest)
        hips.custom_shape_scale_xyz = self.bones_org[1].length * self.bones_org[1].custom_shape_scale_xyz.zyx
        hips.custom_shape_translation = self.bones_org[1].custom_shape_translation * Vector((-1, -1, 1))
        hips.collections += self.bone_sets['FK Controls'].collections
        hips_lower = self.bone_sets['Toon Spine IK'].new(
            name=self.naming.add_prefix(self.base_name, 'HipsLower'),
            source=self.bones_org[0],
            head=self.bones_org[0].tail,
            tail=self.bones_org[0].head,
            parent=hips,
            custom_shape_name=self.params.spine_toon.shape_ik.shape_name,
            custom_shape_wire_width=hips.custom_shape_wire_width/2,
            use_custom_shape_bone_size=False,
            custom_shape_rotation_euler=Vector((0, pi/2, 0)),
        )
        hips_lower.custom_shape_scale_xyz = Vector.lerp(hips.custom_shape_scale_xyz, self.bones_org[0].length*self.bones_org[0].custom_shape_scale_xyz.zyx, 0.5)
        hips_lower.custom_shape_scale_xyz.y *= 0.5
        hips_lower.custom_shape_translation = hips.custom_shape_translation
        hips_lower.roll_align_other(self.bones_org[0], axis='-Z')
        hips_lower.collections += self.bone_sets['FK Controls'].collections

        # Enable anarchy variable access...
        self.hips = hips
        self.hips_lower = hips_lower

        # Hack the FK parenting a bit.
        self.fk_chain[0].parent = hips_lower
        self.fk_chain[1].parent = self.torso_ctr
        self.bones_org[0].parent = hips_lower
        self.fk_chain[0].collections = self.bone_sets['Mechanism Bones'].collections

        self.__make_ik_setup(self.fk_chain, chest, hips_fwd)

        for fk_bone, str_bone in zip(self.fk_chain, self.main_str_bones[1:]):
            str_bone.parent.constraint_infos[0].subtarget = fk_bone
            str_bone.roll_align_other(fk_bone)
        if self.params.chain.tip_control:
            self.main_str_bones[-1].parent = self.fk_chain[-1]
            self.main_str_bones[-1].roll_align_other(self.fk_chain[-1])
        self.main_str_bones[0].parent.constraint_infos[0].subtarget = hips_lower
        self.main_str_bones[0].add_constraint('COPY_ROTATION', subtarget=hips_lower, influence=0.5, invert_xyz=[False, False, True])

    ##############################
    # Toon spine functions.

    def __make_ik_setup(
        self,
        fk_chain: list[BoneInfo],
        chest: BoneInfo,
        hips_fwd: BoneInfo,
    ):
        ikfk_prop_name = f'{self.base_name}_ik'
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=ikfk_prop_name,
            panel_name=n_("FK/IK Switch"),
            slider_name='Spine',
            custom_prop_settings={
                'default' : self.params.spine_toon.default_fkik,
            },
            context_bones=fk_chain + [chest, self.torso_ctr, self.hips, self.hips_lower],
        )
        ik_chain = self.__make_ik_chain(fk_chain, chest, hips_fwd)

        self.__make_ik_str_chain(fk_chain, ik_chain, hips_fwd, chest, ikfk_prop_name)

    @no_overlay
    def __make_ik_chain(self, fk_chain: list[BoneInfo], chest: BoneInfo, hips: BoneInfo) -> list[BoneInfo]:
        ik_chain = []
        def make_ik_bone(bone_name: str, parent: BoneInfo) -> BoneInfo:
            ik_hlp = self.bone_sets['Toon Spine IK Secondary'].new(
                name=bone_name,
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
        next_parent = hips if len(self.fk_chain) > 3 else chest
        for i, fk_bone in enumerate(fk_chain[1:]):
            ik_name = self.naming.add_prefix(fk_bone.source, "IK")
            ik_hlp = make_ik_bone(ik_name, next_parent)
            if 0 < i < len(fk_chain)-3:
                unit = 1 / (len(fk_chain)-3)
                chest_influence = unit*i
                parent_helper = self.create_parent_bone(ik_hlp, bone_set=self.bone_sets['Mechanism Bones'])
                parent_helper.put(Vector.lerp(hips.tail, chest.head, chest_influence))
                parent_helper.vector = (chest.head-hips.tail).normalized() * parent_helper.vector.length
                parent_helper.roll_align_other(hips)
                copy_first, _copy_last, _dt_con = self.constrain_between_bones(parent_helper, hips, chest, chest_influence)
                copy_first.head_tail = 1.0

            next_parent = chest

        # One extra at the end.
        ik_hlp = make_ik_bone(self.naming.increment_name(ik_chain[-1]), next_parent)
        ik_hlp.put(fk_bone.tail)

        # The last two should be hidden.
        for i in (1, 2):
            ik_hlp = ik_chain[-i]
            ik_hlp.collections = self.bone_sets['Toon Spine Mechanism'].collections
        return ik_chain

    @no_overlay
    def __make_ik_str_chain(
        self,
        fk_chain: list[BoneInfo],
        ik_chain: list[BoneInfo],
        hips_fwd: BoneInfo,
        chest: BoneInfo,
        ikfk_prop_name: str
    ) -> list[BoneInfo]:
        squash_prop_name = f"squash_{self.base_name}"
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=squash_prop_name,
            panel_name=n_("IK"),
            slider_name=f'{self.base_name} Squash',
            custom_prop_settings={
                'default' : self.params.spine_toon.default_stretch,
                'soft_max' : 1.0,
                'max': 2.0
            },
            context_bones=ik_chain + [chest, self.torso_ctr, self.hips, self.hips_lower],
        )

        ik_str_chain: list[BoneInfo] = []
        next_parent = hips_fwd
        for i, fk_bone in enumerate(fk_chain):
            ik_str = self.bone_sets['Toon Spine Mechanism'].new(
                name=self.naming.add_prefix(fk_bone.source, "IK-STR"),
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
            n_("Toon Spine IK"),
            color_palette="THEME13",
            collections=["IK Controls"],
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Toon Spine IK Secondary"),
            color_palette="THEME12",
            collections=["IK Secondary"],
            wire_width=1.0,
        )
        cls.define_bone_set(
            n_("Toon Spine Mechanism"),
            collections=["Mechanism Bones"],
            is_advanced=True
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        cls.draw_prop(context, layout, params.spine_toon, "world_align", enabled=(not params.spine_toon.flatten_controls))
        cls.draw_prop(context, layout, params.spine_toon, "flatten_controls", enabled=(not params.spine_toon.world_align))

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_torso")
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_ik")
        cls.draw_prop_custom_shape(context, layout, params.spine_toon, "shape_ik_secondary")
        return layout

    @classmethod
    def draw_custom_prop_params(cls, layout, context, component):
        super().draw_custom_prop_params(layout, context, component)
        layout.separator()
        cls.draw_prop(context, layout, component.params.spine_toon, 'default_fkik', slider=True)
        cls.draw_prop(context, layout, component.params.spine_toon, 'default_stretch', slider=True)


class Params(PropertyGroup):
    """Defines the parameters to be registered in RNA. Must be exactly `Params`."""
    world_align: BoolProperty(
        name="World-Align Torso",
        description="Align the torso control with the world axes",
        default=True,
    )
    flatten_controls: BoolProperty(
        name="Flatten Controls (Deprecated)",
        description="Align torso and hip controls with the closest world axis. This option is deprecated and will be removed in Blender 6.0 in favor of 'World Align Controls'.",
        default=False,
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

    default_fkik: FloatProperty(
        name="Default FK/IK",
        min=0, max=1, default=1,
    )
    default_stretch: FloatProperty(
        name="Default IK Squash",
        min=0, max=1, default=0.7,
    )

RIG_COMPONENT_CLASS = Component_Spine_Toon
