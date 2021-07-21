import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty, EnumProperty
from mathutils.geometry import intersect_point_line
from ..rig_features.mechanism import get_bone_chain

class CLOUDRIG_OT_FlattenChain(bpy.types.Operator):
	"""Flatten a chain of bones on a plane. Useful for perfect IK chains"""

	bl_idname = "object.cloudrig_flatten_bones"
	bl_label = "Flatten Bones"
	bl_options = {'REGISTER', 'UNDO'}

	use_selected: BoolProperty(name="Selected Bones", default=True)

	start_bone: StringProperty(name="Start bone")
	chain_length: IntProperty(name="Chain Length", default=-1)

	axis: EnumProperty(name="Axis",
		items = [
			('X', 'X', 'X'),
			('-X', '-X', '-X'),
			('Y', 'Y', 'Y'),
			('-Y', '-Y', '-Y'),
			('Z', 'Z', 'Z'),
			('-Z', '-Z', '-Z'),
		],
		default = 'Y'
	)

	skip_popup: BoolProperty(name="Skip Popup", description="Just rely on automatic settings", default=False)

	@classmethod
	def poll(cls, context):
		return context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE'

	def invoke(self, context, event):
		if len(context.selected_pose_bones) < 2:
			self.use_selected = False
			if context.active_pose_bone:
				self.start_bone = context.active_pose_bone.name

		# Determine a default flattening axis based on the first two bones
		if self.start_bone!="":
			start_bone = context.object.pose.bones.get(self.start_bone)
			if self.chain_length == -1:
				self.chain_length = len(get_bone_chain(context.object, start_bone))
			bones = get_bone_chain(context.object, start_bone.bone)[:2]
			if len(bones) > 1:
				chain_start = bones[0].head_local
				chain_end = bones[-1].tail_local
				line = (chain_start, chain_end)

				intersect = intersect_point_line(bones[1].head_local, chain_start, chain_end)[0]
				difference = bones[1].head_local - intersect
				inverse = []

				for i, co in enumerate(difference):
					difference[i] = abs(co)
					inverse.append(co < 0)

				if max(difference) == difference[0]:
					self.axis = 'X'
					if inverse[0]:
						self.axis = '-X'
				if max(difference) == difference[1]:
					self.axis = 'Y'
					if inverse[1]:
						self.axis = '-Y'
				if max(difference) == difference[2]:
					self.axis = 'Z'
					if inverse[2]:
						self.axis = '-Z'

		if self.skip_popup:
			return self.execute(context)
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		layout.prop(self, 'use_selected')
		if not self.use_selected:
			layout.prop_search(self, 'start_bone', context.object.pose, 'bones')
			layout.prop(self, 'chain_length')
		layout.prop(self, 'axis')

	def execute(self, context):
		org_mode = context.mode
		bpy.ops.object.mode_set(mode='EDIT')

		rig = context.object

		bones = context.selected_editable_bones
		start_bone = context.active_bone
		if not self.use_selected:
			start_bone = rig.data.edit_bones.get(self.start_bone)
			if not start_bone:
				self.report({'ERROR'}, "A start bone must be specified!")
				return {'CANCELLED'}
		bones = get_bone_chain(rig, start_bone)[:self.chain_length]

		if len(bones) < 2:
			return {'CANCELLED'}

		chain_start = bones[0].head
		chain_end = bones[-1].tail
		line = (chain_start, chain_end)

		bpy.ops.armature.select_all(action='DESELECT')

		bones[0].select=True
		for b in bones[1:]:
			b.select=True
			intersect = intersect_point_line(b.head, chain_start, chain_end)[0]
			if 'X' not in self.axis:
				b.head.x = intersect.x
			if 'Y' not in self.axis:
				b.head.y = intersect.y
			if 'Z' not in self.axis:
				b.head.z = intersect.z

		roll_type = "GLOBAL_POS_" + self.axis[-1]
		if not self.axis.startswith("-"):
			roll_type = roll_type.replace("POS_", "NEG_")

		bpy.ops.armature.calculate_roll(type=roll_type)

		bpy.ops.object.mode_set(mode=org_mode)
		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_FlattenChain)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_FlattenChain)