# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from mathutils import Vector
from bpy.types import PoseBone, ID, FCurve, Constraint, Object, Driver

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .bone_info import BoneInfo
    from ..rig_component_features.bone_set import BoneSet

from ..generation.naming import add_prefix


class CloudMechanismMixin:
    """Mixin class for rigging functions, using mostly the BoneInfo class."""

    def find_bone_info(self, name):
        return self.generator.find_bone_info(name)

    @staticmethod
    def find_component_chain_of_pbone(pose_bone):
        return find_component_chain_of_pbone(pose_bone)

    def get_component_pbone_chain(self):
        pose_bone = self.metarig.pose.bones.get(self.base_bone_name)
        return get_component_pbone_chain(pose_bone)

    def create_parent_bone(self, child, bone_set=None):
        return create_parent_bone(child, bone_set)

    def create_parent_constraint_holder(self, child, bone_set=None):
        return create_parent_constraint_holder(child, bone_set)

    def create_dsp_bone(self, parent, **kwargs):
        return create_dsp_bone(parent, self.bones_mch, **kwargs)

    def constrain_between_bones(self, child: BoneInfo, start: BoneInfo, end: BoneInfo, influence=0.5):
        child.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy Transforms (First)",
            space='WORLD',
            subtarget=start,
        )
        child.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy Transforms (Last)",
            space='WORLD',
            subtarget=end,
            influence=influence,
        )
        child.add_constraint('DAMPED_TRACK', subtarget=end)

    def make_def_bone(self, bone, bone_set):
        """Make a DEF- bone parented to bone."""
        def_bone = bone_set.new(
            name=self.naming.make_name(["DEF"], *self.naming.slice_name(bone.name)[1:]),
            source=bone,
            use_deform=True,
            parent=bone,
        )
        return def_bone

    def get_metarig_pbone(self, bone_name):
        """Find and return a bone in the metarig."""
        return self.generator.metarig.pose.bones.get(bone_name)

    @property
    def metarig_base_pbone(self):
        """Return pose bone in the metarig that has this component assigned."""
        return self.get_metarig_pbone(self.base_bone_name)

    def vector_along_bone_chain(self, chain, length=0, index=-1):
        return vector_along_bone_chain(chain, length, index)


def copy_relink_real_driver(
    src_id: ID, tgt_id: ID, fcurve: FCurve, data_path: str = None, index: int = None
) -> FCurve:
    """Copy a real driver to the target rig.
    Replace references to the metarig with the generated rig.
    May copy to a different data path than the source.
    """
    new_fcurve = copy_driver(fcurve, tgt_id, data_path, index)
    for var in new_fcurve.driver.variables:
        for tgt in var.targets:
            if tgt.id in (None, src_id) and tgt.id_type == tgt_id.id_type:
                tgt.id = tgt_id
        if "@" in var.name:
            split = var.name.split("@")
            var.name = split[0]
            for i, name in split[1:]:
                var.targets[i].bone_target = name
    return new_fcurve

def copy_driver(
    from_fcurve: FCurve, target: ID, data_path: str = None, index: int = None
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


def find_component_chain_of_pbone(pbone: PoseBone) -> list[PoseBone]:
    if pbone.cloudrig_component.component_type:
        return get_component_pbone_chain(pbone)
    if not pbone:
        return []

    return find_component_chain_of_pbone(pbone.parent)


def get_component_pbone_chain(pbone: PoseBone, connected=True) -> list[PoseBone]:
    """Find the chain of bones constituting a rig component that this pose bone belongs to."""

    # We start building a chain with the current bone, prepending bones as we go
    # UP in the hierarchy, until we find a connected bone with a component type.
    # If this never happens, this bone does not belong to any rig component.
    cur_pb = pbone
    chain: list[PoseBone] = []
    found = False
    while cur_pb:
        chain.insert(0, cur_pb)
        if cur_pb.cloudrig_component.component_type != "":
            found = True
            break
        cur_pb = cur_pb.parent

    if not found:
        return []

    # Go down in the hierarchy from the last bone, appending connected bones to the list.
    # NOTE: If one bone has multiple connected children and neither of them have
    # a component type, the chain becomes ambiguous. This case is not supported!
    cur_pb = chain[-1]
    while cur_pb and len(cur_pb.children) > 0:
        next_pb = None
        for child_pb in cur_pb.children:
            if child_pb.cloudrig_component.component_type == "":
                if connected and not child_pb.bone.use_connect:
                    continue
                if next_pb != None:
                    print(
                        f"""Warning: Branching connected bone chain for {pbone.name}: \n
                        \tChain could continue with either {next_pb.name} or {child_pb.name}. \n
                        \tPicking the first one arbitrarily! \n
                        \tDisconnect the bone or assign a component type to make it unambiguous."""
                    )
                else:
                    next_pb = child_pb
        if next_pb:
            chain.append(next_pb)
        cur_pb = next_pb
    return chain


def create_parent_bone(child: BoneInfo, bone_set: BoneSet=None) -> BoneInfo:
    """Copy a bone, prefix it with "P", make the bone shape a bit bigger and
    parent the bone to this copy."""
    if bone_set == None:
        bone_set = child.bone_set
    if child.parent_helper:
        # If it already exists, just return it.
        return child.parent_helper
    parent_bone = bone_set.new(
        name=add_prefix(child, "P"),
        source=child,
        parent=child.parent,
        roll_type='ALIGN',
        roll_bone=child,
        roll=0,
        custom_shape_name=child.custom_shape_name,
        custom_shape=child.custom_shape,
        custom_shape_scale_xyz=Vector(child.custom_shape_scale_xyz) * 1.2,
        custom_shape_translation=Vector(child.custom_shape_translation),
        use_custom_shape_bone_size=child.use_custom_shape_bone_size,
        custom_shape_rotation_euler=child.custom_shape_rotation_euler,
    )

    child.parent = parent_bone
    child.parent_helper = parent_bone
    return parent_bone


def create_parent_constraint_holder(child: BoneInfo, bone_set: BoneSet=None) -> BoneInfo:
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
        roll_type='ALIGN',
        roll_bone=parent,
        roll=0,
        bbone_width=parent.bbone_width * 0.5,
        custom_shape=None,
        parent=parent,
        **kwargs,
    )
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


def vector_along_bone_chain(
    chain: list[BoneInfo], length=0, index=-1
) -> tuple[Vector, Vector]:
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

    length_cumultative = 0
    for b in chain:
        if length_cumultative + b.length > length:
            length_remaining = length - length_cumultative
            direction = b.vector.normalized()
            loc = b.head + direction * length_remaining
            return (loc, direction)
        else:
            length_cumultative += b.length

    length_remaining = length - length_cumultative
    direction = chain[-1].vector.normalized()
    loc = chain[-1].tail + direction * length_remaining
    return (loc, direction)
