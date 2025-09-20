# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Object
from ..rig_components.cloud_base import Component_Base


class TestAnimationGeneratorMixin:
    """Generator code for generating a "test animation", which is an animation
    riggers can use for weight painting assistance to test deformations.
    Rig components can define what keyframes they want to add to this animation.
    """

    ### Deform test animation generation
    def create_test_animation(self):
        """Generate deformation test animation.

        In order to generate the test animation, we need to call add_test_animation() on components
        in a different order than regular component execution, and we also want to account for symmetry.

        Usual rig execution is in order of hierarchical levels: highest level gets executed first,
        then all second level components, then all third level components.
        For the animation, we need a hierarchy to be executed all the way down before moving back up
        to any leftover siblings.

        Symmetrical components should animate at the same time, and with the Y and Z axis rotations flipped.
        """

        if not any(
            [
                hasattr(rig.params.fk_chain, 'test_animation_generate')
                and rig.params.fk_chain.test_animation_generate
                for rig in self.component_map.values()
            ]
        ):
            return

        action = ensure_test_action(self.metarig, self.target_rig)

        components_anim_order = []

        def add_component_hierarchy_to_animation_order(component):
            if (
                hasattr(type(component), 'has_test_animation')
                and type(component).has_test_animation
            ):
                components_anim_order.append(component)
            for child_comp in component.child_components:
                add_component_hierarchy_to_animation_order(child_comp)

        for root_component in self.root_components:
            add_component_hierarchy_to_animation_order(root_component)

        start_frame = 1
        for component in components_anim_order:
            symm_component = self.get_symmetry_rig_component(component)
            symm_new_start_frame = 1
            new_start_frame = component.add_test_animation(action, start_frame)
            if symm_component:
                symm_new_start_frame = symm_component.add_test_animation(
                    action, start_frame, flip_xyz=[False, True, True]
                )
                components_anim_order.remove(symm_component)
            start_frame = max(new_start_frame, symm_new_start_frame)

    def get_symmetry_rig_component(self, component: Component_Base) -> Component_Base | None:
        """Find another component in the generator with the opposite name as the one provided."""
        flipped_name = self.naming.flipped_name(component.base_bone_name)
        if flipped_name == component.base_bone_name:
            return

        for other_component in self.all_components:
            if other_component.base_bone_name == flipped_name:
                return other_component


def ensure_test_action(metarig: Object, target_rig: Object):
    # Ensure test action exists
    test_action = metarig.cloudrig.generator.test_action
    if not test_action:
        test_action = bpy.data.actions.new(
            "DeformTest-" + target_rig.name.replace("NEW-", "")
        )
        metarig.cloudrig.generator.test_action = test_action

    # Nuke all curves
    for fc in test_action.fcurves[:]:
        test_action.fcurves.remove(fc)

    if not target_rig.animation_data:
        target_rig.animation_data_create()

    if not target_rig.animation_data.action:
        target_rig.animation_data.action = test_action

    return test_action
