# These functions are copied from my Lattice Magic addon: https://gitlab.com/blender/lattice_magic
# So they should probably be kept in sync.

import bpy
from typing import List

from .maths import clamp
from mathutils import Vector
from math import sqrt

def get_lattice_vertex_index(lattice: bpy.types.Lattice, xyz: List[int], do_clamp=True) -> int:
	"""Get the index of a lattice vertex based on its position on the XYZ axes."""

	# The lattice vertex indicies start in the -Y, -X, -Z corner,
	# increase on X+, then moves to the next row on Y+, then moves up on Z+.
	res_x, res_y, res_z = lattice.points_u, lattice.points_v, lattice.points_w
	x, y, z = xyz[:]
	if do_clamp:
		x = clamp(x, 0, res_x)
		y = clamp(y, 0, res_y)
		z = clamp(z, 0, res_z)

	assert x < res_x and y < res_y and z < res_z, "Error: Lattice vertex xyz index out of bounds"

	index = (z * res_y*res_x) + (y * res_x) + x
	return index

def ensure_falloff_vgroup(
		lattice_ob: bpy.types.Object,
		vg_name="Group", multiplier=1) -> bpy.types.VertexGroup:
	lattice = lattice_ob.data
	res_x, res_y, res_z = lattice.points_u, lattice.points_v, lattice.points_w

	vg = lattice_ob.vertex_groups.get(vg_name)

	center = Vector((res_x/2, res_y/2, res_z/2))
	max_res = max(res_x, res_y, res_z)

	if not vg:
		vg = lattice_ob.vertex_groups.new(name=vg_name)
	for x in range(res_x-4):
		for y in range(res_y-4):
			for z in range(res_z-4):
				index = get_lattice_vertex_index(lattice, (x+2, y+2, z+2))

				coord = Vector((x+2, y+2, z+2))
				distance_from_center = (coord-center).length
				influence = 1 - distance_from_center / max_res * 2

				vg.add([index], influence * multiplier, 'REPLACE')
	return vg