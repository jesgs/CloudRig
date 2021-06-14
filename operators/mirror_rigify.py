import bpy
from ..utils.naming import flip_name
from bpy.props import BoolProperty

def copy_rigify_params(from_bone, to_bone, mirror=False):
	for key, value in from_bone.rigify_parameters.items():
		val_type = type(value)

		if val_type == int and type(getattr(from_bone.rigify_parameters, key)) == str:
			# NOTE: items() returns the integer value of enum properties, rather than the string value.
			# So EnumProperty needs special treatment.
			value_as_str = from_bone.rigify_parameters[key]
			to_bone.rigify_parameters[key] = value_as_str
			continue
		elif val_type == list:
			# If the rigify property is a CollectionProperty.
			other_coll = getattr(to_bone.rigify_parameters, key)
			other_coll.clear()
			for entry in value:
				new = other_coll.add()
				for sub_key in entry.to_dict().keys():
					sub_value = entry.to_dict()[sub_key]
					if type(sub_value) == str and mirror:
						sub_value = flip_name(sub_value)
					setattr(new, sub_key, sub_value)
			continue
		elif val_type == IDPropertyArray:
			# If the rigify property is any VectorProperty
			if type(getattr(from_bone.rigify_parameters, key)[0]) == bool:
				# If the rigify property is exactly BoolVectorProperty
				setattr(to_bone.rigify_parameters, key, [bool(v) for v in value])
			else:
				setattr(to_bone.rigify_parameters, key, value[:])
			continue
		elif val_type == IDPropertyGroup:
			# If the property is a dictionary, but as far as I know that is only possible for custom properties.
			assert False, f"Mirroring of dictionary {key} not implemented. This should never happen?"

		# Remaining cases: simple integers, floats, strings.
		if val_type == str and mirror:
			value = flip_name(value)
		setattr(to_bone.rigify_parameters, key, value)
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
			copy_rigify_params(pb, flip_bone, mirror=True)

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