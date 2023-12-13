# SPDX-License-Identifier: GPL-2.0-or-later

from typing import Optional, List, Dict, Tuple
from bpy.types import Action, Mesh, Armature, Object
from bl_math import clamp

from rigify.utils.naming import Side, get_name_side, change_name_side, mirror_name
from rigify.utils.mechanism import driver_var_transform, quote_property, make_property, make_driver, make_constraint

class MetarigError(Exception):
    pass

class ActionSlotBase:
    """Abstract non-RNA base for the action list slots."""

    action: Optional[Action]
    enabled: bool
    symmetrical: bool
    subtarget: str
    transform_channel: str
    target_space: str
    frame_start: int
    frame_end: int
    trans_min: float
    trans_max: float
    is_corrective: bool
    trigger_action_a: Optional[Action]
    trigger_action_b: Optional[Action]

    ############################################
    # Action Constraint Setup

    @property
    def keyed_bone_names(self) -> List[str]:
        """Return a list of bone names that have keyframes in the Action of this Slot."""
        keyed_bones = []

        for fc in self.action.fcurves:
            # Extracting bone name from fcurve data path
            if fc.data_path.startswith('pose.bones["'):
                bone_name = fc.data_path[12:].split('"]')[0]

                if bone_name not in keyed_bones:
                    keyed_bones.append(bone_name)

        return keyed_bones

    @property
    def do_symmetry(self) -> bool:
        return self.symmetrical and get_name_side(self.subtarget) != Side.MIDDLE

    @property
    def default_side(self):
        return get_name_side(self.subtarget)

    def get_min_max(self, side=Side.MIDDLE) -> Tuple[float, float]:
        if side == -self.default_side:
            # Flip min/max in some cases - based on code of Paste Pose Flipped
            if self.transform_channel in ['LOCATION_X', 'ROTATION_Z', 'ROTATION_Y']:
                return -self.trans_min, -self.trans_max
        return self.trans_min, self.trans_max

    def get_factor_expression(self, var, side=Side.MIDDLE):
        assert not self.is_corrective

        trans_min, trans_max = self.get_min_max(side)

        if 'ROTATION' in self.transform_channel:
            var = f'({var}*180/pi)'

        return f'clamp(({var} - {trans_min:.4}) / {trans_max - trans_min:.4})'

    def get_trigger_expression(self, var_a, var_b):
        assert self.is_corrective

        return f'clamp({var_a} * {var_b})'

    ##################################
    # Default Frame

    def get_default_channel_value(self) -> float:
        # The default transformation value for rotation and location is 0, but for scale it's 1.
        return 1.0 if 'SCALE' in self.transform_channel else 0.0

    def get_default_factor(self, side=Side.MIDDLE, *, triggers=None) -> float:
        """Based on the transform channel, and transform range,
        calculate the evaluation factor in the default pose.
        """
        if self.is_corrective:
            if not triggers or None in triggers:
                return 0

            val_a, val_b = [trigger.get_default_factor(side) for trigger in triggers]

            return clamp(val_a * val_b)

        else:
            trans_min, trans_max = self.get_min_max(side)

            if trans_min == trans_max:
                # Avoid division by zero
                return 0

            def_val = self.get_default_channel_value()
            factor = (def_val - trans_min) / (trans_max - trans_min)

            return clamp(factor)

    def get_default_frame(self, side=Side.MIDDLE, *, triggers=None) -> float:
        """Based on the transform channel, frame range and transform range,
        we can calculate which frame within the action should have the keyframe
        which has the default pose.
        This is the frame which will be read when the transformation is at its default
        (so 1.0 for scale and 0.0 for loc/rot)
        """
        factor = self.get_default_factor(side, triggers=triggers)

        return self.frame_start * (1 - factor) + self.frame_end * factor

    def is_default_frame_integer(self) -> bool:
        default_frame = self.get_default_frame()

        return abs(default_frame - round(default_frame)) < 0.001


class ActionLayer:
    """An action constraint layer instance, applying an action to a symmetry side."""

    owner: 'ActionLayerComponent'
    slot: ActionSlotBase
    side: Side

    def __init__(self, owner, slot, side):
        self.owner = owner
        self.slot = slot
        self.side = side
        self.generator = owner.generator

        self.name = self._get_name()

        self.use_trigger = False

        if slot.is_corrective:
            trigger_a = self.owner.action_map[slot.trigger_action_a.name]
            trigger_b = self.owner.action_map[slot.trigger_action_b.name]

            self.trigger_a = trigger_a.get(side) or trigger_a.get(Side.MIDDLE)
            self.trigger_b = trigger_b.get(side) or trigger_b.get(Side.MIDDLE)

            self.trigger_a.use_trigger = True
            self.trigger_b.use_trigger = True

        else:
            self.bone_name = change_name_side(slot.subtarget, side)

        self.bones = self._filter_bones()

        self.owner.layers.append(self)

    @property
    def use_property(self):
        return self.slot.is_corrective or self.use_trigger

    def _get_name(self):
        name = self.slot.action.name

        if self.side == Side.LEFT:
            name += ".L"
        elif self.side == Side.RIGHT:
            name += ".R"

        return name

    def _filter_bones(self):
        controls = self._control_bones()
        bones = [bone for bone in self.slot.keyed_bone_names if bone not in controls]

        if self.side != Side.MIDDLE:
            bones = [
                name
                for name in bones
                if get_name_side(name) in (self.side, Side.MIDDLE)
            ]

        return bones

    def _control_bones(self):
        if self.slot.is_corrective:
            return self.trigger_a._control_bones() | self.trigger_b._control_bones()
        elif self.slot.do_symmetry:
            return {self.bone_name, mirror_name(self.bone_name)}
        else:
            return {self.bone_name}

    def create_custom_property(self):
        if self.use_property:
            factor = self.slot.get_default_factor(self.side)

            make_property(owner=self.generator.target_rig.pose.bones.get('root'), name=self.name, default=float(factor))

    def rig_bones_and_shape_keys(self):
        if self.slot.is_corrective and self.use_trigger:
            raise MetarigError(
                f"Corrective action used as trigger: {self.slot.action.name}"
            )

        if self.use_property:
            self.rig_input_driver(self.bone_name, quote_property(self.name))

        for bone_name in self.bones:
            self.rig_bone(bone_name)
        
        self.rig_child_shape_keys()

    def rig_bone(self, bone_name):
        if bone_name not in self.generator.target_rig.pose.bones:
            raise MetarigError(
                f"Bone '{bone_name}' from action '{self.slot.action.name}' not found"
            )

        if self.side != Side.MIDDLE and get_name_side(bone_name) == Side.MIDDLE:
            influence = 0.5
        else:
            influence = 1.0

        con = make_constraint(
            self.generator.target_rig.pose.bones[bone_name],
            'ACTION',
            name=f'Action {self.name}',
            insert_index=0,
            use_eval_time=True,
            action=self.slot.action,
            frame_start=self.slot.frame_start,
            frame_end=self.slot.frame_end,
            mix_mode='BEFORE_SPLIT',
            influence=influence,
        )

        self.rig_output_driver(con, 'eval_time')

    def rig_output_driver(self, obj, prop):
        if self.use_property:
            make_driver(
                obj, prop, variables=[(self.bone_name, self.name)]
            )
        else:
            self.rig_input_driver(obj, prop)

    def rig_input_driver(self, obj, prop):
        if self.slot.is_corrective:
            self.rig_corrective_driver(obj, prop)
        else:
            self.rig_factor_driver(obj, prop)

    def rig_corrective_driver(self, obj, prop):
        make_driver(
            obj,
            prop,
            expression=self.slot.get_trigger_expression('a', 'b'),
            variables={
                'a': (self.bone_name, self.trigger_a.name),
                'b': (self.bone_name, self.trigger_b.name),
            },
        )

    def rig_factor_driver(self, obj, prop):
        if self.side != Side.MIDDLE:
            control_name = change_name_side(self.slot.subtarget, self.side)
        else:
            control_name = self.slot.subtarget

        if control_name not in self.generator.target_rig.pose.bones:
            raise MetarigError(
                f"Control bone '{control_name}' for action '{self.slot.action.name}' not found"
            )

        channel = self.slot.transform_channel.replace("LOCATION", "LOC").replace(
            "ROTATION", "ROT"
        )

        make_driver(
            obj,
            prop,
            expression=self.slot.get_factor_expression('var', side=self.side),
            variables=[
                driver_var_transform(
                    self.generator.target_rig,
                    control_name,
                    type=channel,
                    space=self.slot.target_space,
                    rotation_mode='SWING_TWIST_Y',
                )
            ],
        )

    def rig_child_shape_keys(self):
        for child in self.owner.child_meshes:
            mesh: Mesh = child.data

            if mesh.shape_keys:
                for key_block in mesh.shape_keys.key_blocks[1:]:
                    if key_block.name == self.name:
                        self.rig_shape_key(key_block)

    def rig_shape_key(self, key_block):
        self.rig_output_driver(key_block, 'value')


class ActionLayerComponent:
    """
    An internal component
    Implements centralized generation of action layer constraints.
    """

    slot_list: List[ActionSlotBase]
    layers: List[ActionLayer]
    action_map: Dict[str, Dict[Side, ActionLayer]]
    child_meshes: List[Object]

    def __init__(self, generator):
        self.generator = generator
        metarig_data = generator.metarig.data
        self.slot_list = generator.params.action_slots
        self.layers = []

    def initialize(self):
        if self.slot_list:
            self.action_map = {}
            self.rigify_sub_objects = []

            # Generate layers for active valid slots
            action_slots = [
                slot for slot in self.slot_list if slot.enabled and slot.action
            ]

            # Constraints will be added in reverse order because each one is added to the top
            # of the stack when created. However, Before Original reverses the effective
            # order of transformations again, restoring the original sequence.
            for act_slot in self.sort_slots(action_slots):
                self.spawn_slot_layers(act_slot)

        self.store_child_meshes()

    @staticmethod
    def sort_slots(slots: List[ActionSlotBase]):
        indices = {slot.action.name: i for i, slot in enumerate(slots)}

        def action_key(action: Action):
            return indices.get(action.name, -1) if action else -1

        def slot_key(slot: ActionSlotBase):
            # Ensure corrective actions are added after their triggers.
            if slot.is_corrective:
                return max(
                    action_key(slot.action),
                    action_key(slot.trigger_action_a) + 0.5,
                    action_key(slot.trigger_action_b) + 0.5,
                )
            else:
                return action_key(slot.action)

        return sorted(slots, key=slot_key)

    def spawn_slot_layers(self, act_slot):
        name = act_slot.action.name

        if name in self.action_map:
            raise MetarigError(f"Action slot with duplicate action: {name}")

        if act_slot.is_corrective:
            if not act_slot.trigger_action_a or not act_slot.trigger_action_b:
                raise MetarigError(f"Action slot has missing triggers: {name}")

            trigger_a = self.action_map.get(act_slot.trigger_action_a.name)
            trigger_b = self.action_map.get(act_slot.trigger_action_b.name)

            if not trigger_a or not trigger_b:
                raise MetarigError(
                    f"Action slot references missing trigger slot(s): {name}"
                )

            symmetry = Side.LEFT in trigger_a or Side.LEFT in trigger_b

        else:
            symmetry = act_slot.do_symmetry

        if symmetry:
            self.action_map[name] = {
                Side.LEFT: ActionLayer(self, act_slot, Side.LEFT),
                Side.RIGHT: ActionLayer(self, act_slot, Side.RIGHT),
            }
        else:
            self.action_map[name] = {
                Side.MIDDLE: ActionLayer(self, act_slot, Side.MIDDLE)
            }

    def store_child_meshes(self):
        if self.layers:
            self.child_meshes = [
                child
                for child in self.generator.target_rig.children_recursive
                if child.type == 'MESH'
            ]
