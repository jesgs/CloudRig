# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import BoolProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo
from .cloud_fk_chain import Component_Chain_FK


class Component_Spine_Squashy(Component_Chain_FK):
    """Spine setup that can squash and not just stretch."""

    ui_name = "Spine: Squashy"
    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.hinge': False,
        'fk_chain.root': True,
    }
    always_use_custom_props = True

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.bone_count > 1:
            self.raise_generation_error(
                "Component must consist of a chain of at least 2 connected bones!"
            )

        self.spine_name = self.params.base.base_name or self.naming.slice_name(self.base_bone_name)[1]
        self.squashy_name = "squashy_spine_" + self.spine_name.lower()
        self.squashy_volume_name = "squashy_spine_volume_" + self.spine_name.lower()

        self.root_torso = None

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        # If we want to parent things to the root bone, we use self.root_torso.
        # However, for spine.double to work, self.root_bone must be the bone
        # returned from create_parent_bone().
        self.root_torso = self.root_bone

        self.__make_squashy_spine()

        if self.params.spine_squashy.double:
            self.root_bone = self.create_parent_bone(
                self.root_torso, self.bone_sets['Spine Parent Controls']
            )

    def fk_chain__make_root_bone(self):
        # Create Torso Master control
        root_bone = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["TORSO"], self.spine_name, [self.side_suffix]),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            custom_shape_name="Torso",
            custom_shape_scale=4,
        )
        return root_bone

    def fk_chain__make(self, org_chain) -> list[BoneInfo]:
        fk_chain = super().fk_chain__make(org_chain)

        # Create master hip control
        self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["HIP"], self.spine_name, [self.side_suffix]),
            source=org_chain[0],
            head=org_chain[0].tail,
            tail=org_chain[0].head,
            custom_shape_name="Saddle",
            custom_shape_scale=2,
            parent=self.root_bone,
        )

        # First STR bone should by owned by the hips.
        self.str_chain[0].parent = self.mstr_hips

        if self.params.spine_squashy.world_align:
            self.root_bone.flatten()
            self.mstr_hips.flatten()

        # Parent the first FK control to ROOT.
        self.bone_sets['FK Controls'][0].parent = self.root_bone

        return fk_chain

    ##############################
    # Squashy Spine functions.

    def __make_squashy_spine(self):
        ### Create master chest control
        chest_org = self.bones_org[-1]
        self.mstr_chest = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.add_prefix(self.spine_name, "CHST"),
            source=chest_org,
            head=chest_org.prev.center,
            custom_shape_name="Saddle",
            custom_shape_translation=Vector(
                (0, chest_org.length + chest_org.prev.length / 2, 0)
            ),
            custom_shape_scale=2,
            parent=self.root_torso,
        )
        self.mstr_chest.custom_shape_scale_xyz *= Vector((0.8, -1.3, 0.8))

        if self.params.spine_squashy.double:
            self.create_parent_bone(
                self.mstr_chest, self.bone_sets['Spine Parent Controls']
            )

        # Create squash helper
        self.squash_helper = self.bone_sets['Spine Mechanism'].new(
            name=f"SQS-{self.spine_name}",
            source=self.bones_org[0],
            head=self.fk_chain[0].head,
            tail=self.mstr_chest.head,
            parent=self.mstr_hips,
        )
        stretch_con = self.squash_helper.add_constraint(
            'STRETCH_TO',
            subtarget=self.mstr_chest,
            use_bulge_min=False,
            use_bulge_max=False,
        )
        # Add driver for volume variation
        stretch_con.drivers.append(
            {
                'prop': 'bulge',
                'expression': 'var*2',
                'variables': [(self.properties_bone.name, self.squashy_volume_name)],
            }
        )

        # Attach FK
        arm_cons_fk = []
        for fk_bone in self.fk_chain[:-1]:
            arm_con_fk = fk_bone.add_constraint(
                'ARMATURE',
                targets=[
                    {'subtarget': fk_bone.parent.name},
                    {'subtarget': self.squash_helper.name},
                ],
            )
            arm_cons_fk.append(arm_con_fk)

        arm_con_last_fk = self.fk_chain[-1].add_constraint(
            'ARMATURE',
            targets=[
                {'subtarget': self.fk_chain[-1].parent.name},
                {'subtarget': self.mstr_chest.name},
            ],
        )

        for arm_con in arm_cons_fk + [arm_con_last_fk]:
            arm_con.drivers.append(
                {
                    'prop': 'targets[0].weight',
                    'expression': '1-var',
                    'variables': [(self.properties_bone.name, self.squashy_name)],
                }
            )
            arm_con.drivers.append(
                {
                    'prop': 'targets[1].weight',
                    'variables': [(self.properties_bone.name, self.squashy_name)],
                }
            )

        squash_toggle_driver = {
            'prop': 'influence',
            'variables': [(self.properties_bone.name, self.squashy_name)],
        }
        influence_driven_constraints = [
            stretch_con
        ]  # con_rot_counter, con_trans_fwd, con_trans_side
        for con in influence_driven_constraints:
            con.drivers.append(squash_toggle_driver.copy())

        # Make the hip twisting affect the belly
        counter_rotate = self.main_str_bones[1].add_constraint(
            'COPY_ROTATION',
            subtarget=self.mstr_hips,
            use_xyz=[False, True, False],
            influence=0.5,
        )
        counter_rotate_driver = squash_toggle_driver.copy()
        counter_rotate_driver['expression'] = 'var*0.5'
        counter_rotate.drivers.append(counter_rotate_driver)

        # Store info for UI
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.squashy_name,
            panel_name="FK/IK Switch",
            row_name=self.limb_name,
            slider_name=self.spine_name,
            custom_prop_settings={
                'default': 1.0,
                'description': "Switch to an IK-like posing mode. Instead of posing the spine from bottom to top, this lets you control the two end points in an intuitive way",
            },
        )

        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.squashy_volume_name,
            panel_name="IK",
            row_name=self.limb_name,
            slider_name=self.spine_name + " Squash & Stretch",
            custom_prop_settings={
                'default': 0.0,
                'description': "Allow the spine to stretch beyond its normal length while in IK mode, for a cartoony effect",
            },
        )

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        """Create parameters for this rig's bone sets."""
        cls.define_bone_set(
            'Spine Main Controls', color_palette='THEME12', collections=['IK Controls'], wire_width=2.5
        )
        cls.define_bone_set(
            'Spine Parent Controls',
            color_palette='THEME09',
            collections=['IK Controls'],
            wire_width=2.5,
        )
        cls.define_bone_set(
            'Spine Mechanism', collections=['Mechanism Bones'], is_advanced=True
        )

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == "spine_parent_controls":
            return params.spine.double

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_control_params(layout, context, params)

        layout.separator()
        cls.draw_control_label(layout, "Spine")
        cls.draw_prop(context, layout, params.spine_squashy, 'double')
        cls.draw_prop(context, layout, params.spine_squashy, 'world_align')


class Params(PropertyGroup):
    world_align: BoolProperty(
        name="World-Align Controls",
        description="Flatten the torso and hips to align with the closest world axis",
        default=True,
    )
    double: BoolProperty(
        name="Duplicate Controls",
        description="Make duplicates of the main spine controls",
        default=False,
    )


RIG_COMPONENT_CLASS = Component_Spine_Squashy
