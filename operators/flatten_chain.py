from typing import List, Tuple

import bpy
from bpy.types import EditBone, Operator
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector
from mathutils.geometry import intersect_line_plane
from ..rig_component_features.mechanism import get_bone_chain
from ..generation.troubleshooting import remove_active_log

def is_chain_flat(chain: List[EditBone]) -> bool:
	"""Determine whether a chain of bones is ideal for IK."""
	coords = get_flattened_coords(chain)

	THRESHOLD = 0.01
	for i, eb in enumerate(chain):
		head, tail = coords[i]
		if not head:
			# This happens when several bones are perfectly straight. intersect_line_plane() will return None.
			continue
		if (head - eb.head).length > THRESHOLD or (tail - eb.tail).length > THRESHOLD:
			return False

	return True

def get_flattened_coords(chain: List[EditBone]) -> List[Tuple[Vector]]:
	"""Return a list of head+tail coordinates flattened along a plane."""

	# We need 3 points to define a plane. 2 of these are the head of the first and the tail of the last bone.
	plane_points = [chain[0].head, chain[-1].tail]
	# Let's pick the 3rd point based on whether the first or last bone is longer.
	if chain[0].length > chain[-1].length:
		plane_points.append(chain[0].tail)
	else:
		plane_points.append(chain[-1].head)

	# Find the normal of this plane by finding two non-parallel vectors that lie on the plane
	# and taking their cross product.
	vec1 = plane_points[0] - plane_points[1]
	vec2 = plane_points[1] - plane_points[2]
	plane_normal = vec1.cross(vec2)

	# Now let's flatten each point in the chain onto our plane.
	ret = []
	for edit_bone in chain:
		pair = []
		for vec in [edit_bone.head, edit_bone.tail]:
			# Find the line that connects this vector to its closest point on the plane
			line = [vec - plane_normal*20000, vec + plane_normal*20000]	# XXX Not sure how to use an infinite line for the intersection test... but, this is infinite enough for me.
			# Blender gives us a nice function for intersecting a line with a plane
			intersect = intersect_line_plane(line[0], line[1], plane_points[0], plane_normal)

			# Set the vector to the resulting point
			pair.append(intersect)
		ret.append(pair)
	return ret

class CLOUDRIG_OT_FlattenChain(Operator):
	"""Flatten a chain of bones on a plane. Useful for perfect IK chains"""

	bl_idname = "armature.flatten_chain"
	bl_label = "Flatten Bone Chain"
	bl_options = {'REGISTER', 'UNDO'}

	remove_log: BoolProperty(description="For calling this operator from the Rigify Log", default=False)
	start_bone: StringProperty(description="Use a specific bone as the beginning of the chain, rather than the active bone")

	@classmethod
	def poll(cls, context):
		rig = context.active_object
		return rig and rig.type=='ARMATURE' and rig.mode=='POSE'

	def execute(self, context):
		rig = context.active_object

		# Enter edit mode
		org_mode = rig.mode
		bpy.ops.object.mode_set(mode='EDIT')
		bpy.ops.armature.select_all(action='DESELECT')

		# Find the bone chain that we will be operating on
		if self.start_bone != "":
			start_bone = rig.data.edit_bones.get(self.start_bone)
		else:
			start_bone = context.active_bone
		chain = get_bone_chain(start_bone)

		coords = get_flattened_coords(chain)
		for i, edit_bone in enumerate(chain):
			edit_bone.head, edit_bone.tail = coords[i]

		bpy.ops.object.mode_set(mode=org_mode)

		if self.remove_log:
			remove_active_log(rig)

		return { 'FINISHED' }

registry = [
	CLOUDRIG_OT_FlattenChain
]
