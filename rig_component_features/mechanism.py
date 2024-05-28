from typing import Tuple, List

import bpy
from mathutils import Vector
from bpy.types import ID, FCurve

from ..rig_component_features.bone import BoneInfo
from ..generation.naming import slice_name, make_name


class CloudMechanismMixin:
    """Mixin class for rigging functions, using mostly the BoneInfo class."""

    def find_bone_info(self, name):
        return self.generator.find_bone_info(name)

    @staticmethod
    def find_component_chain_of_pbone(pose_bone):
        return find_component_chain_of_pbone(pose_bone)

    def get_component_pbone_chain(self):
        # TODO 4.0: This could be moved to the RigComponent RNA class.
        pose_bone = self.metarig.pose.bones.get(self.base_bone_name)
        return get_component_pbone_chain(pose_bone)

    def create_parent_bone(self, child, bone_set=None):
        return create_parent_bone(child, bone_set)

    def create_dsp_bone(self, parent):
        return create_dsp_bone(parent, self.bones_mch)

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
        """Return pose bone in the metarig that has this rig type assigned."""
        return self.get_metarig_pbone(self.base_bone_name)

    def vector_along_bone_chain(self, chain, length=0, index=-1):
        return vector_along_bone_chain(chain, length, index)

    def relink_driver_info(self, driver_info):
        relink_driver_info(self.metarig, self.target_rig, driver_info)

    def transfer_relink_driver_info(self, from_bone: BoneInfo, to_bone: BoneInfo):
        """Transfer and relink drivers from one bone to another."""
        for d in from_bone.drivers[:]:
            to_bone.drivers.append(d)
            from_bone.drivers.remove(d)
            self.relink_driver_info(d)


def relink_driver_info(metarig, rig, driver_info):
    """Adjust drivers read from the metarig according to some conventions:

    An empty target object or the metarig as the target object will be replaced
    with the generated rig.
    Variable names with @ in them will be split by the @, and the part after the
    @ will be the target bone name.
    """
    for var_info in driver_info['variables']:
        if type(var_info) == tuple:
            break
        if 'name' in var_info and '@' in var_info['name']:
            splits = var_info['name'].split("@")
            var_info['name'] = splits[0]
            for i, t in enumerate(var_info['targets']):
                var_info['targets'][i]['bone_target'] = splits[i + 1]
        for i, t in enumerate(var_info['targets']):
            if 'id' in t and (t['id'] == None or t['id'] == metarig):
                t['id'] = rig


def find_component_chain_of_pbone(pose_bone) -> List[bpy.types.PoseBone]:
    if pose_bone.cloudrig_component.component_type:
        return get_component_pbone_chain(pose_bone)
    if not pose_bone:
        return None

    return find_component_chain_of_pbone(pose_bone.parent)


def get_component_pbone_chain(pose_bone, connected=True) -> List[bpy.types.Bone]:
    """Find the chain of bones constituting a rig component that this pose bone belongs to."""

    # We start building a chain with the current bone, prepending bones as we go
    # UP in the hierarchy, until we find a connected bone with a component type.
    # If this never happens, this bone does not belong to any rig component.
    cur_pb = pose_bone
    chain = []
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
                        f"""Warning: Branching connected bone chain for {pose_bone.name}: \n
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


def get_bone_chain(start_bone):
    bones = [start_bone]
    if type(start_bone) == bpy.types.PoseBone:
        bones = [start_bone.bone]
    has_connected_children = True
    while has_connected_children:
        # Find first connected child
        has_connected_children = False
        for c in bones[-1].children:
            if c.use_connect:
                bones.append(c)
                has_connected_children = True
                break
    return bones


def create_parent_bone(child, bone_set=None):
    """Copy a bone, prefix it with "P", make the bone shape a bit bigger and
    parent the bone to this copy."""
    sliced = slice_name(child.name)
    sliced[0].append("P")
    parent_name = make_name(*sliced)
    if bone_set == None:
        bone_set = child.bone_set
    parent_bone = bone_set.new(
        name=parent_name,
        source=child,
        parent=child.parent,
        roll_type='ALIGN',
        roll_bone=child,
        roll=0,
        custom_shape_name = child.custom_shape_name,
        custom_shape=child.custom_shape,
        custom_shape_scale_xyz=Vector(child.custom_shape_scale_xyz) * 1.2,
        custom_shape_translation=Vector(child.custom_shape_translation),
        use_custom_shape_bone_size=child.use_custom_shape_bone_size,
        custom_shape_rotation_euler=child.custom_shape_rotation_euler,
    )

    child.parent = parent_bone
    child.parent_helper = parent_bone
    return parent_bone


def create_dsp_bone(parent, bone_set):
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
    )
    parent.custom_shape_transform = dsp_bone
    return dsp_bone

def copy_attributes(from_thing, to_thing, skip=[""], recursive=False):
    """Copy attributes from one thing to another.
    from_thing: Object to copy values from. (Only if the attribute already exists in to_thing)
    to_thing: Object to copy attributes into (No new attributes are created, only existing are changed).
    skip: List of attribute names in from_thing that should not be attempted to be copied.
    recursive: Copy iterable attributes recursively.
    """

    # print("\nCOPYING FROM: " + str(from_thing))
    # print(".... TO: " + str(to_thing))

    bad_stuff = skip + ['active', 'bl_rna', 'error_location', 'error_rotation']
    for prop in dir(from_thing):
        if "__" in prop:
            continue
        if prop in bad_stuff:
            continue

        if hasattr(to_thing, prop):
            from_value = getattr(from_thing, prop)
            # Iterables should be copied recursively, except str.
            if recursive and type(from_value) != str:
                # NOTE: I think This will infinite loop if a CollectionProperty contains a reference to itself!
                warn = False
                try:
                    # Determine if the property is iterable. Otherwise this throws TypeError.
                    iter(from_value)

                    to_value = getattr(to_thing, prop)
                    # The thing we are copying to must therefore be an iterable as well. If this fails though, we should throw a warning.
                    warn = True
                    iter(to_value)
                    count = min(len(to_value), len(from_value))
                    for i in range(0, count):
                        copy_attributes(from_value[i], to_value[i], skip, recursive)
                except TypeError:  # Not iterable.
                    if warn:
                        print(
                            "WARNING: Could not copy attributes from iterable to non-iterable field: "
                            + prop
                            + "\nFrom object: "
                            + str(from_thing)
                            + "\nTo object: "
                            + str(to_thing)
                        )

            # Copy the attribute.
            try:
                setattr(to_thing, prop, from_value)
                # print(prop + ": " + str(from_value))
            except (
                AttributeError
            ):  # Read-Only properties throw AttributeError. We ignore silently, which is not great.
                continue


def find_or_create_constraint(pb, con_type, name=None):
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
    chain: List[BoneInfo], length=0, index=-1
) -> Tuple[Vector, Vector]:
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
