# SPDX-License-Identifier: GPL-3.0-or-later

from itertools import pairwise

from bpy.types import Curve, Object, Spline
from mathutils import Vector
from mathutils.geometry import interpolate_bezier, intersect_point_line
from mathutils.kdtree import KDTree

from .maths import bounding_box_center


def get_spline_points(spline: Spline):
    return spline.bezier_points if spline.type == 'BEZIER' else spline.points


def find_opposite_spline(curve: Curve, spline_idx: int) -> tuple[int, Spline]:
    spline = curve.splines[spline_idx]
    bb_center = get_spline_bounding_box_center(spline)
    opp_co = Vector((-bb_center.x, bb_center.y, bb_center.z))
    for i, other_spline in enumerate(curve.splines):
        if other_spline == spline:
            continue
        other_bb_center = get_spline_bounding_box_center(other_spline)
        if (other_bb_center - opp_co).length < 0.01:
            return i, other_spline

    return spline_idx, spline


def find_opposite_point_on_spline(spline: Spline, point_idx: int) -> tuple[Vector, int, float]:
    """Return the position, index, and offset of the closest point on the
    spline to the coordinate of the given point with its X component inverted."""

    points = get_spline_points(spline)

    kd = KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert(p.co.xyz, i)
    kd.balance()

    # Find the closest point to the opposite side
    co = points[point_idx].co.xyz
    flipped_co = [-co.x, co.y, co.z]
    opp_co, opp_idx, offset = kd.find(flipped_co)
    return opp_co, opp_idx, offset


def find_opposite_point_on_curve(curve: Curve, spline_idx: int, point_idx: int) -> tuple[Spline, int, float]:
    """Return the spline, point index, and position, of the closest point on the
    curve to the coordinate of the given point with its X component inverted."""

    spline = curve.splines[spline_idx]

    point_list: list[tuple[Spline, int, Vector]] = []
    for spl in curve.splines:
        for point_i, point in enumerate(get_spline_points(spl)):
            point_list.append((spl, point_i, point.co.xyz))

    kd = KDTree(len(point_list))
    for i, p in enumerate(point_list):
        kd.insert(p[2], i)
    kd.balance()

    # Find the closest point to the opposite side
    spline_points = get_spline_points(spline)
    co = spline_points[point_idx].co.xyz
    flipped_co = Vector([-co.x, co.y, co.z])
    opp_co, opp_kd_idx, offset = kd.find(flipped_co)

    opp_spline, opp_point_idx, opp_co = point_list[opp_kd_idx]
    return opp_spline, opp_point_idx, offset


def get_spline_bounding_box_center(spline: Spline) -> Vector:
    spline_points = get_spline_points(spline)
    return bounding_box_center([p.co.xyz for p in spline_points])


def evaluate_bezier_spline(spline: Spline, segment_resolution=64) -> list[list[Vector]]:
    assert spline.type == 'BEZIER'
    points = get_spline_points(spline)[:]
    if spline.use_cyclic_u:
        points.append(points[0])
    segments = []
    for point_a, point_b in pairwise(points):
        segment = interpolate_bezier(
            point_a.co, point_a.handle_right, point_b.handle_left, point_b.co.xyz, segment_resolution
        )
        segments.append(segment)
    return segments


def evaluate_point_tangents(curve_ob: Object) -> list[list[Vector]] | None:
    if not curve_ob:
        return

    def calc_tangent_3_points(a: Vector, b: Vector, p: Vector) -> Vector:
        center = intersect_point_line(p, a, b)[0]
        tangent = p - center
        return tangent.normalized()

    spline_tangents: list[list[Vector]] = []
    segment_resolution = 64
    idx_offset = int(segment_resolution / 8)
    for spline in curve_ob.data.splines:
        point_tangents: list[Vector] = []
        if spline.type == 'BEZIER':
            eval_segments = evaluate_bezier_spline(spline, segment_resolution)
            if spline.use_cyclic_u:
                eval_segments.insert(0, eval_segments[-1])
            else:
                first_tangent = eval_segments[0][idx_offset] - eval_segments[0][0]
                point_tangents.append(first_tangent)
            for seg_a, seg_b in pairwise(eval_segments):
                point_a = seg_a[-idx_offset]
                point_b = seg_b[idx_offset]
                point_p = seg_b[0]

                point_tangents.append(calc_tangent_3_points(point_a, point_b, point_p))

            last_tangent = eval_segments[-1][-1] - eval_segments[-1][-idx_offset]
            point_tangents.append(last_tangent)
        else:
            points = get_spline_points(spline)[:]
            if spline.use_cyclic_u:
                points.insert(0, points[-1])
                points.append(points[0])
            for point_a, point_p, point_b in zip(points, points[1:], points[2:]):
                point_tangents.append(calc_tangent_3_points(point_a.co.xyz, point_b.co.xyz, point_p.co.xyz))
            if not spline.use_cyclic_u:
                point_tangents.insert(0, point_tangents[0])
                point_tangents.append(point_tangents[-1])
        spline_tangents.append(point_tangents)
    return spline_tangents
