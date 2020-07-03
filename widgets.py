# Some widgets need to be generated procedurally.
# TODO: but also, move code for load_widgets() in here, cause why not.

from mathutils import Matrix, Vector
from math import pi, sin, cos, acos
import bpy

def bezier_widget(rig, coords, bone):
    """Create a bezier curve widget where coords is a list of Vectors that the curve should be near."""

    ob_name = "WGT-" + bone.name
    data_name = "WGT-" + bone.name

    bpy.ops.object.mode_set(mode='OBJECT')

    # If the object exists, delete it.
    obj = bpy.data.objects.get(ob_name)
    if obj:
        obdata = obj.data
        bpy.data.objects.remove(obj)

    curve = bpy.data.curves.new(data_name, 'CURVE')
    curve.dimensions = '3D'
    obj = bpy.data.objects.new(ob_name, curve)

    spline = curve.splines.new('BEZIER')
    spline.use_cyclic_u = True

    bpy.context.scene.collection.objects.link(obj)

    # Do all the fancy maths by Ivan Cappiello & MAD studios - TODO: ask for permission to use this code, or re-write it a bit nicer.
    coords = project_points_on_plane(coords, bone.vector)
    
    # Create and place the spline points
    spline.bezier_points.add(len(coords)-1)
    for i, p in enumerate(spline.bezier_points):
        co = coords[i]
        # world->bone axis shuffle...
        p.co[0] = co[0]
        p.co[1] = co[2]
        p.co[2] = -co[1]
        p.handle_left_type = 'AUTO'
        p.handle_right_type = 'AUTO'
    
    # Convert to mesh
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')

    # Assign to widget collection
    obj = bpy.context.object
    obj.data.name = obj.name
    rig.generator.wgt_collection.objects.link(obj)
    bpy.context.scene.collection.objects.unlink(obj)

    # Restore selection and modes
    bpy.context.view_layer.objects.active = rig.obj
    rig.obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    return obj

def sort_circular_points(points, axis):
    """Sort a list of points based on their angle around an axis."""
    anlges = [(point, angle(point, axis)) for point in points]

    # sort by angle...
    
    bpy.context.scene['linked_points'] = [vec[:] for vec in linked_points]
    
    return linked_points

def project_points_on_plane (points, projection_axis):
    # Find two vectors(ie. a plane) that are perpendicular to the projection axis.
    projection_direction = projection_axis.normalized()
    plane_x = projection_direction.cross(Vector((0, 0, 1)))
    plane_y = projection_direction.cross(plane_x)

    projected_points = []
    points_sum = Vector()
    for point in points:
        points_sum += point

    points_center = points_sum / len(points) # TODO: use bounding box instead of average

    for point in points:
        center_relative = point - points_center
        projected_point = Vector((center_relative.dot(plane_x), center_relative.dot(plane_y), 0))
        
        angle_from_axis = acos(projected_point.dot(plane_x) / (projected_point.length * plane_x.length))

        projected_points.append((projected_point, angle_from_axis))

    # Sort points by their angle from the projection axis
    projected_points.sort(key=lambda x: x[1])

    return [p[0] for p in projected_points]