# SPDX-License-Identifier: GPL-3.0-or-later

from math import radians

from bpy.props import BoolProperty
from bpy.types import Action, ActionSlot, PropertyGroup
from mathutils import Vector

from ..bs_utils.ui import label_split
from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.rig import (
    calculate_ik_pole_vector,
    is_ideal_ik_chain,
    points_define_plane,
)
from .cloud_fk_chain import Component_Chain_FK


class Component_Chain_IKFK(Component_Chain_FK):
    """IK chain with stretchy IK, IK/FK snapping, squash and stretch controls, and optional IK pole control."""

    ui_name = "Chain: IK"
    parent_switch_behaviour = "The active parent will own the IK and POLE controls."
    parent_switch_overwrites_root_parent = False
    always_use_custom_props = True

    forced_params = {
        "fk_chain.root": True,
    }

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # UI Strings and Custom Property names
        self.ikfk_name = "ik_" + self.limb_name_props
        self.ik_stretch_name = "ik_stretch_" + self.limb_name_props

        self.pole_side = 1
        self.ik_pole_offset = 3  # Scalar on distance from the body. Could become a parameter but it's unimportant.
        self.pole_ctrl = None

        # Will be passed to the IK constraint's chain_count.
        # Elements of the rig can use this to avoid having to make assumptions about correlations
        # between the length of the ORG chain vs how long the IK chain is.
        self.chain_count = self.bone_count - 1
        if self.params.ik_chain.at_tip:
            self.chain_count += 1

        self.ik_controls = []  # Used for creating Gizmo Interaction Data.

    @no_overlay
    def base__apply_parent_switching(
        self,
        *,
        child_bone=None,
        prop_bone=None,
        prop_name="",
        panel_name="IK",
        row_name="",
        label_name="Parent Switching",
        entry_name="",
    ):
        ik_parents_prop_name = "ik_parents_" + self.limb_name_props
        super().base__apply_parent_switching(
            child_bone=child_bone or self.ik_mstr,
            prop_bone=prop_bone or self.properties_bone,
            prop_name=prop_name or ik_parents_prop_name,
            panel_name=panel_name,
            row_name=row_name or self.base_name,
            label_name=label_name,
            entry_name=entry_name or self.limb_ui_name,
        )

        if self.params.ik_chain.use_pole:
            self.ik_chain__make_pole_parent_switch(self.pole_ctrl, self.ik_mstr)

    @no_overlay
    def rig_ui__add_bone_property(self, operator="", op_kwargs={}, **kwargs):
        # TODO: This should be restructured, we shouldn't be overriding this function.

        if self.pole_ctrl and operator == "pose.cloudrig_switch_parent_bake":
            # Hacky fix to issue #188. base__apply_parent_switching() is designed for ONE child
            # bone, but in this case we must snap the IK master control PLUS the IK pole control.
            op_kwargs["bone_names"].append(self.pole_ctrl.name)

        super().rig_ui__add_bone_property(
            operator=operator, op_kwargs=op_kwargs, **kwargs
        )

    @no_overlay
    def gizmos__add_interactions(self):
        if "operator" not in self.ui_data:
            return
        op_kwargs = self.ui_data.copy()
        op_name = op_kwargs.pop("operator")
        op_kwargs["prop_value"] = 0
        op_kwargs["select_bones"] = False
        fk_names = [fk.name for fk in self.bone_sets["FK Controls"]]
        op_kwargs["bones"] = fk_names
        # When FK is interacted, switch to FK and snap IK to FK.
        self.gizmos__add_interaction(
            bone_names=fk_names, operator=op_name, op_kwargs=op_kwargs
        )

        # When IK is interacted, switch to IK and snap FK to IK.
        op_kwargs = op_kwargs.copy()
        op_kwargs["prop_value"] = 1
        ik_names = [ik.name for ik in self.ik_controls]
        op_kwargs["bones"] = ik_names
        self.gizmos__add_interaction(
            bone_names=ik_names, operator=op_name, op_kwargs=op_kwargs
        )

    @no_overlay
    def fk_chain__add_test_animation(
        self, action: Action, slot: ActionSlot, start_frame=1, flip_xyz=[False, False, False]
    ) -> int:
        """Add a keyframe to the IK/FK switch property in the test animation."""
        last_frame = super().fk_chain__add_test_animation(action, slot, start_frame, flip_xyz)
        self.disable_property_until_frame(action, slot, last_frame, self.ikfk_name)
        return last_frame

    def create_bone_infos(self, context):
        if len(self.bones_org) < self.required_chain_length:
            self.raise_generation_error(
                f"Must be a chain of at least {self.required_chain_length} connected bones!"
            )

        self.ik_chain__prevent_straight_chain()

        super().create_bone_infos(context)

        if not is_ideal_ik_chain(self.bones_org):
            self.add_log(
                "IK affects rest pose",
                description="For perfect IK Pole and IK/FK snapping behaviour, the IK chain should be perfectly flat along a plane, and its bone rolls should align towards the pole vector. Simply use the button below.",
                operator="armature.flatten_ik_chain",
                op_kwargs={
                    "remove_active_log": True,
                    "start_bone": self.metarig_base_pbone.name,
                    "limit_count": self.required_chain_length
                },
            )

        self.last_org = self.bones_org[-1]

        if self.params.ik_chain.at_tip:
            # TODO: This feels very criminal, do we really need it?
            self.bones_org.new(
                name="TIP-" + self.last_org.name,
                source=self.last_org,
                head=self.last_org.tail.copy(),
                vector=self.last_org.vector,
            )
        self.ik_chain__make_ik_setup()

        if self.params.ik_chain.world_aligned:
            self.ik_chain__world_align_fk()

        # Add IK/FK Snapping to the UI.
        self.ui_data = self.ik_chain__get_ik_switch_ui_data(
            self.bone_sets["FK Controls"], self.ik_chain, self.ik_mstr, self.pole_ctrl
        )
        self.rig_ui__add_bone_property(**self.ui_data)

        self.__attach_org_to_ik()

    ##############################
    # IK Chain functions.

    def ik_chain__prevent_straight_chain(self, invert_offset=False):
        """An IK chain is not allowed to be perfectly straight.
        Forcing a successful generation would result in an IK constraint which simply does nothing.
        Instead of doing that, and instead of throwing a hard error, let's throw a warning, and offset
        the elbow bone arbitrarily to prevent dysfunction.
        """

        points = (self.bones_org[0].head, self.bones_org[0].tail, self.bones_org[1].tail)
        eps = self.bones_org[0].length * 0.01
        if points_define_plane(*points, eps=eps):
            return

        y_offset = eps
        if invert_offset:
            y_offset *= -1
        self.bones_org[0].tail.y += y_offset
        self.bones_org[1].head.y += y_offset
        self.add_log(
            "Ambiguous IK Pole Direction",
            description=(
                "This IK chain is a perfectly straight line.\n"
                "This would normally prevent the IK constraint from choosing a direction to bend in.\n"
                "To avoid this, the elbow joint was slightly offset in an arbitrarily chosen direction.\n"
                "It would be better if you introduced a kink into the chain yourself."
            ),
            operator='object.cloudrig_tweak_bone_rest_pose',
            op_kwargs={
                'bone_name': self.bones_org[0].name,
                'selection': 'TAIL',
            },
        )


    def ik_chain__make_ik_setup(self):
        # Create IK Master control
        self.ik_mstr = self.ik_chain__make_master_ctr(
            self.bone_sets["IK Controls"],
            self.bones_org[self.chain_count],
        )

        self.__store_ik_info()
        # Create Pole control
        self.pole_ctrl = None
        if self.params.ik_chain.use_pole:
            self.pole_ctrl = self.__make_pole_control()

        # Create IK Chain
        self.ik_chain = self.__make_ik_chain(self.bones_org, self.ik_mstr, self.pole_ctrl)

        if self.pole_ctrl:
            # Create a display helper that aims the pole target at the IK chain
            dsp_bone = self.create_dsp_bone(self.pole_ctrl)
            dsp_bone.add_constraint(
                "DAMPED_TRACK",
                subtarget=self.ik_chain[1].name,
                track_axis="TRACK_NEGATIVE_Y",
            )

        # Set up IK Stretch
        self.stretch_bone = self.__make_ik_stretch()

        if self.params.ik_chain.use_pole:
            self.ik_chain__make_pole_follow_switch(
                self.pole_ctrl, self.ik_mstr, self.stretch_bone
            )

    def ik_chain__make_master_ctr(self, bone_set, source_bone, bone_name="", shape_name=""):
        if bone_name == "":
            bone_name = self.naming.add_prefix(source_bone, "IK")
        if not shape_name:
            shape_name = self.params.ik_chain.shape_ik_master.shape_name

        ik_master = bone_set.new(
            name=bone_name,
            source=source_bone,
            custom_shape_name=shape_name,
            parent=None,
        )

        if not self.generator_params.ensure_root:
            # If there's no rig root bone, parent the IK master to the component's root.
            # Although ideally, components with IK chains in them should really have a root bone.
            ik_master.parent = self.bones_org[0].parent

        self.ik_controls.append(ik_master)

        return ik_master

    def __store_ik_info(self):
        """Calculate pole angle, pole control direction and distance."""
        meta_first = self.bones_org[0]
        meta_second = self.bones_org[1]

        pole_angle_deg, pole_vector, pole_location = calculate_ik_pole_vector(
            meta_first, meta_second
        )
        self.pole_angle_deg = pole_angle_deg
        self.pole_vector = pole_vector

        self.pole_location = pole_location

    def __make_pole_control(self):
        # Create IK Pole Control
        pole_ctrl = self.pole_ctrl = self.bone_sets["IK Controls"].new(
            name=self.make_name(["IK", "POLE"], self.base_name),
            bbone_width=0.1,
            head=self.pole_location,
            tail=self.pole_location + self.pole_vector.normalized() * self.chain_length * 0.2,
            custom_shape_name=self.params.ik_chain.shape_pole.shape_name,
            inherit_scale="AVERAGE",
            display_type='OCTAHEDRAL',
            use_custom_shape_bone_size=True,
        )
        pole_ctrl.roll_align_vector(self.bones_org[0].head)
        self.ik_controls.append(pole_ctrl)
        self.lock_transforms(pole_ctrl, loc=False)

        pole_line = self.bone_sets["IK Controls"].new(
            name=self.naming.make_name(["LINE"], self.base_name, self.suffixes),
            source=pole_ctrl,
            tail=self.bones_org[0].tail.copy(),
            parent=pole_ctrl,
            hide_select=True,
            custom_shape_name="Line",
            display_type='STICK',
            use_custom_shape_bone_size=True,
        )
        pole_line.add_constraint(
            "STRETCH_TO", subtarget=self.bones_org[0].name, head_tail=1
        )
        # Add a driver to the Line's hide property so it's hidden exactly when the pole target is hidden.
        pole_line.drivers.append(
            {
                "prop": "hide",
                "variables": [
                    {
                        "type": "SINGLE_PROP",
                        "targets": [
                            {"data_path": f'pose.bones["{pole_ctrl.name}"].hide'}
                        ],
                    }
                ],
            }
        )

        return pole_ctrl

    def __make_ik_chain(self, org_chain, ik_mstr, pole_target=None) -> list[BoneInfo]:
        """Based on a chain of ORG bones, create an IK chain, optionally with a pole target."""
        ik_chain = []
        for i, org_bone in enumerate(org_chain):
            bone_set = self.bone_sets["IK Mechanism"]
            if i == 0:
                # We want to expose the first IK bone because it needs to be selectable and keyable for snapping purposes.
                bone_set = self.bone_sets["IK Controls Secondary"]
            ik_bone = bone_set.new(
                name=self.naming.add_prefix(org_bone, "IK-M"),
                source=org_bone,
            )
            ik_chain.append(ik_bone)

            if i == 0:
                ik_bone.parent = self.root_bone
                ik_bone.custom_shape_name = self.params.ik_chain.shape_ik_first.shape_name
                ik_bone.custom_shape_translation = Vector((0, 0, 0))
                ik_bone.custom_shape_scale_xyz = Vector((0.66, 1, org_bone.custom_shape_scale*0.66))
                ik_bone.custom_shape_rotation_euler = Vector((0, 0, 0))
                self.ik_controls.append(ik_bone)
            else:
                ik_bone.parent = ik_chain[-2]

            if i == self.chain_count:
                # Add the IK constraint to the previous bone, targetting this one.
                ik_chain[-2].add_constraint(
                    "IK",
                    pole_target=self.target_rig if pole_target else None,
                    pole_subtarget=pole_target.name if pole_target else "",
                    pole_angle=radians(self.pole_angle_deg),
                    subtarget=ik_bone.name,
                    chain_count=i,
                )
                # Parent this one to the IK master.
                ik_bone.parent = ik_mstr
                if self.params.ik_chain.world_aligned:
                    ik_mstr.flatten()

        return ik_chain

    @no_overlay
    def __make_ik_stretch(self):
        """Primary function that starts the entire Stretchy IK set-up.
        Some extra stuff is in __attach_org_to_ik. # TODO: Put these things under a parameter, so IK Stretch can be disabled when not needed.
        """
        ik_org_bone = self.bones_org[self.chain_count]
        stretch_bone = self.bone_sets["IK Mechanism"].new(
            name=self.naming.add_prefix(self.bones_org[0], "IK-STR"),
            source=self.bones_org[0],
            tail=self.ik_mstr.head.copy(),
            parent=self.root_bone,
        )
        stretch_bone.scale_width(0.4)

        # Bone responsible for giving stretch_bone the target position to stretch to.
        self.stretch_target_bone = self.bone_sets["IK Mechanism"].new(
            name=self.naming.add_prefix(ik_org_bone, "IK-STR-TGT"),
            source=ik_org_bone,
            parent=self.ik_mstr,
        )

        chain_length = 0
        for ikb in self.ik_chain[: self.chain_count]:
            chain_length += ikb.length

        length_factor = chain_length / stretch_bone.length
        stretch_bone.add_constraint(
            "STRETCH_TO", subtarget=self.stretch_target_bone.name
        )
        limit_scale = stretch_bone.add_constraint(
            "LIMIT_SCALE", use_max_y=True, max_y=length_factor, influence=0
        )

        limit_scale.drivers.append(
            {
                "prop": "influence",
                "expression": "1-stretch",
                "variables": {
                    "stretch": {
                        "type": "SINGLE_PROP",
                        "targets": [
                            {
                                "id": self.target_rig,
                                "id_type": "OBJECT",
                                "data_path": f'pose.bones["{self.properties_bone.name}"]["{self.ik_stretch_name}"]',
                            }
                        ],
                    }
                },
            }
        )

        # Store info for UI
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=self.ik_stretch_name,
            panel_name="IK",
            label_name="IK Stretch",
            row_name=self.base_name,
            slider_name=self.limb_ui_name,
            custom_prop_settings={
                "default": 1.0,
                "description": "Allow the limb to stretch beyond its normal maximum reach for a cartoony effect",
            },
        )

        # Last IK bone should copy location of the tail of the stretchy bone.
        self.ik_tgt_bone = self.ik_chain[self.chain_count]
        self.ik_tgt_bone.add_constraint(
            "COPY_LOCATION", space="WORLD", subtarget=stretch_bone.name, head_tail=1
        )

        # Create Helpers for main STR bones so they will stick to the stretchy bone during IK stretching.
        self.__make_ik_stretch_helpers(stretch_bone, chain_length)

        return stretch_bone

    @no_overlay
    def __make_ik_stretch_helpers(self, stretch_bone, chain_length):
        """Set up transformation constraint to mid-limb STR bone that ensures
        that it stays in between the root of the limb and the IK master
        control during IK stretching.
        """

        # This driver will cause the Copy Location constraint to activate exactly
        # when the stretch bone's current length exceeds its original length.
        ik_stretch_engaged_driver = {
            "prop": "influence",
            "expression": f"ik * stretch * (distance > {chain_length} * scale)",
            "variables": {
                "stretch": {
                    "type": "SINGLE_PROP",
                    "targets": [
                        {
                            "data_path": f'pose.bones["{self.properties_bone.name}"]["{self.ik_stretch_name}"]'
                        }
                    ],
                },
                "ik": {
                    "type": "SINGLE_PROP",
                    "targets": [
                        {
                            "data_path": f'pose.bones["{self.properties_bone.name}"]["{self.ikfk_name}"]'
                        }
                    ],
                },
                "distance": {
                    "type": "LOC_DIFF",
                    "targets": [
                        {
                            "bone_target": self.ik_tgt_bone.name,
                            "transform_space": "WORLD_SPACE",
                        },
                        {
                            "bone_target": self.ik_chain[0].name,
                            "transform_space": "WORLD_SPACE",
                        },
                    ],
                },
                "scale": {
                    "type": "TRANSFORMS",
                    "targets": [
                        {
                            "bone_target": self.ik_chain[0].name,
                            "transform_type": "SCALE_Y",
                            "transform_space": "WORLD_SPACE",
                        }
                    ],
                },
            },
        }

        cum_length = self.bones_org[0].length
        for i, main_str_bone in enumerate(self.main_str_bones):
            # How far this bone is along the total chain length
            head_tail = cum_length / chain_length
            if head_tail > 1.0:
                break
            if i == 0:
                continue
            if i == len(self.main_str_bones) - 1 and not self.params.ik_chain.at_tip:
                continue
            # Create STR-S helper

            con_name = "CopyLoc_IK_Stretch"
            copyloc = main_str_bone.parent.add_constraint(
                "COPY_LOCATION",
                space="WORLD",
                subtarget=stretch_bone.name,
                name=con_name,
                head_tail=head_tail,
            )
            org_bone = self.bones_org[i]
            cum_length += org_bone.length

            copyloc.drivers.append(dict(ik_stretch_engaged_driver))

    @no_overlay
    def ik_chain__make_pole_follow_switch(self, ik_pole, ik_mstr, stretch_bone, default=0.0):
        if (
            self.params.parenting.parent_switching
            and len(self.parent_ui_names) > 0
        ):
            _parent_ui_names, parent_bone_names = self.sanitize_parent_list(
                self.params.parenting.parent_slots
            )
            first_parent = parent_bone_names[0]
        elif self.generator_params.ensure_root:
            first_parent = self.generator_params.ensure_root
        else:
            first_parent = self.bones_org[0].parent

        pole_parent_helper = self.create_parent_bone(ik_pole, bone_set=self.bones_mch)
        pole_parent_helper.custom_shape = None

        ik_pole_follow_name = "ik_pole_follow_" + self.limb_name_props
        self.create_driven_armature_constraint(
            pole_parent_helper,
            target_bones=[first_parent, ik_mstr],
            prop_bone=self.properties_bone,
            prop_name=ik_pole_follow_name,
            preserve_volume=True,
        )

        # Let Stretch Helper copy rotation of IK master, for nice controlling of the IK Pole.
        stretch_bone.add_constraint("COPY_ROTATION", index=0, subtarget=ik_mstr)

        # Add IK Pole Follows option to the UI.
        self.rig_ui__add_bone_property(
            prop_bone=self.properties_bone,
            prop_id=ik_pole_follow_name,
            panel_name="IK",
            label_name="IK Pole Follow",
            row_name=self.base_name,
            slider_name=self.limb_ui_name,
            custom_prop_settings={
                "default": default,
                "description": f'Make "{ik_pole.name}" follow "{ik_mstr.name}"',
            },
            operator="pose.cloudrig_snap_bake",
            op_icon="FILE_REFRESH",
            op_kwargs={
                "bone_names": [ik_pole.name],
            },
        )

    @no_overlay
    def ik_chain__world_align_fk(self):
        # Make last FK bone world-aligned.
        self.ik_chain__world_aligned_helper(self.last_org.fk_bone)

    def ik_chain__world_aligned_helper(self, fk_bone: BoneInfo) -> BoneInfo:
        """Make a control align to the closest world axis (flatten the bone),
        while keeping a back-up of the original transforms in a child bone.
        """
        # This is the target of a Copy Transforms constraint on the ORG bone.
        world_bone = self.bone_sets["Mechanism Bones"].new(
            name=self.naming.add_prefix(fk_bone.name, "W"),
            source=fk_bone,
            parent=fk_bone,
        )
        fk_bone.source.constraint_infos[0].subtarget = world_bone
        fk_bone.custom_shape_transform = world_bone
        fk_bone.flatten()
        return world_bone

    @no_overlay(return_value={})
    def ik_chain__get_ik_switch_ui_data(self, fk_chain, ik_chain, ik_mstr, ik_pole) -> dict:
        """Return UI data to be stored for FK/IK switching and snapping."""

        # List of bone tuples to snap (from, to).
        # Which bone will be snapped to which when the custom property is set to 1.
        map_ik_to_fk = [
            (ik_mstr.name, fk_chain[-1].name),
            (ik_chain[0].name, fk_chain[0].name),
        ]
        # Which bone will be snapped to which when the custom property is set to 0.
        map_fk_to_ik = []

        if self.params.fk_chain.double_first:
            map_fk_to_ik.append((fk_chain[0].parent.name, ik_chain[0].name))

        for i in range(len(fk_chain)):
            map_fk_to_ik.append((fk_chain[i].name, ik_chain[i].name))

        return {
            "prop_bone": self.properties_bone,
            "prop_id": self.ikfk_name,
            "panel_name": "FK/IK Switch",
            "row_name": self.base_name,
            "slider_name": self.limb_ui_name,
            "custom_prop_settings": {
                "default": 1.0,
                "description": f"Switch {self.base_name} to Inverse Kinematics posing mode",
            },
            "operator": "pose.cloudrig_toggle_ikfk_bake",
            "op_icon": "FILE_REFRESH",
            "op_kwargs": {
                "map_fk_to_ik": map_fk_to_ik,
                "map_ik_to_fk": map_ik_to_fk,
                "ik_pole": ik_pole.name if ik_pole else "",
                "ik_first": ik_chain[0].name,
                "fk_first": fk_chain[0].name,
            },
        }

    @no_overlay
    def __attach_org_to_ik(self):
        # Note: Runs after fk_chain__attach_org_to_fk().

        # Add Copy Transforms constraints to the ORG bones to copy the IK bones.
        # Put driver on the influence to be able to disable IK.

        for org_bone in self.bones_org:
            # Copy Transforms to IK bone
            ik_bone = self.find_bone_info(self.naming.add_prefix(org_bone, "IK-M"))
            ct_ik = org_bone.add_constraint(
                "COPY_TRANSFORMS",
                space="WORLD",
                subtarget=ik_bone.name,
                name="Copy Transforms IK",
            )

            ct_ik.drivers.append(
                {
                    "prop": "influence",
                    "variables": [(self.properties_bone.name, self.ikfk_name)],
                }
            )

    @no_overlay
    def ik_chain__make_pole_parent_switch(self, ik_pole, ik_mstr):
        """Tweak the IK Pole control's constraint to support parent switching."""

        pole_parent = ik_pole.parent

        # The pole parent already has an Armature constraint for the
        # IK Follow slider, so we need to hack parent switching into that...
        arm_con_info = pole_parent.constraint_infos[0]
        if (
            not ik_mstr.parent
            or len(ik_mstr.parent.constraint_infos) == 0
            or len(ik_mstr.parent.constraint_infos[0].drivers) == 0
        ):
            return
        arm_con_info.drivers[0] = ik_mstr.parent.constraint_infos[0].drivers[0].copy()
        for target, driver in zip(
            ik_mstr.parent.constraint_infos[0].targets[1:],
            ik_mstr.parent.constraint_infos[0].drivers[1:],
        ):
            arm_con_info.targets.append(target)
            driver = driver.copy()
            driver["prop"] = f"targets[{len(arm_con_info.targets)-1}].weight"
            arm_con_info.drivers.append(driver)

        # arm_con_info.drivers.extend(ik_mstr.parent.constraint_infos[0].drivers)

        ik_pole_follow_name = "ik_pole_follow_" + self.limb_name_props
        # Tweak each driver on the IK pole parent.
        for i, d in enumerate(arm_con_info.drivers):
            if i != 1:
                d["expression"] = f"({d['expression']}) - follow"

                # Add "follow" variable.
                d["variables"]["follow"] = {
                    "type": "SINGLE_PROP",
                    "targets": [
                        {
                            "data_path": f'pose.bones["{self.properties_bone.name}"]["{ik_pole_follow_name}"]'
                        }
                    ],
                }

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            "IK Controls",
            color_palette="THEME13",
            collections=["IK Controls"],
            wire_width=2.0,
        )
        cls.define_bone_set(
            "IK Controls Secondary",
            color_palette="THEME13",
            collections=["IK Secondary"],
            wire_width=1.0,
        )
        cls.define_bone_set(
            "IK Mechanism",
            collections=["Mechanism Bones"],
            is_advanced=True,
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        layout.separator()
        cls.draw_control_label(layout, "IK")

        cls.draw_prop(context, layout, params.ik_chain, "use_pole")
        cls.draw_prop(context, layout, params.ik_chain, "at_tip")

        if cls.is_advanced_mode(context):
            cls.draw_prop(context, layout, params.ik_chain, "world_aligned")

        split = label_split(layout, text="")
        split.operator("armature.flatten_ik_chain")

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.ik_chain, 'shape_ik_master')
        cls.draw_prop_custom_shape(context, layout, params.ik_chain, 'shape_ik_first')
        if params.ik_chain.use_pole:
            cls.draw_prop_custom_shape(context, layout, params.ik_chain, 'shape_pole')
        return layout



class Params(PropertyGroup):
    at_tip: BoolProperty(
        name="IK At Tail",
        description="Put the IK control at the tail of the chain, rather than the head of the last bone",
        default=False,
    )
    world_aligned: BoolProperty(
        name="World Aligned IK Master",
        description="Ankle/Wrist IK/FK controls are aligned with world axes",
        default=False,
    )
    use_pole: BoolProperty(
        name="Create IK Pole",
        description=(
            "If disabled, you can control the rotation of the IK chain by simply rotating its first "
            "bone, rather than with an IK pole control"
        ),
        default=True,
    )

    shape_ik_master: Component_Chain_FK.make_custom_shape_params(
        identifier="IK Master",
        default="Sphere"
    )
    shape_ik_first: Component_Chain_FK.make_custom_shape_params(
        identifier="First IK",
        default="IK First"
    )
    shape_pole: Component_Chain_FK.make_custom_shape_params(
        identifier="IK Pole",
        default="Pole"
    )

RIG_COMPONENT_CLASS = Component_Chain_IKFK
