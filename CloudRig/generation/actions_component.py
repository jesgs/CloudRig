# SPDX-License-Identifier: GPL-3.0-or-later

# Originally designed and implemented by me (Demeter Dzadik),
# then re-written without functional changes for Rigify by Alexander Gavrilov.
# Then I threw away all my code, and modified his to fit into CloudRig again.

# The UI for these features are implemented in ui/actions_ui.py.

from __future__ import annotations

from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import Action, Mesh, Object
from bpy.utils import flip_name as mirror_name

from ..rig_component_features.properties_ui import make_property
from ..ui.actions_ui import ACTION_NAME_SEPARATOR, ActionConstraintSetup
from ..utils.mechanism import (
    driver_var_transform,
    make_constraint,
    make_driver,
    quote_property,
)
from ..utils.naming import Side, change_name_side, get_name_side
from .troubleshooting import LoggerMixin


class ActionConstraintSide(LoggerMixin):
    """An action constraint layer instance, applying an action to a symmetry side."""

    owner: ActionConstraintComponent
    action_setup: ActionConstraintSetup
    side: Side

    def __init__(self, owner, action_setup, side):
        self.owner = owner
        self.action_setup = action_setup
        self.side = side
        self.generator = owner.generator

        self.used_as_trigger = False

        if action_setup.is_corrective:
            if not (action_setup.trigger_a and action_setup.trigger_b):
                self.add_log(
                    rpt_("Missing trigger Action Setup"),
                    description=rpt_('Action Setup "{action}" references missing trigger setup').format(
                        action=action_setup.name
                    ),
                )
                return
            trigger_a = self.owner.action_setup_side_map[action_setup.trigger_a]
            trigger_b = self.owner.action_setup_side_map[action_setup.trigger_b]

            self.trigger_a = trigger_a.get(side) or trigger_a.get(Side.MIDDLE)
            self.trigger_b = trigger_b.get(side) or trigger_b.get(Side.MIDDLE)

            self.trigger_a.used_as_trigger = True
            self.trigger_b.used_as_trigger = True

            self.bone_name = change_name_side(self.trigger_a.action_setup.subtarget, side)
        else:
            self.bone_name = change_name_side(action_setup.subtarget, side)

        self.owner.layers.append(self)

    @property
    def use_property(self):
        return self.action_setup.is_corrective or self.used_as_trigger

    @property
    def control_name(self):
        if self.side != Side.MIDDLE:
            return change_name_side(self.action_setup.subtarget, self.side)
        else:
            return self.action_setup.subtarget

    @property
    def name(self):
        name = self.action_setup.name

        if self.side == Side.LEFT:
            name += ".L"
        elif self.side == Side.RIGHT:
            name += ".R"

        return name

    @property
    def bones(self) -> list[str]:
        controls = self.control_bones
        bones = [bone for bone in self.action_setup.keyed_bone_names if bone not in controls]

        if self.side != Side.MIDDLE:
            bones = [name for name in bones if get_name_side(name) in (self.side, Side.MIDDLE)]

        return bones

    @property
    def control_bones(self) -> set[str]:
        if self.action_setup.is_corrective:
            return self.trigger_a.control_bones | self.trigger_b.control_bones
        elif self.action_setup.do_symmetry:
            return {self.bone_name, mirror_name(self.bone_name)}
        else:
            return {self.bone_name}

    def create_custom_property(self):
        if self.use_property:
            factor = self.action_setup.get_default_factor(self.side)

            owner = self.generator.target_rig.pose.bones.get(self.bone_name)

            make_property(
                owner=owner,
                name=self.name,
                default=float(factor),
            )

    def rig_bones_and_shape_keys(self):
        if self.action_setup.is_corrective and self.used_as_trigger:
            self.add_log(
                rpt_("Corrective cannot be trigger"),
                description=rpt_(
                    'Corrective action "{action}" used as trigger. This is not currently supported.'
                ).format(action=self.action_setup.name),
            )
            # TODO: Why isn't this supported? Should be fine imo.
            return

        if not self.action_setup.is_corrective and self.control_name not in self.generator.target_rig.pose.bones:
            self.add_log(
                rpt_("Missing Action Control"),
                note=self.control_name,
                note_icon='BONE_DATA',
                description=rpt_("Control bone '{bone}' for action '{action}' not found").format(
                    bone=self.control_name, action=self.action_setup.name
                ),
            )
            return

        if self.use_property:
            self.rig_input_driver(
                self.generator.target_rig.pose.bones.get(self.bone_name),
                quote_property(self.name),
            )

        for bone_name in self.bones:
            self.rig_bone(bone_name)

        self.rig_child_shape_keys()

    def rig_bone(self, bone_name):
        if bone_name not in self.generator.target_rig.pose.bones:
            self.generator.logger.log(
                rpt_("Action constraint failed"),
                trouble_bone=bone_name,
                description=rpt_(
                    'Bone "{bone}" was not found, so it cannot get an Action constraint for `{action}`.'
                ).format(bone=bone_name, action=self.action_setup.name),
            )
            return

        if self.side != Side.MIDDLE and get_name_side(bone_name) == Side.MIDDLE:
            influence = 0.5
        else:
            influence = 1.0

        con_name = f'Action {self.name}'
        if len(con_name) > 61:
            con_name = self.name
        if len(con_name) > 61:
            con_name = self.action_setup.action_slot.name

        con = make_constraint(
            self.generator.target_rig.pose.bones[bone_name],
            'ACTION',
            name=con_name,
            insert_index=0,
            use_eval_time=True,
            action=self.action_setup.action,
            action_slot=self.action_setup.action_slot,
            frame_start=self.action_setup.frame_start,
            frame_end=self.action_setup.frame_end,
            mix_mode='BEFORE_SPLIT',
            influence=influence,
        )

        self.rig_output_driver(con, 'eval_time')

    def rig_output_driver(self, owner, prop_name):
        if self.use_property:
            make_driver(
                owner,
                prop_name,
                variables=[
                    (
                        self.generator.target_rig,
                        f'pose.bones["{self.bone_name}"]["{self.name}"]',
                    )
                ],
            )
        else:
            self.rig_input_driver(owner, prop_name)

    def rig_input_driver(self, owner, prop_name):
        if self.action_setup.is_corrective:
            self.rig_corrective_driver(owner, prop_name)
        else:
            self.rig_factor_driver(owner, prop_name)

    def rig_corrective_driver(self, owner, prop_name):
        make_driver(
            owner,
            prop_name,
            expression=self.action_setup.get_trigger_expression('a', 'b'),
            variables={
                'a': (
                    self.generator.target_rig,
                    f'pose.bones["{owner.name}"]["{self.trigger_a.name}"]',
                ),
                'b': (
                    self.generator.target_rig,
                    f'pose.bones["{self.trigger_b.bone_name}"]["{self.trigger_b.name}"]',
                ),
            },
        )

    def rig_factor_driver(self, owner, prop_name):
        channel = self.action_setup.transform_channel.replace("LOCATION", "LOC").replace("ROTATION", "ROT")

        make_driver(
            owner,
            prop_name,
            expression=self.action_setup.get_factor_expression('var', side=self.side),
            variables=[
                driver_var_transform(
                    self.generator.target_rig,
                    self.control_name,
                    type=channel,
                    space=self.action_setup.target_space,
                    rotation_mode='SWING_TWIST_Y',
                )
            ],
        )

    def rig_child_shape_keys(self):
        for child in self.owner.child_meshes:
            mesh: Mesh = child.data

            if mesh.shape_keys:
                for key_block in mesh.shape_keys.key_blocks[1:]:
                    if key_block.name in (self.name, self.name.rsplit(ACTION_NAME_SEPARATOR + " ")[-1]):
                        self.rig_shape_key(key_block)

    def rig_shape_key(self, key_block):
        self.rig_output_driver(key_block, 'value')


class ActionConstraintComponent(LoggerMixin):
    """
    An internal component
    Implements centralized generation of action constraints.
    """

    action_setups: list[ActionConstraintSetup]
    layers: list[ActionConstraintSide]
    action_map: dict[ActionConstraintSetup, dict[Side, ActionConstraintSide]]
    child_meshes: list[Object]

    def __init__(self, generator):
        self.action_setups = generator.params.action_setups
        self.layers = []
        self.generator = generator

        # Generate ActionConstraintSide for active valid slots.
        # This has to happen incrementally, because later entries
        # in the side map rely on previous entries having already been created.
        self.action_setup_side_map = {}
        if self.action_setups:
            valid_setups = [
                act_setup
                for act_setup in self.action_setups
                if act_setup.enabled and act_setup.action and act_setup.action_slot
                # TODO SLOTS: Probably make this an is_valid @property.
            ]

            # Constraints will be added in reverse order because each one is added to the top
            # of the stack when created. However, the Before Original mixing mode reverses the
            # effective order of transformations again, restoring the original sequence.
            for action_setup in self.sort_action_setups(valid_setups):
                self.action_setup_side_map[action_setup] = self.instantiate_action_setup_sides(action_setup)

        self.child_meshes = self.get_child_meshes()

    def get_child_meshes(self):
        if self.layers and self.generator.params.target_rig:
            return [child for child in self.generator.params.target_rig.children_recursive if child.type == 'MESH']
        return []

    @staticmethod
    def sort_action_setups(action_setups: list[ActionConstraintSetup]):
        indices = {action_setup.unique_id: i for i, action_setup in enumerate(action_setups)}

        def action_order(action_setup: ActionConstraintSetup) -> int:
            return indices.get(action_setup.unique_id, -1)

        def action_setup_order(action_setup: ActionConstraintSetup) -> float:
            # Ensure corrective actions are added AFTER their triggers.
            if action_setup.is_corrective:
                return max(
                    action_order(action_setup),
                    action_order(action_setup.trigger_a) + 0.5 if action_setup.trigger_a else 0,
                    action_order(action_setup.trigger_b) + 0.5 if action_setup.trigger_b else 0,
                )
            else:
                return action_order(action_setup)

        return sorted(action_setups, key=action_setup_order)

    def get_setups_by_action(self, action: Action) -> list[ActionConstraintSetup]:
        for action_setup in self.action_setups:
            if action_setup.action == action:
                yield action_setup

    def instantiate_action_setup_sides(self, action_setup: ActionConstraintSetup):
        if action_setup.is_corrective:
            if not action_setup.trigger_a or not action_setup.trigger_b:
                self.add_log(
                    rpt_("Missing trigger action"),
                    description=rpt_(
                        'Action Setup "{action}" is marked as corrective but missing at least one trigger selection.'
                    ).format(action=action_setup.name),
                )
                return

            symmetry = action_setup.trigger_a.do_symmetry or action_setup.trigger_b.do_symmetry

        else:
            symmetry = action_setup.do_symmetry

        if symmetry:
            return {
                Side.LEFT: ActionConstraintSide(self, action_setup, Side.LEFT),
                Side.RIGHT: ActionConstraintSide(self, action_setup, Side.RIGHT),
            }
        else:
            return {Side.MIDDLE: ActionConstraintSide(self, action_setup, Side.MIDDLE)}
