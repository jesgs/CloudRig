"""
This file is executed and loaded into a self-registering text datablock when a 
rig is generated with the CloudRig feature set.
It's responsible for drawing rig UI and operators such as IK/FK snapping and
keyframe baking.

The only change made during rig generation is replacing SCRIPT_ID with the name 
of the blend file. This is used to allow multiple characters generated with 
different versions of CloudRig to co-exist in the same scene. So each rig uses 
the script that belongs to it, and not another, potentially newer or older version.
"""

import bpy, traceback, json
from typing import List, Dict
from bpy.props import (
						StringProperty, BoolProperty, BoolVectorProperty, 
						EnumProperty, FloatVectorProperty, PointerProperty, 
						CollectionProperty, IntProperty
					)
from mathutils import Vector, Matrix
from math import radians, acos
from rna_prop_ui import rna_idprop_quote_path

from rigify.feature_sets.CloudRig.rig_ui import (get_chain_transform_matrices,
	RigifyBakeKeyframesMixin, set_transform_from_matrix, set_custom_property_value,
	get_autokey_flags, add_flags_if_set, keyframe_transform_properties)

script_id = "SCRIPT_ID"
# TODO: Shouldn't this be added to operator bl_idnames?

def get_rigs():
	""" Find all cloudrig armatures in the file. """
	return [o for o in bpy.data.objects if o.type=='ARMATURE' and 'cloudrig' in o.data]

def active_cloudrig():
	""" If the active object is a cloudrig, return it. """
	o = bpy.context.pose_object or bpy.context.object
	if o and o.type == 'ARMATURE' and 'cloudrig' in o.data and o.data['cloudrig']==script_id:
		return o

def get_char_bone(rig):
	for b in rig.pose.bones:
		if b.name.startswith("Properties_Character"):
			return b

def get_bones(rig, names):
	""" Return a list of pose bones from a string of bone names in json format. """
	return list(filter(None, map(rig.pose.bones.get, json.loads(names))))

def draw_rig_settings(layout, rig, dict_name, label=""):
	"""
	dict_name is the name of the custom property dictionary that we expect to find in the rig.
	Everything stored in a single dictionary is drawn in one call of this function.
	These dictionaries are created during rig generation.

	For an example dictionary, select an existing CloudRig, and put this in the PyConsole:
	>>> import json
	>>> print(json.dumps(C.object.data['ik_stretches'].to_dict(), indent=4))

	Parameters expected to be found in the dictionary:
		prop_bone: Name of the pose bone that holds the custom property.
		prop_id: Name of the custom property on aforementioned bone. This is the property that gets drawn in the UI as a slider.

	Further optional parameters:
		texts: List of strings to display alongside an integer property slider.
		operator: Specify an operator to draw next to the slider.
		icon: Override the icon of the operator. If not specified, default to 'FILE_REFRESH'.
		Any other arbitrary parameters will be passed on to the operator as kwargs.
	"""

	if dict_name not in rig.data: return

	if label != "":
		layout.label(text=label)

	main_dict = rig.data[dict_name].to_dict()
	# Each top-level dictionary within the main dictionary defines a row.
	for row_name in main_dict.keys():
		row = layout.row()
		# Each second-level dictionary within that defines a slider (and operator, if given).
		# If there is more than one, they will be drawn next to each other, since they're in the same row.
		row_entries = main_dict[row_name]
		for entry_name in row_entries.keys():
			info = row_entries[entry_name]		# This is the lowest level dictionary that contains the parameters for the slider and its operator, if given.
			assert 'prop_bone' in info and 'prop_id' in info, f"ERROR: Limb definition lacks properties bone or prop ID: {row_name}, {info}"
			prop_bone = rig.pose.bones.get(info['prop_bone'])
			prop_id = info['prop_id']
			assert prop_bone and prop_id in prop_bone, f"ERROR: Properties bone or property does not exist: {info}"

			col = row.column()
			sub_row = col.row(align=True)

			slider_text = entry_name
			if 'texts' in info:
				prop_value = prop_bone[prop_id]
				cur_text = info['texts'][int(prop_value)]
				slider_text = entry_name + ": " + cur_text

			sub_row.prop(prop_bone, '["' + prop_id + '"]', slider=True, text=slider_text)

			# Draw an operator if provided.
			if 'operator' in info:
				icon = 'FILE_REFRESH'
				if 'icon' in info:
					icon = info['icon']

				operator = sub_row.operator(info['operator'], text="", icon=icon)
				# Pass on any paramteres to the operator that it will accept.
				for param in info.keys():
					if hasattr(operator, param):
						value = info[param]
						# Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
						if type(value) in [list, dict]:
							value = json.dumps(value)
						setattr(operator, param, value)

def get_custom_property_value(rig, bone_name, prop_id):
	prop_bone = rig.pose.bones.get(bone_name)
	assert prop_bone, f"Bone snapping failed: Properties bone {bone_name} not found.)"
	assert prop_id in prop_bone, f"Bone snapping failed: Bone {bone_name} has no property {bone_id}"
	return prop_bone[prop_id]

class CloudRigSnapBakeMixin(RigifyBakeKeyframesMixin):
	""" Extend Rigify's keyframe baking with the ability to select the frame range
		as part of the operator, make baking optional, 
		and add the ability to affect more than a single bone.
	"""
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	bones:		  StringProperty(name="Control Bones")
	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	@classmethod
	def poll(cls, context):
		return context.pose_object

	### Override some inherited functions
	def init_invoke(self, context):
		self.frame_start = context.scene.frame_start
		self.frame_end = context.scene.frame_end
		self.bone_names = json.loads(self.bones)

	def init_execute(self, context):
		# In case the operator is executed without init.
		self.init_invoke(context)

	def bake_init(self, context):
		# Override to use operator's frame range instead of Rigify's globally set range.
		super().bake_init(context)
		self.bake_frame_range = (self.frame_start, self.frame_end)
		self.bake_frame_range_raw = self.nla_to_raw(self.bake_frame_range)

	def execute_scan_curves(self, context, obj):
		"Register frames to be baked, and return curves that should be cleared."
		self.bake_add_bone_frames(self.bone_names)
		return None

	def set_selection(self, context, bones):
		if self.select_bones:
			for b in context.selected_pose_bones:
				b.bone.select = False
			for b in bones:
				b.bone.select = True

class CLOUDRIG_OT_snap_bake(CloudRigSnapBakeMixin, bpy.types.Operator):
	""" Toggle a custom property while ensuring that some bones stay in place. """
	bl_idname = "pose.cloudrig_snap_bake"
	bl_label = "Snap And Bake Bones"

	def draw(self, context):
		# TODO: Display name of the property bone and property whose keyframes will be cleared.
		layout = self.layout

		self.layout.prop(self, 'do_bake')
		time_row = layout.row(align=True)
		if self.do_bake:
			time_row.prop(self, 'frame_start')
			time_row.prop(self, 'frame_end')

		bone_names = layout.column(align=True)
		bone_names.label(text="Affected bones:")
		for b in self.bone_names:
			bone_names.label(text="            " + b)

	def execute(self, context):
		rig = context.pose_object or context.active_object
		# TODO: Instead of relying on scene settings(auto-keying, keyingset, etc) maybe it would be better to have a custom boolean to decide whether to insert keyframes or not. Ask animators.
		self.keyflags = get_autokey_flags(context, ignore_keyset=True)
		self.keyflags_switch = add_flags_if_set(self.keyflags, {'INSERTKEY_AVAILABLE'})

		self.bone_names = json.loads(self.bones)

		if self.do_bake:
			return super().execute(context)

		bone_names = json.loads(self.bones)
		bones = get_bones(rig, self.bones)

		try:
			matrices = self.save_frame_state(context, rig)
			self.after_save_state(context, rig)
			self.apply_frame_state(context, rig, matrices)

		except Exception as e:
			traceback.print_exc()
			self.report({'ERROR'}, 'Exception: ' + str(e))

		self.set_selection(context, bones)

		return {'FINISHED'}

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		if not bone_names:
			bone_names = self.bone_names
		return get_chain_transform_matrices(rig, bone_names)

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value."""
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		if self.do_bake:
			any_curves_on_property = self.bake_get_bone_prop_curves(self.prop_bone, f'["{self.prop_id}"]')
			if any_curves_on_property:
				self.bake_replace_custom_prop_keys_constant(
					self.prop_bone, self.prop_id, 1-value
				)
		else:
			set_custom_property_value(
				rig, self.prop_bone, self.prop_id, 1-value,
				keyflags=self.keyflags_switch
			)
		context.view_layer.update()

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Restore transform matrices
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)

class CLOUDRIG_OT_switch_parent_bake(CLOUDRIG_OT_snap_bake):
	"""Extend CLOUDRIG_OT_snap_bake with a parent selector."""
	bl_idname = "pose.cloudrig_switch_parent_bake"
	bl_label = "Apply Switch Parent To Keyframes"
	bl_description = "Switch parent over a frame range, adjusting keys to preserve the bone position and orientation"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	bones:		  StringProperty(name="Control Bones")
	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])
	
	parent_names: StringProperty(name="Parent Names")

	def parent_items(self, context):
		parents = json.loads(self.parent_names)
		items = [(str(i), name, name) for i, name in enumerate(parents)]
		return items

	selected: EnumProperty(
		name='Selected Parent',
		items=parent_items
	)

	def draw(self, context):
		layout = self.layout

		self.layout.prop(self, 'selected', text='')
		super().draw(context)

	def after_save_state(self, context, rig):
		"""After saving the bone matrices, it's time to set the property value."""
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		if self.do_bake:
			self.bake_replace_custom_prop_keys_constant(
				self.prop_bone, self.prop_id, int(self.selected)
			)
		else:
			set_custom_property_value(
				rig, self.prop_bone, self.prop_id, int(self.selected),
				keyflags=self.keyflags_switch
			)
		context.view_layer.update()

class CLOUDRIG_OT_snap_mapped_bake(CLOUDRIG_OT_snap_bake):
	""" Extend CLOUDRIG_OT_snap_bake with the ability to snap a list of bones
		to another (equal length) list of bones.
	"""

	bl_idname = "pose.cloudrig_snap_mapped_bake"
	bl_label = "Snap And Bake Bones (Mapped)"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	map_on:		  StringProperty()		# Bone name dictionary to use when the property is toggled ON.
	map_off:	  StringProperty()		# Bone name dictionary to use when the property is toggled OFF.

	hide_on:	  StringProperty()		# List of bone names to hide when property is toggled ON.
	hide_off:	  StringProperty()		# List of bone names to hide when property is toggled OFF.

	# In save_frame_state, we save the states of the bones we're mapping to, and in apply_frame_state, we apply those states to the bones we're mapping from.
	# That should be the only tricky part I think... but I'm probably wrong.
	# For initial testing, use this for IK/FK switching (ignore pole target)

	def init_invoke(self, context):
		rig = context.pose_object or context.active_object
		value = get_custom_property_value(rig, self.prop_bone, self.prop_id)

		map_on = json.loads(self.map_on)
		map_off = json.loads(self.map_off)

		self.bone_map = map_off if value==1 else map_on
		bone_names = [t[0] for t in self.bone_map]
		self.bones = json.dumps(bone_names)
		super().init_invoke(context)	# This creates self.bone_names based on self.bones.

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		if not bone_names:
			bone_names = [t[1] for t in self.bone_map]
		return get_chain_transform_matrices(rig, bone_names, space='WORLD')

	def execute_scan_curves(self, context, obj):
		"Register frames to be baked, and return curves that should be cleared."
		bone_names = [t[1] for t in self.bone_map]
		self.bake_add_bone_frames(bone_names)
		bone_names = [t[0] for t in self.bone_map]
		self.bake_add_bone_frames(bone_names)
		return None

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Slap the transform matrices of the map_from bones to the map_to bones
		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, space='WORLD', keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)
			context.evaluated_depsgraph_get().update()	# This matters!!!!

class CLOUDRIG_OT_ikfk_bake(CLOUDRIG_OT_snap_mapped_bake):
	""" This should extend CLOUDRIG_OT_snap_mapped_bake with special treatment 
		for the IK elbow.
	"""

	bl_idname = "pose.cloudrig_toggle_ikfk_bake"
	bl_label = "Toggle And Bake IK/FK"
	bl_description = "Toggle a custom property and snap some bones to some other bones"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	# TODO: For some reason operator property definitions don't get inherited...???
	do_bake: BoolProperty(
		name="Bake Keyframes in Range",
		options={'SKIP_SAVE'},
		description="Bake keyframes for the affected bones and remove keyframes from the switched property",
		default=False
	)
	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame")

	prop_bone:	  StringProperty(name="Property Bone")
	prop_id:	  StringProperty(name="Property")
	select_bones: BoolProperty(name="Select Affected Bones", default=True)
	locks:		  BoolVectorProperty(name="Locked", size=3, default=[False,False,False])

	map_on:		  StringProperty()		# Bone name dictionary to use when the property is toggled ON.
	map_off:	  StringProperty()		# Bone name dictionary to use when the property is toggled OFF.

	hide_on:	  StringProperty()		# List of bone names to hide when property is toggled ON.
	hide_off:	  StringProperty()		# List of bone names to hide when property is toggled OFF.

	ik_pole:	StringProperty()
	fk_first:	StringProperty()
	fk_last:	StringProperty()

	def init_invoke(self, context):
		rig = context.object

		self.pole = rig.pose.bones.get(self.ik_pole)	# Can be None.
		prop_value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
		self.is_pole = prop_value==0 and self.pole!=None

		super().init_invoke(context)

		if self.is_pole:
			self.bone_names.append(self.pole.name)

	def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
		matrices = super().save_frame_state(context, rig, bone_names)
		if self.is_pole:
			matrices.append(self.get_pole_target_matrix())
		return matrices

	def apply_frame_state(self, context, rig, matrices: List[Matrix]):
		# Restore transform matrices

		for i, bone_name in enumerate(self.bone_names):
			old_matrix = matrices[i]
			set_transform_from_matrix(
				rig, bone_name, old_matrix, keyflags=self.keyflags,
				no_loc=self.locks[0], no_rot=self.locks[1], no_scale=self.locks[2]
			)
			context.evaluated_depsgraph_get().update()

	def get_pole_target_matrix(self):
		""" Find the matrix where the IK pole should be. """
		""" This is only accurate when the bone chain lies perfectly on a plane 
			and the IK Pole Angle is divisible by 90. 
			This should be the case for a correct IK chain! 
		"""

		fk_first = rig.pose.bones.get(self.fk_first)
		fk_last = rig.pose.bones.get(self.fk_last)
		assert fk_first and fk_last, f"Error: Can't calculate pole target location due to on of these FK bones missing: {self.fk_first}, {self.fk_last}"

		chain_length = fk_first.vector.length + fk_last.vector.length
		pole_distance = chain_length/2

		pole_direction = (fk_first.vector - fk_last.vector).normalized()

		pole_loc = fk_first.tail + pole_direction * pole_distance

		mat = self.pole.matrix.copy()
		mat.translation = pole_loc
		return mat

class CLOUDRIG_OT_reset_colors(bpy.types.Operator):
	bl_description = "Reset rig color properties to their stored default"
	bl_idname = "object.reset_rig_colors"
	bl_label = "Reset Rig Colors"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		rig = context.pose_object or context.object
		return 'cloudrig' in rig.data

	def execute(self, context):
		rig = context.pose_object or context.object
		for cp in rig.cloud_colors:
			cp.current = cp.default
		return {'FINISHED'}

class CloudRig_ColorProperties(bpy.types.PropertyGroup):
	""" Store a color property that can be used to drive colors on the rig, and then be controlled even when the rig is linked. """
	# Currently, a generated rig won't create any customproperties for itself.
	# You would have to create these for yourself with a separate python script.
	# C.object.data.cloud_colors.new()

	# The reset colors operator will reset all color properties to this default.
	# Nothing's stopping you from changing this default, but it's not exposed in the UI, so it shouldn't be easy to accidently mess up.
	default: FloatVectorProperty(
		name='Default',
		description='',
		subtype='COLOR',
		min=0,
		max=1,
		options={'LIBRARY_EDITABLE'}	# Make it not animatable.
	)
	current: FloatVectorProperty(
		name='Color',
		description='',
		subtype='COLOR',
		min=0,
		max=1,
		options={'LIBRARY_EDITABLE'}	# Make it not animatable.
	)

class CloudRig_Properties(bpy.types.PropertyGroup):
	""" PropertyGroup for storing fancy custom properties in. """

	def get_rig(self):
		""" Find the armature object that is using this instance (self). """

		for rig in get_rigs():
			if rig.cloud_rig == self:
				return rig

	def items_outfit(self, context):
		""" Items callback for outfits EnumProperty.
			Build and return a list of outfit names based on a bone naming convention.
			Bones storing an outfit's properties must be named "Properties_Outfit_OutfitName".
		"""
		rig = self.get_rig()
		if not rig: return [(('0', 'Default', 'Default'))]

		outfits = []
		for b in rig.pose.bones:
			if b.name.startswith("Properties_Outfit_"):
				outfits.append(b.name.replace("Properties_Outfit_", ""))

		# Convert the list into what an EnumProperty expects.
		items = []
		for i, outfit in enumerate(outfits):
			items.append((outfit, outfit, outfit, i))	# Identifier, name, description, can all be the outfit name.

		# If no outfits were found, don't return an empty list so the console doesn't spam "'0' matches no enum" warnings.
		if items==[]:
			return [(('0', 'Default', 'Default'))]

		return items

	def change_outfit(self, context):
		""" Update callback of outfits EnumProperty. """

		rig = self.get_rig()
		if not rig: return

		if self.outfit == '':
			self.outfit = self.items_outfit(context)[0][0]

		outfit_bone = rig.pose.bones.get("Properties_Outfit_"+self.outfit)

		if outfit_bone:
			# Reset all settings to default.
			for key in outfit_bone.keys():
				value = outfit_bone[key]
				if type(value) in [float, int]:
					pass # TODO: Can't seem to reset custom properties to their default, or even so much as read their default!?!?

			# For outfit properties starting with "_", update the corresponding character property.
			char_bone = get_char_bone(rig)
			for key in outfit_bone.keys():
				if key.startswith("_") and key[1:] in char_bone:
					char_bone[key[1:]] = outfit_bone[key]

		context.evaluated_depsgraph_get().update()

	# TODO: This should be implemented as an operator instead, just like parent switching.
	outfit: EnumProperty(
		name	= "Outfit",
		items	= items_outfit,
		update	= change_outfit,
		options	= {"LIBRARY_EDITABLE"} # Make it not animatable.
	)

class CLOUDRIG_PT_main(bpy.types.Panel):
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = 'CloudRig'

	@classmethod
	def poll(cls, context):
		return active_cloudrig() is not None

	def draw(self, context):
		layout = self.layout

class CLOUDRIG_PT_character(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_character_" + script_id
	bl_label = "Character"

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False

		# Only display this panel if there is either an outfit with options, multiple outfits, or character options.
		rig = active_cloudrig()
		if not rig: return
		rig_props = rig.cloud_rig
		multiple_outfits = len(rig_props.items_outfit(context)) > 1
		outfit_properties_bone = rig.pose.bones.get("Properties_Outfit_"+rig_props.outfit)
		char_bone = get_char_bone(rig)

		return multiple_outfits or outfit_properties_bone or char_bone

	def draw(self, context):
		layout = self.layout
		rig = context.pose_object or context.object

		rig_props = rig.cloud_rig

		def add_props(prop_owner):
			props_done = []
			bool_props = []		# Not implemented.

			def get_text(prop_id, value):
				""" If there is a property on prop_owner named $prop_id, expect it to be a list of strings and return the valueth element."""
				text = prop_id.replace("_", " ")
				if "$"+prop_id in prop_owner and type(value)==int:
					names = prop_owner["$"+prop_id]
					if value > len(names)-1:
						print(f"Warning: Name list for this property is not long enough for current value: {prop_id}")
						return text
					return text + ": " + names[value]
				else:
					return text

			def add_prop(layout, prop_owner, prop_id):
				if prop_id in props_done: return

				if(prop_id in bool_props):
					bp = bool_props[prop_id]
					layout.prop(bp, 'value', toggle=True, text=bp.name, icon='TRIA_DOWN' if parent_prop_value in values else 'TRIA_RIGHT')
				elif type(prop_owner[prop_id]) in [int, float]:
					layout.prop(prop_owner, '["'+prop_id+'"]', slider=True,
						text = get_text(prop_id, prop_owner[prop_id])
					)
				elif str(type(prop_owner[prop_id])) == "<class 'IDPropertyArray'>":
					# Vectors
					layout.prop(prop_owner, '["'+prop_id+'"]', text=prop_id.replace("_", " "))

			# Drawing properties with hierarchy
			if 'prop_hierarchy' in prop_owner:
				prop_hierarchy = prop_owner['prop_hierarchy']
				if type(prop_hierarchy)==str:
					prop_hierarchy = eval(prop_hierarchy)

				for parent_prop_name in prop_hierarchy.keys():
					parent_prop_name_without_values = parent_prop_name
					values = [1]	# Values which this property needs to be for its children to show. For bools this is always 1.
					# Example entry in prop_hierarchy: ['Jacket-23' : ['Hood', 'Belt']] This would mean Hood and Belt are only visible when Jacket is either 2 or 3.
					if('-' in parent_prop_name):
						split = parent_prop_name.split('-')
						parent_prop_name_without_values = split[0]
						values = [int(val) for val in split[1]]	# Convert them to an int list ( eg. '23' -> [2, 3] )

					parent_prop_value = prop_owner[parent_prop_name_without_values]

					# Drawing parent prop, if it wasn't drawn yet.
					add_prop(layout, prop_owner, parent_prop_name_without_values)

					# Marking parent prop as done drawing.
					props_done.append(parent_prop_name_without_values)

					# Checking if we should draw children.
					if(parent_prop_value not in values): continue

					# Drawing children.
					childrens_box = layout.box()
					for child_prop_name in prop_hierarchy[parent_prop_name]:
						add_prop(childrens_box, prop_owner, child_prop_name)

				# Marking child props as done drawing. (Regardless of whether they were actually drawn or not, since if the parent is disabled, we don't want to draw them.)
				for parent in prop_hierarchy.keys():
					for child in prop_hierarchy[parent]:
						props_done.append(child)

			# Drawing properties without hierarchy
			for prop_id in sorted(prop_owner.keys()):
				if prop_id.startswith("_"): continue
				if prop_id in props_done: continue

				add_prop(layout, prop_owner, prop_id)

		# Add character properties to the UI, if any.
		char_bone = get_char_bone(rig)
		if char_bone:
			add_props(char_bone)
			layout.separator()

		# Add outfit properties to the UI, if any.
		outfit_properties_bone = rig.pose.bones.get("Properties_Outfit_"+rig_props.outfit)
		if outfit_properties_bone:
			layout.prop(rig_props, 'outfit')
			add_props(outfit_properties_bone)

def draw_layers_ui(layout, rig, show_hidden=False, owner=None, layers_prop='layers'):
	""" Draw rig layer toggles based on data stored in rig.data.rigify_layers. """
	data = rig.data
	if not owner:
		owner = data
	# This should work even if the Rigify addon is not enabled.
	if 'rigify_layers' not in data:
		row = layout.row()
		row.alert=True
		row.label(text="Create Rigify layer data in the Rigify Layer Names panel.")
		return
	layer_data = data['rigify_layers']
	rigify_layers = [dict(l) for l in layer_data]

	for i, l in enumerate(rigify_layers):
		# When the Rigify addon is not enabled, finding the original index after sorting is impossible, so just store it.
		l['index'] = i
		if 'row' not in l:
			l['row'] = 1

	sorted_layers = sorted(rigify_layers, key=lambda l: l['row'])
	sorted_layers = [l for l in sorted_layers if 'name' in l and l['name']!=" "]
	current_row_index = 0
	for rigify_layer in sorted_layers:
		if rigify_layer['name'] in ["", " "]: continue
		if rigify_layer['name'].startswith("$") and not show_hidden: continue

		if rigify_layer['row'] > current_row_index:
			current_row_index = rigify_layer['row']
			row = layout.row()
		row.prop(owner, layers_prop, index=rigify_layer['index'], toggle=True, text=rigify_layer['name'])

class CLOUDRIG_PT_layers(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_layers_" + script_id
	bl_label = "Layers"

	@staticmethod

	def draw(self, context):
		rig = active_cloudrig()
		if not rig: return
		draw_layers_ui(self.layout, rig)

class CLOUDRIG_PT_settings(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_settings_" + script_id
	bl_label = "Settings"

class CLOUDRIG_PT_fkik(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_fkik_" + script_id
	bl_label = "FK/IK Switch"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		return rig and "ik_switches" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return

		draw_rig_settings(layout, rig, "ik_switches")

class CLOUDRIG_PT_ik(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_ik_" + script_id
	bl_label = "IK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		if not rig: return False
		ik_settings = ['ik_stretches', 'ik_hinges', 'parents', 'ik_pole_follows']
		for ik_setting in ik_settings:
			if ik_setting in rig.data:
				return True
		return False

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return

		draw_rig_settings(layout, rig, "ik_stretches", label="IK Stretch")
		draw_rig_settings(layout, rig, "ik_parents", label="IK Parents")
		draw_rig_settings(layout, rig, "ik_hinges", label="IK Hinge")
		draw_rig_settings(layout, rig, "ik_pole_follows", label="IK Pole Follow")

class CLOUDRIG_PT_fk(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_fk_" + script_id
	bl_label = "FK Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		if not rig: return False
		fk_settings = ['fk_hinges', 'auto_rubber_hose']
		for fk_setting in fk_settings:
			if fk_setting in rig.data:
				return True
		return False

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return

		draw_rig_settings(layout, rig, "fk_hinges", label='FK Hinge')
		draw_rig_settings(layout, rig, "auto_rubber_hose", label='Auto Rubber Hose')

class CLOUDRIG_PT_face(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_face_" + script_id
	bl_label = "Face Settings"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		return rig and "face_settings" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return

		draw_rig_settings(layout, rig, "face_settings", label='')

class CLOUDRIG_PT_misc(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_misc_" + script_id
	bl_label = "Misc"
	bl_parent_id = "CLOUDRIG_PT_settings_" + script_id

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		return rig and "misc_settings" in rig.data

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return

		draw_rig_settings(layout, rig, "misc_settings", label='')

class CLOUDRIG_PT_viewport(CLOUDRIG_PT_main):
	bl_idname = "CLOUDRIG_PT_viewport_" + script_id
	bl_label = "Viewport Display"

	@classmethod
	def poll(cls, context):
		rig = active_cloudrig()
		return rig and hasattr(rig, "cloud_colors") and len(rig.cloud_colors)>0

	def draw(self, context):
		layout = self.layout
		rig = active_cloudrig()
		if not rig: return
		layout.operator(CLOUDRIG_OT_reset_colors.bl_idname, text="Reset Colors")
		layout.separator()
		for cp in rig.cloud_colors:
			layout.prop(cp, "current", text=cp.name)

classes = (
	CLOUDRIG_OT_switch_parent_bake
	,CLOUDRIG_OT_ikfk_bake
	,CLOUDRIG_OT_snap_mapped_bake
	,CLOUDRIG_OT_snap_bake
	,CLOUDRIG_OT_reset_colors

	,CloudRig_ColorProperties
	,CloudRig_Properties

	,CLOUDRIG_PT_character
	,CLOUDRIG_PT_layers
	,CLOUDRIG_PT_settings
	,CLOUDRIG_PT_fkik
	,CLOUDRIG_PT_ik
	,CLOUDRIG_PT_fk
	,CLOUDRIG_PT_face
	,CLOUDRIG_PT_misc
	,CLOUDRIG_PT_viewport
)

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

	# We store everything in Object rather than Armature because Armature data cannot be accessed on proxy armatures.
	bpy.types.Object.cloud_rig = PointerProperty(type=CloudRig_Properties)
	bpy.types.Object.cloud_colors = CollectionProperty(type=CloudRig_ColorProperties)

def unregister():
	from bpy.utils import unregister_class
	for c in classes:
		unregister_class(c)

	del bpy.types.Object.cloud_rig
	del bpy.types.Object.cloud_colors

register()