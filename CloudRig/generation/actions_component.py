# SPDX-License-Identifier: GPL-3.0-or-later

# Originally designed and implemented by me (Demeter Dzadik),
# then re-written without functional changes for Rigify by Alexander Gavrilov.
# Then I threw away all my code, and modified his to fit into CloudRig again.

# The UI for these features are implemented in ui/actions_ui.py.

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .cloud_generator import CloudRig_Generator

import random
from math import degrees

import bpy
from bl_math import clamp
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import (
    Action,
    ActionChannelbag,
    ActionSlot,
    Context,
    FCurve,
    Mesh,
    Object,
    PropertyGroup,
    ShapeKey,
)
from bpy.utils import flip_name as mirror_name
from bpy_extras import anim_utils

from ..rig_component_features.properties_ui import make_property
from ..utils.mechanism import (
    driver_var_transform,
    make_constraint,
    make_driver,
    quote_property,
)
from ..utils.naming import Side, change_name_side, get_name_side
from .troubleshooting import LoggerMixin


ACTION_NAME_SEPARATOR = "➔"


def get_fcurve_transform_channel(fcurve: FCurve) -> str:
    """Return the transform channel that an FCurve affects, in a form that can be assigned to Action constraints."""
    if fcurve.data_path.endswith("location"):
        return "LOCATION_" + "XYZ"[fcurve.array_index]
    if (
        fcurve.data_path.endswith("rotation_euler") or fcurve.data_path.endswith("rotation_quaternion")
    ) and fcurve.array_index < 2:
        return "ROTATION_" + "XYZ"[fcurve.array_index]
    if fcurve.data_path.endswith("scale"):
        return "SCALE_" + "XYZ"[fcurve.array_index]
    return ""


def guess_action_setup_props(fcurves: list[FCurve]) -> tuple[str, int, int, float, float]:
    """Analyze the given fcurves to determine and return:
    - Transform channel of the f-curve with the greatest range of motion.
    - First and last frame across all fcurves.
    - Lowest and highest value across all fcurves.
    Useful to determine the properties of an Action constraint,
    if the passed fcurves are that of the Action's control bone.
    """
    min_frame = fcurves[0].keyframe_points[0].co.x
    max_frame = fcurves[0].keyframe_points[0].co.x
    max_value_range = (get_fcurve_transform_channel(fcurves[0]), 0, 0, 0)
    for fc in fcurves:
        if fc.array_index > 2:
            # We can't get anything useful out of W rotation of quats...
            continue
        min_value = fc.keyframe_points[0].co.y
        max_value = fc.keyframe_points[0].co.y
        for kf in fc.keyframe_points:
            if kf.co.y < min_value:
                min_value = kf.co.y
            if kf.co.y > max_value:
                max_value = kf.co.y
            if kf.co.x < min_frame:
                min_frame = kf.co.x
            if kf.co.x > max_frame:
                max_frame = kf.co.x
        value_range = max_value - min_value
        if value_range > max_value_range[1]:
            max_value_range = (get_fcurve_transform_channel(fc), value_range, min_value, max_value)

    return max_value_range[0], int(min_frame), int(max_frame), max_value_range[2], max_value_range[3]


class ActionConstraintSetup(PropertyGroup):
    def update_ui(self, _context: Context):
        if not self.action:
            return
        # Initialize the unique ID the first time an Action is set.
        self.unique_id
        # Set the first slot if none are set.
        if self.action and self.action.slots and not self.action_slot:
            self.action_slot = self.action.slots[0]
        self['name'] = self.get_name_transform()

    action: PointerProperty(
        name="Action",
        type=Action,
        description="Action to apply to the rig via constraints",
        update=update_ui,
    )

    def slot_name_from_handle(self, curr_value: str, _is_set: bool) -> str:
        try:
            curr_value = int(curr_value)
        except ValueError:
            return ""
        action_slot = next((s for s in self.action.slots if s.handle == curr_value), None)
        if not action_slot:
            return ""
        return action_slot.name_display

    def slot_name_to_handle(self, new_value: str, _curr_value: str, _is_set: bool) -> str:
        action_slot = next(
            (s for s in self.action.slots if s.name_display == new_value and s.identifier.startswith("OB")), None
        )
        if not action_slot:
            return ""
        return str(action_slot.handle)

    action_slot_ui: StringProperty(
        name="Acion Slot",
        description="Slot of the Action to use for the Action Constraints",
        get_transform=slot_name_from_handle,
        set_transform=slot_name_to_handle,
        update=update_ui,
    )

    @property
    def unique_id(self) -> int:
        if not self.action and 'unique_id' not in self:
            return 0
        if 'unique_id' in self and self['unique_id'] != 0:
            return self.get('unique_id')
        self['unique_id'] = random.randint(0, 100_000_000)
        return self['unique_id']

    @property
    def action_slot(self) -> ActionSlot | None:
        return self.action.slots.get("OB" + self.action_slot_ui)

    @action_slot.setter
    def action_slot(self, slot: ActionSlot):
        if slot:
            self.action_slot_ui = slot.name_display

    def get_name_transform(self):
        if self.action:
            name = self.action.name
            if self.action_slot and len(self.action.slots) > 1:
                return f"{name} {ACTION_NAME_SEPARATOR} {self.action_slot.name_display}"
        else:
            name = str(self.unique_id)
        return name

    name: StringProperty(get=get_name_transform) if bpy.app.version >= (5, 1, 0) else StringProperty()

    enabled: BoolProperty(
        name="Enabled",
        description="Create constraints for this action on the Target Rig",
        default=True,
    )

    symmetrical: BoolProperty(
        name="Symmetrical",
        description="Apply the same setup but mirrored to the opposite side control, shown in "
        "parentheses. Bones will only be affected by the control with the same side "
        "(eg., .L bones will only be affected by the .L control). Bones without a "
        "side in their name (so no .L or .R) will be affected by both controls "
        "with 0.5 influence each",
        default=True,
    )

    def update_subtarget(self, _context: Context):
        """Little UX sugar; We can take a pretty solid guess at the frame range,
        transform channel, and range, based on fcurves of the chosen bone in
        the chosen action slot.
        """
        channelbag = self.channelbag
        if not (channelbag and channelbag.fcurves):
            return

        fcurves_of_subtarget = [fc for fc in channelbag.fcurves if f'pose.bones["{self.subtarget}"]' in fc.data_path]
        transform_channel, min_frame, max_frame, value_min, value_max = guess_action_setup_props(
            fcurves_of_subtarget or channelbag.fcurves
        )

        self.frame_start = int(min_frame)
        self.frame_end = int(max_frame)

        if not fcurves_of_subtarget:
            # If the use didn't key the control bone, then we can't deduce the transform limits.
            return

        if 'ROTATION' in transform_channel:
            value_max = degrees(value_max)
            value_min = degrees(value_min)

        self.transform_channel = transform_channel or 'LOCATION_X'
        if abs(value_min) < abs(value_max):
            self.trans_min = value_min
            self.trans_max = value_max
        else:
            self.trans_min = value_max
            self.trans_max = value_min

    subtarget: StringProperty(
        name="Control Bone",
        description="Select a bone on the Target Rig which will drive this action",
        update=update_subtarget,
    )

    transform_channel: EnumProperty(
        name="Transform Channel",
        items=[
            ("LOCATION_X", "X Location", "X Location"),
            ("LOCATION_Y", "Y Location", "Y Location"),
            ("LOCATION_Z", "Z Location", "Z Location"),
            ("ROTATION_X", "X Rotation", "X Rotation"),
            ("ROTATION_Y", "Y Rotation", "Y Rotation"),
            ("ROTATION_Z", "Z Rotation", "Z Rotation"),
            ("SCALE_X", "X Scale", "X Scale"),
            ("SCALE_Y", "Y Scale", "Y Scale"),
            ("SCALE_Z", "Z Scale", "Z Scale"),
        ],
        description="Transform channel",
        default="LOCATION_X",
    )

    target_space: EnumProperty(
        name="Transform Space",
        items=[
            ("WORLD", "World Space", "World Space"),
            ("POSE", "Pose Space", "Pose Space"),
            ("LOCAL_WITH_PARENT", "Local With Parent", "Local With Parent"),
            ("LOCAL", "Local Space", "Local Space"),
        ],
        default="LOCAL",
    )

    def update_frame_start(self, _context: Context):
        if self.frame_start > self.frame_end:
            self.frame_end = self.frame_start

    frame_start: IntProperty(
        name="Start Frame",
        description="First frame of the action's timeline",
        update=update_frame_start,
    )

    def update_frame_end(self, _context: Context):
        if self.frame_end < self.frame_start:
            self.frame_start = self.frame_end

    frame_end: IntProperty(
        name="End Frame",
        default=2,
        description="Last frame of the action's timeline",
        update=update_frame_end,
    )

    trans_min: FloatProperty(
        name="Min",
        default=-0.05,
        description="Value that the transformation value must reach to put the action's timeline "
        "to the first frame. Rotations are in degrees",
    )

    trans_max: FloatProperty(
        name="Max",
        default=0.05,
        description="Value that the transformation value must reach to put the action's timeline "
        "to the last frame. Rotations are in degrees",
    )

    def update_is_corrective(self, _context: Context):
        channelbag = self.channelbag
        if not (channelbag and channelbag.fcurves):
            return
        _chan, min_frame, max_frame, _vmin, _vmax = guess_action_setup_props(channelbag.fcurves)
        self.frame_start = min_frame
        self.frame_end = max_frame

    is_corrective: BoolProperty(
        name="Corrective",
        description="Indicate that this is a corrective action. Corrective actions will activate "
        "based on the activation of two other actions",
        update=update_is_corrective,
    )

    def setup_id_to_str(self, curr_value: str, _is_set: bool):
        try:
            curr_value = int(curr_value.rstrip('_'))
        except ValueError:
            return ""
        action_setups = self.id_data.cloudrig.generator.action_setups
        action_setup = next((setup for setup in action_setups if setup.unique_id == curr_value), None)
        if not action_setup:
            return ""
        return action_setup.name

    def setup_name_to_id(self, new_value: str, curr_value: str, _is_set: bool):
        action_setups = self.id_data.cloudrig.generator.action_setups
        action_setup = next((setup for setup in action_setups if setup.name == new_value), None)
        if not action_setup:
            return ""
        # NOTE: Workaround no longer needed in bpy.app.version(5, 2, 0)
        # Workaround for #346: RNA_property_as_string allocates the buffer using
        # RNA_property_string_length (stored value length) but RNA_property_string_get
        # writes the get_transform'd value, causing a heap overflow when the display name
        # is longer than the stored ID. Pad the stored ID with underscores to match the
        # name length so the allocated buffer is always large enough.
        return str(action_setup.unique_id).ljust(len(new_value), '_')

    trigger_select_a: StringProperty(
        name="Trigger A",
        description="Action Setup whose activation will trigger this setup as a corrective",
        get_transform=setup_id_to_str if bpy.app.version >= (5, 1, 0) else None,
        set_transform=setup_name_to_id if bpy.app.version >= (5, 1, 0) else None,
    )
    trigger_select_b: StringProperty(
        name="Trigger B",
        description="Action Setup whose activation will trigger this setup as a corrective",
        get_transform=setup_id_to_str if bpy.app.version >= (5, 1, 0) else None,
        set_transform=setup_name_to_id if bpy.app.version >= (5, 1, 0) else None,
    )

    @property
    def trigger_a(self) -> ActionConstraintSetup | None:
        action_setups = self.id_data.cloudrig.generator.action_setups
        return action_setups.get(self.trigger_select_a)

    @trigger_a.setter
    def trigger_a(self, action_setup: ActionConstraintSetup | None):
        self.trigger_select_a = action_setup.name if action_setup else ""

    @property
    def trigger_b(self) -> ActionConstraintSetup | None:
        action_setups = self.id_data.cloudrig.generator.action_setups
        return action_setups.get(self.trigger_select_b)

    @trigger_b.setter
    def trigger_b(self, action_setup: ActionConstraintSetup | None):
        self.trigger_select_b = action_setup.name if action_setup else ""

    @property
    def generator(self):
        return self.id_data.cloudrig.generator

    @property
    def corrective_slots(self) -> Iterator[ActionConstraintSetup]:
        """Return all corrective action setups targetting this setup."""
        for action_setup in self.generator.action_setups:
            if not action_setup.is_corrective:
                continue
            if action_setup.trigger_a == self:
                yield action_setup
            if action_setup.trigger_b == self:
                yield action_setup

    show_action_a: BoolProperty(name="Show Settings")
    show_action_b: BoolProperty(name="Show Settings")

    @property
    def channelbag(self) -> ActionChannelbag | None:
        return anim_utils.action_get_channelbag_for_slot(self.action, self.action_slot)

    @property
    def keyed_bone_names(self) -> list[str]:
        channelbag = self.channelbag
        if not channelbag:
            return []
        keyed_bones = []
        for fc in channelbag.fcurves:
            # Extracting bone name from fcurve data path
            if not fc.data_path.startswith('pose.bones["'):
                continue
            bone_name = fc.data_path.removeprefix('pose.bones["').split('"]')[0]
            if bone_name not in keyed_bones:
                keyed_bones.append(bone_name)
        return keyed_bones

    @property
    def do_symmetry(self) -> bool:
        return self.symmetrical and get_name_side(self.subtarget) != Side.MIDDLE

    @property
    def default_side(self) -> Side:
        return get_name_side(self.subtarget)

    def get_min_max(self, side=Side.MIDDLE) -> tuple[float, float]:
        if side == -self.default_side and side != Side.MIDDLE:
            # Flip min/max in some cases - based on code of Paste Pose Flipped
            if self.transform_channel in ['LOCATION_X', 'ROTATION_Z', 'ROTATION_Y']:
                return -self.trans_min, -self.trans_max
        return self.trans_min, self.trans_max

    def get_factor_expression(self, var_name: str, side=Side.MIDDLE):
        assert not self.is_corrective

        trans_min, trans_max = self.get_min_max(side)

        if 'ROTATION' in self.transform_channel:
            var_name = f'({var_name}*180/pi)'

        return f'clamp(({var_name} - {trans_min:.4}) / {trans_max - trans_min:.4})'

    def get_trigger_expression(self, var_a_name: str, var_b_name: str) -> str:
        assert self.is_corrective

        return f'clamp({var_a_name} * {var_b_name})'

    ##################################
    # Default Frame

    def get_default_channel_value(self) -> float:
        # The default transformation value for rotation and location is 0, but for scale it's 1.
        return 1.0 if 'SCALE' in self.transform_channel else 0.0

    def get_default_factor(self, side=Side.MIDDLE) -> float:
        """Based on the transform channel, and transform range,
        calculate the evaluation factor in the default pose.
        """
        if self.is_corrective:
            return 0

        trans_min, trans_max = self.get_min_max(side)

        if trans_min == trans_max:
            # Avoid division by zero
            return 0

        def_val = self.get_default_channel_value()
        factor = (def_val - trans_min) / (trans_max - trans_min)

        return clamp(factor)

    def get_default_frame(self, side=Side.MIDDLE) -> float:
        """Based on the transform channel, frame range and transform range,
        we can calculate which frame within the action should have the keyframe
        which has the default pose.
        This is the frame which will be read when the transformation is at its default
        (so 1.0 for scale and 0.0 for loc/rot)
        """
        factor = self.get_default_factor(side)

        return self.frame_start * (1 - factor) + self.frame_end * factor

    def is_default_frame_integer(self) -> bool:
        default_frame = self.get_default_frame()

        return abs(default_frame - round(default_frame)) < 0.001


registry = (ActionConstraintSetup,)


class ActionConstraintSide(LoggerMixin):
    """An action constraint layer instance, applying an action to a symmetry side."""

    owner: ActionConstraintComponent
    action_setup: ActionConstraintSetup
    side: Side

    def __init__(self, owner: ActionConstraintComponent, action_setup: ActionConstraintSetup, side: Side):
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
            trigger_a = self.owner.action_setup_side_map.get(action_setup.trigger_a)
            trigger_b = self.owner.action_setup_side_map.get(action_setup.trigger_b)

            if trigger_a is None or trigger_b is None:
                raise RuntimeError(
                    f'Action Setup "{action_setup.name}" references a trigger that failed to initialize. This is a bug.'
                )

            self.trigger_a = trigger_a.get(side) or trigger_a.get(Side.MIDDLE)
            self.trigger_b = trigger_b.get(side) or trigger_b.get(Side.MIDDLE)

            self.trigger_a.used_as_trigger = True
            self.trigger_b.used_as_trigger = True

            self.bone_name = change_name_side(self.trigger_a.action_setup.subtarget, side)
        else:
            self.bone_name = change_name_side(action_setup.subtarget, side)

        self.owner.layers.append(self)

    @property
    def use_property(self) -> bool:
        return self.action_setup.is_corrective or self.used_as_trigger

    @property
    def control_name(self) -> str:
        if self.side != Side.MIDDLE:
            return change_name_side(self.action_setup.subtarget, self.side)
        else:
            return self.action_setup.subtarget

    @property
    def name(self) -> str:
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

    def rig_bone(self, bone_name: str):
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

    def rig_output_driver(self, owner: Any, prop_name: str):
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

    def rig_input_driver(self, owner: Any, prop_name: str):
        if self.action_setup.is_corrective:
            self.rig_corrective_driver(owner, prop_name)
        else:
            self.rig_factor_driver(owner, prop_name)

    def rig_corrective_driver(self, owner: Any, prop_name: str):
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

    def rig_factor_driver(self, owner: Any, prop_name: str):
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

    def rig_shape_key(self, key_block: ShapeKey):
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

    def __init__(self, generator: CloudRig_Generator):
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

    def get_child_meshes(self) -> list[Object]:
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
            return action_order(action_setup)

        return sorted(action_setups, key=action_setup_order)

    def get_setups_by_action(self, action: Action) -> Iterator[ActionConstraintSetup]:
        for action_setup in self.action_setups:
            if action_setup.action == action:
                yield action_setup

    def instantiate_action_setup_sides(
        self, action_setup: ActionConstraintSetup
    ) -> dict[Side, ActionConstraintSide] | None:
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
