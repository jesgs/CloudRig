# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import (
    BoolProperty,
    BoolVectorProperty,
    FloatProperty,
    IntVectorProperty,
)
from bpy.types import Action, ActionSlot, PropertyGroup

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.generate_animation import CloudAnimationMixin
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_chain import Component_ToonChain


class Component_Chain_FK(Component_ToonChain, CloudAnimationMixin):
    """FK chain with squash and stretch controls."""

    ui_name = "Chain: FK"

    relink_default_prefix = "FK"

    has_test_animation = True
    use_base_name = True

    required_chain_length = -1

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.limb_ui_name = self.base_name
        if self.side_prefix != "":
            self.limb_ui_name = self.side_prefix + " " + self.limb_ui_name

        self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
        self.fk_hinge_name = "fk_hinge_" + self.limb_name_props
        self.reverse_fk_name = "fk_reverse_" + self.limb_name_props

        if not (self.params.fk_chain.root and self.generator_params.ensure_root):
            self.params.fk_chain.hinge = False

        if not self.params.fk_chain.root:
            self.params.fk_chain.create_curl_control = False

        self.__check_correct_chain_length()

    @no_overlay
    def base__apply_parent_switching(
        self,
        *,
        child_bone=None,
        prop_bone=None,
        prop_name="",
        panel_name="FK",
        row_name="",
        label_name="Parent Switching",
        entry_name="",
    ):
        super().base__apply_parent_switching(
            child_bone=child_bone,
            prop_bone=prop_bone or self.properties_bone,
            prop_name=prop_name,
            panel_name=panel_name,
            row_name=row_name,
            label_name=label_name,
            entry_name=entry_name,
        )

    def toon__is_cyclic(self) -> bool:
        """Cyclic rigs are not supported beyond just the toon chain, since
        FK chains cannot be cyclic.
        """
        return False

    @no_overlay
    def toon__make_def_chain(self, str_chain: list[BoneInfo]) -> list[BoneInfo]:
        """Extend cloud_chain by tweaking some bbone values."""
        def_chain = super().toon__make_def_chain(str_chain)

        last_def = def_chain[-1]
        if last_def == def_chain[0]:
            return def_chain

        # If there's no tip control, parent DEF to ORG.
        # Useful for example for an arm rig.
        # TODO: Maybe this should be in cloud_limb or cloud_chain?
        if not self.params.chain.tip_control and not self.params.chain.unlock_deform:
            last_def.parent = self.bones_org[-1]

        return def_chain

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        if self.params.fk_chain.root:
            self.root_bone = self.fk_chain__make_root_bone()

        self.fk_chain = self.fk_chain__make(self.bones_org)
        if self.params.fk_chain.create_curl_control:
            self.__make_curl_control(self.fk_chain)

        if self.params.fk_chain.counter_rotate_stretch_bones > 0:
            self.fk_chain__counter_rotate_str_bones(
                self.fk_chain,
                self.main_str_bones,
                self.params.fk_chain.counter_rotate_stretch_bones
            )

        self.fk_chain__attach_org_to_fk(self.bones_org, self.fk_chain)

        if self.root_bone == self.bones_org[0]:
            self.root_bone = self.bone_sets["FK Controls"][0]

    ##############################
    # FK Chain functions.

    def __check_correct_chain_length(self):
        req_len = type(self).required_chain_length
        if req_len != -1 and self.bone_count != req_len:
            self.raise_generation_error(
                f"Chain must be exactly {req_len} connected bones."
            )

    def fk_chain__make_root_bone(self):
        # Socket/Root bone to parent IK and FK to.
        root_name = self.naming.add_prefix(self.base_bone_name, "ROOT")
        org_bone = self.bones_org[0]
        root_bone = self.bone_sets["FK Controls Extra"].new(
            name=root_name,
            source=org_bone,
            parent=org_bone.parent,
            custom_shape_name=self.params.fk_chain.shape_fk_root.shape_name,
            inherit_scale=self.params.fk_chain.inherit_scale,
        )
        org_bone.parent = root_bone
        return root_bone

    def fk_chain__make(self, org_chain: list[BoneInfo]) -> list[BoneInfo]:
        # Keep track of which bone will need to be parented to the Hinge helper bone.
        hng_child = None
        fk_chain = []
        for i, org_bone in enumerate(org_chain):
            fk_bone = self.__make_fk_bone(org_bone)
            fk_chain.append(fk_bone)
            if i == 0:
                hng_child = fk_bone
                if self.params.fk_chain.double_first:
                    # Make a parent for the first control.
                    fk_parent_bone = self.create_parent_bone(
                        fk_bone,
                        bone_set=self.bone_sets["FK Controls Extra"],
                    )
                    hng_child = fk_parent_bone
                    if not self.params.fk_chain.root:
                        self.root_bone = fk_parent_bone

        # Create Hinge helper
        if self.params.fk_chain.hinge:
            self.__make_hinge_setup(
                bone=hng_child,
                bone_set=self.bone_sets["Mechanism Bones"],
                category=self.base_name,
                parent_bone=self.root_bone,
                hng_name=self.naming.add_prefix(self.base_bone_name, "FK-HNG"),
                prop_bone=self.properties_bone,
                prop_name=self.fk_hinge_name,
                limb_name=self.limb_ui_name,
            )

        return fk_chain

    def __make_fk_bone(self, org_bone: BoneInfo) -> BoneInfo:
        fk_name = self.naming.add_prefix(org_bone, "FK")

        rot_mode = self.params.fk_chain.rot_mode
        if rot_mode == "PROPAGATE":
            rot_mode = org_bone.rotation_mode

        fk_bone = self.bone_sets["FK Controls"].new(
            name=fk_name,
            source=org_bone,
            custom_shape_name=self.params.fk_chain.shape_fk.shape_name,
            inherit_scale=self.params.fk_chain.inherit_scale,
            rotation_mode=rot_mode,
            # gizmo_vgroup=self.def_bones_of_org[org_bone][0].name,
            # gizmo_operator="transform.rotate",
        )
        if self.params.fk_chain.display_center:
            fk_bone.custom_shape_along_length = 0.5

        org_bone.fk_bone = fk_bone

        # Parent FK bone to previous FK bone.
        if org_bone.prev:
            fk_bone.parent = org_bone.prev.fk_bone
        else:
            # Parent first FK to the root.
            fk_bone.parent = org_bone.parent
        return fk_bone

    @no_overlay
    def __make_hinge_setup(
        self,
        bone,
        category,
        *,
        prop_bone,
        prop_name,
        default_value=0.0,
        parent_bone=None,
        root_bone="",
        hng_name=None,
        limb_name=None,
        bone_set=None,
        panel_name="FK",
        label_name="Hinge",
    ):
        """Create a hinge toggle for a bone.
        Bone is usually the first bone in an FK chain.
        When hinge is turned on, the bone doesn't inherit rotation from its
        parents, but still inherits rotation from the passed root bone.
        """

        # Defaults for optional parameters
        if root_bone == "":
            root_bone = self.generator.params.ensure_root
        if not hng_name:
            sliced = self.naming.slice_name(bone.name)
            sliced[0].insert(0, "HNG")
            hng_name = self.naming.make_name(*sliced)
        if not parent_bone:
            parent_bone = bone.parent
        if not limb_name:
            limb_name = (
                "Hinge: "
                + self.side_suffix
                + " "
                + self.naming.slice_name(bone.name)[1]
            )
        if bone_set is None:
            bone_set = bone.bone_set

        # Create Hinge helper bone
        hng_bone = bone_set.new(
            name=hng_name, source=bone, head=bone.source.head, tail=bone.source.tail
        )

        # Store UI info
        self.rig_ui__add_bone_property(
            prop_bone=prop_bone,
            prop_id=prop_name,
            panel_name=panel_name,
            label_name=label_name,
            row_name=category,
            slider_name=limb_name,
            custom_prop_settings={
                "default": default_value,
                "description": "When enabled, rotation is not inherited, except from the armature's root",
            },
            operator="pose.cloudrig_snap_bake",
            op_icon="FILE_REFRESH",
            op_kwargs={
                "bone_names": [bone.name],
            },
        )

        self.create_driven_armature_constraint(
            hng_bone,
            target_bones=[parent_bone, root_bone],
            prop_bone=prop_bone,
            prop_name=prop_name,
            name="Armature (FK Hinge)",
        )

        # Hinge Copy Location & Scale constraints
        hng_bone.add_constraint(
            "COPY_LOCATION", space="WORLD", subtarget=str(parent_bone)
        )
        hng_bone.add_constraint("COPY_SCALE", space="WORLD", subtarget=str(parent_bone))

        # Parenting
        bone.parent = hng_bone
        return hng_bone

    def __make_curl_control(self, fk_chain):
        curl_control = self.bone_sets["FK Curl Control"].new(
            name="CURL-" + self.bones_org[0].name,
            source=fk_chain[0],
            custom_shape_name=self.params.fk_chain.shape_fk.shape_name,
            inherit_scale=self.params.fk_chain.inherit_scale,
            custom_shape_translation=[0, fk_chain[-1].length, 0],
            custom_shape_transform=fk_chain[-1],
        )
        # These constraints will add together, so we want their total influence to add up to 1.
        # Otherwise, the transformations will feel "slippery", as in, faster or slower than
        # you're used to.
        influence = 1 / len(fk_chain)
        for fk_bone in fk_chain:
            fk_bone.add_constraint(
                "COPY_LOCATION",
                target_space="LOCAL",
                owner_space="CUSTOM",
                space_subtarget=self.root_bone,
                use_offset=True,
                influence=influence,
                subtarget=curl_control,
            )
            fk_bone.add_constraint(
                "COPY_ROTATION",
                space="LOCAL",
                mix_mode="BEFORE",
                influence=influence,
                subtarget=curl_control,
            )
            fk_bone.add_constraint(
                "COPY_SCALE",
                space="LOCAL",
                use_offset=True,
                subtarget=curl_control,
                influence=influence,
            )

    @no_overlay
    def fk_chain__counter_rotate_str_bones(self, fk_chain: list[BoneInfo], main_str_bones: list[BoneInfo], influence=0.5):
        for fk_bone, main_str_bone in zip(fk_chain, main_str_bones):
            main_str_bone.add_constraint(
                "COPY_ROTATION",
                name="Copy Rotation (Counter-Rotate)",
                use_xyz=[True, False, True],
                invert_xyz=[True, False, True],
                euler_order="XZY",
                mix_mode="BEFORE",
                space="LOCAL",
                influence=influence,
                subtarget=fk_bone,
            )

    @no_overlay
    def fk_chain__attach_org_to_fk(self, org_bones: list[BoneInfo], fk_bones: list[BoneInfo]):
        """Make ORG bones Copy Transforms of FK bones."""
        for org_bone, fk_bone in zip(org_bones, fk_bones):
            org_bone.use_connect = False
            org_bone.add_constraint(
                "COPY_TRANSFORMS",
                space="WORLD",
                subtarget=fk_bone.name,
                name="Copy Transforms FK",
            )

    @no_overlay
    def fk_chain__add_test_animation(
        self, action: Action, slot: ActionSlot, start_frame=1, flip_xyz=[False, False, False]
    ) -> int:
        """Add animation curves to the action to test this rig.

        Return the frame at which animation is finished.
        """

        if not self.params.fk_chain.test_animation_generate:
            return start_frame

        # Create FCurves
        curve_map = self.test_action_create_fcurves(
            action, slot, self.bone_sets["FK Controls"], "rotation_euler"
        )

        # Populate FCurves with keyframes
        min_rot = self.params.fk_chain.test_animation_rotation_range[0]
        max_rot = self.params.fk_chain.test_animation_rotation_range[1]

        axes_boolean = self.params.fk_chain.test_animation_axes
        order = [0, 2, 1]
        axes = [order[i] for i in range(3) if axes_boolean[i]]

        last_frame = self.create_keyframes_on_curves(
            curve_map,
            start_frame=start_frame,
            values=[0, max_rot, 0, min_rot, 0],
            flip_xyz=flip_xyz,
            axes=axes,
        )

        return last_frame

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            "FK Controls",
            color_palette="THEME02",
            collections=["FK Controls"],
            wire_width=1.5,
        )
        cls.define_bone_set(
            "FK Curl Control",
            color_palette="THEME07",
            collections=["FK Controls"],
            wire_width=2.0,
        )
        cls.define_bone_set(
            "FK Controls Extra", color_palette="THEME02", collections=["FK Secondary"]
        )

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == "fk_controls_extra":
            return params.fk_chain.root

        if set_name == "fk_curl_control":
            return params.fk_chain.root and params.fk_chain.create_curl_control

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.fk_chain, 'shape_fk')
        if params.fk_chain.root:
            cls.draw_prop_custom_shape(context, layout, params.fk_chain, 'shape_fk_root')
        cls.draw_prop(context, layout, params.fk_chain, "display_center", enabled=component.appearance_enabled)
        return layout

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        generator = context.object.cloudrig.generator

        layout.separator()
        cls.draw_control_label(layout, "FK")

        cls.draw_prop(context, layout, params.fk_chain, "root")
        row = cls.draw_prop(context, layout.row(), params.fk_chain, "hinge")
        if row:
            row.enabled = bool(params.fk_chain.root and generator.ensure_root)
        cls.draw_prop(
            context,
            layout.row(),
            params.fk_chain,
            "create_curl_control",
            enabled=params.fk_chain.root,
        )

        if not cls.is_advanced_mode(context):
            return
        cls.draw_prop(
            context,
            layout,
            params.fk_chain,
            "counter_rotate_stretch_bones",
            slider=True,
        )
        cls.draw_prop(context, layout, params.fk_chain, "inherit_scale")
        cls.draw_prop(context, layout, params.fk_chain, "rot_mode")
        cls.draw_prop(context, layout, params.fk_chain, "double_first")

    @classmethod
    def draw_anim_params(cls, layout, context, component):
        params = component.params
        col = layout.column()
        col.enabled = params.fk_chain.test_animation_generate

        row = col.row()
        row.prop(params.fk_chain, "test_animation_rotation_range", index=0)
        row.prop(params.fk_chain, "test_animation_rotation_range", index=1, text="")
        row = col.row(heading="Rotation Axes", align=True)
        row.prop(params.fk_chain, "test_animation_axes", text="X", toggle=True, index=0)
        row.prop(params.fk_chain, "test_animation_axes", text="Y", toggle=True, index=1)
        row.prop(params.fk_chain, "test_animation_axes", text="Z", toggle=True, index=2)

    @classmethod
    def base__is_using_custom_props(cls, context, params):
        if super().base__is_using_custom_props(context, params):
            return True

        cloudrig = context.object.cloudrig.generator
        if params.fk_chain.hinge and params.fk_chain.root and cloudrig.ensure_root:
            return True


class Params(PropertyGroup):
    # We are re-defining this instead of using the bone's own `inherit_scale` property because we
    # want the default to be 'ALIGNED' instead of 'FULL'.
    inherit_scale: Component_Chain_FK.make_inherit_scale_param(
        description="Scale inheritance type for FK controls", default="ALIGNED"
    )
    display_center: BoolProperty(
        name="Display Centered",
        description=(
            "Display all FK controls' shapes in the center of the bone, "
            "rather than the beginning of the bone"
        ),
        default=True,
    )
    counter_rotate_stretch_bones: FloatProperty(
        name="Counter-Rotate Stretch Controls",
        description="Rotating FK bones will counter-rotate the child stretch bones. This can result in smoother chains",
        min=0,
        max=1,
        default=0,
    )
    double_first: BoolProperty(
        name="Duplicate First FK",
        description=(
            "Create a parent control for the first FK control. This can be useful when the Rest Pose "
            "is far from the character's common pose, to avoid gimbal locking"
        ),
        default=False,
    )

    root: BoolProperty(
        name="Create Root", description="Create a root control", default=False
    )
    hinge: BoolProperty(
        name="Hinge",
        description=(
            "Set up a hinge toggle which allows this FK chain to not inherit rotation from its "
            "parent, but still inherit rotation from the rig root. There must be a root bone name "
            "specified in generator settings for this"
        ),
        default=True,
    )
    rot_mode: Component_Chain_FK.make_rotation_mode_param(
        description="Set the rotation mode of the FK controls", can_propagate=True
    )
    create_curl_control: BoolProperty(
        name="Create Curl Control",
        description=(
            "Create a control that lets you easily curl this FK chain. Can be useful for tails and "
            "fingers and such. Requires a root bone for space calculations"
        ),
        default=False,
    )

    test_animation_generate: BoolProperty(
        name="Generate Test Animation",
        description="Include this rig component in the test animation",
        default=False,
    )
    test_animation_rotation_range: IntVectorProperty(
        name="Rotation Range",
        description="Minimum and Maximum rotations for the test animation",
        size=2,
        default=(-130, 130),
        min=-180,
        max=180,
    )
    test_animation_axes: BoolVectorProperty(
        name="Rotation Axes",
        description="Rotation axes to test in the test animation",
        subtype="EULER",
        default=(True, True, True),
    )

    shape_fk: Component_ToonChain.make_custom_shape_params(
        identifier="FK",
        default="Square 2"
    )
    shape_fk_root: Component_ToonChain.make_custom_shape_params(
        identifier="FK Root",
        default="Cube"
    )


RIG_COMPONENT_CLASS = Component_Chain_FK
