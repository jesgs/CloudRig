# SPDX-License-Identifier: GPL-3.0-or-later

from math import atan2

from mathutils import Vector


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def bounding_box(points: list[Vector]) -> tuple[Vector, Vector]:
    """Return two vectors representing the lowest and highest coordinates of
    the bounding box of the passed points.
    """

    lowest = points[0].copy()
    highest = points[0].copy()
    for p in points:
        for i in range(len(p)):
            if p[i] < lowest[i]:
                lowest[i] = p[i]
            if p[i] > highest[i]:
                highest[i] = p[i]

    return lowest, highest


def bounding_box_diagonal_size(points: list[Vector]) -> float:
    low, high = bounding_box(points)
    return (high - low).length


def bounding_box_center(points: list[Vector]) -> Vector:
    bbox_low, bbox_high = bounding_box(points)
    return bbox_low + (bbox_high - bbox_low) / 2


def scale_points_from_center(points: list[Vector], scale: Vector | float) -> list[Vector]:
    center = bounding_box_center(points)
    new_points = []
    for p in points:
        new_points.append(center + (center - p) * scale)
    return new_points


def project_vector_on_plane(vec: Vector, plane_x: Vector, plane_y: Vector | None = None) -> Vector:
    # If plane_y wasn't passed, plane_x is treated as the plane's normal.
    normal = plane_x
    if plane_y:
        normal = plane_x.cross(plane_y).normalized()

    projection = vec - vec.dot(normal) * normal
    return projection


def project_points_on_plane(points: list[Vector], projection_axis: Vector) -> list[Vector]:
    """Return points that are flattened onto a plane.
    projection_axis is the plane's normal, and the plane's depth is the
    average depth of the points along this axis."""

    # Find two vectors(ie. a plane) that are perpendicular to the projection axis.
    projection_direction = projection_axis.normalized()
    plane_x = projection_direction.cross(Vector((0, 0, 1)))
    plane_y = projection_direction.cross(plane_x)
    projected_points = []
    points_center = bounding_box_center(points)

    for point in points:
        center_relative = point - points_center
        projected_point = Vector((center_relative.dot(plane_x), center_relative.dot(plane_y), 0))

        angle_from_axis = atan2(projected_point.x - plane_y.x, projected_point.y - plane_y.y)

        projected_points.append((projected_point, angle_from_axis))

    # Sort points by their angle from the projection axis
    projected_points.sort(key=lambda entry: entry[1])

    return [entry[0] for entry in projected_points]


def flat(vec: Vector) -> Vector:
    """Return a copy of a vector with its two absolute lowest values set to 0.
    Useful for making vectors world-aligned.
    """
    new_vec = vec.copy()

    maxabs = 0
    max_index = 0
    for i, val in enumerate(vec):
        if abs(val) > maxabs:
            maxabs = abs(val)
            max_index = i

    for i in range(len(vec)):
        if i != max_index:
            new_vec[i] = 0

    return new_vec


def clamp(val: float | int, _min=0, _max=1) -> float | int:
    if val < _min:
        return _min
    if val > _max:
        return _max
    return val


def point_to_segment_dist(point: Vector, seg_head: Vector, seg_tail: Vector) -> float:
    """Distance from point to the nearest point on a line segment."""
    ab = seg_tail - seg_head
    ab_len_sq = ab.dot(ab)
    if ab_len_sq == 0.0:
        return (point - seg_head).length
    t = max(0.0, min(1.0, (point - seg_head).dot(ab) / ab_len_sq))
    return (point - (seg_head + t * ab)).length
