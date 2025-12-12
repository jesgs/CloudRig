# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Object, PropertyGroup

from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from .cloud_curve import Component_Curve_Hooked, get_points


class Component_Curve_SplineIK(Component_Curve_Hooked):
    """Create a bezier curve object to drive a bone chain with Spline IK constraint, controlled by Hooks."""

    ui_name = "Curve: Spline IK"

    forced_params = {
        'curve.x_axis_symmetry': False,
    }

    # TODO: Original bones are needed currently because of bone roll calculations (which are relative to the original bones)
    # but ideally that should not be the case.
    keep_original_bones = True

    ################################
    # Inherited functions.

    def base__relink_get_target(self, org_i: int, con_info: ConstraintInfo) -> BoneInfo:
        if not self.params.spline_ik.match_hooks:
            # Don't allow base__relinking if the number of hooks doesn't match the number of org bones.
            return self.bones_org[org_i]

        if con_info.name.startswith("TAIL-"):
            return self.bone_sets['Curve Hooks'][org_i+1]

        return super().base__relink_get_target(org_i, con_info)

    def curve__initialize(self):
        length = self.bone_count
        subdiv = self.params.spline_ik.subdivide
        total = length * subdiv
        if length > 255:
            self.raise_generation_error(
                f"Spline IK component consists of {length} bones but the Spline IK constraint only supports a chain of 255 bones max."
            )
        if total > 255:
            old_total = total
            old_subdiv = subdiv
            while total > 255:
                subdiv -= 1
                total = length * subdiv
            self.add_log(
                "Spline IK clamped to 255 bones",
                description=f"Trying to subdivide {length} bones {old_subdiv} times, would result in {old_total} bones. \nThe Spline IK constraint only supports a chain of 255 bones, so subdivisions has been capped at {subdiv} for a new total of {total} bones.",
            )

        self.num_controls = (
            self.bone_count + 1
            if self.params.spline_ik.match_hooks
            else self.params.spline_ik.hooks
        )

    def create_bone_infos(self, context):
        # Skip the parent class's create_bone_infos() function, but call the grandparent's.
        # This is because we need to do things in a different order than cloud_curve:
        # The curve object is created based on the controls, rather than the other way around.
        super(Component_Curve_Hooked, self).create_bone_infos(context)
        self.root_bone = self.bones_org[0].parent  # Should be allowed to be None!
        if self.params.curve.create_root:
            self.curve__make_root()
        if not self.params.curve.target:
            self.params.curve.target = self.__ensure_curve_obj(context)
        self.__reset_curve_obj(self.params.curve.target)
        self.hooks_of_splines = self.curve__make_ctrls_for_points(self.params.curve.target)

        if self.params.spline_ik.create_fk_chain:
            self.__make_fk_chain()

        ik_chain = self.bones_org
        if self.params.spline_ik.deform_setup == 'CREATE':
            ik_chain = self.__make_def_chain()
        self.__add_spline_ik(ik_chain)

    def create_helper_objects(self, context):
        """Apply the rest pose of the deform bones, as dictated by
        the Spline IK constraint."""
        super().create_helper_objects(context)
        self.__apply_def_chain_pose()

    ################################
    # Spline IK functions.

    def __ensure_curve_obj(self, context) -> Object:
        """Find or create the Bezier Curve that will be used by the rig."""

        curve_ob = self.params.curve.target
        if curve_ob:
            return curve_ob

        # Create and name curve object.
        curve_name = "CUR-" + self.generator.metarig.name.replace("META-", "")
        curve_name += "_" + (
            self.params.curve.hook_name
            if self.params.curve.hook_name != ""
            else self.base_bone_name.replace("ORG-", "")
        )

        curve = bpy.data.curves.new(curve_name, 'CURVE')
        curve_ob = bpy.data.objects.new(curve_name, curve)
        context.scene.collection.objects.link(curve_ob)
        self.lock_transforms(curve_ob)
        return curve_ob

    def __reset_curve_obj(self, curve_ob):
        # Remove all splines, then add a new one.
        for spline in curve_ob.data.splines[:]:
            curve_ob.data.splines.remove(spline)
        spline = curve_ob.data.splines.new(type='BEZIER')
        # Remove all Hook modifiers. They seem to cause an issue where deform bones get created at 0,0,0...
        # Blows my mind, don't ask me.
        for m in curve_ob.modifiers[:]:
            if m.type == 'HOOK':
                curve_ob.modifiers.remove(m)

        curve_ob.data.dimensions = '3D'
        sum_bone_length = sum([b.length for b in self.bones_org])
        length_unit = sum_bone_length / (self.num_controls - 1)
        handle_length = length_unit * self.params.spline_ik.handle_length

        self.params.curve.target = curve_ob

        # Add the necessary number of curve points to the spline
        points = get_points(spline)
        assert len(points) == 1
        points.add(self.num_controls - len(points))
        num_points = len(points)

        # Configure control points...
        for i in range(0, num_points):
            point_along_chain = i * length_unit
            p = points[i]

            # Place control points
            index = i if self.params.spline_ik.match_hooks else -1
            loc, direction = self.vector_along_bone_chain(
                self.bones_org, point_along_chain, index
            )
            p.co = loc
            p.handle_right = loc + handle_length * direction
            p.handle_left = loc - handle_length * direction

        return curve_ob

    def __make_fk_chain(self):
        for spline_idx, hooks_of_spline in enumerate(self.hooks_of_splines):
            next_parent = hooks_of_spline[0].parent
            for hook_idx, hook_ctrl in enumerate(hooks_of_spline):
                fk_ctrl = self.bone_sets['Curve FK Controls'].new(
                    name=hook_ctrl.name.replace("Hook_", "FK-"),
                    source=hook_ctrl,
                    use_custom_shape_bone_size=True,
                    custom_shape_name=self.params.spline_ik.shape_fk.shape_name,
                    custom_shape_scale=self.params.curve.widget_size,
                    parent=next_parent,
                    rotation_mode='YZX',
                    inherit_scale=self.params.curve.inherit_scale,
                    roll_type='ALIGN',
                    roll_bone=hook_ctrl,
                    roll=0,
                )
                hook_ctrl.parent = fk_ctrl
                next_parent = fk_ctrl
                hook_ctrl.add_constraint(
                    'COPY_ROTATION',
                    name="Copy Rotation (Counter-Rotate)",
                    use_xyz = [True, False, True],
                    invert_xyz = [True, False, True],
                    euler_order = 'XZY',
                    mix_mode = 'BEFORE',
                    space = 'LOCAL',
                    influence = 0.5,
                    subtarget=fk_ctrl,
                )

    def __make_def_chain(self):
        segments = self.params.spline_ik.subdivide

        count_def_bone = 0
        for org_bone in self.bones_org:
            for i in range(0, segments):
                ## Create Deform bones
                if self.params.curve.hook_name != "":
                    def_name = self.params.curve.hook_name
                    counter = count_def_bone
                else:
                    def_name = org_bone.name.replace("ORG-", "")
                    counter = i
                prefixes, base, suffixes = self.naming.slice_name(def_name)
                base += "_" + str(counter).zfill(len(str(segments)))
                prefixes.insert(0, "DEF")
                def_name = self.naming.make_name(prefixes, base, suffixes)
                count_def_bone += 1

                unit = org_bone.vector / segments
                def_bone = self.bone_sets['Deform Bones'].new(
                    name=def_name,
                    source=org_bone,
                    head=org_bone.head + (unit * i),
                    tail=org_bone.head + (unit * (i + 1)),
                    roll=org_bone.roll,
                    use_deform=True,
                    bbone_segments=self.params.spline_ik.bbone_segments
                )

                if len(self.bone_sets['Deform Bones']) > 1:
                    def_bone.parent = self.bone_sets['Deform Bones'][-2]
                    def_bone.use_connect = True # Note: This must be set after the parent.
                else:
                    def_bone.parent = self.bones_org[0]

        return self.bone_sets['Deform Bones']

    def __add_spline_ik(self, bone_chain):
        # Add constraint to deform chain
        bone_chain[-1].add_constraint(
            'SPLINE_IK',
            target=self.params.curve.target,
            use_curve_radius=True,
            chain_count=len(bone_chain),
        )

    def __apply_def_chain_pose(self):
        # TODO: This is quite hacky. We could add a flag in BoneInfo named "Apply Pose", then
        # if any bones have that flag during generation, run the Apply Pose as Rest Pose
        # operator with those bones selected. That's also a little hacky, but maybe a bit less. (I'm not sure if all the bones would be visible)
        self.target_rig.data.pose_position = 'POSE'
        bpy.ops.object.mode_set(mode='EDIT')

        for def_bi in self.bone_sets['Deform Bones']:
            eb = self.target_rig.data.edit_bones.get(def_bi.name)
            if not eb:
                continue
            pb = self.target_rig.pose.bones.get(def_bi.name)
            eb.head = pb.matrix.to_translation()

        self.target_rig.data.pose_position = 'REST'
        bpy.ops.object.mode_set(mode='OBJECT')

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Curve FK Controls', color_palette='THEME02', wire_width=2.0)

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'curve_fk_controls':
            return params.spline_ik.create_fk_chain

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def curve__draw_selector_ui(cls, layout, context, params):
        """Disable the curve selection."""
        row = cls.draw_prop(
            context, layout.row(), params.curve, "target", icon='OUTLINER_OB_CURVE'
        )
        if not cls.is_advanced_mode(context):
            # We don't usually want user to be able to edit the curve object,
            # but when duplicating a component bone, we need to be able to clear the pointer.
            row.enabled = False

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        super().draw_appearance_params(layout, context, params)
        if params.spline_ik.create_fk_chain:
            layout.separator()
            cls.draw_prop_custom_shape(context, layout, params.spine, "shape_fk")
        return layout

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_control_params(layout, context, params)

        layout.separator()
        cls.draw_control_label(layout, "Spline IK")

        if cls.is_advanced_mode(context):
            cls.draw_prop(context, layout, params.spline_ik, 'handle_length')

        cls.draw_prop(context, layout, params.spline_ik, 'deform_setup', expand=True)
        if params.spline_ik.deform_setup == 'CREATE':
            cls.draw_prop(context, layout, params.spline_ik, 'subdivide')
            cls.draw_prop(context, layout, params.spline_ik, 'bbone_segments')
        # TODO: When this is false, the directions of the curve points and bones
        # don't match, and both of them are unsatisfactory. It would be nice if
        # we would interpolate between the direction of the two bones, using
        # length_remaining/bone.length as a factor, or something similar to that.
        cls.draw_prop(context, layout, params.spline_ik, 'match_hooks')
        if not params.spline_ik.match_hooks:
            cls.draw_prop(context, layout, params.spline_ik, 'hooks')

        cls.draw_prop(context, layout, params.spline_ik, 'create_fk_chain')


class Params(PropertyGroup):
    match_hooks: BoolProperty(
        name="Match Controls to Bones",
        description="Hook controls will be created at each bone, instead of being equally distributed across the length of the chain",
        default=True,
    )
    deform_setup: EnumProperty(
        name="Deform Setup",
        items=[
            (
                'NONE',
                'None',
                "Disable deform flag, so this component won't work with Armature modifiers",
            ),
            ('PRESERVE', 'Preserve', "Preserve deform flag of each bone"),
            ('CREATE', 'Create', "Create deform bones prefixed with DEF-"),
        ],
        description="How this curve rig component should behave with Armature modifiers",
    )
    subdivide: IntProperty(
        name="Subdivide Bones",
        description="For each original bone, create this many deform bones in the spline chain (Bendy Bones don't take the curve into account, so it's best to use quite a few real bones) NOTE: Spline IK only supports 255 bones in the chain",
        default=3,
        min=1,
        max=99,
    )
    bbone_segments: IntProperty(
        name="Bendy Segments",
        description="While the bendy bone curvature doesn't take the curve's curvature into account, it can still help smoothen the deformation",
        min=1,
        max=32,
        default=1,
    )
    handle_length: FloatProperty(
        name="Curve Handle Length",
        description="Increasing this will result in longer curve handles, resulting in a sharper curve. A value of 1 means the curve handle reaches the neighbouring curve point",
        default=0.4,
        min=0.01,
        max=2.0,
    )
    hooks: IntProperty(
        name="Number of Hooks",
        description="Number of controls that will be spaced out evenly across the entire chain",
        default=3,
        min=3,
        max=99,
    )
    create_fk_chain: BoolProperty(
        name="Create FK Chain",
        description="Create an FK chain on top of the hook controls",
        default=False,
    )

    shape_fk: Component_Curve_SplineIK.make_custom_shape_params(
        identifier="FK",
        default="Square"
    )

RIG_COMPONENT_CLASS = Component_Curve_SplineIK
