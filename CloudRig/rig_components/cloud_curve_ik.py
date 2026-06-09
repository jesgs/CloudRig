# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from math import radians
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import ComponentParams, RigComponent

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import Context, UILayout

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.rig import calculate_ik_pole_vector
from .cloud_curve import Component_Curve_Hooked


class Component_Curve_IK_Hooked(Component_Curve_Hooked):
    """Curve hooks with an IK handle at the tip of each spline. Pose the tip
    with the IK handle, then refine the shape by animating the hooks."""

    ui_name = "Curve: IK with Hooks"
    parent_switch_behaviour = n_("The active parent will own the IK control(s).")
    parent_switch_overwrites_root_parent = False

    forced_params = {
        'curve.x_axis_symmetry': False,
    }

    ##############################
    # Inherited functions.

    def curve__initialize(self):
        """Defer initialization until create_bone_infos() if no curve is assigned yet."""
        if self.params.curve.target:
            super().curve__initialize()

    def create_bone_infos(self, context: Context):
        """Auto-generate the curve if missing, then build IK handles and pole controls for each spline."""
        if not self.params.curve.target:
            num_points = self.bone_count + 1 if self.params.spline_ik.match_hooks else self.params.spline_ik.hooks
            curve_ob = self.curve__create_curve_object(context)
            self.curve__reset_to_default_spline(
                curve_ob,
                num_points=num_points,
                handle_length=self.params.spline_ik.handle_length,
            )
            self.params.curve.target = curve_ob
            # Run the deferred parent initialization now that a curve exists.
            super().curve__initialize()

        super().create_bone_infos(context)
        if not getattr(self, 'hooks_of_splines', None):
            return

        self.ik_masters: list[BoneInfo] = []
        self.pole_ctrls: list[BoneInfo] = []

        for spline_idx, hooks in enumerate(self.hooks_of_splines):
            self.__make_ik_for_spline(spline_idx, hooks)

    @no_overlay
    def base__apply_parent_switching(
        self,
        *,
        _child_bone: BoneInfo | None = None,
        prop_bone: BoneInfo | None = None,
        _prop_name="",
        panel_name=n_("IK"),
        _row_name="",
        label_name=n_("Parent Switching"),
        _entry_name="",
    ):
        """Apply parent switching to each IK master"""
        for ik_master in getattr(self, 'ik_masters', []):
            super().base__apply_parent_switching(
                child_bone=ik_master,
                prop_bone=prop_bone,
                prop_name="ik_parents_" + ik_master.name,
                panel_name=panel_name,
                label_name=label_name,
                row_name=ik_master.name,
                entry_name=ik_master.name,
            )

    ##############################
    # IK Curve functions.

    def __make_ik_for_spline(self, spline_idx: int, hooks: list[BoneInfo]):
        """Build the IK mechanism chain, master control, optional pole, and reparent hooks for one spline."""
        if len(hooks) < 2:
            self.add_log(
                rpt_("Spline skipped for IK"),
                description=rpt_("Spline {idx} has fewer than 2 hooks, skipping IK handle.").format(idx=spline_idx),
            )
            return
        if self.params.curve.target.data.splines[spline_idx].use_cyclic_u:
            self.add_log(
                rpt_("Cyclic spline skipped for IK"),
                description=rpt_(
                    "Spline {idx} is cyclic, which has no clear tip for an "
                    "IK handle. Disable Cyclic on the curve to enable IK."
                ).format(idx=spline_idx),
            )
            return
        num_hooks = len(hooks)
        spline_root = hooks[0].parent  # curve root or spline root

        ik_chain = self.__make_ik_mech_chain(hooks, spline_root)

        ik_master = self.__make_ik_master(spline_idx, hooks)
        self.ik_masters.append(ik_master)
        ik_chain[-1].parent = ik_master

        pole_ctrl = None
        pole_angle_deg = 0.0  # only used when pole_ctrl is set
        if self.params.ik_chain.use_pole and num_hooks >= 3:
            pole_ctrl, pole_angle_deg = self.__make_pole_control(spline_idx, hooks, ik_chain)
            if pole_ctrl is not None:
                self.pole_ctrls.append(pole_ctrl)

        # IK constraint goes on the second-to-last mechanism bone,
        # targeting the last (which is parented to the IK master).
        ik_chain[-2].add_constraint(
            "IK",
            pole_target=self.target_rig if pole_ctrl else None,
            pole_subtarget=pole_ctrl.name if pole_ctrl else "",
            pole_angle=radians(pole_angle_deg) if pole_ctrl else 0,
            subtarget=ik_chain[-1].name,
            chain_count=num_hooks - 1,
        )

        # Reparent hooks so they ride on the IK-solved chain. Interior hooks
        # get a tangent bone that averages the rotation of the two neighboring
        # IK segments, so bezier handles bend smoothly through each point
        # instead of inheriting only the outgoing segment's rotation.
        self.__reparent_hooks_on_ik(hooks, ik_chain)

    def __make_ik_mech_chain(self, hooks: list[BoneInfo], root_parent: BoneInfo) -> list[BoneInfo]:
        """Create a chain of one IK mechanism bone per hook."""
        num_hooks = len(hooks)
        ik_chain: list[BoneInfo] = []
        for i, hook in enumerate(hooks):
            if i < num_hooks - 1:
                tail = hooks[i + 1].head.copy()
            else:
                prev_head = hooks[i - 1].head
                direction = (hook.head - prev_head).normalized()
                tail = hook.head + direction * hook.length

            ik_bone = self.bone_sets['IK Mechanism'].new(
                name=self.naming.add_prefix(hook.name, "IK-M"),
                source=hook,
                head=hook.head.copy(),
                tail=tail,
                parent=ik_chain[-1] if ik_chain else root_parent,
            )
            ik_bone.roll_align_other(hook)
            ik_chain.append(ik_bone)
        return ik_chain

    def __make_ik_master(self, spline_idx: int, hooks: list[BoneInfo]) -> BoneInfo:
        """Create the IK handle control positioned at the tip of the spline."""
        last_hook = hooks[-1]
        tip_head = last_hook.head.copy()
        direction = (last_hook.head - hooks[-2].head).normalized()
        tip_tail = tip_head + direction * last_hook.length

        ik_master_parent = self.generator.params.ensure_root
        if not ik_master_parent:
            ik_master_parent = hooks[0].parent

        ik_master = self.bone_sets['IK Controls'].new(
            name=self.__get_ik_name(spline_idx, "IK"),
            source=last_hook,
            head=tip_head,
            tail=tip_tail,
            parent=ik_master_parent,
            custom_shape_name=self.params.ik_chain.shape_ik_master.shape_name,
            use_custom_shape_bone_size=True,
            # source=last_hook may carry rotation locks from non-bezier hooks;
            # the user needs full rotation control on the IK handle.
            lock_rotation=[False, False, False],
        )
        ik_master.roll_align_other(last_hook)
        return ik_master

    def __make_pole_control(
        self,
        spline_idx: int,
        hooks: list[BoneInfo],
        ik_chain: list[BoneInfo],
    ) -> tuple[BoneInfo | None, float]:
        """Create the IK pole control and return it with the computed pole angle,
        or (None, 0.0) for straight chains.
        """
        pole_angle_deg, pole_vector, pole_location = calculate_ik_pole_vector(ik_chain[0], ik_chain[1])

        # A perfectly straight chain has no defined bend direction, so
        # calculate_ik_pole_vector returns a zero pole_vector. Skip the
        # pole and let the user introduce a bend if they want one.
        if pole_vector.length < 1e-6:
            self.add_log(
                rpt_("IK Pole skipped"),
                description=rpt_(
                    "Spline {idx} is a straight (collinear) chain — there's "
                    "no clear bend direction for an IK pole. Introduce a "
                    "slight bend in the curve to enable the pole."
                ).format(idx=spline_idx),
            )
            return None, 0.0

        pole_parent = self.generator.params.ensure_root
        if not pole_parent:
            pole_parent = hooks[0].parent

        pole_ctrl = self.create_ik_pole_control(
            bone_set=self.bone_sets['IK Controls'],
            name=self.__get_ik_name(spline_idx, "POLE"),
            pole_location=pole_location,
            pole_vector=pole_vector,
            pole_tail_length=hooks[0].length,
            elbow_bone=ik_chain[1],
            chain_root=ik_chain[0],
            custom_shape_name=self.params.ik_chain.shape_pole.shape_name,
            parent=pole_parent,
        )
        return pole_ctrl, pole_angle_deg

    def __reparent_hooks_on_ik(self, hooks: list[BoneInfo], ik_chain: list[BoneInfo]):
        """Reparent hooks onto the IK chain, inserting tangent-averaging bones at interior points."""
        num_hooks = len(hooks)
        for i, hook in enumerate(hooks):
            if 0 < i < num_hooks - 1:
                tan_bone = self.bone_sets['IK Mechanism'].new(
                    name=self.naming.add_prefix(hook.name, "TAN"),
                    source=hook,
                    parent=ik_chain[i],
                )
                # Armature constraint blends full transforms of the two
                # neighboring IK segments. Since both segments' rest poses
                # meet at hook[i], position stays correct; rotation becomes
                # the average of incoming and outgoing tangents. This
                # preserves the hook's rest orientation, which COPY_ROTATION
                # in REPLACE mode would otherwise overwrite and cause flips.
                tan_bone.add_constraint(
                    'ARMATURE',
                    use_deform_preserve_volume=True,
                    targets=[
                        {'subtarget': ik_chain[i - 1]},
                        {'subtarget': ik_chain[i]},
                    ],
                )
                hook.parent = tan_bone
            else:
                hook.parent = ik_chain[i]

    def __get_ik_name(self, spline_idx: int, prefix: str) -> str:
        """Build a prefixed bone name for IK bones, appending a spline index suffix for multi-spline curves."""
        spline_part = ""
        if len(self.params.curve.target.data.splines) > 1:
            spline_part = f"_{spline_idx}"

        suffix = self.side_suffix
        suffix_part = ""
        if suffix:
            suffix_part = self.naming.SUFFIX_SEPARATOR + suffix

        base = f"{self.base_name}{spline_part}{suffix_part}"
        return self.naming.add_prefix(base, prefix)

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        cls.define_bone_set(
            n_("IK Controls"),
            color_palette='THEME13',
            collections=["IK Controls"],
            wire_width=2.0,
        )
        cls.define_bone_set(
            n_("IK Mechanism"),
            collections=["Mechanism Bones"],
            is_advanced=True,
        )

    @classmethod
    def curve__draw_selector_ui(cls, layout: UILayout, context: Context, params: ComponentParams):
        # The curve is optional here — it'll be auto-generated if missing.
        curve_ob = params.curve.target
        # TODO: UI consistency - If we want to use an Add icon when a pointer wasn't specified yet, just do it
        # automatically inside draw_prop.
        icon = 'OUTLINER_OB_CURVE' if curve_ob else 'ADD'
        cls.draw_prop(context, layout, params.curve, 'target', icon=icon)

    @classmethod
    def draw_control_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_control_params(layout, context, component)
        params = component.params

        layout.separator()
        cls.draw_control_label(layout, iface_("IK"))
        cls.draw_prop(context, layout, params.ik_chain, 'use_pole')

        if not params.curve.target:
            layout.separator()
            cls.draw_control_label(layout, iface_("Auto-Generated Curve"))
            cls.draw_prop(context, layout, params.spline_ik, 'match_hooks')
            if not params.spline_ik.match_hooks:
                cls.draw_prop(context, layout, params.spline_ik, 'hooks')
            if cls.is_advanced_mode(context):
                cls.draw_prop(context, layout, params.spline_ik, 'handle_length')

    @classmethod
    def draw_appearance_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        layout.separator()
        cls.draw_prop_custom_shape(context, layout, params.ik_chain, 'shape_ik_master')
        if params.ik_chain.use_pole:
            cls.draw_prop_custom_shape(context, layout, params.ik_chain, 'shape_pole')


RIG_COMPONENT_CLASS = Component_Curve_IK_Hooked
