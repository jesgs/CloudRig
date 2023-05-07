
from typing import List, Tuple

import bpy
from bpy.types import PropertyGroup
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty
from ..utils.generic_ui_list import draw_ui_list
from ..utils.misc import get_active_pose_bone
from ..rig_component_features.ui import draw_label_with_linebreak

# TODO: Creating a helper bone to hold the Armature constraint should also be optional when using parent switching.

class CLOUDRIG_UL_parent_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		metarig = context.object
		rig = metarig.data.cloudrig.target_rig
		parent_slot = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(parent_slot, 'name', text=f"", emboss=True)
			row.prop_search(parent_slot, 'bone', rig.data, 'bones', text="")
			row.prop(parent_slot, 'is_default', text="")
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class ParentSlot(bpy.types.PropertyGroup):
	name: StringProperty(name="Name", description="Name to display in the UI for this parent option")
	bone: StringProperty(name="Bone", description="Bone that will be used as the parent")

	def update_is_default(self, context):
		arm_ob = context.object
		active_pb = get_active_pose_bone(context)

		for ps in active_pb.cloudrig_component.params.parenting.parent_slots:
			if ps != self:
				ps['is_default'] = False
			else:
				ps['is_default'] = True

	is_default: BoolProperty(
		name = "Is Default", 
		description = "Set this parent option as the default when the rig is generated", 
		default = False, 
		update = update_is_default
	)

def draw_cloudrig_parents(layout, context, text=""):
	draw_label_with_linebreak(layout, text, align_split=False)

	split = layout.split(factor=0.43)
	row = split.row()
	row.label(text="  UI Name")
	
	sub = split.split(factor=0.8)
	row = sub.row()
	row.label(text="Bone")

	sub = split.split(factor=0.8)
	row = sub.row()
	row.alignment='RIGHT'
	row.label(text="Default")

	draw_ui_list(
		layout
		,context
		,class_name = 'CLOUDRIG_UL_parent_slots'
		,list_path = 'active_pose_bone.bone.cloudrig_component.params.parenting.parent_slots'
		,active_index_path = 'active_pose_bone.cloudrig_component.params.parenting.active_parent_index'
	)

class CloudParentingMixin:
	parent_switch_behaviour = "The active parent will own the rig's root bone."
	parent_switch_overwrites_root_parent = True

	"""Class that provides parent switching parameters to Component_Base."""
	def apply_parent_switching(self, parent_slots, *,
			child_bone=None, prop_bone=None, prop_name="",
			panel_name="Space Switch", row_name="", label_name="", entry_name=""
		):
		"""Rig a bone with multiple switchable parents, using Armature constraint and drivers."""
		if not child_bone:
			child_bone = self.root_bone
		if not prop_bone:
			prop_bone = self.properties_bone
		if prop_name == "":
			prop_name="parents_"+child_bone.name
		if row_name == "":
			row_name = child_bone.name.split(".")[0]
		if entry_name == "":
			entry_name = child_bone.name

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
		if len(parent_bone_names) > 1:
			# Only add UI slider if there's more than 1 parent option.
			# For some components, it might make sense to only supply 1 parent,
			# eg. for cloud_ik_chain, since there the parent swithcing setup
			# relates to the IK master and pole target rather than the root bone.
			self.add_ui_data(panel_name, row_name, info
				,label_name = label_name
				,entry_name = entry_name
				,default = self.get_default_parent_index(parent_bone_names, parent_slots)
				,max = len(parent_ui_names)-1
			)

		# Add armature constraint
		arm_con = arm_con_bone.add_constraint('ARMATURE',
			targets = targets
		)

		if len(parent_bone_names) == 1:
			return

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
					,description = f'Parent slot #{i}: "{ps.bone}" not specified, skipping.'
				)
				continue
			if ps.name == "":
				self.add_log(
					"Nameless parent"
					,description = f'Parent slot #{i}: "{ps.bone}" has no UI name, falling back to the name of the bone.'
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

		return parent_ui_names, parent_bone_names

	def get_default_parent_index(self, parent_bone_names: List[str], parent_slots: List[ParentSlot]) -> int:
		for ps in parent_slots:
			if ps.is_default:
				parent_bone = ps.bone
				break
		else:
			parent_bone = parent_slots[0].bone

		for i, bone_name in enumerate(parent_bone_names):
			if bone_name == parent_bone:
				return i

	def apply_custom_root_parent(self, bone=None, parent_name=""):
		if not bone:
			bone = self.root_bone
		if parent_name == "":
			parent_name = self.params.parenting.root_parent

		parent_bone = self.generator.find_bone_info(parent_name)

		if not parent_bone:
			# Still try string-based parenting. If this fails, an error will be
			# logged in write_edit_data().
			self.add_log("Name-based parenting",
				description=f'Parent bone "{parent_name}" did not yet exist at time of parenting. This could be caused by incorrect metarig bone hierarchy, where a child rig is not parented to its intended parent rig, so it executes before the parent.'
			)
			bone.parent = parent_name
			return

		if parent_bone.bbone_segments == 1 or not self.params.parenting.use_armature_constraint:
			bone.parent = parent_bone
			return

		constrained_bone = bone
		if self.params.parenting.use_helper_bone:
			constrained_bone = self.create_parent_bone(bone, self.bones_mch)
			constrained_bone.custom_shape = None

		constrained_bone.add_constraint('ARMATURE', 
			index = -len(constrained_bone.constraint_infos),
			use_deform_preserve_volume = True,
			targets = [
				{
					"subtarget" : parent_bone.name
				}
			]
		)

	@classmethod
	def draw_parent_param(cls, layout, rig, params):
		parent_bone = rig.pose.bones.get(params.parenting.root_parent)
		is_parent_bendy = parent_bone and parent_bone.bone.bbone_segments > 1
		text = "Root Parent (Bendy): " if is_parent_bendy else "Root Parent: "
		
		row = layout.row(align=True)
		cls.draw_prop_search(row, params, 'parenting.root_parent', rig.pose, 'bones', text=text)
		if is_parent_bendy:
			cls.draw_prop(row, params, 'parenting.use_armature_constraint', icon='CON_ARMATURE', text="")
			if params.parenting.use_armature_constraint:
				cls.draw_prop(row, params, 'parenting.use_helper_bone', icon='BONE_DATA', text="")
			else:
				row.label(text="", icon="BONE_DATA")

	@classmethod
	def draw_parenting_params(cls, layout, context, params):
		metarig = context.object
		rig = metarig.data.cloudrig.target_rig
		if not rig:
			draw_label_with_linebreak(layout, "Generate the rig to see parenting parameters.", align_split=True)
			return

		if cls.parent_switch_overwrites_root_parent:
			cls.draw_prop(layout, params.parenting, "parent_switching")
			if params.parenting.parent_switching:
				draw_cloudrig_parents(layout, context, cls.parent_switch_behaviour)
			else:
				cls.draw_parent_param(layout, rig, params)
		else:
			cls.draw_parent_param(layout, rig, params)
			cls.draw_prop(layout, params.parenting, "parent_switching")
			if params.parenting.parent_switching:
				draw_cloudrig_parents(layout, context, cls.parent_switch_behaviour)

class Params(PropertyGroup):
	parent_switching: BoolProperty(
		name		 = "Parent Switching"
		,description = "Use parent switching for this rig. Different rig types may implement this differently. A rig-type-specific explanation is shown below when enabled"
		,default	 = False
	)
	use_armature_constraint: BoolProperty(
		name		 = "Use Armature Constraint"
		,description = "Instead of directly parenting this bone to the parent, use an Armature constraint. This allows the bone to follow the parent's bendy bone curvature"
		,default	 = True
	)
	use_helper_bone: BoolProperty(
		name		 = "Create Parent Helper"
		,description = "Instead of adding the Armature constraint directly to this bone, create a parent bone prefixed with 'P-' and add it to that one instead. This will keep the local transformations of this bone clear from any parenting-induced transformations, as would be the case with normal parenting"
		,default	 = True
	)
	root_parent: StringProperty(
		name		 = "Root Parent"
		,description = "If specified, parent the root of this rig to the chosen bone. If a bendy bone is chosen, a parent helper bone with an Armature Constraint will be created to correctly inherit transforms from the curvature"
		,default	 = ""
	)

	parent_slots: CollectionProperty(type=ParentSlot)
	active_parent_index: IntProperty()

registry = [
	ParentSlot,
	CLOUDRIG_UL_parent_slots,
]

