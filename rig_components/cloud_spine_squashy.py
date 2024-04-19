from typing import List
from bpy.types import PropertyGroup
from ..rig_component_features.bone import BoneInfo

from bpy.props import BoolProperty
from mathutils import Vector
from math import pi

from .cloud_fk_chain import Component_Chain_FK

"""TODO
Re-implement FK-C bones (maybe under a param)
    Their values would probably have to be dependent on the length of the bone.
    Ie., longer bones slide more when rotated.
"""


class Component_Spine_Squashy(Component_Chain_FK):
    """Spine setup that can squash and not just stretch."""

    ui_name = "Spine: Squashy"
    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.shift_to_center': True,
        'fk_chain.double_first': False,
        'fk_chain.hinge': False,
        'fk_chain.display_center': False,
        'fk_chain.root': True,
    }
    always_use_custom_props = True

    def initialize(self):
        """Gather and validate data about the rig."""
        super().initialize()

        if not self.bone_count > 1:
            self.raise_generation_error(
                "Spine rig must consist of a chain of at least 2 connected bones!"
            )

        self.spine_name = self.naming.slice_name(self.base_bone_name)[1]
        self.squashy_name = "squashy_spine_" + self.spine_name.lower()
        self.squashy_volume_name = "squashy_spine_volume_" + self.spine_name.lower()

        self.root_torso = None

    def make_root_bone(self):
        """Overrides cloud_fk_chain."""

        # Create Torso Master control
        limb_root_bone = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["ROOT"], self.spine_name, [self.side_suffix]),
            parent=self.bones_org[0].parent,
            source=self.bones_org[0],
            head=self.bones_org[0].center,
            custom_shape_name="Torso_Master",
        )
        return limb_root_bone

    def make_fk_chain(self, org_chain) -> List[BoneInfo]:
        """Overrides cloud_fk_chain."""
        fk_chain = super().make_fk_chain(org_chain)

        # Create master hip control
        self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.make_name(["HIP"], self.spine_name, [self.side_suffix]),
            source=org_chain[0],
            head=org_chain[0].center,
            custom_shape_name="Hyperbola",
            custom_shape_scale_xyz=Vector((0.8, -0.8, 0.8)),
            parent=self.root_bone,
        )

        if self.params.spine_squashy.world_align:
            self.root_bone.flatten()
            self.mstr_hips.flatten()

        # Parent the first FK control to ROOT.
        self.bone_sets['FK Controls'][0].parent = self.root_bone

        return fk_chain

    def make_fk_bone(self, org_bone) -> BoneInfo:
        """Overrides cloud_fk_chain.
        We offset each FK bone to its center point, and create a child helper at the original position.
        Furthermore, we parent each FK control to the previous FK control's child helper.
        """
        fk_bone = super().make_fk_bone(org_bone)
        fk_bone.head = fk_bone.center.copy()
        fk_child = self.bone_sets['FK Helpers'].new(
            name=fk_bone.name.replace("FK-", "FKO-"), source=org_bone, parent=fk_bone
        )
        fk_bone.fk_child = fk_child

        if fk_bone.prev:
            fk_bone.parent = fk_bone.prev.fk_child

        return fk_bone

    def attach_org_to_fk(self, org_bones, fk_bones):
        """Overrides cloud_fk_chain.
        We want to attach the ORG bones to the fk_child helper rather than the fk_bone.
        """
        for org_bone, fk_bone in zip(org_bones, fk_bones):
            org_bone.add_constraint(
                'COPY_TRANSFORMS',
                space='WORLD',
                subtarget=fk_bone.fk_child.name,
                name="Copy Transforms FK Child",
            )

        # We also need the STR bones to be parented one step lower in the ORG chain.
        str_bones = self.main_str_bones
        str_bones[0].parent = self.mstr_hips
        for org_bone, str_bone in zip(org_bones, str_bones[1:]):
            str_bone.parent = org_bone

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        # If we want to parent things to the root bone, we use self.root_torso.
        # However, for spine.double to work, self.root_bone must be the bone
        # returned from create_parent_bone().
        self.root_torso = self.root_bone

        self.make_squashy_spine()

        if self.params.spine_squashy.double:
            self.root_bone = self.create_parent_bone(
                self.root_torso, self.bone_sets['Spine Parent Controls']
            )

    def make_squashy_spine(self):
        ### Create master chest control
        chest_org = self.bones_org[-1]
        self.mstr_chest = self.bone_sets['Spine Main Controls'].new(
            name=self.naming.add_prefix(self.spine_name, "CHST"),
            source=chest_org,
            custom_shape_name="Hyperbola",
            custom_shape_scale_xyz=Vector((0.8, -1.3, 0.8)),
            custom_shape_translation=Vector((0, chest_org.length, 0)),
            parent=self.root_torso,
        )

        if self.params.spine_squashy.double:
            self.create_parent_bone(
                self.mstr_chest, self.bone_sets['Spine Parent Controls']
            )

        # Create squash helper
        self.squash_helper = self.bone_sets['Spine Mechanism'].new(
            name=f"SQS-{self.spine_name}",
            source=self.bones_org[0],
            head=self.mstr_hips.head.copy(),
            tail=self.mstr_chest.head.copy(),
            parent=self.root_torso,
        )
        copy_loc = self.squash_helper.add_constraint(
            'COPY_LOCATION', subtarget=self.mstr_hips, space='WORLD'
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
                'expression': '1+var',
                'variables': [(self.properties_bone.name, self.squashy_volume_name)],
            }
        )

        squash_constraints = [copy_loc, stretch_con]

        # Attach FK
        self.fk_chain[0].parent = self.squash_helper
        arm_con1 = self.fk_chain[-1].add_constraint(
            'ARMATURE',
            targets=[
                {'subtarget': self.fk_chain[-1].parent.name},
                {'subtarget': self.mstr_chest.name},
            ],
        )

        # Create a parent helper for the 2nd to last STR bone for counter-rotation.
        str_bone = self.main_str_bones[-2]
        copy_rot_helper = self.create_parent_bone(
            str_bone, bone_set=self.bone_sets['Spine Mechanism']
        )
        con_rot_counter = copy_rot_helper.add_constraint(
            'COPY_ROTATION',
            subtarget=self.mstr_chest,
            use_xyz=[True, False, True],
            invert_xyz=[True, False, True],
            influence=0.5,
        )

        parent_helper = self.create_parent_bone(
            copy_rot_helper, bone_set=self.bone_sets['Spine Mechanism']
        )
        # Parent 2nd to last STR to Torso when Squash is enabled
        arm_con2 = parent_helper.add_constraint(
            'ARMATURE',
            targets=[
                {'subtarget': self.bones_org[-2].name},
                {'subtarget': self.mstr_chest.name},
            ],
        )

        for arm_con in [arm_con1, arm_con2]:
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

        con_trans_fwd = str_bone.add_constraint(
            'TRANSFORM',
            name="Transform (Bend Fwd)",
            subtarget=self.mstr_chest,
            map_from='ROTATION',
            from_rotation_mode='SWING_TWIST_Y',
            from_min_x_rot=-pi / 2,
            from_max_x_rot=pi / 2,
            map_to='LOCATION',
            map_to_z_from='X',
            to_min_z=-0.04,
            to_max_z=0.04,
        )
        con_trans_side = str_bone.add_constraint(
            'TRANSFORM',
            name="Transform (Bend Sideways)",
            subtarget=self.mstr_chest,
            map_from='ROTATION',
            from_rotation_mode='SWING_TWIST_Y',
            from_min_z_rot=-pi / 2,
            from_max_z_rot=pi / 2,
            map_to='LOCATION',
            map_to_x_from='Z',
            to_min_x=0.04,
            to_max_x=-0.04,
        )
        squash_constraints.extend([con_rot_counter, con_trans_fwd, con_trans_side])

        squash_toggle_driver = {
            'prop': 'influence',
            'variables': [(self.properties_bone.name, self.squashy_name)],
        }
        for con in squash_constraints:
            con.drivers.append(squash_toggle_driver.copy())
        con_rot_counter.drivers[0]['expression'] = 'var/2'

        # Make the hip twisting affect the belly
        self.main_str_bones[1].add_constraint(
            'COPY_ROTATION',
            subtarget=self.mstr_hips,
            use_xyz=[False, True, False],
            influence=0.5,
        )

        # Store info for UI
        info = {'prop_bone': self.properties_bone, 'prop_id': self.squashy_name}
        self.add_ui_data(
            "FK/IK Switch",
            self.limb_name,
            info,
            entry_name=self.spine_name,
            default=1.0,
        )
        info = {'prop_bone': self.properties_bone, 'prop_id': self.squashy_volume_name}
        self.add_ui_data(
            "IK",
            self.limb_name,
            info,
            entry_name=self.spine_name + " Volume",
            default=0.0,
        )

    def parent_str_to_fk(self, fk_chain, org_chain, str_chain):
        """Overrides cloud_fk_chain."""
        super().parent_str_to_fk(fk_chain, org_chain, str_chain)
        # First STR bone should by owned by the hips.
        str_chain[0].parent = self.mstr_hips

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        """Create parameters for this rig's bone sets."""
        cls.define_bone_set(
            'Spine Main Controls', color_palette='THEME03', collections=['IK Controls']
        )
        cls.define_bone_set(
            'Spine Parent Controls',
            color_palette='THEME09',
            collections=['IK Controls'],
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
        default=True,
    )


RIG_COMPONENT_CLASS = Component_Spine_Squashy
