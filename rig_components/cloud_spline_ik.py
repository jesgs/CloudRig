# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import BoolProperty, IntProperty, FloatProperty, EnumProperty
from bpy.types import PropertyGroup

from .cloud_curve import Component_Curve_Hooked, get_points


class Component_Curve_SplineIK(Component_Curve_Hooked):
    """Create a bezier curve object to drive a bone chain with Spline IK constraint, controlled by Hooks."""

    ui_name = "Curve: Spline IK"
    relinking_behaviour = "Constraints will be moved to the Hook controls. Only works when Match Controls to Bones option is enabled."

    forced_params = {
        'curve.x_axis_symmetry': False,
    }

    def initialize_curve_rig(self):
        length = self.bone_count
        subdiv = self.params.spline_ik.subdivide
        total = length * subdiv
        if length > 255:
            self.raise_generation_error(
                f"Spline IK rig consists of {length} bones but the Spline IK constraint only supports a chain of 255 bones."
            )
        if total > 255:
            old_total = total
            old_subdiv = subdiv
            while total > 255:
                subdiv -= 1
                total = length * subdiv
            self.add_log(
                "Spline IK longer than 255 bones",
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
            self.make_curve_root_ctrl()
        if not self.params.curve.target:
            self.ensure_curve_obj(context)
        self.reset_curve_obj(self.params.curve.target)
        self.make_ctrls_for_curve_points()

        ik_chain = self.bones_org
        if self.params.spline_ik.deform_setup == 'CREATE':
            ik_chain = self.make_def_chain()
        self.add_spline_ik(ik_chain)

    def ensure_curve_obj(self, context):
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
        self.params.curve.target = curve_ob
        return curve_ob

    def reset_curve_obj(self, curve_ob):
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

    def make_def_chain(self):
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
                def_bone = self.bone_sets['Curve Deform Bones'].new(
                    name=def_name,
                    source=org_bone,
                    head=org_bone.head + (unit * i),
                    tail=org_bone.head + (unit * (i + 1)),
                    roll=org_bone.roll,
                    bbone_width=0.03,
                    use_deform=True,
                )

                if len(self.bone_sets['Curve Deform Bones']) > 1:
                    def_bone.parent = self.bone_sets['Curve Deform Bones'][-2]
                else:
                    def_bone.parent = self.bones_org[0]

        return self.bone_sets['Curve Deform Bones']

    def add_spline_ik(self, bone_chain):
        # Add constraint to deform chain
        bone_chain[-1].add_constraint(
            'SPLINE_IK',
            target=self.params.curve.target,
            use_curve_radius=True,
            chain_count=len(bone_chain),
        )

    def relink(self):
        """Override cloud_curve.
        Move constraints from ORG to Hook controls and relink them.
        Only works when params.spline_ik.match_hooks==True.
        """
        if not self.params.spline_ik.match_hooks:
            return
        for i, org in enumerate(self.bones_org):
            for c in org.constraint_infos[:]:
                if not c.is_from_real:
                    continue
                to_bone = self.bone_sets['Curve Hooks'][i]
                to_bone.constraint_infos.append(c)
                org.constraint_infos.remove(c)
                c.relink()

    def create_helper_objects(self, context):
        """Apply the rest pose of the deform bones, as dictated by
        the Spline IK constraint."""
        super().create_helper_objects(context)

        self.target_rig.data.pose_position = 'POSE'
        bpy.ops.object.mode_set(mode='EDIT')

        for def_bi in self.bone_sets['Curve Deform Bones']:
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
        super().define_bone_sets()
        """Create parameters for this rig's bone sets."""
        cls.define_bone_set(
            'Curve Deform Bones', collections=['Deform Bones'], is_advanced=True
        )

    @classmethod
    def curve_selector_ui(cls, layout, context, params):
        """Overrides cloud_curve to disable the curve selection."""
        row = cls.draw_prop(
            context, layout.row(), params.curve, "target", icon='OUTLINER_OB_CURVE'
        )
        if row:
            row.enabled = False

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
        # TODO: When this is false, the directions of the curve points and bones
        # don't match, and both of them are unsatisfactory. It would be nice if
        # we would interpolate between the direction of the two bones, using
        # length_remaining/bone.length as a factor, or something similar to that.
        cls.draw_prop(context, layout, params.spline_ik, 'match_hooks')
        if not params.spline_ik.match_hooks:
            cls.draw_prop(context, layout, params.spline_ik, 'hooks')


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
        description="For each original bone, create this many deform bones in the spline chain (Bendy Bones do not work well with Spline IK, so we create real bones) NOTE: Spline IK only supports 255 bones in the chain",
        default=3,
        min=1,
        max=99,
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


RIG_COMPONENT_CLASS = Component_Curve_SplineIK
