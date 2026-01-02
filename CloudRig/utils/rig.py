from math import atan2, pi

from bpy.types import Armature, Bone, EditBone, Object, PoseBone
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_line_plane

from ..generation.cloudrig import active_rig, calculate_ik_pole_vector


def get_pbone_of_active(context) -> PoseBone | None:
    """Return the PoseBone of the active bone. Can be None. Useful for drawing
    data stored on the PoseBone, in Edit Mode.
    """
    if context.mode not in ('OBJECT', 'PAINT_WEIGHT', 'EDIT_ARMATURE', 'POSE'):
        return
    bone = context.active_pose_bone or context.active_bone
    if not bone:
        return
    rig = active_rig(context)
    return rig.pose.bones.get(bone.name)


def get_pbones_of_selected(context, whole_ebone=True) -> list[PoseBone]:
    if context.mode in ('PAINT_WEIGHT', 'POSE'):
        return context.selected_pose_bones
    elif context.mode == 'EDIT_ARMATURE':
        def is_ebone_select(eb):
            if whole_ebone:
                return (eb.select and eb.select_head and eb.select_tail)
            return (eb.select or eb.select_head or eb.select_tail)
        rig = context.active_object
        pbones = rig.pose.bones
        return [pbones[eb.name] for eb in rig.data.edit_bones if is_ebone_select(eb) and eb.name in pbones]
    else:
        return []


def bone_is_visible(bone: Bone | PoseBone | EditBone):
    pbone = None
    if isinstance(bone, PoseBone):
        pbone = bone
        bone = bone.bone

    if not any([coll.is_visible_effectively for coll in bone.collections]):
        return False

    if pbone and pbone.id_data.mode != 'EDIT':
        return not pbone.hide

    if isinstance(bone.id_data, Armature):
        if bone.id_data.edit_bones:
            ebone = bone.id_data.edit_bones.get(bone.name)
            if ebone:
                return not ebone.hide
        else:
            return not bone.hide

    # We can get here in absurd cases like caller is in Pose Mode but passed in a Bone.
    return True

def get_selected_bone_tuples(
        context, exclude_active=False
    ) -> list[tuple[Object, Bone | EditBone]]:
    """Return a list of Bones or EditBones depending on context."""
    bone_tuples = []
    if context.mode in ('POSE', 'PAINT_WEIGHT'):
        bone_tuples = [(pb.id_data, pb.bone) for pb in context.selected_pose_bones]
    elif context.mode == 'EDIT_ARMATURE':
        for rig in get_current_rigs(context):
            # We can't use context.selected_editable_bones because
            # it actually includes non-selected bones when use_mirror_x==True.
            bone_tuples += [(rig, eb) for eb in rig.data.edit_bones if eb.select]

    if exclude_active:
        rig = active_rig(context)
        active_bone = get_active_bone(context)
        if isinstance(active_bone, PoseBone):
            active_bone = active_bone.bone
        active_tup = (rig, active_bone)
        if active_tup in bone_tuples:
            bone_tuples.remove(active_tup)

    return bone_tuples


def get_current_rigs(context):
    objs = set(context.selected_objects)
    objs.add(active_rig(context))

    for obj in objs:
        if not obj:
            continue
        if context.mode in {'POSE', 'EDIT_ARMATURE'} and obj.type == 'ARMATURE':
            yield obj


def get_parentless_pbones(rig: Object) -> list[PoseBone]:
    return [pb for pb in rig.pose.bones if pb.bone and not pb.bone.parent]


def get_active_bone(context) -> EditBone | PoseBone | None:
    """Return active PoseBone or EditBone, depending on context."""
    if context.mode == 'EDIT_ARMATURE':
        return context.active_bone
    else:
        return get_pbone_of_active(context)


####################################
### Bone Roll functions.

def signed_angle_on_plane(vec_a: Vector, vec_b: Vector, plane_normal: Vector) -> float:
    vec_a = vec_a.normalized()
    vec_b = vec_b.normalized()
    return atan2(
        plane_normal.dot(vec_a.cross(vec_b)),
        vec_a.dot(vec_b)
    )

def wrap_angle_pi(angle: float) -> float:
    return (angle + pi) % (2 * pi) - pi


def align_bone_axis_to_vector(ebone: EditBone, vector: Vector, axis="+Z"):
    ebone.roll = calc_roll_to_align_axis(ebone, vector, axis)


def project_point_to_plane(point: Vector, origin: Vector, normal: Vector) -> Vector:
    if normal.length == 0:
        raise ValueError(f"This normal vector cannot define a plane! ({normal})")
    normal = normal.normalized()
    vector = point - origin
    dist = vector.dot(normal)
    return point - dist * normal


def calc_roll_to_align_axis(ebone: EditBone, vector: Vector, axis="+Z") -> float:
    offset_map = {
        "+Z": 0,
        "-Z": pi,
        "+X": pi / 2,
        "-X": -pi / 2,
    }
    assert axis in offset_map, f"'{axis}' must be one of {tuple(offset_map.keys())}"
    offset = offset_map[axis]
    roll = ebone.roll
    # Target vector flattened to lie on a plane defined by the bone's forward axis.
    projected = project_point_to_plane(vector, ebone.head, ebone.y_axis)
    vec_a = ebone.z_axis
    vec_b = projected - ebone.head
    angle = signed_angle_on_plane(vec_a, vec_b, ebone.y_axis)
    roll += angle + offset
    roll = wrap_angle_pi(roll)
    return roll


def get_armature_bounding_box(armature_obj: Object) -> tuple[Vector, Vector]:
    """Return lowest and highest coordinates of the rest position heads/tails of all bones."""

    if armature_obj.type != 'ARMATURE':
        raise TypeError(f"Object {armature_obj.name} is not an armature")

    min_corner = Vector((float('inf'), float('inf'), float('inf')))
    max_corner = Vector((float('-inf'), float('-inf'), float('-inf')))

    for bone in armature_obj.data.bones:
        head = bone.head_local
        tail = bone.tail_local

        for v in (head, tail):
            min_corner.x = min(min_corner.x, v.x)
            min_corner.y = min(min_corner.y, v.y)
            min_corner.z = min(min_corner.z, v.z)
            max_corner.x = max(max_corner.x, v.x)
            max_corner.y = max(max_corner.y, v.y)
            max_corner.z = max(max_corner.z, v.z)

    return min_corner, max_corner


def get_armature_dimensions(armature_obj: Object) -> Vector:
    min_corner, max_corner = get_armature_bounding_box(armature_obj)
    return max_corner - min_corner


#####################################
### IK Chain functions.


def ik_chain_flatten_single_iter(eb_chain, axis="+Z") -> bool:
    coords = get_flattened_coords(eb_chain)
    assert coords

    did_anything = False
    for i, edit_bone in enumerate(eb_chain):
        flattened_head, flattened_tail = coords[i]
        if edit_bone.head != flattened_head or edit_bone.tail != flattened_tail:
            edit_bone.head = flattened_head
            edit_bone.tail = flattened_tail
            did_anything = True

    _ik_angle, _pole_direction, pole_location = calculate_ik_pole_vector(eb_chain[0], eb_chain[1])

    # We loop over again because roll has to be re-calculated after the whole chain has been flattened.
    for edit_bone in eb_chain:
        desired_roll = calc_roll_to_align_axis(edit_bone, pole_location, axis)
        if edit_bone.roll != desired_roll:
            edit_bone.roll = desired_roll
            did_anything = True

    return did_anything


def is_ideal_ik_chain(chain: list[EditBone]) -> bool:
    """Determine whether a chain of bones is ideal for IK.
    Return True only if the chain's bones lie on a plane, and for each bone,
    one of their axes (out of +Z/-Z/+X/-X) points towards the (theoretical)
    pole target position.
    """
    coords = get_flattened_coords(chain)

    THRESHOLD = 0.01
    for (head, tail), ebone in zip(coords, chain):
        if not head:
            # This happens when several bones are perfectly straight.
            # (intersect_line_plane() will return None).
            continue
        if (head - ebone.head).length > THRESHOLD or (tail - ebone.tail).length > THRESHOLD:
            return False

    _ik_angle, _pole_direction, pole_location = calculate_ik_pole_vector(chain[0], chain[1])
    for ebone in chain:
        desired_roll = calc_roll_to_align_axis(ebone, pole_location)
        wrapped_roll = wrap_angle_pi(ebone.roll)
        # Allow any 90-degree increment.
        good_rolls = (wrapped_roll, wrapped_roll + pi, wrapped_roll - pi, wrapped_roll + pi / 2, wrapped_roll - pi / 2)
        threshold = 0.001
        if not any([abs(desired_roll - good_roll) < threshold for good_roll in good_rolls]):
            return False

    return True


def points_define_plane(p1, p2, p3, eps=1e-8) -> bool:
    v1 = p2 - p1
    v2 = p3 - p1
    return v1.cross(v2).length > eps


def get_flattened_coords(eb_chain: list[EditBone]) -> list[tuple[Vector, Vector]]:
    """For a set of bones, return a list of head+tail coordinate pairs flattened along a plane.
    The plane is defined by the head of the first bone, tail of the last bone, and another point depending on
    the length of those bones.

    In the case of a perfectly straight bone chain, we cannot find a plane, and a ValueError will be raised instead.
    """

    # We need 3 points to define a plane. 2 of these are the head of the first and the tail of the last bone.
    plane_points = [eb_chain[0].head, eb_chain[-1].tail]
    # Let's pick the 3rd point based on whether the first or last bone is longer.
    if eb_chain[0].length > eb_chain[-1].length:
        plane_points.append(eb_chain[0].tail)
    else:
        plane_points.append(eb_chain[-1].head)
    if not points_define_plane(*plane_points):
        for ebone in eb_chain:
            for joint in (ebone.head, ebone.tail):
                plane_points = [eb_chain[0].head, eb_chain[-1].tail, joint]
                if points_define_plane(*plane_points):
                    break
    if not points_define_plane(*plane_points):
        raise ValueError(f"This bone chain is perfectly straight, and cannot define a plane: {[eb.name for eb in eb_chain]}")

    # Find the normal of this plane by finding two non-parallel vectors that lie on the plane.
    # and taking their cross product.
    vec1 = plane_points[0] - plane_points[1]
    vec2 = plane_points[1] - plane_points[2]
    plane_normal = vec1.cross(vec2)
    assert isinstance(plane_normal, Vector)

    # Now let's project each head/tail in the bone chain onto the chosen plane.
    ret = []
    for edit_bone in eb_chain:
        pair = []
        for point in [edit_bone.head, edit_bone.tail]:
            # Find the line that connects this vector to its closest point on the plane
            line = [
                point - plane_normal * 20000,
                point + plane_normal * 20000,
            ]    # XXX Not sure how to use an infinite line for the intersection test... but, this is infinite enough for me.
            # Blender gives us a nice function for intersecting a line with a plane
            intersect = intersect_line_plane(line[0], line[1], plane_points[0], plane_normal)
            # Set the vector to the resulting point
            if not intersect:
                raise ValueError(f"Could not define a plane from this bone chain: {[eb.name for eb in eb_chain]}")

            pair.append(intersect)
        if pair:
            ret.append(pair)
    return ret
