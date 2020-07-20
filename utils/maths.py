from typing import Tuple, List

import bpy
from mathutils import Vector
from math import atan2

def bounding_box(points) -> Tuple[Vector, Vector]:
	"""Return two vectors representing the lowest and highest coordinates of a the bounding box of the passed points."""

	lowest = points[0].copy()
	highest = points[0].copy()
	for p in points:
		for i in range(len(p)):
			if p[i] < lowest[i]:
				lowest[i] = p[i]
			if p[i] > highest[i]:
				highest[i] = p[i]
	
	return lowest, highest

def bounding_box_center(points) -> Vector:
    """Find the bounding box center of some points."""
    bbox_low, bbox_high = bounding_box(points)
    return bbox_low + (bbox_high-bbox_low)/2

def scale_points_from_center(points, scale) -> List[Vector]:
	"""Scale some points from their bounding box center."""
	center = bounding_box_center(points)
	new_points = []
	for p in points:
		new_points.append(
			center + (center-p) * (scale)
		)
	return new_points

def project_points_on_plane (points, projection_axis) -> List[Vector]:
	# Find two vectors(ie. a plane) that are perpendicular to the projection axis.
	projection_direction = projection_axis.normalized()
	plane_x = projection_direction.cross(Vector((0, 0, 1)))
	plane_y = projection_direction.cross(plane_x)

	projected_points = []
	points_sum = Vector()
	for point in points:
		points_sum += point

	points_center = bounding_box_center(points)

	bpy.context.scene.cursor.location = points_center

	for point in points:
		center_relative = point - points_center
		projected_point = Vector((center_relative.dot(plane_x), center_relative.dot(plane_y), 0))
		
		angle_from_axis = atan2(
            projected_point.x - plane_y.x,
            projected_point.y - plane_y.y
        )

		projected_points.append((projected_point, angle_from_axis))

	# Sort points by their angle from the projection axis
	projected_points.sort(key=lambda x: x[1])

	return [p[0] for p in projected_points]

def flat(vec) -> Vector:
	"""Return a copy of a vector with its two absolute lowest values set to 0. Useful for making vectors world-aligned."""
	new_vec = vec.copy()

	maxabs = 0
	max_index = 0
	for i, val in enumerate(vec):
		if abs(val) > maxabs:
			maxabs = abs(val)
			max_index = i

	for i in range(0, len(vec)):
		if i != max_index:
			new_vec[i] = 0

	return new_vec