from typing import List
from bpy.types import PropertyGroup
from ..rig_component_features.bone import BoneInfo

from bpy.props import (
    BoolProperty,
    IntVectorProperty,
    BoolVectorProperty,
    EnumProperty,
    FloatProperty,
)

from .cloud_chain import Component_ToonChain
from ..rig_component_features.animation import CloudAnimationMixin


class Component_Chain_FK(Component_ToonChain, CloudAnimationMixin):
    """FK chain with squash and stretch controls."""

    ui_name = "Chain: FK"
    # Strings to try to communicate obscure behaviours of this rig type in the params UI.
    relinking_behaviour = "Constraints will be moved to the FK controls."

    has_test_animation = True

    def initialize(self):
        """Gather and validate data about the rig."""
        super().initialize()

        self.limb_name = self.naming.slice_name(self.base_bone_name)[1]
        self.limb_ui_name = self.limb_name
        if self.side_prefix != "":
            self.limb_ui_name = self.side_prefix + " " + self.limb_ui_name

        self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
        self.fk_hinge_name = "fk_hinge_" + self.limb_name_props

        if not self.params.fk_chain.root and self.generator_params.ensure_root:
            self.params.fk_chain.hinge = False

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        if self.params.fk_chain.root:
            self.root_bone = self.make_root_bone()

        self.fk_chain = self.make_fk_chain(self.bones_org)
        self.attach_org_to_fk(self.bones_org, self.fk_chain)

        if self.root_bone == self.bones_org[0]:
            self.root_bone = self.bone_sets['FK Controls'][0]

    def apply_parent_switching(
        self,
        parent_slots,
        *,
        child_bone=None,
        prop_bone=None,
        prop_name="",
        panel_name="FK",
        row_name="",
        label_name="Parent Switching",
        entry_name=""
    ):
        """Overrides cloud_base."""

        super().apply_parent_switching(
            parent_slots,
            child_bone=child_bone,
            prop_bone=prop_bone or self.properties_bone,
            prop_name=prop_name,
            panel_name=panel_name,
            row_name=row_name,
            label_name=label_name,
            entry_name=entry_name,
        )

    def relink(self):
        """Override cloud_chain.
        Move constraints from ORG to FK chain and relink them.
        """
        for i, org in enumerate(self.bones_org):
            for c in org.constraint_infos[:]:
                if not c.is_from_real:
                    continue
                to_bone = self.bone_sets['FK Controls'][i]
                if i == 0 and self.params.fk_chain.double_first:
                    to_bone = to_bone.parent
                to_bone.constraint_infos.append(c)
                org.constraint_infos.remove(c)
                c.relink()

    def make_root_bone(self):
        # Socket/Root bone to parent IK and FK to.
        root_name = self.naming.add_prefix(self.base_bone_name, "ROOT")
        org_bone = self.bones_org[0]
        root_bone = self.bone_sets['FK Controls Extra'].new(
            name=root_name,
            source=org_bone,
            parent=org_bone.parent,
            custom_shape=self.ensure_widget("Cube"),
            inherit_scale=self.params.fk_chain.inherit_scale,
        )
        org_bone.parent = root_bone
        return root_bone

    def make_fk_chain(self, org_chain) -> List[BoneInfo]:
        fk_name = ""

        hng_child = None  # For keeping track of which bone will need to be parented to the Hinge helper bone.
        for i, org_bone in enumerate(org_chain):
            fk_bone = self.make_fk_bone(org_bone)
            if i == 0:
                hng_child = fk_bone
                if self.params.fk_chain.double_first:
                    # Make a parent for the first control.
                    fk_parent_bone = self.create_parent_bone(
                        fk_bone, bone_set=self.bone_sets['FK Controls Extra']
                    )
                    fk_parent_bone.custom_shape = fk_bone.custom_shape
                    fk_parent_bone.custom_shape_along_length = (
                        self.params.fk_chain.display_center / 2
                    )
                    hng_child = fk_parent_bone

        # Create Hinge helper
        if self.params.fk_chain.hinge:
            hng_bone = self.make_hinge_setup(
                bone=hng_child,
                bone_set=self.bone_sets['FK Helpers'],
                category=self.limb_name,
                parent_bone=self.root_bone,
                hng_name=self.naming.add_prefix(self.base_bone_name, "FK-HNG"),
                prop_bone=self.properties_bone,
                prop_name=self.fk_hinge_name,
                limb_name=self.limb_ui_name,
            )

        return self.bone_sets['FK Controls']

    def make_fk_bone(self, org_bone) -> BoneInfo:
        fk_name = self.naming.add_prefix(org_bone, "FK")

        rot_mode = self.params.fk_chain.rot_mode
        if rot_mode == 'PROPAGATE':
            rot_mode = org_bone.rotation_mode

        fk_bone = self.bone_sets['FK Controls'].new(
            name=fk_name,
            source=org_bone,
            custom_shape=self.ensure_widget("Circle_Spiked_2"),
            inherit_scale=self.params.fk_chain.inherit_scale,
            custom_shape_along_length=self.params.fk_chain.display_center / 2,
            rotation_mode=rot_mode,
            gizmo_vgroup=self.def_bones_of_org[org_bone][0].name,
            gizmo_operator='transform.rotate',
        )

        if self.params.fk_chain.position_along_bone > 0:
            position = (
                org_bone.head
                + (org_bone.tail - org_bone.head)
                * self.params.fk_chain.position_along_bone
            )
            fk_bone.put(position)

        org_bone.fk_bone = fk_bone
        # Parent FK bone to previous FK bone.
        if org_bone.prev:
            fk_bone.parent = org_bone.prev.fk_bone
        else:
            # Parent first FK to the root.
            fk_bone.parent = org_bone.parent
        return fk_bone

    def make_hinge_setup(
        self,
        bone,
        category,
        *,
        prop_bone,
        prop_name,
        default_value=0.0,
        parent_bone=None,
        hng_name=None,
        limb_name=None,
        bone_set=None
    ):
        """Create a hinge toggle for a bone.
        Bone is usually the first bone in an FK chain.
        When hinge is turned on, the bone doesn't inherit rotation from its
        parents, but still inherits rotation from the rig's root bone.
        """

        # Defaults for optional parameters
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
        if bone_set == None:
            bone_set = bone.bone_set

        info = {
            "prop_bone": prop_bone,
            "prop_id": prop_name,
            "operator": "pose.cloudrig_snap_bake",
            "bones": [bone.name],
        }

        # Store UI info
        self.add_ui_data(
            "FK",
            category,
            info,
            label_name="Hinge",
            entry_name=limb_name,
            default=default_value,
        )

        # Create Hinge helper bone
        hng_bone = bone_set.new(
            name=hng_name, source=bone, head=bone.source.head, tail=bone.source.tail
        )

        # Hinge Armature constraint
        hng_con = hng_bone.add_constraint(
            'ARMATURE',
            targets=[{"subtarget": 'root'}, {"subtarget": str(parent_bone)}],
        )

        hng_con.drivers.append(
            {'prop': 'targets[0].weight', 'variables': [(prop_bone.name, prop_name)]}
        )

        hng_con.drivers.append(
            {
                'prop': 'targets[1].weight',
                'expression': '1-var',
                'variables': [(prop_bone.name, prop_name)],
            }
        )

        # Hinge Copy Location & Scale constraints
        hng_bone.add_constraint(
            'COPY_LOCATION', space='WORLD', subtarget=str(parent_bone)
        )
        hng_bone.add_constraint('COPY_SCALE', space='WORLD', subtarget=str(parent_bone))

        # Parenting
        bone.parent = hng_bone
        return hng_bone

    def make_def_chain(self, str_chain: List[BoneInfo]) -> List[BoneInfo]:
        """Extend cloud_chain by tweaking some bbone values."""
        def_chain = super().make_def_chain(str_chain)

        last_def = def_chain[-1]
        if last_def == def_chain[0]:
            return

        # If we didn't put a stretch constraint on the final deform bone,
        # it must mean there is no cap control.
        if len(last_def.constraint_infos) == 0 and not self.params.chain.unlock_deform:
            if last_def.prev:
                # In this case, set the previous def_bone's easeout to 0.
                last_def.prev.bbone_easeout = 0
            # Also, parent this to the ORG bone. This is so that scaling
            # the last STR control doesn't affect this deform bone.
            if not self.params.chain.unlock_deform:
                last_def.parent = self.bones_org[-1]

    def attach_org_to_fk(self, org_bones, fk_bones):
        """Make ORG bones Copy Transforms of FK bones."""
        if self.params.fk_chain.position_along_bone > 0:
            for str_bone, fk_bone in zip(self.main_str_bones[1:], fk_bones):
                str_bone.parent = fk_bone
            return

        for org_bone, fk_bone in zip(org_bones, fk_bones):
            org_bone.add_constraint(
                'COPY_TRANSFORMS',
                space='WORLD',
                subtarget=fk_bone.name,
                name="Copy Transforms FK",
            )

    ##############################
    # Test Action

    def add_test_animation(
        self, action, start_frame=1, flip_xyz=[False, False, False]
    ) -> int:
        """Add animation curves to the action to test this rig.

        Return the frame at which animation is finished.
        """

        if not self.params.fk_chain.test_animation_generate:
            return start_frame

        # Create FCurves
        curve_map = self.test_action_create_fcurves(
            action, self.bone_sets['FK Controls'], 'rotation_euler'
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
            'FK Controls', color_palette='THEME02', collections=['FK Controls']
        )
        cls.define_bone_set(
            'FK Controls Extra', color_palette='THEME02', collections=['FK Secondary']
        )
        cls.define_bone_set(
            'FK Helpers', collections=['Mechanism Bones'], is_advanced=True
        )

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        cls.draw_prop(context, layout, params.fk_chain, 'display_center')

        return layout

    @classmethod
    def draw_control_params(cls, layout, context, params):
        super().draw_control_params(layout, context, params)

        generator = context.object.cloudrig.generator

        layout.separator()
        cls.draw_control_label(layout, "FK")

        cls.draw_prop(context, layout, params.fk_chain, 'root')
        row = cls.draw_prop(context, layout.row(), params.fk_chain, 'hinge')
        if row:
            row.enabled = params.fk_chain.root and generator.ensure_root

        if not cls.is_advanced_mode(context):
            return
        cls.draw_prop(
            context, layout, params.fk_chain, 'position_along_bone', slider=True
        )
        cls.draw_prop(context, layout, params.fk_chain, 'inherit_scale')
        cls.draw_prop(context, layout, params.fk_chain, 'rot_mode')
        cls.draw_prop(context, layout, params.fk_chain, 'double_first')

    @classmethod
    def draw_anim_params(cls, layout, context, params):
        col = layout.column()
        col.enabled = params.fk_chain.test_animation_generate

        row = col.row()
        row.prop(params.fk_chain, 'test_animation_rotation_range', index=0)
        row.prop(params.fk_chain, 'test_animation_rotation_range', index=1, text="")
        row = col.row(heading="Rotation Axes", align=True)
        row.prop(params.fk_chain, 'test_animation_axes', text="X", toggle=True, index=0)
        row.prop(params.fk_chain, 'test_animation_axes', text="Y", toggle=True, index=1)
        row.prop(params.fk_chain, 'test_animation_axes', text="Z", toggle=True, index=2)

    @classmethod
    def is_using_custom_props(cls, context, params):
        """Overrides cloud_base."""
        if super().is_using_custom_props(context, params):
            return True

        cloudrig = context.object.cloudrig.generator
        if params.fk_chain.hinge and params.fk_chain.root and cloudrig.ensure_root:
            return True


class Params(PropertyGroup):
    # We are re-defining this instead of using the bone's own `inherit_scale` property because we want the default to be 'ALIGNED' instead of 'FULL'.
    inherit_scale: Component_Chain_FK.make_inherit_scale_param(
        description="Scale inheritance type for FK controls", default='ALIGNED'
    )
    display_center: BoolProperty(
        name="Display FK in center",
        description="Display all FK controls' shapes in the center of the bone, rather than the beginning of the bone",
        default=True,
    )
    position_along_bone: FloatProperty(
        name="Position Along Bone",
        description="Whether the position of each FK control should be at the deform bone's head or tail. Increasing this above 0 also means ORG bones won't be constrained to FK bones, and STR bones get parented to FK bones directly",
        default=0,
        min=0,
        max=1,
    )
    double_first: BoolProperty(
        name="Duplicate First FK",
        description="Create a parent control for the first FK control. This can be useful when the Rest Pose is far from the character's common pose, to avoid gimbal locking",
        default=False,
    )

    root: BoolProperty(
        name="Create Root", description="Create a root control", default=False
    )
    hinge: BoolProperty(
        name="Hinge",
        description="Set up a hinge toggle which allows this FK chain to not inherit rotation from its parent, but still inherit rotation from the rig root. The 'Create Root' generator setting must be enabled for this",
        default=True,
    )
    rot_mode: Component_Chain_FK.make_rotation_mode_param(
        description="Set the rotation mode of the FK controls", can_propagate=True
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
        subtype='EULER',
        default=(True, True, True),
    )


class RigComponent(Component_Chain_FK):
    pass
