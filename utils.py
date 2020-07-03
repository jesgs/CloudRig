import bpy
from mathutils import Vector
from math import acos

def bounding_box(points):
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

def bounding_box_center(points):
    """Find the bounding box center of some points."""
    bbox_low, bbox_high = bounding_box(points)
    return bbox_low + (bbox_high-bbox_low)/2

def project_points_on_plane (points, projection_axis):
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
		
		angle_from_axis = acos(projected_point.dot(plane_x) / (projected_point.length * plane_x.length))

		projected_points.append((projected_point, angle_from_axis))

	# Sort points by their angle from the projection axis
	projected_points.sort(key=lambda x: x[1])

	return [p[0] for p in projected_points]