import bpy
from bpy.types import Object, Curve, PropertyGroup, BezierSplinePoint
from bpy.props import BoolProperty, StringProperty, PointerProperty
from mathutils import Matrix, Vector

from ..rig_component_features.bone import BoneInfo
from .cloud_base import Component_Base
from ..utils import curve as curve_utils


def is_curve(self, obj):
    return obj.type == 'CURVE'


def get_points(spline):
    return curve_utils.get_spline_points(spline)


def get_points_propname(spline):
    if spline.bezier_points:
        return 'bezier_points'
    return 'points'


class Component_Curve_Hooked(Component_Base):
    """Create hook controls for an existing bezier curve."""

    ui_name = "Curve: With Hooks"
    relinking_behaviour = "Constraints will be moved to the Curve Root."

    def initialize(self):
        """Gather and validate data about the rig."""
        super().initialize()
        self.initialize_curve_rig()

    def initialize_curve_rig(self):
        curve_ob = self.params.curve.target
        if not curve_ob:
            self.raise_generation_error("Curve object not found!")
        if curve_ob.type != 'CURVE':
            self.raise_generation_error("Curve target must be a curve!")

        if not self.params.curve.controls_for_handles:
            self.params.curve.rotatable_handles = False
            self.params.curve.separate_radius = False

        if len(curve_ob.data.splines) < 2:
            self.params.curve.root_per_spline = False

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.root_bone = self.bones_org[0].parent  # Should be allowed to be None!
        self.make_curve_controls()

    def relink(self):
        """Override cloud_base.
        Move constraints from the ORG to the ROOT bone and relink them.
        """
        org = self.bones_org[0]
        for c in org.constraint_infos[:]:
            self.root_bone.constraint_infos.append(c)
            org.constraint_infos.remove(c)
            c.relink()

    def make_curve_controls(self):
        if self.params.curve.create_root:
            self.make_curve_root_ctrl()
        self.make_ctrls_for_curve_points()

    def make_curve_root_ctrl(self):
        org_bone = self.bones_org[0]
        self.root_bone = self.bone_sets['Curve Root'].new(
            name=self.naming.add_prefix(self.base_bone_name, "ROOT"),
            source=org_bone,
            use_custom_shape_bone_size=True,
        )
        org_bone.parent = self.root_bone
        if org_bone.custom_shape:
            self.root_bone.copy_custom_shape(org_bone)
        else:
            self.root_bone.custom_shape_name = 'Cube'

    def make_ctrls_for_curve_points(self):
        curve_ob = self.params.curve.target

        # Function to convert a location vector in the curve's local space into world space.
        # For some reason this doesn't work when the curve object is parented to something, and we need it to be parented to the root bone kindof.
        # Use matrix_basis instead of matrix_world in case there are constraints on the curve.
        worldspace = lambda loc: (
            curve_ob.matrix_basis @ Matrix.Translation(loc)
        ).to_translation()

        self.all_hooks: list[list[BoneInfo]] = []
        for spline_idx, spline in enumerate(curve_ob.data.splines):
            parent_bone = self.root_bone
            if self.params.curve.root_per_spline:
                loc = curve_utils.get_spline_bounding_box_center(spline)
                loc_delta = self.params.curve.target.matrix_world.to_translation()
                dir = get_points(spline)[0].co - loc  # .normalized()
                spline_name = self.make_spline_name(spline_idx)
                if (
                    self.params.curve.x_axis_symmetry
                    and self.naming.side_is_left(spline_name) == None
                ):
                    dir = self.root_bone.vector
                spline_root = self.bone_sets['Spline Roots'].new(
                    name=spline_name,
                    source=self.root_bone,
                    head=loc + loc_delta,
                    tail=loc + loc_delta + dir,
                    parent=self.root_bone,
                    custom_shape_name='Cube',
                    inherit_scale=self.params.curve.inherit_scale,
                )
                spline_root.flatten()
                parent_bone = spline_root
            hooks = []
            points = get_points(spline)
            if len(points) < 2:
                self.raise_generation_error("Curve spline with <2 points")

            for i, cp in enumerate(points):
                is_bezier = type(cp) == BezierSplinePoint
                if is_bezier:
                    loc_left = cp.handle_left
                    loc_right = cp.handle_right
                else:
                    if i > 0:
                        delta = cp.co - points[i - 1].co
                    else:
                        delta = points[i + 1].co - cp.co

                    loc_left = cp.co + (delta) / 2
                    loc_right = cp.co - (delta) / 2

                # For some reason, non-bezier Spline points have 4 coordinates...
                loc_left = worldspace(Vector(loc_left[0:3]))
                loc_right = worldspace(Vector(loc_right[0:3]))

                hooks.append(
                    self.make_ctrls_for_curve_point(
                        loc=worldspace(cp.co),
                        loc_left=loc_left,
                        loc_right=loc_right,
                        spline_idx=spline_idx,
                        point_idx=i,
                        parent_bone=parent_bone,
                        is_bezier=is_bezier,
                        cyclic=spline.use_cyclic_u,
                    )
                )
            self.all_hooks.append(hooks)

    def get_x_axis_opposite_curve_point(
        self,
        curve: Curve,
        spline_idx: int,
        point_idx: int,
        threshold=0.01,
        must_exist=False,
    ) -> int:
        """Return spline point at the opposite side of this point.
        The curve must be perfectly symmetrical."""
        spline = curve.splines[spline_idx]
        spline_point = get_points(spline)[point_idx]
        opp_spline, opp_point_idx, offset = curve_utils.find_opposite_point_on_curve(
            curve, spline_idx, point_idx
        )
        opp_point = get_points(opp_spline)[opp_point_idx]

        if (opp_point == spline_point) and not must_exist:
            return spline, point_idx

        if offset > threshold:
            point_path = spline_point.path_from_id()
            opp_point_path = opp_point.path_from_id()
            point_name = ".".join(point_path.split(".")[0:])
            opp_point_name = ".".join(opp_point_path.split(".")[0:])
            self.raise_generation_error(
                description=f'The nearest point to the X-axis flipped coordinate of point "{point_name} ({curve.path_resolve(point_path).co})" is point "{opp_point_name} (({curve.path_resolve(opp_point_path).co}))".\n Distance: {offset}\n Threshold: {threshold}\nDistance must be lower than the threshold. Make sure the curve is symmetrical along its X axis. If this message keeps popping up, you might be modifying a shape key instead of the base shape.',
                description_short="Curve is not symmetrical",
                note=f"Curve must be symmetrical.",
            )
        return opp_spline, opp_point_idx

    def make_spline_name(self, spline_idx: int, prefix="") -> str:
        curve = self.params.curve.target.data
        spline = curve.splines[spline_idx]

        prefix_part = ""
        if prefix:
            prefix_part = "_" + prefix

        if self.params.curve.hook_name:
            hook_name = self.params.curve.hook_name
        else:
            hook_name = self.base_bone_name.replace("ORG-", "")

        spline_part = ""
        if len(self.params.curve.target.data.splines) > 1:
            spline_part = f"_{spline_idx}"
            if self.params.curve.x_axis_symmetry:
                # TODO: callling find_opposite_spline() for each spline is very inefficient!
                opp_spl_idx, opp_spl = curve_utils.find_opposite_spline(
                    curve, spline_idx
                )
                spline_part = "_" + str(min(spline_idx, opp_spl_idx))

        if self.params.curve.x_axis_symmetry:
            x_co = curve_utils.get_spline_bounding_box_center(spline).x
            if x_co > 0.001:
                suffix = ".L"
            elif x_co < -0.001:
                suffix = ".R"
            else:
                suffix = ""
        else:
            suffix = self.side_suffix
            if suffix != "":
                suffix = self.naming.suffix_separator + suffix

        return f"Spline{prefix_part}_{hook_name}{spline_part}{suffix}"

    def make_hook_name(self, spline_idx: int, point_idx: int, prefix="") -> str:
        spline_name = self.make_spline_name(spline_idx, prefix).replace(
            "Spline", "Hook"
        )
        prefixes, base, suffixes = self.naming.slice_name(spline_name)

        suffixes = list(set(suffixes))
        suffix = suffixes[0] if suffixes else ""

        assert len(suffixes) < 2, (
            "Hook control name should have max one suffix: " + spline_name
        )

        point_name = point_idx
        if self.params.curve.x_axis_symmetry:
            curve = self.params.curve.target.data
            opp_spline, opp_point_idx = self.get_x_axis_opposite_curve_point(
                curve, spline_idx, point_idx
            )
            opp_point = get_points(opp_spline)[opp_point_idx]
            point = get_points(curve.splines[spline_idx])[point_idx]

            if opp_point != point:
                point_name = min([point_idx, opp_point_idx])
                spline = curve.splines[spline_idx]
                x_co = get_points(spline)[point_idx].co.x
                if x_co > 0:
                    suffix = "L"
                elif x_co < 0:
                    suffix = "R"
            else:
                suffix = ""

        base += f"_{str(point_name).zfill(2)}"

        return self.naming.make_name(prefixes, base, [suffix])

    def make_ctrls_for_curve_point(
        self,
        loc: Vector,
        loc_left: Vector,
        loc_right: Vector,
        spline_idx: int,
        point_idx: int,
        parent_bone: BoneInfo,
        is_bezier=True,
        cyclic=False,
    ):
        """Create hook controls for a bezier curve point defined by three points (loc, loc_left, loc_right)."""

        tail = loc_left
        source_bone = self.bones_org[0]
        hook_ctr = self.bone_sets['Curve Hooks'].new(
            name=self.make_hook_name(spline_idx, point_idx),
            source=source_bone,
            use_custom_shape_bone_size=True,
            head=loc,
            tail=tail,
            parent=parent_bone,
            rotation_mode='YZX',
            inherit_scale=self.params.curve.inherit_scale,
            roll_type='ALIGN' if source_bone else "",
            roll_bone=source_bone,
            roll=0,
        )
        hook_ctr.invert_tilt = False
        if self.params.curve.x_axis_symmetry:
            opp_hook_ctr = self.generator.find_bone_info(
                self.naming.flipped_name(hook_ctr)
            )
            if opp_hook_ctr:
                hook_ctr.tail = opp_hook_ctr.tail * Vector([-1, 1, 1])
                hook_ctr.invert_tilt = True

        hook_ctr.spline_idx = spline_idx
        hook_ctr.left_handle_control = None
        hook_ctr.right_handle_control = None

        shape = 'Circle'
        if is_bezier and self.params.curve.controls_for_handles:
            shape = 'Curve_Point'
            self.make_bezier_handle_controls(
                hook_ctr, spline_idx, point_idx, loc, loc_left, loc_right, cyclic
            )

        hook_ctr.custom_shape_name = shape

        return hook_ctr

    def make_bezier_handle_controls(
        self, hook_ctr, spline_idx, point_idx, loc, loc_left, loc_right, cyclic
    ):
        handles = []

        if self.params.curve.separate_radius:
            radius_control = self.bone_sets['Curve Handles'].new(
                name=self.make_hook_name(spline_idx, point_idx, "Radius"),
                source=hook_ctr,
                tail=loc_left,
                use_custom_shape_bone_size=False,
                custom_shape_scale=0.8,
                parent=hook_ctr,
                custom_shape_name="Circle",
            )
            radius_control.length *= 0.8
            self.lock_transforms(
                radius_control, loc=True, rot=True, scale=[False, True, False]
            )
            if not self.params.curve.x_axis_symmetry:
                self.lock_transforms(
                    hook_ctr, loc=False, rot=False, scale=[True, False, True]
                )
            hook_ctr.radius_control = radius_control

        left_name = "L"
        right_name = "R"
        if self.params.curve.x_axis_symmetry and loc.x > 0:
            left_name, right_name = right_name, left_name
        if (point_idx != 0) or cyclic:
            # Skip for first hook unless cyclic.
            handle_left_ctr = self.bone_sets['Curve Handles'].new(
                name=self.make_hook_name(spline_idx, point_idx, left_name),
                source=hook_ctr,
                head=loc,
                tail=loc_left,
                parent=hook_ctr,
                custom_shape_name="Curve_Handle",
                use_custom_shape_bone_size=False,
                roll=0,
                roll_type='ALIGN',
                roll_bone=hook_ctr,
            )
            hook_ctr.left_handle_control = handle_left_ctr
            handles.append(handle_left_ctr)

        last_point_idx = (
            len(get_points(self.params.curve.target.data.splines[spline_idx])) - 1
        )

        if (point_idx != last_point_idx) or cyclic:
            # Skip for last hook unless cyclic.
            handle_right_ctr = self.bone_sets['Curve Handles'].new(
                name=self.make_hook_name(spline_idx, point_idx, right_name),
                source=hook_ctr,
                head=loc,
                tail=loc_right,
                parent=hook_ctr,
                roll=0,
                roll_type='ALIGN',
                roll_bone=hook_ctr,
                custom_shape_name="Curve_Handle",
                use_custom_shape_bone_size=False,
            )
            hook_ctr.right_handle_control = handle_right_ctr
            handles.append(handle_right_ctr)

        for handle in handles:
            handle.use_custom_shape_bone_size = True
            if self.params.curve.rotatable_handles:
                dsp_bone = self.create_dsp_bone(handle)
                dsp_bone.head = handle.tail.copy()
                dsp_bone.tail = handle.head.copy()

                self.lock_transforms(
                    handle, loc=False, rot=False, scale=[True, False, True]
                )

                dsp_bone.add_constraint('DAMPED_TRACK', subtarget=hook_ctr.name)
                dsp_bone.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)
            else:
                head = handle.head.copy()
                handle.head = handle.tail.copy()
                handle.tail = head

                self.lock_transforms(handle, loc=False)

                handle.add_constraint('DAMPED_TRACK', subtarget=hook_ctr.name)
                handle.add_constraint('STRETCH_TO', subtarget=hook_ctr.name)

        return handles

    def make_hook_modifier(
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
        for i in range(0, spline_i):
            idx_offset += len(get_points(curve_ob.data.splines[i])) * 3

        indices = []
        if is_bezier:
            if main_handle:
                indices.append(idx_offset + point_i * 3 + 1)
            if left_handle:
                indices.append(idx_offset + point_i * 3)
            if right_handle:
                indices.append(idx_offset + point_i * 3 + 2)
        else:
            indices = [point_i]

        # Set active bone
        bone = rig_ob.data.bones.get(bonename)
        rig_ob.data.bones.active = bone

        hook_m = curve_ob.modifiers.get(bonename)
        if not hook_m:
            for m in curve_ob.modifiers:
                if m.type == 'HOOK' and m.subtarget == bonename:
                    hook_m = m
                    break

        if not hook_m:
            # Add hook modifier
            hook_m = curve_ob.modifiers.new(name=bonename, type='HOOK')

        hook_m.vertex_indices_set(indices)
        hook_m.show_expanded = False
        hook_m.show_in_editmode = True
        hook_m.use_apply_on_spline = True

        hook_m.object = rig_ob
        hook_m.subtarget = bonename

    def create_helper_objects(self, context):
        self.setup_curve(self.all_hooks)
        super().create_helper_objects(context)

    def setup_curve(self, all_hooks: list[list[BoneInfo]]):
        """Configure the Hook Modifiers for the curve.
        all_hooks: List of List of BoneInfo objects that were created with make_ctrls_for_curve_point().
                        Each list corresponds to one curve spline.
        """

        curve_ob = self.params.curve.target
        if not curve_ob:
            self.raise_generation_error("Curve object not found!")
        curve_visible = self.ensure_visible(curve_ob)

        if not curve_ob.visible_get():
            self.raise_generation_error(
                f'Curve "{curve_ob.name}" could not be made visible. Perhaps it has a driver on its hide_viewport property that forces it to True?'
            )

        for spline_i, hooks in enumerate(all_hooks):
            self.setup_spline(curve_ob, spline_i, hooks)

        curve_visible.restore()

        self.params.curve.target = curve_ob

    def setup_spline(self, curve_ob: Object, spline_i: int, hooks: list[BoneInfo]):
        spline = curve_ob.data.splines[spline_i]
        points = get_points(spline)
        num_points = len(points)

        assert num_points == len(
            hooks
        ), f"Curve object {curve_ob.name} spline has {num_points} points, but {len(hooks)} hooks were passed."

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

        bpy.context.view_layer.update()

        for point_i in range(0, num_points):
            hook_b = hooks[point_i]
            shared_kwargs = {
                "rig_ob": self.target_rig,
                "curve_ob": self.params.curve.target,
                "spline_i": spline_i,
                "point_i": point_i,
                "is_bezier": type(points[0]) == BezierSplinePoint,
            }
            if not self.params.curve.controls_for_handles:
                self.make_hook_modifier(
                    bonename=hook_b.name,
                    main_handle=True,
                    left_handle=True,
                    right_handle=True,
                    **shared_kwargs,
                )
            else:
                self.make_hook_modifier(
                    bonename=hook_b.name,
                    main_handle=True,
                    **shared_kwargs,
                )
                if hook_b.left_handle_control:
                    self.make_hook_modifier(
                        bonename=hook_b.left_handle_control.name,
                        left_handle=True,
                        **shared_kwargs,
                    )
                if hook_b.right_handle_control:
                    self.make_hook_modifier(
                        bonename=hook_b.right_handle_control.name,
                        right_handle=True,
                        **shared_kwargs,
                    )

            # Add Radius driver
            data_path = f"splines[{hook_b.spline_idx}].{get_points_propname(spline)}[{point_i}].radius"
            curve_ob.data.driver_remove(data_path)

            D = curve_ob.data.driver_add(data_path)
            driver = D.driver

            driver.expression = "var"
            my_var = driver.variables.new()
            my_var.name = "var"
            my_var.type = 'TRANSFORMS'

            var_tgt = my_var.targets[0]
            var_tgt.id = self.target_rig
            var_tgt.transform_space = 'WORLD_SPACE'
            var_tgt.transform_type = 'SCALE_X'
            var_tgt.bone_target = hooks[point_i].name

            if self.params.curve.separate_radius:
                var_tgt.bone_target = hooks[point_i].radius_control.name

            # Add Tilt driver
            data_path = f"splines[{hook_b.spline_idx}].{get_points_propname(spline)}[{point_i}].tilt"
            curve_ob.data.driver_remove(data_path)

            D = curve_ob.data.driver_add(data_path)
            driver = D.driver

            if hook_b.invert_tilt:
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

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Curve Root', color_palette='THEME02')
        cls.define_bone_set('Spline Roots', color_palette='THEME03')
        cls.define_bone_set('Curve Hooks', color_palette='THEME01')
        cls.define_bone_set('Curve Handles', color_palette='THEME09')

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        # We only want to draw Curve Handles bone set UI if the option for it is enabled.
        if set_name == 'curve_handles':
            return params.curve.controls_for_handles
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def curve_selector_ui(cls, layout, context, params):
        """Since this rig requires a curve object, draw with alert=True otherwise."""
        curve_ob = params.curve.target
        bad_curve = curve_ob == None or curve_ob.type != 'CURVE'

        icon = 'ERROR' if bad_curve else 'OUTLINER_OB_CURVE'
        cls.draw_prop(context, layout, params.curve, 'target', icon=icon)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        curve_ob = params.curve.target
        cls.curve_selector_ui(layout, context, params)
        cls.draw_prop(context, layout, params.curve, 'create_root')
        if curve_ob and len(curve_ob.data.splines) > 1:
            cls.draw_prop(context, layout, params.curve, "root_per_spline")

        cls.draw_prop(context, layout, params.curve, "hook_name")
        cls.draw_prop(context, layout, params.curve, "inherit_scale")
        cls.draw_prop(context, layout, params.curve, "x_axis_symmetry")
        cls.draw_prop(context, layout, params.curve, "controls_for_handles")
        if params.curve.controls_for_handles:
            cls.draw_prop(context, layout, params.curve, "rotatable_handles")
            cls.draw_prop(context, layout, params.curve, "separate_radius")


class Params(PropertyGroup):
    create_root: BoolProperty(
        name="Create Root",
        description="Create a root bone for this rig component",
        default=True,
    )
    hook_name: StringProperty(
        name="Custom Name",
        description="Used in the naming of created bones and objects. If empty, use the base bone's name",
        default="",
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


RIG_COMPONENT_CLASS = Component_Curve_Hooked


def create_sample(obj):
    # load_sample_by_file(__file__)
    # load_sample_by_file() does not deal with additional dependent objects,
    # so we have to bring the curve object into the scene collection.
    curve_ob = bpy.data.objects.get(("cloud_curve", None))
    context = bpy.context
    context.scene.collection.objects.link(curve_ob)
    curve_ob.location = context.scene.cursor.location
