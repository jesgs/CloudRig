import bpy
from ..utils.naming import flip_name
from bpy.props import BoolProperty

def copy_rigify_params(from_bone, to_bone):
	for key, value in from_bone.rigify_parameters.items():
		try:
			setattr(to_bone.rigify_parameters, key, getattr(from_bone.rigify_parameters, key))
		except:
			pass

class MirrorRigifyParameters(bpy.types.Operator):
	"""Mirror rigify type and parameters of selected bones"""

	bl_idname = "pose.rigify_mirror"
	bl_label = "Mirror Rigify Parameters"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		obj = context.object
		return obj and obj.type=='ARMATURE' and obj.mode=='POSE' and len(context.selected_pose_bones)>0

	def execute(self, context):
		rig = context.object

		for pb in context.selected_pose_bones:
			flip_bone = rig.pose.bones.get(flip_name(pb.name))
			if flip_bone==pb or not flip_bone:
				# Bone name could not be flipped or bone with flipped name doesn't exist, skip.
				continue
			if flip_bone.bone.select:
				print(f"Warning: Bone {pb.name} selected on both sides, mirroring would be ambiguous, skipping. Only select the left or right side, not both!")
				continue
			
			flip_bone.rigify_type = pb.rigify_type
			copy_rigify_params(pb, flip_bone)

		return { 'FINISHED' }

class CopyRigifyParameters(bpy.types.Operator):
	"""Copy rigify type and parameters from active to selected bones"""

	bl_idname = "pose.rigify_copy"
	bl_label = "Copy Rigify Parameters To Selected Bones"
	bl_options = {'REGISTER', 'UNDO'}

	copy_type: BoolProperty(name="Copy Rigify Type", default=True)

	@classmethod
	def poll(cls, context):
		obj = context.object
		return obj and obj.type=='ARMATURE' and obj.mode=='POSE' and len(context.selected_pose_bones)>1 and context.active_pose_bone!=None

	def execute(self, context):
		rig = context.object
		active_bone = context.active_pose_bone

		for pb in context.selected_pose_bones:
			if pb == active_bone: continue
			if self.copy_type:
				pb.rigify_type = active_bone.rigify_type
			copy_rigify_params(active_bone, pb)

		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(MirrorRigifyParameters)
	register_class(CopyRigifyParameters)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(MirrorRigifyParameters)
	unregister_class(CopyRigifyParameters)