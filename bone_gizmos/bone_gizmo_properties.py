import bpy
from bpy.types import Object, Scene, PropertyGroup
from bpy.props import (
	IntProperty, PointerProperty, BoolProperty,
	FloatVectorProperty, StringProperty, EnumProperty,
)

from .bone_gizmo_group import update_gizmos

class CloudGizmoProperties(PropertyGroup):
	enabled: BoolProperty(
		name		 = "Enable Gizmo"
		,description = "Attach a custom gizmo to this bone"
		,default	 = False
		,update		 = update_gizmos
	)

	operator: EnumProperty(
		name		 = "Operator"
		,description = "Operator to use when click and dragging on the gizmo"
		,items		 = [
			('transform.translate', "Translate", "Translate")
			,('transform.rotate', "Rotate", "Rotate")
			,('transform.scale', "Scale", "Scale")
		]
		,default	 = 'transform.translate'
	)

	shape_object: PointerProperty(
		name		 = "Shape"
		,type		 = Object
		,description = "Object to use as shape for this gizmo"
		,poll		 = lambda self, object: object.type == 'MESH'
		,update		 = update_gizmos
	)
	face_map_name: StringProperty(
		name		 = "Face Map"
		,description = "Face Map to use as shape for this gizmo"
		,update		 = update_gizmos
	)
	vertex_group_name: StringProperty(
		name		 = "Vertex Group"
		,description = "Vertex Group to use as shape for this gizmo"
		,update		 = update_gizmos
	)
	use_face_map: BoolProperty(
		name		 = "Mesh Mask Type"
		,description = "Toggle between using Face Maps or Vertex Groups as the mesh masking data"	# Currently it seems face maps are just worse vertex groups, but maybe they are faster, or maybe it's good to have them separated.
		,update		 = update_gizmos
	)

	draw_style: EnumProperty(
		name		 = "Style"
		,description = "Display style of the gizmo"
		,items		 = [
			('POINTS', "Points", "Points")
			,('LINES', "Lines", "Lines")
			,('TRIS', "Tris", "Tris")
		]
		,default	 = 'LINES'
		,update		 = update_gizmos
	)

	color: FloatVectorProperty(
		name		 = "Color"
		,description = "Color of the gizmo"
		,subtype	 = 'COLOR'
		,size		 = 4
		,min		 = 0.0
		,max		 = 1.0
		,default	 = (1.0, 0.05, 0.38, 0.5)
		,update		 = update_gizmos
	)

	color_highlight: FloatVectorProperty(
		name		 = "Highlight Color"
		,description = "Color of the gizmo when mouse hovered"
		,subtype	 = 'COLOR'
		,size		 = 4
		,min		 = 0.0
		,max		 = 1.0
		,default	 = (1.0, 0.5, 1.0, 0.5)
		,update		 = update_gizmos
	)

	line_width: IntProperty(
		name		 = "Line Width"
		,description = "Thickness of the drawn lines in pixels"
		,min		 = 1
		,max		 = 10
		,default	 = 1
		,update		 = update_gizmos
	)

	# This is made redundant by the ability to set the color to fully transparent.
	use_draw_hover: BoolProperty(
		name		 = "Hover Only"
		,description = "Draw the gizmo only when it is being mouse hovered"
		,default	 = False
		,update		 = update_gizmos
	)

	# These functionalities sadly don't work when the gizmo uses target_set_operator,
	# which we absolutely need.
	use_draw_modal: BoolProperty(
		name		 = "Draw During Interact"
		,description = "Draw the gizmo during interaction"
		,default	 = True
		,update		 = update_gizmos
	)

	use_draw_value: BoolProperty(
		name		 = "Draw Interact Value"
		,description = "Draw values in the top-left corner of the viewport during interaction"
		,default	 = True
		,update		 = update_gizmos
	)

	use_draw_cursor: BoolProperty(
		name		 = "Draw Interact Mouse"
		,description = "Draw the mouse cursor during interaction"
		,default	 = True
		,update		 = update_gizmos
	)

classes = (
	CloudGizmoProperties,
)
register_cls, unregister_cls = bpy.utils.register_classes_factory(classes)


def register():
	register_cls()

	bpy.types.PoseBone.cloudrig_gizmo = PointerProperty(type=CloudGizmoProperties)

	Scene.cloud_gizmos_enabled = BoolProperty(
		name		 = "CloudRig Gizmos"
		,description = "Globally deactivate CloudRig gizmos"
		,default	 = True
		,update		 = update_gizmos
	)


def unregister():
	unregister_cls()

	del bpy.types.PoseBone.cloudrig_gizmo
	del Scene.cloud_gizmos_enabled
