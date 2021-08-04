import bpy
from mathutils.geometry import intersect_line_plane
from ..rig_features.mechanism import get_bone_chain

class CLOUDRIG_OT_FlattenChain(bpy.types.Operator):
	"""Flatten a chain of bones on a plane. Useful for perfect IK chains"""

	bl_idname = "armature.flatten_chain"
	bl_label = "Flatten Bone Chain"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE'

	def execute(self, context):
		# Enter edit mode
		org_mode = context.object.mode
		bpy.ops.object.mode_set(mode='EDIT')
		bpy.ops.armature.select_all(action='DESELECT')

		# Find the bone chain that we will be operating on
		start_bone = context.active_bone
		chain = get_bone_chain(start_bone)

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
		for edit_bone in chain:
			for vec in [edit_bone.head, edit_bone.tail]:
				# Find the line that connects this vector to its closest point on the plane
				line = [vec - plane_normal, vec + plane_normal]
				# Blender gives us a nice function for intersecting a line with a plane
				intersect = intersect_line_plane(line[0], line[1], plane_points[0], plane_normal)

				# Set the vector to the resulting point
				vec.xyz = intersect[:]

		bpy.ops.object.mode_set(mode=org_mode)
		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_FlattenChain)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_FlattenChain)