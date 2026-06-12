# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import ComponentParams, RigComponent

import bpy
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty, FloatProperty, PointerProperty
from bpy.types import BezierSplinePoint, Context, Curve, Object, PropertyGroup, Spline, UILayout
from mathutils import Matrix, Vector

from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.curve import (
    evaluate_point_tangents,
    find_opposite_point_on_curve,
    find_opposite_spline,
    get_spline_bounding_box_center,
    get_spline_points,
)
from .cloud_base import Component_Base


class Component_Curve_Hooked(Component_Base):
    """Create hook controls for an existing bezier curve."""

    ui_name = "Curve: With Hooks"
    use_base_name = True

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.curve__initialize()

    def create_bone_infos(self, context: Context):
        """Build the root bone and hook controls for each point on the curve's splines."""
        curve_ob = self.params.curve.target
        if not curve_ob:
            return

        self.check_object_in_scene(context, curve_ob, create_log=True)

        super().create_bone_infos(context)
        self.root_bone = self.bones_org[0].parent
        if self.params.curve.create_root:
            self.root_bone = self.curve__make_root()

        self.hooks_of_splines = self.curve__make_ctrls_for_points(curve_ob)

    def base__relink_get_target(self, org_i: int, con: ConstraintInfo) -> BoneInfo:
        """Return the curve root bone as the relink target for all ORG constraints."""
        return self.root_bone

    def create_helper_objects(self, context: Context):
        self.__hook_curve_to_rig(context, self.hooks_of_splines)
        super().create_helper_objects(context)

    ##############################
    # Curve functions.

    def curve__initialize(self):
        """Validate the curve target and pre-compute point tangents for roll alignment."""
        curve_ob = self.params.curve.target
        if not curve_ob:
            self.raise_generation_error(rpt_("Curve object not found!"))
            return
        if curve_ob.type != 'CURVE':
            self.raise_generation_error(rpt_("Curve target must be a curve!"))
            return

        if not self.params.curve.controls_for_handles:
            self.params.curve.rotatable_handles = False
            self.params.curve.separate_radius = False

        if len(curve_ob.data.splines) < 2:
            self.params.curve.root_per_spline = False

        self.point_tangents = evaluate_point_tangents(self.params.curve.target)

    def curve__make_root(self) -> BoneInfo:
        org_bone = self.bones_org[0]
        root_bone = self.bone_sets['Curve Root'].new(
            name=self.naming.add_prefix(self.base_bone_name, "ROOT"),
            source=org_bone,
            use_custom_shape_bone_size=True,
        )
        org_bone.parent = root_bone
        if org_bone.custom_shape:
            root_bone.copy_custom_shape(org_bone)
        else:
            root_bone.custom_shape_name = self.params.curve.shape_root.shape_name
        return root_bone

    @no_overlay
    def curve__create_curve_object(self, context: Context) -> Object:
        """Create an empty curve object suitable for use as the component's
        curve target. The object is named after the metarig + hook name,
        linked into the scene, has its transforms locked, and is set to 3D.
        Caller is responsible for populating its splines (e.g. via
        curve__reset_to_default_spline) and assigning it to params.curve.target.
        """
        curve_name = "CUR-" + self.generator.metarig.name.replace("META-", "")
        if self.params.base.base_name:
            curve_name += "_" + self.base_name

        curve_data = bpy.data.curves.new(curve_name, 'CURVE')
        curve_ob = bpy.data.objects.new(curve_name, curve_data)
        context.scene.collection.objects.link(curve_ob)
        self.lock_transforms(curve_ob)
        curve_data.dimensions = '3D'
        return curve_ob

    @no_overlay
    def curve__reset_to_default_spline(
        self,
        curve_ob: Object,
        num_points: int,
        handle_length: float = 0.4,
        point_indices: list[int] | None = None,
    ) -> Spline:
        """Replace curve_ob's splines with a single bezier spline whose points
        are distributed along the ORG bone chain.

        num_points: number of bezier points on the new spline (>= 2).
        handle_length: bezier handle length as a fraction of the per-segment
                       distance between points.
        point_indices: optional list of length num_points, one bone-chain
                       index per point — used when the caller wants each
                       curve point bound to a specific bone (e.g. Spline IK's
                       match_hooks mode). When None, points are auto-distributed
                       by length traveled along the chain.
        """
        curve_data = curve_ob.data
        # Coerce to 3D in case a user-assigned curve was 2D — bezier handles
        # in 3D space are required for the rig hooks to behave correctly.
        curve_data.dimensions = '3D'
        # Stale splines and hook modifiers from a previous generation prevent
        # the new layout from taking effect. Wipe them.
        for spline in curve_data.splines[:]:
            curve_data.splines.remove(spline)
        for m in curve_ob.modifiers[:]:
            if m.type == 'HOOK':
                curve_ob.modifiers.remove(m)

        spline = curve_data.splines.new(type='BEZIER')
        points = get_spline_points(spline)
        # A fresh bezier spline starts with one point.
        points.add(num_points - len(points))

        sum_bone_length = sum(b.length for b in self.bones_org)
        length_unit = sum_bone_length / (num_points - 1)
        handle_dist = length_unit * handle_length

        for i in range(num_points):
            point_along_chain = i * length_unit
            index = point_indices[i] if point_indices is not None else -1
            loc, direction = self.vector_along_bone_chain(self.bones_org, point_along_chain, index)
            p = points[i]
            p.co = loc
            p.handle_right = loc + handle_dist * direction
            p.handle_left = loc - handle_dist * direction

        return spline

    def curve__make_ctrls_for_points(self, curve_ob: Object) -> list[list[BoneInfo]]:
        """Create hook control bones for every point on every spline in the curve."""
        hooks_of_splines: list[list[BoneInfo]] = []

        if self.painter and not curve_ob:
            return hooks_of_splines

        for spline_idx, spline in enumerate(curve_ob.data.splines):
            parent_bone = self.root_bone
            if self.params.curve.root_per_spline:
                loc = get_spline_bounding_box_center(spline)
                object_offset = self.params.curve.target.matrix_world.to_translation()
                direction = (get_spline_points(spline)[0].co.xyz - loc).normalized()
                spline_name = self.__get_spline_name(spline_idx)
                if self.params.curve.x_axis_symmetry and self.naming.side_is_left(spline_name) is None:
                    direction = self.root_bone.vector
                spline_root = self.bone_sets['Spline Roots'].new(
                    name=spline_name,
                    source=self.root_bone,
                    head=loc + object_offset,
                    tail=loc + object_offset + direction * self.bones_org[0].length,
                    parent=self.root_bone,
                    custom_shape_name=self.params.curve.shape_spline_root.shape_name,
                    custom_shape_scale_xyz=Vector((1, 1, 1)) * self.bones_org[0].custom_shape_scale_xyz,
                    inherit_scale=self.params.curve.inherit_scale,
                )
                spline_root.flatten()
                parent_bone = spline_root
            hook_controls = []
            points = get_spline_points(spline)
            if len(points) < 2:
                self.raise_generation_error(rpt_("All curve splines must consist of at least 2 points"))

            for point_idx, _point in enumerate(points):
                hook_controls.append(
                    self.__make_ctrls_for_point(
                        spline_idx=spline_idx,
                        point_idx=point_idx,
                        parent_bone=parent_bone,
                    )
                )

            for i, hook in enumerate(hook_controls):
                if not hook.custom_data.get('is_bezier'):
                    if i + 1 < len(hook_controls):
                        bone_to_stretch = hook
                        subtarget = hook_controls[i + 1]
                    elif spline.use_cyclic_u:
                        dsp_helper = self.bone_sets['Mechanism Bones'].new(
                            source=hook,
                            parent=hook,
                            name=self.naming.add_prefix(hook.name, "DSP"),
                        )
                        hook.custom_shape_transform = dsp_helper
                        bone_to_stretch = dsp_helper
                        subtarget = hook_controls[0]
                    bone_to_stretch.add_constraint('STRETCH_TO', subtarget=subtarget)

            hooks_of_splines.append(hook_controls)

        return hooks_of_splines

    def __get_spline_name(self, spline_idx: int, prefix="") -> str:
        """Build a bone name for a spline root, including X-symmetry side suffix and spline index."""
        curve = self.params.curve.target.data
        spline = curve.splines[spline_idx]

        prefix_part = ""
        if prefix:
            prefix_part = "_" + prefix

        spline_part = ""
        if len(self.params.curve.target.data.splines) > 1:
            spline_part = f"_{spline_idx}"
            if self.params.curve.x_axis_symmetry:
                # NOTE: Callling find_opposite_spline() for each spline is arguably inefficient,
                # compared to making a mapping of opposites ahead of time.
                opp_spl_idx, opp_spl = find_opposite_spline(curve, spline_idx)
                spline_part = "_" + str(min(spline_idx, opp_spl_idx))

        if self.params.curve.x_axis_symmetry:
            x_co = get_spline_bounding_box_center(spline).x
            if x_co > 0.001:
                suffix = ".L"
            elif x_co < -0.001:
                suffix = ".R"
            else:
                suffix = ""
        else:
            suffix = self.side_suffix
            if suffix != "":
                suffix = self.naming.SUFFIX_SEPARATOR + suffix

        return f"Spline{prefix_part}_{self.base_name}{spline_part}{suffix}"

    def __get_mirror_point(
        self,
        curve: Curve,
        spline_idx: int,
        point_idx: int,
        threshold=0.01,
        must_exist=False,
    ) -> tuple[Spline, int]:
        """Return spline point at the opposite side of this point.
        The curve must be perfectly symmetrical."""
        spline = curve.splines[spline_idx]
        spline_point = get_spline_points(spline)[point_idx]
        opp_spline, opp_point_idx, offset = find_opposite_point_on_curve(curve, spline_idx, point_idx)
        opp_point = get_spline_points(opp_spline)[opp_point_idx]

        if (opp_point == spline_point) and not must_exist:
            return spline, point_idx

        if offset > threshold:
            point_path = spline_point.path_from_id()
            opp_point_path = opp_point.path_from_id()
            self.raise_generation_error(
                description=rpt_(
                    'The nearest point to the X-axis flipped coordinate of point '
                    '"{point_name} ({vector_a})" is point '
                    '"{opp_point_name} ({vector_b})".'
                    '\nDistance: {offset}\nThreshold: {threshold}\n'
                    'Distance must be lower than the threshold. Make sure the curve is symmetrical '
                    'along its X axis. If this message keeps popping up, you might be modifying '
                    'a shape key instead of the base shape.'
                ).format(
                    point_name=point_path,
                    vector_a=curve.path_resolve(point_path).co.xyz,
                    opp_point_name=opp_point_path,
                    vector_b=curve.path_resolve(opp_point_path).co.xyz,
                    offset=offset,
                    threshold=threshold,
                ),
                description_short="Curve is not symmetrical",
                note="Curve must be symmetrical.",
            )
        return opp_spline, opp_point_idx

    def __get_hook_name(self, spline_idx: int, point_idx: int, prefix="") -> str:
        """Build a bone name for a hook control, incorporating point index and X-symmetry suffix."""
        spline_name = self.__get_spline_name(spline_idx, prefix)
        hook_name = spline_name.replace("Spline", "Hook")
        prefixes, base, suffixes = self.naming.slice_name(hook_name)

        suffixes = list(set(suffixes))
        suffix = suffixes[0] if suffixes else ""

        assert len(suffixes) < 2, f"Hook name should have max 1 suffix: {hook_name}"

        idx_str = point_idx
        if self.params.curve.x_axis_symmetry:
            curve = self.params.curve.target.data
            spline = curve.splines[spline_idx]
            point = get_spline_points(spline)[point_idx]

            opp_spline, opp_point_idx = self.__get_mirror_point(curve, spline_idx, point_idx)
            opp_point = get_spline_points(opp_spline)[opp_point_idx]

            if opp_point != point:
                idx_str = min([point_idx, opp_point_idx])
                x_co = point.co.x
                if x_co > 0:
                    suffix = "L"
                elif x_co < 0:
                    suffix = "R"
            else:
                suffix = ""

        base += f"_{str(idx_str).zfill(2)}"

        return self.naming.make_name(prefixes, base, [suffix])

    def __make_ctrls_for_point(
        self,
        spline_idx: int,
        point_idx: int,
        parent_bone: BoneInfo,
    ) -> BoneInfo:
        """Create hook controls for a bezier curve point defined by three points (loc, loc_left, loc_right)."""

        curve_ob = self.params.curve.target
        spline = curve_ob.data.splines[spline_idx]
        cyclic = spline.use_cyclic_u
        points = get_spline_points(spline)
        point = points[point_idx]

        # Function to convert a location vector in the curve's local space into world space.
        # For some reason this doesn't work when the curve object is parented to something, and we need it to be parented to the root bone kindof.
        # Use matrix_basis instead of matrix_world in case there are constraints on the curve.
        def worldspace(loc: Vector):
            return (curve_ob.matrix_basis @ Matrix.Translation(loc.xyz)).to_translation()

        point_loc = worldspace(point.co.xyz)

        is_bezier = isinstance(point, BezierSplinePoint)
        if is_bezier:
            shape = self.params.curve.shape_bezier.shape_name
            left_handle_loc = worldspace(point.handle_left)
            right_handle_loc = worldspace(point.handle_right)
            tail = left_handle_loc
        else:
            shape = self.params.curve.shape_handle.shape_name
            if len(points) > point_idx + 1:
                tail = points[point_idx + 1].co.xyz
            elif cyclic:
                tail = points[0].co.xyz
            else:
                prev_point_co = points[point_idx - 1].co.xyz
                tail = point.co.xyz + (point.co.xyz - prev_point_co) / 5
                shape = self.params.curve.shape_point.shape_name

            tail = worldspace(tail)

        source_bone = self.bones_org[0]
        hook_ctr = self.bone_sets['Curve Hooks'].new(
            name=self.__get_hook_name(spline_idx, point_idx),
            source=source_bone,
            use_custom_shape_bone_size=True,
            custom_shape_scale_xyz=Vector((self.params.curve.shape_size, 1, self.params.curve.shape_size)),
            head=point_loc,
            tail=tail,
            parent=parent_bone,
            rotation_mode='YZX',
            inherit_scale=self.params.curve.inherit_scale,
        )
        if not is_bezier:
            hook_ctr.lock_rotation = [True, False, True]
        assert self.point_tangents
        hook_ctr.roll_align_vector(point_loc + self.point_tangents[spline_idx][point_idx])

        hook_ctr.custom_data['invert_tilt'] = False
        if self.params.curve.x_axis_symmetry:
            opp_hook_ctr = self.generator.find_bone_info(self.naming.flip_name(hook_ctr))
            if opp_hook_ctr and opp_hook_ctr != hook_ctr:
                hook_ctr.tail = opp_hook_ctr.tail * Vector((-1, 1, 1))
                hook_ctr.roll_flip()
                hook_ctr.custom_data['invert_tilt'] = True
        hook_ctr.custom_data['is_bezier'] = is_bezier

        hook_ctr.custom_data['spline_idx'] = spline_idx
        hook_ctr.custom_data['left_ctr'] = None
        hook_ctr.custom_data['right_ctr'] = None
        swap_em = False

        if is_bezier and self.params.curve.controls_for_handles:
            shape = self.params.curve.shape_bezier_center.shape_name
            if self.params.curve.x_axis_symmetry and point_loc.x > 0:
                left_handle_loc, right_handle_loc = right_handle_loc, left_handle_loc
                swap_em = True
            self.__make_ctrls_for_handles(
                hook_ctr, spline_idx, point_idx, point_loc, left_handle_loc, right_handle_loc, cyclic
            )
            if swap_em:
                hook_ctr.custom_data['left_ctr'], hook_ctr.custom_data['right_ctr'] = (
                    hook_ctr.custom_data['right_ctr'],
                    hook_ctr.custom_data['left_ctr'],
                )

        hook_ctr.custom_shape_name = shape

        return hook_ctr

    def __make_ctrls_for_handles(
        self,
        hook_ctr: BoneInfo,
        spline_idx: int,
        point_idx: int,
        loc: Vector,
        loc_left: Vector,
        loc_right: Vector,
        cyclic: bool,
    ) -> list[BoneInfo]:
        """Create left/right handle controls and an optional radius control for a bezier hook."""
        handles = []

        if self.params.curve.separate_radius:
            radius_control = self.bone_sets['Curve Handles'].new(
                name=self.__get_hook_name(spline_idx, point_idx, "Radius"),
                source=hook_ctr,
                parent=hook_ctr,
                custom_shape_name=self.params.curve.shape_radius.shape_name,
                use_custom_shape_bone_size=True,
            )
            radius_control.length *= 0.8
            self.lock_transforms(radius_control, loc=True, rot=True, scale=[False, True, False])
            self.lock_transforms(hook_ctr, loc=False, rot=False, scale=[True, False, True])
            hook_ctr.custom_data['radius_control'] = radius_control
            hook_ctr.custom_shape_transform = radius_control

        LEFT = "L"
        RIGHT = "R"
        left_handle_name = self.__get_hook_name(spline_idx, point_idx, LEFT)
        right_handle_name = self.__get_hook_name(spline_idx, point_idx, RIGHT)
        if self.params.curve.x_axis_symmetry and self.naming.side_is_left(hook_ctr) is None:
            # We're setting up the handles for the center-bone of a symmetrical spline.
            if loc_left.x < 0:
                LEFT, RIGHT = RIGHT, LEFT
            left_handle_name = self.__get_hook_name(spline_idx, point_idx) + "." + LEFT
            right_handle_name = self.__get_hook_name(spline_idx, point_idx) + "." + RIGHT

        if (point_idx != 0) or cyclic:
            # Skip for first hook unless cyclic.
            handle_left_ctr = self.bone_sets['Curve Handles'].new(
                name=left_handle_name,
                source=hook_ctr,
                head=loc,
                tail=loc_left,
                parent=hook_ctr,
                custom_shape_name=self.params.curve.shape_handle.shape_name,
                use_custom_shape_bone_size=True,
                inherit_scale='ALIGNED',
            )
            handle_left_ctr.reverse()
            handle_left_ctr.roll_align_other(hook_ctr)
            hook_ctr.custom_data['left_ctr'] = handle_left_ctr
            handles.append(handle_left_ctr)

        last_point_idx = len(get_spline_points(self.params.curve.target.data.splines[spline_idx])) - 1

        if (point_idx != last_point_idx) or cyclic:
            # Skip for last hook unless cyclic.
            handle_right_ctr = self.bone_sets['Curve Handles'].new(
                name=right_handle_name,
                source=hook_ctr,
                head=loc_right,
                tail=loc,
                parent=hook_ctr,
                custom_shape_name=self.params.curve.shape_handle.shape_name,
                use_custom_shape_bone_size=True,
                inherit_scale='ALIGNED',
            )
            hook_ctr.custom_data['right_ctr'] = handle_right_ctr
            handles.append(handle_right_ctr)

        for handle in handles:
            handle.use_custom_shape_bone_size = True
            if self.params.curve.rotatable_handles:
                dsp_bone = self.create_dsp_bone(handle)
                handle.reverse()

                self.lock_transforms(handle, loc=False, rot=False, scale=[True, False, True])

                dsp_bone.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)
            else:
                self.lock_transforms(handle, loc=False)

                handle.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)

        return handles

    def __hook_curve_to_rig(self, context: Context, hooks_of_splines: list[list[BoneInfo]]):
        """Configure the Hook Modifiers for the curve.
        hooks_of_splines: List of List of BoneInfo objects that were created with __make_ctrls_for_point().
                        Each list corresponds to one curve spline.
        """

        curve_ob = self.params.curve.target
        if not curve_ob:
            self.raise_generation_error(rpt_("Curve object not found!"))

        for mod in curve_ob.modifiers[:]:
            if mod.type == 'HOOK' and (not mod.object or mod.object == self.generator.params.target_rig):
                curve_ob.modifiers.remove(mod)

        for spline_i, hooks in enumerate(hooks_of_splines):
            self.__hook_spline_to_rig(context, curve_ob, spline_i, hooks)

        self.params.curve.target = curve_ob

    def __hook_spline_to_rig(self, context: Context, curve_ob: Object, spline_i: int, hooks: list[BoneInfo]):
        """Apply Hook modifiers and radius/tilt drivers for every point in one spline."""
        spline = curve_ob.data.splines[spline_i]
        points = get_spline_points(spline)
        num_points = len(points)

        assert num_points == len(hooks), (
            f"Curve object {curve_ob.name} spline has {num_points} points, but {len(hooks)} hooks were passed."
        )

        # Disable all modifiers on the curve object
        mod_vis_backup = {}
        for m in curve_ob.modifiers:
            mod_vis_backup[m.name] = m.show_viewport
            m.show_viewport = False

        # Disable all constraints on the curve object
        constraint_vis_backup = {}
        for c in curve_ob.constraints:
            constraint_vis_backup[c.name] = c.mute
            c.mute = True

        context.view_layer.update()

        for point_i in range(num_points):
            # For Beziers, handle type must be Aligned, otherwise rotations don't work.
            point = points[point_i]
            if hasattr(point, 'handle_left_type'):
                point.handle_left_type = 'ALIGNED'
                point.handle_right_type = 'ALIGNED'

            hook_b = hooks[point_i]
            shared_kwargs = {
                "rig_ob": self.target_rig,
                "curve_ob": self.params.curve.target,
                "spline_i": spline_i,
                "point_i": point_i,
                "is_bezier": isinstance(points[0], BezierSplinePoint),
            }
            if not self.params.curve.controls_for_handles:
                self.__hook_point_to_rig(
                    bonename=hook_b.name,
                    main_handle=True,
                    left_handle=True,
                    right_handle=True,
                    **shared_kwargs,
                )
            else:
                self.__hook_point_to_rig(
                    bonename=hook_b.name,
                    main_handle=True,
                    **shared_kwargs,
                )
                if hook_b.custom_data['left_ctr']:
                    self.__hook_point_to_rig(
                        bonename=hook_b.custom_data['left_ctr'].name,
                        left_handle=True,
                        **shared_kwargs,
                    )
                if hook_b.custom_data['right_ctr']:
                    self.__hook_point_to_rig(
                        bonename=hook_b.custom_data['right_ctr'].name,
                        right_handle=True,
                        **shared_kwargs,
                    )

            # Add Radius driver
            data_path = f"splines[{hook_b.custom_data['spline_idx']}].{get_points_propname(spline)}[{point_i}].radius"
            curve_ob.data.driver_remove(data_path)

            fc = curve_ob.data.driver_add(data_path)
            driver = fc.driver

            driver.expression = "var"
            my_var = driver.variables.new()
            my_var.name = "var"
            var_tgt = my_var.targets[0]
            var_tgt.id = self.target_rig

            # We have to implement Pose Space ourselves, since
            # Blender doesn't have that option for Drivers...
            my_var.type = 'SINGLE_PROP'
            var_tgt.data_path = f'pose.bones["{hooks[point_i].name}"].matrix'
            driver.expression = "var.to_scale().x"

            if self.params.curve.separate_radius and hooks[point_i].custom_data.get('radius_control'):
                var_tgt.data_path = f'pose.bones["{hooks[point_i].custom_data["radius_control"].name}"].matrix'

            # Add Tilt driver
            data_path = f"splines[{hook_b.custom_data['spline_idx']}].{get_points_propname(spline)}[{point_i}].tilt"
            curve_ob.data.driver_remove(data_path)

            fc = curve_ob.data.driver_add(data_path)
            driver = fc.driver

            if hook_b.custom_data.get('invert_tilt'):
                driver.expression = "var"
            else:
                driver.expression = "-var"
            my_var = driver.variables.new()
            my_var.name = "var"

            # Use Single Property instead of Transforms driver type, this allows
            # greater than 180 degree tilt control.
            var_tgt = my_var.targets[0]
            var_tgt.id = self.target_rig
            var_tgt.data_path = f'pose.bones["{hook_b.name}"].rotation_euler.y'
            var_tgt.bone_target = hooks[point_i].name

        # Restore modifier visibility on curve object
        for m in curve_ob.modifiers:
            if m.name in mod_vis_backup:
                m.show_viewport = mod_vis_backup[m.name]

        # Restore constraints visibility on the curve object
        for c in curve_ob.constraints:
            c.mute = constraint_vis_backup[c.name]

    def __hook_point_to_rig(
        self,
        rig_ob: Object,
        bonename: str,
        curve_ob: Object,
        spline_i: int,
        point_i: int,
        main_handle=False,
        left_handle=False,
        right_handle=False,
        is_bezier=True,
    ):
        """Create a Hook modifier on the curve(active object, in edit mode), hooking the control point at a given index to a given bone. The bone must exist."""
        if not bonename:
            return

        # Workaround of T74888: Re-grab references to curve object, splines and points.
        # A potential fix, D7190 was sadly rejected.
        curve_ob = self.params.curve.target
        idx_offset = 0
        for i in range(spline_i):
            spline = curve_ob.data.splines[i]
            num_points = len(get_spline_points(curve_ob.data.splines[i]))
            if spline.type == 'BEZIER':
                num_points *= 3
            idx_offset += num_points

        indices = []
        if is_bezier:
            if main_handle:
                indices.append(idx_offset + point_i * 3 + 1)
            if left_handle:
                indices.append(idx_offset + point_i * 3)
            if right_handle:
                indices.append(idx_offset + point_i * 3 + 2)
        else:
            indices = [idx_offset + point_i]

        # Set active bone
        bone = rig_ob.data.bones.get(bonename)
        rig_ob.data.bones.active = bone

        # Add hook modifier
        hook_m = curve_ob.modifiers.new(name=bonename + f" ({point_i})", type='HOOK')

        hook_m.vertex_indices_set(indices)
        hook_m.show_expanded = False
        hook_m.show_in_editmode = True
        hook_m.use_apply_on_spline = True

        hook_m.object = rig_ob
        hook_m.subtarget = bonename

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Curve Root"),
            color_palette='THEME02',
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Spline Roots"),
            color_palette='THEME12',
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("Curve Hooks"),
            color_palette='THEME01',
            wire_width=1.5,
        )
        cls.define_bone_set(
            n_("Curve Handles"),
            color_palette='THEME09',
            wire_width=1.0,
        )

    @classmethod
    def creates_spline_roots(cls, params: ComponentParams) -> bool:
        return params.curve.root_per_spline and params.curve.target and len(params.curve.target.data.splines) > 1

    @classmethod
    def is_bone_set_used(cls, context: Context, rig: Object, params: ComponentParams, set_name: str) -> bool:
        if set_name == 'curve_handles':
            return params.curve.controls_for_handles

        if set_name == 'curve_root':
            return params.curve.create_root

        if set_name == 'spline_roots':
            return cls.creates_spline_roots(params)

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def curve__draw_selector_ui(cls, layout: UILayout, context: Context, params: ComponentParams):
        """Since this component requires a curve object, draw with alert=True otherwise."""
        curve_ob = params.curve.target
        bad_curve = curve_ob is None or curve_ob.type != 'CURVE'

        icon = 'ERROR' if bad_curve else 'OUTLINER_OB_CURVE'
        cls.draw_prop(context, layout, params.curve, 'target', icon=icon)

    @classmethod
    def draw_control_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_control_params(layout, context, component)
        params = component.params
        cls.curve__draw_selector_ui(layout, context, params)
        curve_ob = params.curve.target
        if not curve_ob:
            return
        cls.draw_prop(context, layout, params.curve, 'create_root')
        if len(curve_ob.data.splines) > 1:
            cls.draw_prop(context, layout, params.curve, "root_per_spline")

        cls.draw_prop(context, layout, params.curve, "x_axis_symmetry")
        if curve_ob.data and any((spline.type == 'BEZIER' for spline in curve_ob.data.splines)):
            cls.draw_prop(context, layout, params.curve, "controls_for_handles")
            if params.curve.controls_for_handles:
                cls.draw_prop(context, layout, params.curve, "rotatable_handles")
                cls.draw_prop(context, layout, params.curve, "separate_radius")

        if cls.is_advanced_mode(context):
            cls.draw_prop(context, layout, params.curve, "inherit_scale")

    @classmethod
    def draw_appearance_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        curve_ob = params.curve.target
        if not curve_ob:
            layout.label(text="Select a curve object in the Controls parameters.")
            return
        if len(curve_ob.data.splines) == 0:
            layout.label(text="Selected curve has no splines!")
            return
        if params.curve.controls_for_handles:
            cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_bezier_center')
            cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_handle')
        else:
            is_bezier = isinstance(get_spline_points(curve_ob.data.splines[0])[0], BezierSplinePoint)
            if is_bezier:
                cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_bezier')
            else:
                cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_point')
        if cls.creates_spline_roots(params):
            cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_spline_root')
        if (
            any((spline.type == 'BEZIER' for spline in curve_ob.data.splines))
            and params.curve.controls_for_handles
            and params.curve.separate_radius
        ):
            cls.draw_prop_custom_shape(context, layout, params.curve, 'shape_radius')
        cls.draw_prop(context, layout, params.curve, 'shape_size', text="Size", enabled=component.appearance_enabled)


def is_curve(self, obj: Object) -> bool:
    """PointerProperty poll: filter to Curve objects only."""
    return obj.type == 'CURVE'


def get_points_propname(spline: Spline) -> str:
    if spline.bezier_points:
        return 'bezier_points'
    return 'points'


class Params(PropertyGroup):
    create_root: BoolProperty(
        name="Create Root",
        description="Create a root bone for this rig component",
        default=True,
    )
    controls_for_handles: BoolProperty(
        name="Controls for Handles",
        description="For every curve point control, create two children that control the handles of that curve point",
        default=False,
    )
    rotatable_handles: BoolProperty(
        name="Rotatable Handles",
        description="Use a setup which allows handles to be rotated and scaled - Will behave oddly when rotation is done after translation",
        default=False,
    )
    separate_radius: BoolProperty(
        name="Separate Radius Control",
        description="Create a separate control for controlling the curve points' radii, instead of using the hook control's scale",
        default=False,
    )
    x_axis_symmetry: BoolProperty(
        name="X Axis Symmetry",
        description="Controls will be named with .L/.R suffixes based on their X position. A curve object that is symmetrical around its own X 0 point is expected, otherwise results may be unexpected. Useful for character mouths",
        default=False,
    )
    root_per_spline: BoolProperty(
        name="Root Per Spline",
        description="This curve has more than one spline. Enable this option to create a root bone for each spline",
        default=False,
    )
    inherit_scale: Component_Base.make_inherit_scale_param(
        description="Scale inheritance setting of the curve hook and spline root controls",
        can_propagate=False,
    )

    target: PointerProperty(name="Curve", type=Object, poll=is_curve)

    shape_root: Component_Base.make_custom_shape_params(identifier="Curve Root", default="Cube")
    shape_point: Component_Base.make_custom_shape_params(identifier="Path Point", default="Square")
    shape_handle: Component_Base.make_custom_shape_params(identifier="Curve Handle", default="Handle")
    shape_bezier_center: Component_Base.make_custom_shape_params(identifier="Bezier Center", default="Circle")
    shape_bezier: Component_Base.make_custom_shape_params(identifier="Bezier", default="Bezier")
    shape_spline_root: Component_Base.make_custom_shape_params(identifier="Spline Root", default="Cube")
    shape_radius: Component_Base.make_custom_shape_params(identifier="Radius", default="Circle")
    shape_size: FloatProperty(
        name="Custom Shape Size",
        description="Size for curve custom shapes",
        default=1.0,
    )


RIG_COMPONENT_CLASS = Component_Curve_Hooked
