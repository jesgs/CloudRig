# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

from bpy.types import ID, Constraint, FCurve, PoseBone
from mathutils import Vector

if TYPE_CHECKING:
    from ..rig_component_features.bone_set import BoneSet
    from .bone_info import BoneInfo, ConstraintInfo

from ..generation.naming import add_prefix


class CloudMechanismMixin:
    """Mixin class for rigging functions, using mostly the BoneInfo class."""

    max_bones_in_chain = -1

    # Whether only connected bone children should be considered part of
    # this component, (and loaded into self.bones_org), or simply ALL children.
    only_connected_children = True

    def find_bone_info(self, name: str) -> BoneInfo | None:
        """Find and return a BoneInfo by name, or None if not found."""
        return self.generator.find_bone_info(name)

    def get_component_pbone_chain(self) -> list[PoseBone]:
        """Return the chain of pose bones assigned to this component."""
        pose_bone = self.metarig.pose.bones.get(self.base_bone_name)
        return pose_bone.cloudrig_component.component_pbone_chain

    def create_parent_bone(self, child: BoneInfo, bone_set: BoneSet | None = None) -> BoneInfo:
        return create_parent_bone(child, bone_set)

    def create_parent_constraint_holder(self, child: BoneInfo, bone_set: BoneSet | None = None) -> BoneInfo:
        return create_parent_constraint_holder(child, bone_set)

    def ensure_free_transforms(self, child: BoneInfo, bone_set: BoneSet | None = None) -> BoneInfo | None:
        def get_transform_drivers(bone: BoneInfo) -> list[tuple[str, int]]:
            """Return all driver refs on this bone that affect transforms."""
            drivers = []
            for driver_ref in bone.drivers_to_copy:
                data_path, array_index = driver_ref
                if any(
                    (
                        data_path.endswith(prop_name)
                        for prop_name in (
                            "location",
                            "rotation_euler",
                            "rotation_quaternion",
                            "rotation_axis_angle",
                            "rotation_mode",
                            "scale",
                        )
                    )
                ):
                    drivers.append((driver_ref))
            return drivers

        drivers = get_transform_drivers(child)
        if not drivers and not child.constraint_infos:
            # Transforms are already free, so this function doesn't need to do anything.
            return

        helper = create_parent_constraint_holder(child, bone_set)
        for driver_ref in drivers:
            helper.drivers_to_copy.append(driver_ref)
            child.drivers_to_copy.remove(driver_ref)
        return helper

    def create_dsp_bone(self, parent: BoneInfo, **kwargs) -> BoneInfo:
        """Create a display helper bone for the given parent bone."""
        return create_dsp_bone(parent, self.bones_mch, **kwargs)

    def constrain_between_bones(
        self, child: BoneInfo, start: BoneInfo, end: BoneInfo, influence=0.5
    ) -> tuple[ConstraintInfo, ConstraintInfo, ConstraintInfo]:
        """Constrain child to lie between start and end via Copy Transforms + Damped Track."""
        copy_first = child.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy Transforms (First)",
            space='WORLD',
            subtarget=start,
        )
        copy_last = child.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy Transforms (Last)",
            space='WORLD',
            subtarget=end,
            influence=influence,
        )
        dt_con = child.add_constraint('DAMPED_TRACK', subtarget=end)

        return copy_first, copy_last, dt_con

    def make_def_bone(self, parent_bone: BoneInfo, bone_name: str, bone_set: BoneSet) -> BoneInfo:
        """Make a DEF- bone parented to bone."""
        def_bone = bone_set.new(
            name=bone_name,
            source=parent_bone,
            use_deform=True,
            parent=parent_bone,
        )
        return def_bone

    def get_metarig_pbone(self, bone_name: str) -> PoseBone | None:
        """Find and return a bone in the metarig."""
        return self.generator.metarig.pose.bones.get(bone_name)

    @property
    def metarig_base_pbone(self) -> PoseBone | None:
        """Return pose bone in the metarig that has this component assigned."""
        return self.get_metarig_pbone(self.base_bone_name)

    def vector_along_bone_chain(self, chain: list[BoneInfo], length=0, index=-1) -> tuple[Vector, Vector]:
        """Delegate to the module-level vector_along_bone_chain."""
        return vector_along_bone_chain(chain, length, index)

    def create_ik_pole_control(
        self,
        bone_set: BoneSet,
        name: str,
        pole_location: Vector,
        pole_vector: Vector,
        pole_tail_length: float,
        elbow_bone: BoneInfo,
        chain_root: BoneInfo,
        custom_shape_name: str,
        parent: BoneInfo | None = None,
    ) -> BoneInfo:
        """Create an IK pole target control bone with an accompanying visual
        line that stretches from the pole to the chain's elbow.

        bone_set:         BoneSet to add the pole control + line into.
        name:             desired name for the pole control bone.
        pole_location:    rest position for the pole control's head, in world
                          space. Typically the third return value of
                          calculate_ik_pole_vector.
        pole_vector:      direction the pole's tail should point from its head;
                          typically the second return value of
                          calculate_ik_pole_vector.
        pole_tail_length: length of the pole control bone (sized for visibility).
        elbow_bone:       bone representing the IK chain's elbow joint at runtime
                          — the line's tail tracks this via STRETCH_TO.
        chain_root:       first bone of the IK chain. The pole control's roll is
                          aligned toward chain_root.head.
        custom_shape_name: custom shape for the pole control.
        parent:           optional parent for the pole control. When None, the
                          caller is expected to set a parent via parent-switching
                          after creation.

        Returns the created pole control bone.
        """
        pole_ctrl = bone_set.new(
            name=name,
            source=None,
            bbone_width=0.1,
            head=pole_location,
            tail=pole_location + pole_vector.normalized() * pole_tail_length,
            parent=parent,
            custom_shape_name=custom_shape_name,
            inherit_scale='AVERAGE',
            display_type='OCTAHEDRAL',
            use_custom_shape_bone_size=True,
        )
        pole_ctrl.roll_align_vector(chain_root.head)
        self.lock_transforms(pole_ctrl, loc=False)

        pole_line = bone_set.new(
            name=self.naming.add_prefix(pole_ctrl, "LINE"),
            source=pole_ctrl,
            tail=elbow_bone.head.copy(),
            parent=pole_ctrl,
            hide_select=True,
            custom_shape_name='Line',
            display_type='STICK',
            use_custom_shape_bone_size=True,
        )
        pole_line.add_constraint('STRETCH_TO', subtarget=elbow_bone.name)
        # Hide the line whenever the pole control is hidden.
        pole_line.drivers.append(
            {
                "prop": "hide",
                "variables": [
                    {
                        "type": "SINGLE_PROP",
                        "targets": [{"data_path": f'pose.bones["{pole_ctrl.name}"].hide'}],
                    }
                ],
            }
        )

        # Create a display helper that aims the pole target at the IK chain
        dsp_bone = self.create_dsp_bone(pole_ctrl)
        dsp_bone.add_constraint(
            "DAMPED_TRACK",
            subtarget=pole_line,
            head_tail=1.0,
            track_axis="TRACK_NEGATIVE_Y",
        )

        return pole_ctrl


def copy_relink_real_driver(
    src_id: ID,
    tgt_id: ID,
    fcurve: FCurve,
    data_path: str | None = None,
    index: int | None = None,
) -> FCurve:
    """Copy a real driver to the Target Rig.
    Replace references to the Metarig with the Target Rig.
    May copy to a different data path than the source.
    """
    new_fcurve = copy_driver(fcurve, tgt_id, data_path, index)
    relink_real_driver(src_id, tgt_id, new_fcurve)
    return new_fcurve


def relink_real_driver(src_id: ID, tgt_id: ID, new_fcurve: FCurve):
    """Anything that was targeting src_id or None should now target tgt_id.
    Any variable names which had an @ character in the name, should target a bone
    in tgt_id, whose name is provided after the @.
    """
    for var in new_fcurve.driver.variables:
        for tgt in var.targets:
            if tgt.id in (None, src_id) and tgt.id_type == tgt_id.id_type:
                tgt.id = tgt_id
        if "@" in var.name:
            split = var.name.split("@")
            var.name = split[0]
            for i, name in enumerate(split[1:]):
                var.targets[i].bone_target = name


def copy_driver(
    from_fcurve: FCurve,
    target: ID,
    data_path: str | None = None,
    index: int | None = None,
) -> FCurve:
    """Copy an existing FCurve containing a driver to a new ID, by creating a copy
    of the existing driver on the target ID.

    Args:
        from_fcurve: FCurve containing a driver
        target: ID that can have AnimationData
        data_path: Data Path of new driver. Defaults to copying the passed fcurve
        index: array index of the property to drive. Defaults to copying the passed fcurve

    Returns:
        FCurve: Fcurve with new driver on target ID
    """

    # Ensure anim data.
    if not target.animation_data:
        target.animation_data_create()

    # Remove old driver if it exists.
    tgt_drivers = target.animation_data.drivers
    if not data_path:
        data_path = from_fcurve.data_path
    if index not in {-1, None}:
        old_fcurve = tgt_drivers.find(data_path, index=index)
    else:
        old_fcurve = tgt_drivers.find(data_path)

    if old_fcurve:
        tgt_drivers.remove(old_fcurve)

    new_fcurve = tgt_drivers.from_existing(src_driver=from_fcurve)
    new_fcurve.data_path = data_path
    if index not in {None, -1}:
        new_fcurve.array_index = index

    return new_fcurve


def create_parent_bone(child: BoneInfo, bone_set: BoneSet | None = None) -> BoneInfo:
    """Copy a bone, prefix it with "P", make the bone shape a bit bigger and
    parent the bone to this copy."""
    if bone_set is None:
        bone_set = child.bone_set
    if child.parent_helper:
        # If it already exists, just return it.
        return child.parent_helper
    parent_bone = bone_set.new(
        name=add_prefix(child, "P"),
        source=child,
        parent=child.parent,
    )
    parent_bone.copy_custom_shape(child)
    parent_bone.custom_shape_scale = 1.2

    child.parent = parent_bone
    child.parent_helper = parent_bone
    return parent_bone


def create_parent_constraint_holder(child: BoneInfo, bone_set: BoneSet | None = None) -> BoneInfo:
    """Create a parent bone that takes over child's constraints, leaving child transform-free."""
    constrained_parent = create_parent_bone(
        child,
        bone_set=bone_set,
    )
    for con_info in child.constraint_infos[:]:
        if 'KEEP' not in con_info['name']:
            if con_info.type == 'ARMATURE':
                for existing in constrained_parent.constraint_infos:
                    if existing.type == 'ARMATURE':
                        constrained_parent.constraint_infos.remove(existing)
            constrained_parent.constraint_infos.append(con_info)
            child.constraint_infos.remove(con_info)

    return constrained_parent


def create_dsp_bone(parent: BoneInfo, bone_set: BoneSet, **kwargs) -> BoneInfo:
    """Create a bone to be used as another control's custom_shape_transform."""
    dsp_name = "DSP-" + parent.name
    dsp_bone = bone_set.new(
        name=dsp_name,
        source=parent,
        bbone_width=parent.bbone_width * 0.5,
        custom_shape=None,
        parent=parent,
        **kwargs,
    )
    dsp_bone.roll_align_other(parent)
    parent.custom_shape_transform = dsp_bone
    return dsp_bone


def find_or_create_constraint(pb: PoseBone, con_type: str, name=None) -> Constraint:
    """Create a constraint on a bone if it doesn't exist yet.
    If a constraint with the given type already exists, just return that.
    If a name was passed, also make sure the name matches before deeming it a match and returning it.
    pb: Must be a pose bone.
    """
    for con in pb.constraints:
        if con.type == con_type:
            if name:
                if con.name == name:
                    return con
            else:
                return con
    con = pb.constraints.new(type=con_type)
    if name:
        con.name = name
    return con


def vector_along_bone_chain(chain: list[BoneInfo], length=0, index=-1) -> tuple[Vector, Vector]:
    """On a bone chain, find the point a given length down the chain. Return its position and direction."""
    if index > -1:
        # Instead of using bone length, simply return the location and direction of a bone at a given index.

        # If the index is too high, return the tail of the bone.
        if index >= len(chain):
            b = chain[-1]
            return (b.tail.copy(), b.vector.normalized())

        b = chain[index]
        direction = b.vector.normalized()

        if index > 0:
            prev_bone = chain[index - 1]
            direction = (b.vector + prev_bone.vector).normalized()
        return (b.head.copy(), direction)

    length_cumulative = 0
    for b in chain:
        if length_cumulative + b.length > length:
            length_remaining = length - length_cumulative
            direction = b.vector.normalized()
            loc = b.head + direction * length_remaining
            return (loc, direction)
        else:
            length_cumulative += b.length

    length_remaining = length - length_cumulative
    direction = chain[-1].vector.normalized()
    loc = chain[-1].tail + direction * length_remaining
    return (loc, direction)
