import bpy
import json
import traceback

from bpy.props import StringProperty, IntProperty

from .utils import naming
from .utils.ui import is_cloud_metarig, draw_label_with_linebreak, draw_dropdown

# This whole thing could be part of Rigify.

"""
Possible warnings to implement:
	- IK Chain is not flat - IK Chains should be flat along a plane for perfect IK/FK snapping and predictable bending direction. Instant Fix: Flatten Chain.
	- Arbitrary data - For debugging, this could be a lot more convenient than printing to the console.
	- Search code for "warning:" and "self.raise_error()" for more.
	- Can search "assert" but I think I cleaned them all up. (Asserts should never be user-facing and should always halt generation)
Some things are expensive to test so maybe should be checked outside of generation:
	- Symmetrical action setup's transform curves are actually asymmetrical
	- Action setup for curves whose value never changes
	- Symmetrically named rig owners have asymetrical children in the chain
	- Symmetrically named rigs have asymmetrical transformations
	- Symmetrically named rigs have asymmmetrical constraints
"""

def get_pretty_stack() -> str:
	ret = []
	stack = traceback.extract_stack()
	after_generator = False
	previous_sort_file = ""
	for i, frame in enumerate(stack):
		if 'generator' in frame.filename:
			after_generator = True
		if not after_generator:
			continue

		if 'troubleshooting.py' in frame.filename or frame.name=="add_log":
			continue

		short_file = frame.filename
		if 'scripts' in short_file:
			short_file = frame.filename.split("scripts")[1]
		
		if i>0 and frame.filename == stack[i-1].filename:
			short_file = " " * int(len(frame.filename)/2)

		ret.append(f"{short_file} -> {frame.name} -> line {frame.lineno}")

	ret = f" {chr(8629)}\n".join(ret)
	return ret

def get_object_hierarchy_recursive(obj, all_objects=[]):
	if obj not in all_objects:
		all_objects.append(obj)

	for c in obj.children:
		get_object_hierarchy_recursive(c, all_objects)

	return all_objects

class CloudLogManager:
	def __init__(self, metarig, rig):
		self.metarig = metarig
		self.rig = rig

	def log(self
			,description_short
			,owner_bone = ""
			,trouble_bone = ""
			,description = "Something went terribly wrong!"
			,icon = 'ERROR'
			,note = ""
			,note_icon = ''
			,operator = ''
			,op_kwargs = {}
			,op_text = ""
		):
		"""Add a log entry to the metarig object's data."""
		entry = self.metarig.data.cloudrig_parameters.logs.add()
		entry.pretty_stack = get_pretty_stack()
		entry.owner_bone = owner_bone
		entry.trouble_bone = trouble_bone
		entry.description_short = description_short
		entry.description = description
		entry.note = note
		entry.note_icon = note_icon
		entry.icon = icon
		entry.operator = operator
		entry.op_kwargs = json.dumps(op_kwargs)
		entry.op_text = op_text
		return entry
	
	def clear(self):
		cloudrig = self.metarig.data.cloudrig_parameters
		cloudrig.logs.clear()
		cloudrig.active_log_index = 0

	####################################################################
	# Functions for finding various issues at the end of rig generation.
	def report_unused_named_layers(self):
		rig = self.rig
		used_layers = [False]*32
		for b in rig.data.bones:
			for i in range(32):
				used_layers[i] = used_layers[i] or b.layers[i]

		rigify_layers = rig.data.rigify_layers
		for i, rigify_layer in enumerate(rigify_layers):
			if rigify_layer.name!="" and not rigify_layer.name.startswith("$") and not used_layers[i]:
				self.log("Layer named but empty"
					,description = f"Named Rigify Layer {rigify_layer.name} has no bones assigned so it should be removed or some bones assigned to it."
					,icon = 'LAYER_USED'
					,note = f"{rigify_layer.name} ({i})"
				)
		
		for i in range(32):
			if used_layers[i] and rigify_layers[i].name=="":
				self.log("Layer used but not named"
					,description = f"Layer {i} has bones on it, but it does not have a Rigify Layer Name, therefore it won't display in the Layers panel."
					,icon = 'LAYER_ACTIVE'
					,note = str(i)
				)

	def report_invalid_drivers(self):
		rig = self.rig
		objects = [rig] + get_object_hierarchy_recursive(rig)
		for o in objects:
			if not (hasattr(o, 'animation_data') and o.animation_data):
				continue
			for d in o.animation_data.drivers:
				if not d.is_valid:
					self.log("Invalid Driver"
						,description = f"Invalid driver:\nObject:\n {o.name}\nData path:\n {d.data_path}\nIndex: {d.array_index}"
						,icon = 'DRIVER'
						,note = o.name
					)
				

class CloudRigLogEntry(bpy.types.PropertyGroup):
	icon: StringProperty(
		name = "Icon"
		,description = "Icon for this log entry"
		,default = 'ERROR'
	)
	owner_bone: StringProperty(
		name = "Rig Bone"
		,description = "Name of the bone on the metarig which owns the rig that created this entry"
		,default = ""
	)
	note: StringProperty(
		name = "Note"
		,description = "Extra note that gets displayed in the UIList when there's no owner bone"
		,default = ""
	)
	note_icon: StringProperty(
		name = "Note Icon"
		,description = "Icon for the extra note"
		,default = ''
	)
	trouble_bone: StringProperty(
		name = "Problem Bone"
		,description = "Name of the bone on the generated rig which the entry relates to"
		,default = ""
	)
	description_short: StringProperty(
		name = "Short Description"
		,description = "Something went wrong!"
		,default = ""
	)
	description: StringProperty(
		name = "Description"
		,description = ""
		,default = ""
	)
	pretty_stack: StringProperty(
		name = "Pretty Stack"
		,description = "Stack trace in the code of where this log entry was added. For internal use only"
	)
	operator: StringProperty(
		name = "Operator"
		,description = "Operator that can fix the issue"
		,default=''
	)
	op_kwargs: StringProperty(
		name = "Operator Arguments"
		,description = "Keyword arguments that will be passed to the operator. This should be a string that can be eval()'d into a python dict"
		,default=''
	)
	op_text: StringProperty(
		name = "Operator Text"
		,description = "Text to display on quick fix button"
		,default=''
	)

class CLOUDRIG_UL_log_entry_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		rig = context.object
		cloudrig = data
		log = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(log, 'description_short', text="", icon=log.icon, emboss=False)
			if log.note!="":
				row.prop(log, 'note', emboss=False, text="")
			elif log.owner_bone!="":
				row.prop(log, 'owner_bone', text="", emboss=False, icon='BONE_DATA')

		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class CLOUDRIG_PT_log(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = 'data'
	bl_label = "Rigify Log"

	@classmethod
	def poll(cls, context):
		obj = context.object
		return is_cloud_metarig(context.object) and obj.mode in ('POSE', 'OBJECT')

	def draw(self, context):
		obj = context.object
		draw_cloudrig_log(self.layout, obj)

def draw_cloudrig_log(layout, metarig):
	rig = metarig.data.rigify_target_rig
	cloudrig = metarig.data.cloudrig_parameters
	logs = cloudrig.logs
	active_index = cloudrig.active_log_index

	row = layout.row()

	row.template_list(
		'CLOUDRIG_UL_log_entry_slots',
		'',
		cloudrig,
		'logs',
		cloudrig,
		'active_log_index',
	)

	if len(logs)==0:
		return

	log = logs[active_index]

	layout.use_property_split = False

	if log.owner_bone!="":
		split = layout.row().split(factor=0.3)
		split.label(text="Rig Element:")
		row = split.row()
		row.prop_search(log, 'owner_bone', metarig.data, 'bones', text="")
		row.enabled = False

	if rig and log.trouble_bone!="":
		split = layout.row().split(factor=0.3)
		split.label(text="Generated Bone:")
		row = split.row()
		row.prop_search(log, 'trouble_bone', metarig.data, 'bones', text="")
		row.enabled = False
	
	desc = log.description_short
	if log.description!="":
		desc = log.description
	draw_label_with_linebreak(layout, desc)

	if log.operator!='':
		row = layout.row()
		split = row.split(factor=0.2)
		split.label(text="Quick Fix:")
		if log.op_text:
			op = split.operator(log.operator, text=log.op_text)
		else:
			op = split.operator(log.operator)
		kwargs = json.loads(log.op_kwargs)
		for key in kwargs.keys():
			setattr(op, key, kwargs[key])

	layout.separator()

	if draw_dropdown(layout, cloudrig, 'log_show_stack_trace'):
		col = draw_label_with_linebreak(layout, log.pretty_stack, alert=True)

########################################
######### Quick-Fix Operators ##########
########################################
class CLOUDRIG_OT_Troubleshoot_RotationMode(bpy.types.Operator):
	"""Change rotation mode of a bone."""

	bl_idname = "pose.cloudrig_troubleshoot_rotationmode"
	bl_label = "Change Rotation Mode"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	bone_name: StringProperty()

	def invoke(self, context, event):
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		metarig = context.object
		pbone = metarig.pose.bones.get(self.bone_name)
		layout.prop(pbone, 'rotation_mode')

	def execute(self, context):
		metarig = context.object
		pbone = metarig.pose.bones.get(self.bone_name)
		if not pbone or pbone.rotation_mode=='QUATERNION':
			return {'CANCELLED'}

		remove_active_log(metarig)
		return { 'FINISHED' }

def remove_active_log(metarig):
	cloudrig = metarig.data.cloudrig_parameters
	logs = cloudrig.logs
	
	active_index = cloudrig.active_log_index
	# This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
	to_index = active_index
	if to_index > len(logs)-2:
		to_index = len(logs)-2

	cloudrig.logs.remove(active_index)
	cloudrig.active_log_index = to_index

classes = [
	CLOUDRIG_UL_log_entry_slots,
	CloudRigLogEntry,
	CLOUDRIG_PT_log,
	CLOUDRIG_OT_Troubleshoot_RotationMode
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)
