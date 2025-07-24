from bpy.types import Bone, EditBone, PoseBone, Object
import math

def get_pbone_of_active(context) -> PoseBone | None:
    """Return the PoseBone of the active bone. Can be None. Useful for drawing
    data stored on the PoseBone, in Edit Mode.
    """
    bone = context.active_pose_bone or context.active_bone
    if not bone:
        return
    rig = context.pose_object or context.active_object
    return rig.pose.bones.get(bone.name)


def get_selected_bone_tuples(
    context, exclude_active=False
) -> list[tuple[Object, Bone | EditBone]]:
    """Return a list of Bones or EditBones depending on context."""
    bone_tuples = []
    if context.mode == 'POSE':
        bone_tuples = [(pb.id_data, pb.bone) for pb in context.selected_pose_bones]
    elif context.mode == 'EDIT_ARMATURE':
        for rig in get_current_rigs(context):
            # We can't use context.selected_editable_bones because
            # it actually includes non-selected bones when use_mirror_x==True.
            bone_tuples += [(rig, eb) for eb in rig.data.edit_bones if eb.select]

    if exclude_active:
        active_rig = context.pose_object or context.active_object
        active_bone = get_active_bone(context)
        if type(active_bone) == PoseBone:
            active_bone = active_bone.bone
        active_tup = (active_rig, active_bone)
        if active_tup in bone_tuples:
            bone_tuples.remove(active_tup)

    return bone_tuples


def get_current_rigs(context):
    objs = set(context.selected_objects)
    objs.add(context.active_object)

    for obj in objs:
        if context.mode in {'POSE', 'EDIT_ARMATURE'} and obj.type == 'ARMATURE':
            yield obj


def get_parentless_pbones(rig: Object) -> list[PoseBone]:
    return [pb for pb in rig.pose.bones if not pb.bone.parent]


def get_active_bone(context):
    """Return active PoseBone or EditBone, depending on context."""
    if context.mode == 'EDIT_ARMATURE':
        return context.active_bone
    else:
        return get_pbone_of_active(context)


def project_point_to_plane(point, origin, normal):
    vector = point - origin
    dist = vector.dot(normal)
    return point - dist * normal


def signed_angle_on_plane(vec_a, vec_b, plane_normal):
    # Get the angle between vec_a and vec_b projected onto a plane
    angle = vec_a.angle(vec_b)
    cross = vec_a.cross(vec_b)
    if cross.dot(plane_normal) < 0:
        angle = -angle
    return angle


def wrap_angle_pi(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def align_bone_z_axis_to_vector(ebone, vector):
    projected = project_point_to_plane(vector, ebone.head, ebone.y_axis)

    vec_a = ebone.z_axis.normalized()
    vec_b = (projected - ebone.head).normalized()
    angle = signed_angle_on_plane(vec_a, vec_b, ebone.y_axis)

    ebone.roll += angle
    ebone.roll = wrap_angle_pi(ebone.roll)
