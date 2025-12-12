# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import Curve, Spline
from mathutils import Vector
from mathutils.kdtree import KDTree

from .maths import bounding_box_center


def get_spline_points(spline: Spline):
    return spline.bezier_points if spline.type == 'BEZIER' else spline.points


def find_opposite_spline(curve, spline_idx):
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


def find_opposite_point_on_spline(
    spline: Spline, point_idx: int
) -> tuple[Vector, int, float]:
    """Return the position, index, and offset of the closest point on the
    spline to the coordinate of the given point with its X component inverted."""

    points = get_spline_points(spline)

    kd = KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert(p.co, i)
    kd.balance()

    # Find the closest point to the opposite side
    co = points[point_idx].co
    flipped_co = [-co.x, co.y, co.z]
    opp_co, opp_idx, offset = kd.find(flipped_co)
    return opp_co, opp_idx, offset


def find_opposite_point_on_curve(
    curve: Curve, spline_idx: int, point_idx: int
) -> tuple[Spline, int, float]:
    """Return the spline, point index, and position, of the closest point on the
    curve to the coordinate of the given point with its X component inverted."""

    spline = curve.splines[spline_idx]

    point_list: list[tuple[Spline, int, Vector]] = []
    for spl in curve.splines:
        for point_i, point in enumerate(get_spline_points(spl)):
            point_list.append((spl, point_i, point.co))

    kd = KDTree(len(point_list))
    for i, p in enumerate(point_list):
        kd.insert(p[2], i)
    kd.balance()

    # Find the closest point to the opposite side
    spline_points = get_spline_points(spline)
    co = spline_points[point_idx].co
    flipped_co = Vector([-co.x, co.y, co.z])
    opp_co, opp_kd_idx, offset = kd.find(flipped_co)

    opp_spline, opp_point_idx, opp_co = point_list[opp_kd_idx]
    return opp_spline, opp_point_idx, offset


def get_spline_bounding_box_center(spline: Spline) -> Vector:
    spline_points = get_spline_points(spline)
    return bounding_box_center([p.co for p in spline_points])
