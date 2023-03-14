import bpy
from typing import Tuple
from bpy.types import Spline
from mathutils import Vector
from mathutils.kdtree import KDTree

def get_spline_points(spline: Spline):
    return spline.bezier_points if spline.type == 'BEZIER' else spline.points

def find_opposite_point_on_spline(spline: bpy.types.Spline, point_idx: int) -> Tuple[Vector, int, float]:
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