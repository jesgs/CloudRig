from typing import List
from bpy.types import PropertyGroup, Panel, UIList, Operator, Object
from bpy.props import StringProperty

import bpy, os, traceback
import json, webbrowser, time
import struct, platform, io, urllib.parse, importlib

from ..rig_features.ui import is_cloud_metarig, draw_label_with_linebreak, is_advanced_mode

from rigify.utils.errors import MetarigError

# This whole thing could be part of Rigify.

"""
About generation errors: Fatal errors can happen in 3 distinct ways:
- Generic execution error: This is a bug, should never happen and should be reported on GitLab.
	- Raised by: Interpreter
	- Caught in: generate_rig()
	- User gets a stack trace in both the pop-up and the Rigify Log; The latter also provides a Report Bug button.
- Post-generation script error: This is a bug in the code written by the user.
	- Raised by: Interpreter
	- Caught in: execute_custom_script()
	- User gets a stack trace of only their script, both in the pop-up and the Rigify Log.
- Metarig Error: This is a mistake in the MetaRig's bone setup.
	- Raised by: self.raise_error() -> logger.log_error()
	- Caught in: generate_rig()
	- User gets no stack trace unless they look at the Rigify Log with Advanced Mode enabled.

Common to all 3 types:
	- Since these are fatal errors, any other rig errors are removed from the Rigify Log.
"""

"""
Possible warnings to implement:
	- IK Chain is not flat - IK Chains should be flat along a plane for perfect IK/FK snapping and predictable bending direction. Instant Fix: Flatten Chain.
Some things are expensive to test so maybe should be checked outside of generation:
	- Symmetrical action setup's transform curves are actually asymmetrical
	- Action setup for curves whose value never changes
	- Symmetrically named rig owners have asymetrical children in the chain
	- Symmetrically named rigs have asymmetrical transformations
	- Symmetrically named rigs have asymmmetrical constraints
"""


def cloudrig_last_modified() -> str:
	"""Return the date at which the most recent CloudRig .py file was modified.

	Used in the bug report form pre-fill.
	"""
	max_mtime = 0
	for dirname, subdirs, files in os.walk(os.path.dirname(__file__)):
		for fname in files:
			full_path = os.path.join(dirname, fname)
			mtime = os.path.getmtime(full_path)
			if mtime > max_mtime:
				max_mtime = mtime
				max_file = fname

	# For me this is in UTC, I can only hope it is for everyone.
	return time.strftime('%Y-%m-%d %H:%M', time.gmtime(max_mtime))

def url_prefill_from_cloudrig(stack_trace=""):
	fh = io.StringIO()

	fh.write("**System Information**\n")
	fh.write(
		"Operating system: %s %d Bits\n" % (
			platform.platform(),
			struct.calcsize("P") * 8,
		)
	)

	fh.write(
		"\n"
		"**Blender Version**\n"
	)
	fh.write(
		"%s, branch: %s, commit: [%s](https://developer.blender.org/rB%s)\n" % (
			bpy.app.version_string,
			bpy.app.build_branch.decode('utf-8', 'replace'),
			bpy.app.build_commit_date.decode('utf-8', 'replace'),
			bpy.app.build_hash.decode('ascii'),
		)
	)

	cloudrig_folder_name = os.path.dirname(__file__).split(os.sep)[-2]
	CloudRig = importlib.import_module('rigify.feature_sets.' + cloudrig_folder_name)
	cloudrig_version = CloudRig.rigify_info['version']
	last_modified = cloudrig_last_modified()
	fh.write(
		f"\n**CloudRig Version**: {cloudrig_version} ({last_modified})\n"
	)

	if stack_trace!="":
		fh.write(
			"\nStack trace\n```\n" + stack_trace + "\n```\n"
		)

	fh.write(
		"\n"
		"***************************************"
	)

	fh.write(
		"\n"
		"Description of the problem:\n"
		"Attached .blend file to reproduce the problem:\n"
		"\n"
	)

	fh.seek(0)

	return (
		"https://gitlab.com/blender/CloudRig/-/issues/new?issue[description]=" +
		urllib.parse.quote(fh.read())
	)

def get_pretty_stack() -> str:
	ret = []
	stack = traceback.extract_stack()
	after_generator = False
	for i, frame in enumerate(stack):
		if 'generator' in frame.filename:
			after_generator = True
		if not after_generator:
			continue
		if frame.name in ("log", "log_error", "log_bug"):
			break

		short_file = frame.filename
		if 'scripts' in short_file:
			short_file = frame.filename.split("scripts")[1]

		if i>0 and frame.filename == stack[i-1].filename:
			short_file = " " * int(len(frame.filename)/2)

		ret.append(f"{short_file} -> {frame.name} -> line {frame.lineno}")

	ret = f" {chr(8629)}\n".join(ret)
	return ret

# TODO: This should move to rig_features.object
def get_object_hierarchy_recursive(obj: Object, all_objects=[]):
	if obj not in all_objects:
		all_objects.append(obj)

	for c in obj.children:
		get_object_hierarchy_recursive(c, all_objects)

	return all_objects

def get_datablock_type_icon(datablock):
	"""Return the icon string representing a datablock type"""
	# It's beautiful.
	# There's no proper way to get the icon of a datablock, so we use the
	# RNA definition of the id_type property of the DriverTarget class,
	# which is an enum with a mapping of each datablock type to its icon.
	# TODO: It would unfortunately be nicer to just make my own mapping.
	if not hasattr(datablock, "type"):
		# shape keys...
		return 'NONE'
	typ = datablock.type
	if datablock.type == 'SHADER':
		typ = 'NODETREE'
	return bpy.types.DriverTarget.bl_rna.properties['id_type'].enum_items[typ].icon

class CloudLogManager:
	"""Class to manage CloudRigLogEntry CollectionProperty on metarigs.

	This class is instanced once per rig generation, by the CloudGenerator class.
	"""

	def __init__(self, metarig, rig=None):
		self.metarig = metarig
		self.rig = rig

	def log(self
			,description_short: str
			,*
			,owner_bone = ""
			,trouble_bone = ""
			,description = "No description."
			,icon = 'ERROR'
			,note = ""
			,note_icon = 'NONE'
			,operator = ''
			,op_kwargs = {}
			,op_text = ""
		):
		"""Add a log entry to the metarig object's data."""
		entry = self.metarig.data.cloudrig_parameters.logs.add()
		entry.pretty_stack = get_pretty_stack()
		entry.owner_bone = owner_bone
		entry.trouble_bone = trouble_bone
		entry.name = owner_bone + " " + trouble_bone + " " + description_short + " " + note + " " + description # For search.
		entry.description_short = description_short
		entry.description = description
		entry.note = note
		entry.note_icon = note_icon
		entry.icon = icon
		entry.operator = operator
		entry.op_kwargs = json.dumps(op_kwargs)
		entry.op_text = op_text
		return entry

	def log_bug(self
			,description_short: str
			,*
			,description = "Execution error occurred."
			,icon = 'URL'
			,operator = 'wm.cloudrig_report_bug'
			,**kwargs
		):
		"""This should be used over asserts, especially when something small goes wrong that shouldn't halt generation."""
		if 'op_kwargs' not in kwargs:
			kwargs['op_kwargs'] = {}
			kwargs['op_kwargs']['stack_trace'] = get_pretty_stack()
		self.clear()
		return self.log(
			"(Fatal) " + description_short
			,description = description + "\nThis might be a bug in CloudRig."
			,icon = icon
			,operator = operator
			,**kwargs
		)

	def log_error(self
			,description_short: str
			,popup_text = ""
			,pretty_stack = ""
			,clear_logs = True
			,*
			,description = ""
			,**kwargs
		):
		"""This should be used by self.raise_error()."""
		if clear_logs:
			self.clear()
		entry = self.log(
			"(Fatal) " + description_short
			,description = description or description_short
			,**kwargs
		)

		if pretty_stack:
			entry.pretty_stack = pretty_stack

		message = description or description_short
		if 'owner_bone' in kwargs:
			owner_bone = kwargs['owner_bone']
			message = f'"{owner_bone}": {message}'
		
		message += "\n" + popup_text

		raise MetarigError(message)

	def clear(self):
		cloudrig = self.metarig.data.cloudrig_parameters
		cloudrig.logs.clear()
		cloudrig.active_log_index = 0

	####################################################################
	# Functions for finding various issues at the end of rig generation.
	# For these, self.rig is expected to be set.
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
					,description = f'Named Rigify Layer "{rigify_layer.name}" has no bones assigned so it should be removed or some bones assigned to it.'
					,icon		 = 'LAYER_USED'
					,note		 = f"{rigify_layer.name} ({i})"
				)

		for i in range(32):
			if i > len(rigify_layers)-1:
				# TODO (upstream): Rigify Layers should be initialized as a list of 32 booleans!!!
				break
			if used_layers[i] and rigify_layers[i].name=="":
				self.log("Layer used but not named"
					,description = f"Layer {i} has bones on it, but it does not have a Rigify Layer Name, therefore it won't display in the Layers panel."
					,icon = 'LAYER_ACTIVE'
					,note = str(i)
				)

	def report_invalid_drivers_on_datablock(self, datablock, owner_datablock=None):
		if not datablock: return
		if not hasattr(datablock, "animation_data"): return
		if not datablock.animation_data: return
		for fcurve in datablock.animation_data.drivers:
			driver = fcurve.driver
			if not driver.is_valid:
				owner = owner_datablock or datablock

				owner_bone = ""
				trouble_bone = ""
				if 'pose.bones' in fcurve.data_path:
					bone_name = fcurve.data_path.split('pose.bones["')[1].split('"]')[0]
					if type(datablock) == Object and datablock.type == 'ARMATURE' and datablock.data.rigify_target_rig == self.rig:
						owner_bone = bone_name
					elif datablock == self.rig:
						trouble_bone = bone_name

				self.log("Invalid Driver"
					,description  = f'Invalid driver:\nDatablock: "{owner.name}"\nData path: "{fcurve.data_path}"\nIndex: {fcurve.array_index}'
					,icon		  = 'DRIVER'
					,note		  = owner.name
					,note_icon	  = get_datablock_type_icon(datablock)
					,owner_bone	  = owner_bone
					,trouble_bone = trouble_bone
					,operator	  = 'screen.drivers_editor_show'
				)

	def report_invalid_drivers_on_object_hierarchy(self, object: Object):
		"""Create log entries for invalid drivers of the object or any of its children"""
		objects = get_object_hierarchy_recursive(object, all_objects=[])

		for o in objects:
			self.report_invalid_drivers_on_datablock(o)
			if hasattr(o, "data") and o.data:
				self.report_invalid_drivers_on_datablock(o.data, owner_datablock=o)
			if o.type=='MESH':
				self.report_invalid_drivers_on_datablock(o.data.shape_keys, owner_datablock=o)

			for ms in o.material_slots:
				if ms.material:
					self.report_invalid_drivers_on_datablock(ms.material)
					self.report_invalid_drivers_on_datablock(ms.material.node_tree, owner_datablock=ms.material)

	def report_widgets(self, widget_collection):
		"""Find and log unused and duplicate widgets."""

		widgets = widget_collection.all_objects

		used_widgets = []
		for pb in self.rig.pose.bones:
			if pb.custom_shape and pb.custom_shape.name not in used_widgets:
				used_widgets.append(pb.custom_shape.name)

		for widget in widgets:
			unprefixed = widget.name
			if widget.name[-4]=='.':
				unprefixed = widget.name[:-4]

			if widget.name not in used_widgets and unprefixed not in used_widgets:
				self.log("Unused widget"
					,note = widget.name
					,icon = 'X'
					,description = f"Widget '{widget.name}' is not used by any bones."
					,operator = CLOUDRIG_OT_Delete_Object.bl_idname
					,op_kwargs = {'ob_name' : widget.name}
				)

			if unprefixed != widget.name:
				if unprefixed in bpy.data.objects:
					self.log("Duplicate widget"
						,note		 = widget.name
						,icon		 = 'DUPLICATE'
						,description = f"There exists a widget called '{unprefixed}', that should be used instead of '{widget.name}'."
						,operator	 = CLOUDRIG_OT_Swap_Bone_Shape.bl_idname
						,op_kwargs	 = {'old_name' : widget.name, 'new_name' : unprefixed}
					)
				else:
					self.log("Widget with number suffix"
						,note		 = widget.name
						,icon		 = 'FILE_TEXT'
						,description = f"The '{widget.name[-4:]}' suffix in the name of this widget is not necessary."
						,operator	 = CLOUDRIG_OT_Rename_Object.bl_idname
						,op_kwargs	 = {'old_name' : widget.name, 'new_name' : unprefixed}
					)

class CloudRigLogEntry(PropertyGroup):
	"""Container for storing information about a single metarig warning/error.

	A CollectionProperty of CloudRigLogEntries are added to the armature datablock
	in cloud_generator.register().

	This CollectionProperty is then populated by CloudLogManager via log() and
	log_bug() functions.
	"""

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
		,default = 'NONE'
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

class CLOUDRIG_UL_log_entry_slots(UIList):
	"""CloudRigLogEntry's are displayed under Properties->Armature->Rigify Log,
	when the active object is a CloudRig Metarig.
	"""
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		rig = context.object
		cloudrig = data
		log = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(log, 'description_short', text="", icon=log.icon, emboss=False)
			if log.note != "":
				row.prop(log, 'note', emboss=False, text="", icon=log.note_icon or 'NONE')
			elif log.owner_bone != "":
				row.prop(log, 'owner_bone', text="", emboss=False, icon='BONE_DATA')

		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class CLOUDRIG_PT_log(Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = 'data'
	bl_label = "Rigify Log"
	bl_options = {'DEFAULT_CLOSED'}

	@classmethod
	def poll(cls, context):
		obj = context.object
		return is_cloud_metarig(context.object) and obj.mode in ('POSE', 'OBJECT')

	def draw(self, context):
		metarig = context.object
		cloudrig = metarig.data.cloudrig_parameters
		logs = cloudrig.logs
		active_index = cloudrig.active_log_index
		layout = self.layout
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

		# It is optional for the log entry to provide a bone from the metarig, in case
		# the log entry relates to a rigify type.
		if log.owner_bone != "":
			split = layout.row().split(factor=0.3)
			split.label(text="Rig Element:")
			main_row = split.column().row(align=True)
			row = main_row.row(align=True)
			row.prop_search(log, 'owner_bone', metarig.data, 'bones', text="")
			row.enabled = False
			row = main_row.row(align=True)
			op = row.operator('ui.jump_to_target', text="", icon='LOOP_FORWARDS')
			op.target_bone = log.owner_bone

		if log.trouble_bone != "":
			split = layout.row().split(factor=0.3)
			split.label(text="Generated Bone:")
			main_row = split.column().row(align=True)
			row = main_row.row(align=True)
			row.prop_search(log, 'trouble_bone', metarig.data, 'bones', text="")
			row.enabled = False
			row = main_row.row(align=True)
			op = row.operator('ui.jump_to_target', text="", icon='LOOP_FORWARDS')
			op.use_target_rig = True
			op.target_bone = log.trouble_bone

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

class CLOUDRIG_PT_stack_trace(Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_parent_id = 'CLOUDRIG_PT_log'
	bl_label = "Python Stack Trace"

	@classmethod
	def poll(cls, context):
		cloudrig = context.object.data.cloudrig_parameters
		logs = cloudrig.logs
		is_fatal_error = len(logs) == 1 and "Fatal" in logs[0].name	# Always display stack trace of fatal errors, even without Advanced Mode.
		return len(logs) > 0 and is_advanced_mode(context) or is_fatal_error

	def draw(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		logs = cloudrig.logs
		active_index = cloudrig.active_log_index
		log = logs[active_index]
		draw_label_with_linebreak(self.layout, log.pretty_stack, alert=True)

########################################
######### Quick-Fix Operators ##########
########################################
class CLOUDRIG_OT_Change_Rotation_Mode(Operator):
	"""Change rotation mode of a bone"""

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

class CLOUDRIG_OT_Report_Bug(Operator):
	"""Report a bug on the CloudRig repository"""

	bl_idname = "wm.cloudrig_report_bug"
	bl_label = "Report Bug (Requires GitLab Account)"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	stack_trace: StringProperty()

	def execute(self, context):
		webbrowser.open(url_prefill_from_cloudrig(self.stack_trace))

		return { 'FINISHED' }

class CLOUDRIG_OT_Rename_Bone(Operator):
	"""Rename a bone"""

	bl_idname = "object.cloudrig_rename_bone"
	bl_label = "Rename Bone"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	old_name: StringProperty() # Should be provided to the operator by the UI, and not changed!
	new_name: StringProperty(name="Name") # Exposed to user

	def invoke(self, context, event):
		wm = context.window_manager
		self.new_name = self.old_name
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		metarig = context.object
		if self.new_name in metarig.data.bones:
			layout.prop(self, 'new_name', icon='ERROR')
			layout.label(text="This bone name is taken!")
		else:
			layout.prop(self, 'new_name')
			layout.label(text="Bone name available!")

	def execute(self, context):
		metarig = context.object
		bone = metarig.data.bones.get(self.old_name)
		if self.new_name in metarig.data.bones:
			self.report({'ERROR'}, "That bone name is already taken!")
			return {'CANCELLED'}
		assert bone, f"Error! Old bone {self.old_name} not found or not provided! This should never happen."

		bone.name = self.new_name
		if bone.name == self.new_name:
			remove_active_log(metarig)
		return { 'FINISHED' }

class CLOUDRIG_OT_Swap_Bone_Shape(Operator):
	"""Redirect custom bone shape references from one object to another"""

	bl_idname = "object.cloudrig_swap_bone_shape"
	bl_label = "Swap Bone Shapes"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# Both of these should be provided by the UI.
	old_name: StringProperty()
	new_name: StringProperty()

	def execute(self, context):
		metarig = context.object
		old_obj = bpy.data.objects.get((self.old_name, None))
		new_obj = bpy.data.objects.get((self.new_name, None))

		assert old_obj and new_obj, f"Error! One of {self.old_name} or {self.new_name} wasn't found! This should never happen."

		rigs = [metarig]

		rig = metarig.data.rigify_target_rig
		if rig:
			rigs.append(rig)

		for rig in rigs:
			for pb in rig.pose.bones:
				if pb.custom_shape == old_obj:
					pb.custom_shape = new_obj

		bpy.data.objects.remove(old_obj)
		widget_collection = metarig.data.cloudrig_parameters.widget_collection
		if widget_collection and new_obj.name not in widget_collection.objects:
			widget_collection.objects.link(new_obj)

		remove_active_log(metarig)
		self.report({'INFO'}, f"Successfully replaced all references of {self.old_name}(now deleted) to {self.new_name}.")
		return { 'FINISHED' }

class CLOUDRIG_OT_Rename_Object(Operator):
	"""Rename an object"""

	bl_idname = "object.cloudrig_rename_object"
	bl_label = "Rename Object"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	old_name: StringProperty() # Should be provided to the operator by the UI, and not changed!
	new_name: StringProperty(name="Name") # Exposed to user

	def invoke(self, context, event):
		wm = context.window_manager
		if self.new_name=='':
			self.new_name = self.old_name
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		if self.new_name in bpy.data.objects:
			layout.prop(self, 'new_name', icon='ERROR')
			layout.label(text="This object name is taken!")
		else:
			layout.prop(self, 'new_name')
			layout.label(text="Object name available!")

	def execute(self, context):
		metarig = context.object
		obj = bpy.data.objects.get((self.old_name, None))

		if self.new_name in bpy.data.objects:
			self.report({'ERROR'}, "That object name is already taken!")
			return {'CANCELLED'}
		assert obj, f"Error! Old object {self.old_name} not found or not provided! This should never happen."

		obj.name = self.new_name
		if obj.name == self.new_name:
			remove_active_log(metarig)
		return { 'FINISHED' }

class CLOUDRIG_OT_Delete_Object(Operator):
	"""Delete an object"""

	bl_idname = "object.cloudrig_delete_object"
	bl_label = "Delete Object"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# Should be provided by the UI.
	ob_name: StringProperty()

	def execute(self, context):
		metarig = context.object
		ob = bpy.data.objects.get((self.ob_name, None))

		assert ob, f"Error! {self.ob_name} wasn't found! This should never happen."

		bpy.data.objects.remove(ob)

		remove_active_log(metarig)
		self.report({'INFO'}, f"Successfully deleted {self.ob_name}.")
		return { 'FINISHED' }

class CLOUDRIG_OT_Clear_Pointer(Operator):
	"""Set a datablock pointer parameter to None"""

	bl_idname = "object.cloudrig_clear_pointer_param"
	bl_label = "Clear Pointer Parameter"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# Should be provided by the UI.
	bone_name: StringProperty()
	param_name: StringProperty()

	def execute(self, context):
		metarig = context.object
		bone = metarig.pose.bones.get(self.bone_name)
		old_ref = getattr(bone.rigify_parameters, self.param_name)
		setattr(bone.rigify_parameters, self.param_name, None)

		self.report({'INFO'}, f"Successfully cleared reference to {old_ref.name} on {bone.name}.")
		remove_active_log(metarig)
		return { 'FINISHED' }

def remove_active_log(metarig: Object):
	cloudrig = metarig.data.cloudrig_parameters
	logs = cloudrig.logs

	active_index = cloudrig.active_log_index
	# This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
	to_index = active_index
	if to_index > len(logs)-2:
		to_index = len(logs)-2

	cloudrig.logs.remove(active_index)
	cloudrig.active_log_index = to_index

registry = [
	CLOUDRIG_UL_log_entry_slots,
	CloudRigLogEntry,
	CLOUDRIG_PT_log,
	CLOUDRIG_PT_stack_trace,

	CLOUDRIG_OT_Change_Rotation_Mode,
	CLOUDRIG_OT_Report_Bug,
	CLOUDRIG_OT_Rename_Bone,
	CLOUDRIG_OT_Swap_Bone_Shape,

	CLOUDRIG_OT_Rename_Object,
	CLOUDRIG_OT_Delete_Object,

	CLOUDRIG_OT_Clear_Pointer
]