
from typing import List, Tuple

import bpy
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty
from .utils.ui_list import draw_ui_list
from .utils.ui import draw_label_with_linebreak

class CLOUDRIG_UL_parent_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		parent_slot = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(parent_slot, 'name', text=f"", emboss=True)
			row.prop_search(parent_slot, 'bone', rig.data, 'bones', text="")
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class ParentSlot(bpy.types.PropertyGroup):
	name: StringProperty(name="Name", description="Name to display in the UI for this parent option")
	bone: StringProperty(name="Bone", description="Bone that will be used as the parent")

def draw_cloudrig_parents(layout, context, text=""):
	draw_label_with_linebreak(layout, text, align_split=True)

	draw_ui_list(
		layout
		,context
		,class_name = 'CLOUDRIG_UL_parent_slots'
		,list_context_path = 'active_pose_bone.rigify_parameters.CR_base_parent_slots'
		,active_idx_context_path = 'active_pose_bone.rigify_parameters.CR_base_active_parent_slot_index'
	)

class CloudParentSwitchMixin:
	"""Class that provides parent switching parameters to CloudBaseRig."""
	def apply_parent_switching(self, parent_slots,
			child_bone=None,
			prop_bone=None, prop_name="",
			ui_area="misc_settings", row_name="", col_name=""
		):
		"""Rig a bone with multiple switchable parents, using Armature constraint and drivers."""
		if not child_bone:
			child_bone = self.root_bone
		if not prop_bone:
			prop_bone = self.properties_bone
		if prop_name=="":
			prop_name="parents_"+child_bone.name
		if row_name=="":
			row_name = child_bone.name.split(".")[0]
		if col_name=="":
			col_name = child_bone.name

		# Create parent bone that will hold the Armature constraint.
		arm_con_bone = self.create_parent_bone(child_bone, self.bones_mch)
		arm_con_bone.name = "P-" + child_bone.name
		arm_con_bone.custom_shape = None

		parent_ui_names, parent_bone_names = self.sanitize_parent_list(parent_slots)
		if not parent_ui_names:
			return

		targets = [{'subtarget' : bone_name} for bone_name in parent_bone_names]

		# Create custom property
		info = {
			"prop_bone" : prop_bone,
			"prop_id" : prop_name,
			"texts" : parent_ui_names,

			"operator" : "pose.cloudrig_switch_parent_bake",
			"icon" : "COLLAPSEMENU",
			"parent_names" : parent_ui_names,
			"bones" : [child_bone.name],
			}
		self.add_ui_data(ui_area, row_name, col_name, info, default=0, max=len(parent_ui_names)-1)

		# Add armature constraint
		arm_con = arm_con_bone.add_constraint('ARMATURE',
			targets = targets
		)

		# Add weight drivers
		for i, t in enumerate(arm_con.targets):
			arm_con.drivers.append({
				'prop' : f'targets[{i}].weight',
				'expression' : f'parent=={i}',
				'variables' : {
					'parent' : {
						'type' : 'SINGLE_PROP',
						'targets' : [{
							'data_path' : f'pose.bones["{prop_bone.name}"]["{prop_name}"]'
						}]
					}
				}
			})

	def sanitize_parent_list(self, parent_slots: List[ParentSlot]) -> Tuple[List[str], List[str]]:
		"""Gather parent information and check for issues.
		Returns two lists of equal length, first one is the UI name second is 
		the bone name of each parent.
		"""

		parent_bone_names = []
		parent_ui_names = []

		for i, ps in enumerate(parent_slots):
			if ps.bone == "":
				self.add_log(
					"Parent not found"
					,description=f"Parent slot #{i}: {ps.bone} not specified, skipping."
				)
				continue
			if ps.name == "":
				self.add_log(
					"Nameless parent"
					,description = f"Parent slot #{i}: {ps.bone} has no UI name, falling back to the bone's name."
				)
				parent_ui_names.append(ps.bone)
			else:
				parent_ui_names.append(ps.name)
			parent_bone_names.append(ps.bone)

		if len(parent_ui_names) == 0:
			self.add_log("No parents found"
				,description = f"No parents specified for parent switching setup, skipping completely."
			)
			return [], []

		# Force the Root to be an available parent for all parent switching setups
		# TODO: This should be removed after Sprite Fright!
		if self.generator_params.cloudrig_parameters.create_root and 'root' not in parent_bone_names:
			parent_ui_names.insert(0, "Root")
			parent_bone_names.insert(0, 'root')

		return parent_ui_names, parent_bone_names

	def apply_custom_root_parent(self, bone=None, parent_name=""):
		if not bone:
			bone = self.root_bone
		if parent_name == "":
			parent_name = self.params.CR_base_parent

		self.bendy_parenting(bone, parent_name)

	@classmethod
	def add_parent_switch_parameters(cls, params):
		params.CR_base_parent_switching = BoolProperty(
			name		 = "Parent Switching"
			,description = "Use parent switching for this rig. Different rig types may implement this differently. A rig-type-specific explanation is shown below when enabled"
			,default	 = False
		)
		params.CR_base_parent = StringProperty(
			name		 = "Root Parent"
			,description = "If specified, parent the root of this rig to the chosen bone. If a bendy bone is chosen, a parent helper bone with an Armature Constraint will be created to correctly inherit transforms from the curvature"
			,default	 = ""
		)
		params.CR_base_active_parent_slot_index = IntProperty()

		# NOTE: Currently this causes an error when turning the Rigify addon off and back on, unless running Reload Scripts in between.
		# I suspect this is because of the whole ParameterValidator shennanigans, but I couldn't figure out a fix.
		params.CR_base_parent_slots = CollectionProperty(type=ParentSlot)

	@classmethod
	def draw_parent_param(cls, layout, rig, params):
		parent_bone = rig.pose.bones.get(params.CR_base_parent)
		text = "Root Parent: "
		if parent_bone and parent_bone.bone.bbone_segments > 1:
			text = "Root Parent (Bendy): "
		cls.draw_prop_search(layout, params, 'CR_base_parent', rig.pose, 'bones', text=text)

	@classmethod
	def draw_parenting_params(cls, layout, context, params):
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		if not rig:
			draw_label_with_linebreak(layout, "Generate the rig to see parenting parameters.", align_split=True)
			return

		if cls.parent_switch_overwrites_root_parent:
			cls.draw_prop(layout, params, "CR_base_parent_switching")
			if params.CR_base_parent_switching:
				draw_cloudrig_parents(layout, context, cls.parent_switch_behaviour)
			else:
				cls.draw_parent_param(layout, rig, params)
		else:
			cls.draw_parent_param(layout, rig, params)
			cls.draw_prop(layout, params, "CR_base_parent_switching")
			if params.CR_base_parent_switching:
				draw_cloudrig_parents(layout, context, cls.parent_switch_behaviour)

classes = [
	ParentSlot,
	CLOUDRIG_UL_parent_slots,
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)