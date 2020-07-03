# Some widgets need to be generated procedurally.
# TODO: but also, move code for load_widgets() in here, cause why not.

from mathutils import Matrix, Vector
from math import pi, sin, cos
import bpy

def bezier_widget(rig, coords, bone):
    """Create a bezier curve widget where coords is a list of Vectors that the curve should be near.
    Find the outer-most points, ignore any "inner" ones.
    Prune remaining points that are too close to each other. (TODO: what does too close mean, it would mean different things at different scales)
    Flatten remaining points so that they fit on a flat plane.
    Sort these points starting with an arbitrary one, the next one is the nearest one, the next one is the nearest one that wasn't already sorted.
    Place bezier curve points at the coordinates.
    Convert the curve to mesh and return the object.
    """

    ob_name = "curveobname"
    data_name = "curvename"

    bpy.ops.object.mode_set(mode='OBJECT')

    # Delete if exists (TODO: put under Force Widget Update check)
    # obj = bpy.data.objects.get(ob_name)
    # if obj:
    #     bpy.data.objects.remove(obj)
    #     bpy.data.curves.remove(obj.data)

    curve = bpy.data.curves.new(data_name, 'CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('BEZIER')
    spline.use_cyclic_u = True
    obj = bpy.data.objects.new(ob_name, curve)
    bpy.context.scene.collection.objects.link(obj)

    # Do all the fancy maths by Ivan Cappiello & MAD studios - TODO: ask for permission to use this code, or re-write it a bit nicer.
    coords = project_points_on_plane(coords, bone.vector)
    # coords = get_2d_border(coords, double=False)[0]
    
    # Create and place the spline points
    spline.bezier_points.add(len(coords)-1)
    print("coords:\n\n")
    for i, p in enumerate(spline.bezier_points):
        p.co = coords[i][:3]
        print(p.co)
        p.handle_left_type = 'AUTO'
        p.handle_right_type = 'AUTO'
    
    # Convert to mesh
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    obj = bpy.context.object
    rig.generator.wgt_collection.objects.link(obj)
    bpy.context.scene.collection.objects.unlink(obj)

    bpy.context.view_layer.objects.active = rig.obj
    rig.obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    return obj

def project_points_on_plane (points, projection_axis):
    # Define a plane based on the projection axis: find two vectors(ie. a plane) that are perpendicular to the projection axis.
    plane_x = projection_axis.cross(Vector((0.142523434, 0.1123124, 1)))
    plane_y = projection_axis.cross(plane_x)

    projected_points = []
    points_sum = Vector()
    for point in points:
        points_sum += point
    
    points_center = points_sum / len(points) # TODO: use bounding box instead of average

    for point in points:
        center_relative = point - points_center
        projected_point = Vector((center_relative.dot(plane_x), center_relative.dot(plane_y), 0))
        projected_points.append(projected_point)

    return projected_points