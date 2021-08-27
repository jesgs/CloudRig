from bpy.types import Operator, Armature
from bpy.props import BoolVectorProperty
from ..generation.cloudrig import (is_active_cloudrig, is_active_cloud_metarig, 
									draw_layers_ui, register_hotkey)

# Layer Select operator can be found in cloudrig.py instead of here,
# since it needs to be included with rigs when CloudRig isn't installed.

class CLOUDRIG_OT_layer_assign(Operator):
	"""Assign active layers for selected bones using the named Rigify layers"""
	bl_idname = "pose.cloudrig_assign_layers"
	bl_label = "Assign Bone Layers"
	bl_options = {'REGISTER', 'UNDO'}

	def update_layers(self, context):
		for pb in context.selected_pose_bones:
			pb.bone.layers = self.layers[:]
		for i, layer in enumerate(self.layers):
			if context.object.data.layers[i] == False and layer == True:
				context.object.data.layers[i] = True

	layers: BoolVectorProperty(size = 32, subtype = 'LAYER', description = f"Layers to assign selected bones to", update=update_layers)

	@classmethod
	def poll(cls, context):
		return is_active_cloudrig(context) or is_active_cloud_metarig(context)

	def invoke(self, context, event):
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		draw_layers_ui(self.layout, context.pose_object, show_hidden_checkbox=True, owner=self)

	def execute(self, context):
		return {'FINISHED'}


def init_cloudrig_layers(armature: Armature):
	for i in range(len(armature.rigify_layers), len(armature.layers)):
		layer = armature.rigify_layers.add()

		if i==0:
			layer.name = "IK"
		elif i==16:
			layer.name = "IK Secondary"
		elif i==1:
			layer.name = "FK"
			layer.row = 2
		elif i==17:
			layer.name = "FK Secondary"
			layer.row = 2
		elif i==2:
			layer.name = "Stretch"
			layer.row = 3

		elif i==3:
			layer.name = "Face"
			layer.row = 4
		elif i==19:
			layer.name = "Face Extras"
			layer.row = 4
		elif i==20:
			layer.name = "Face Tweak"
			layer.row = 4

		elif i==5:
			layer.name = "Fingers"
			layer.row = 5

		elif i==6:
			layer.name = "Hair"
			layer.row = 6
		elif i==7:
			layer.name = "Clothes"
			layer.row = 7

		elif i==29:
			layer.name = "$DEF"
			layer.row = 32
		elif i==30:
			layer.name = "$MCH"
			layer.row = 32
		elif i==31:
			layer.name = "$ORG"
			layer.row = 32
		else:
			layer.name = ""


class CLOUDRIG_OT_layer_init(Operator):
	"""Initialize armature rigify layers with CloudRig's default names"""

	bl_idname = "pose.cloudrig_layer_init"
	bl_label = "Add Rigify Layers"
	bl_options = {'UNDO', 'INTERNAL'}

	def execute(self, context):
		armature = context.object.data

		init_cloudrig_layers(armature)

		return {'FINISHED'}

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_layer_assign)
	register_class(CLOUDRIG_OT_layer_init)

	register_hotkey(CLOUDRIG_OT_layer_assign.bl_idname
		,hotkey_kwargs = {'type': "M", 'value': "PRESS"}
		,key_cat = "Pose"
		,space_type = 'VIEW_3D'
	)
	register_hotkey(CLOUDRIG_OT_layer_assign.bl_idname
		,hotkey_kwargs = {'type': 'M', 'value': 'PRESS'}
		,key_cat = 'Armature'
	)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_layer_assign)
	unregister_class(CLOUDRIG_OT_layer_init)