# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Action, ActionSlot, Object
from bpy_extras import anim_utils

from ..rig_components.cloud_base import Component_Base


class TestAnimationGeneratorMixin:
    """Generator code for generating a "test animation", which is an animation
    riggers can use for weight painting assistance to test deformations.
    Rig components can define what keyframes they want to add to this animation.
    """

    ### Deform test animation generation
    def components_create_test_animation(self):
        """Generate deformation test animation.

        In order to generate the test animation, we need to call fk_chain__add_test_animation() on components
        in a different order than regular component execution, and we also want to account for symmetry.

        Usual rig execution is in order of hierarchical levels: highest level gets executed first,
        then all second level components, then all third level components.
        For the animation, we need a hierarchy to be executed all the way down before moving back up
        to any leftover siblings.

        Symmetrical components should animate at the same time, and with the Y and Z axis rotations flipped.
        """

        if not any(
            (
                hasattr(rig.params.fk_chain, 'test_animation_generate') and rig.params.fk_chain.test_animation_generate
                for rig in self.component_map.values()
            )
        ):
            return

        action, slot = ensure_test_action(self.metarig, self.target_rig)

        components_anim_order = []

        def add_component_hierarchy_to_animation_order(component: Component_Base):
            if hasattr(type(component), 'has_test_animation') and type(component).has_test_animation:
                components_anim_order.append(component)
            for child_comp in component.child_components:
                add_component_hierarchy_to_animation_order(child_comp)

        for root_component in self.root_components:
            add_component_hierarchy_to_animation_order(root_component)

        start_frame = 1
        for component in components_anim_order:
            symm_component = self.get_symmetry_rig_component(component)
            new_start_frame = component.fk_chain__add_test_animation(action, slot, start_frame)
            if symm_component and symm_component in components_anim_order:
                symm_start_frame = symm_component.fk_chain__add_test_animation(
                    action, slot, start_frame, flip_xyz=[False, True, True]
                )
                components_anim_order.remove(symm_component)
                new_start_frame = max(new_start_frame, symm_start_frame)
            start_frame = new_start_frame

    def get_symmetry_rig_component(self, component: Component_Base) -> Component_Base | None:
        """Find another component in the generator with the opposite name as the one provided."""
        flipped_name = self.naming.flip_name(component.base_bone_name)
        if flipped_name == component.base_bone_name:
            return

        for other_component in self.all_components:
            if other_component.base_bone_name == flipped_name:
                return other_component


def ensure_test_action(metarig: Object, target_rig: Object) -> tuple[Action, ActionSlot]:
    """Ensure the test action and its slot exist, then wipe all existing FCurves from it."""
    # Ensure test action exists
    test_action = metarig.cloudrig.generator.test_action
    slot_name = "Test Action"
    if not test_action:
        test_action = bpy.data.actions.new("DeformTest-" + target_rig.name.replace("NEW-", ""))
        metarig.cloudrig.generator.test_action = test_action
    slot = test_action.slots.get(f'OB{slot_name}')
    if not slot:
        slot = test_action.slots.new(id_type='OBJECT', name=slot_name)

    # Nuke all curves.
    channelbag = anim_utils.action_get_channelbag_for_slot(action=test_action, slot=slot)
    if not channelbag:
        channelbag = anim_utils.action_ensure_channelbag_for_slot(test_action, slot)

    assert channelbag, f"Failed to find Channelbag of slot '{slot.name_display}' in Action '{test_action.name}'."

    for fc in channelbag.fcurves[:]:
        channelbag.fcurves.remove(fc)

    if not target_rig.animation_data:
        target_rig.animation_data_create()

    if not target_rig.animation_data.action:
        target_rig.animation_data.action = test_action
        target_rig.animation_data.action_slot = slot

    return test_action, slot
