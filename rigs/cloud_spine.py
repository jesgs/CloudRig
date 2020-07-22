import bpy
from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

from rigify.base_rig import stage
from rigify.utils.bones import BoneDict

from .cloud_fk_chain import CloudChainRig

"""TODO
Maybe should be split up to Spine/Neck/Head rigs. Or well, just remove the neck and head, and those should be separate FK chain rigs. Might make the code a lot simpler, but also might not.
IK-CTR-Spine should have a copy rotation constraint to MSTR-Hips and possibly also MSTR-Chest. Ofc, implement this in a smart way, that works with arbitrary spine length. (Similar deal to how STR bones stay inbetween STR main bones, but in this case it's rotation instead of location)
Re-implement FK-C bones (maybe under a param)
	Their values would probably have to be dependent on the length of the bone. Ie, a long bone should slide more when it's rotated, compared to a short bone.

Bug: IK-CTR-Chest flies away when moving the chest master far, needs a DSP- bone?

Allow multiple spine rigs in the same rig.
 Currently there can be only one spine in the rig, or at least only one that will be displayed in the UI, since the spine rig's IK property is always simply "ik_spine".
	head hinge also has some hardcoded name strings.
	When registering bones as a parent, the parent identifiers are also non-unique.
	Main control names like MSTR-Torso are also non-unique...
"""

class CloudSpineRig(CloudChainRig):
	"""Spine setup with FK, IK-like and stretchy IK controls. Currently only one of these per rig is supported."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.params.CR_chain_segments = 1

		assert len(self.bones.org.main) >= self.params.CR_spine_length, f"Spine Length parameter value({self.params.CR_spine_length}) cannot exceed length of bone chain connected to {self.base_bone} ({len(self.bones.org.main)})"
		assert len(self.bones.org.main) > 2, "Spine must consist of at least 3 connected bones."

		self.ik_prop_name = "ik_spine"
		self.ik_stretch_name = "ik_stretch_spine"

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.spine_fk			= self.ensure_bone_set("Spine FK Controls")
		self.spine_main			= self.ensure_bone_set("Spine Main Controls")
		self.spine_parent_ctrls	= self.ensure_bone_set("Spine Parent Controls")
		self.spine_ik_secondary	= self.ensure_bone_set("Spine IK Secondary")
		self.spine_mch			= self.ensure_bone_set("Spine Mechanism")

	@stage.prepare_bones
	def prepare_fk_spine(self):
		# Create Troso Master control
		self.mstr_torso = self.spine_main.new(
			name 		  = "MSTR-Torso"
			,source 	  = self.org_chain[0]
			,head 		  = self.org_chain[0].center
			,custom_shape = self.load_widget("Torso_Master")
		)

		# Create master (reverse) hip control
		self.mstr_hips = self.spine_main.new(
				name				= "MSTR-Hips"
				,source				= self.org_chain[0]
				,head				= self.org_chain[0].center
				,custom_shape 		= self.load_widget("Hips")
				,custom_shape_scale	= 0.7
				,parent				= self.mstr_torso
		)
		self.register_parent(self.mstr_torso, "Torso")
		self.mstr_torso.flatten()
		if self.params.CR_spine_double:
			double_mstr_pelvis = self.create_parent_bone(self.mstr_torso, self.spine_parent_ctrls)

		self.org_spines = self.org_chain[:self.params.CR_spine_length]
		self.org_necks = []
		self.org_head = None
		if len(self.org_chain) > self.params.CR_spine_length:	
			self.org_necks = self.org_chain[self.params.CR_spine_length:-1]
			self.org_head = self.org_chain[-1]

		# Create FK bones
		self.fk_chain = []
		fk_name = ""
		next_parent = self.mstr_torso
		for i, org_bone in enumerate(self.org_chain):
			fk_name = org_bone.name.replace("ORG", "FK")
			org_bone.fk_bone = fk_bone = self.spine_fk.new(
				name				= fk_name
				,source				= org_bone
				,custom_shape 		= self.load_widget("FK_Limb")
				,custom_shape_scale = 0.9 * org_bone.custom_shape_scale
				,parent				= next_parent
			)
			next_parent = fk_bone

			self.fk_chain.append(fk_bone)

			if org_bone in self.org_spines:	# Spine section
				# Shift FK controls up to the center of their ORG bone
				org_bone = self.org_chain[i]
				fk_bone.put(org_bone.center)
				if i < len(self.org_spines)-1:
					fk_bone.tail = self.org_chain[i+1].center

		# Register final spine FK as an available parent.
		self.register_parent(self.fk_chain[self.params.CR_spine_length-1], "Chest")

		# Head Hinge
		if self.org_head:
			hng_bone = self.hinge_setup(
				bone = self.fk_chain[-1], 
				category = "Head",
				parent_bone = self.fk_chain[-2],
				hng_name = self.fk_chain[-1].name.replace("FK", "FK-HNG"),
				prop_bone = self.ikfk_properties_bone,
				prop_name = "fk_hinge_head",
				limb_name = "Head",
				head_tail = 1,
				bone_set = self.spine_mch
			)

	@stage.prepare_bones
	def prepare_ik_spine(self):
		if not self.params.CR_spine_use_ik: return

		# Create master chest control
		self.mstr_chest = self.spine_main.new(
				name				= "MSTR-Chest"
				,source 			= self.org_spines[-2]
				,head				= self.org_spines[-2].center
				,tail 				= self.org_spines[-2].center + Vector((0, 0, self.scale))
				,custom_shape 		= self.load_widget("Chest_Master")
				,custom_shape_scale = 0.7
				,parent				= self.mstr_torso
			)

		if self.params.CR_spine_double:
			double_mstr_chest = self.create_parent_bone(self.mstr_chest, self.spine_parent_ctrls)
		
		self.mstr_hips.flatten()
		self.register_parent(self.mstr_hips, "Hips")

		self.ik_ctr_chain = []
		for i, org_spine in enumerate(self.org_spines):
			fk_bone = org_spine.fk_bone
			ik_ctr_name = fk_bone.name.replace("FK", "IK-CTR")	# Equivalent of IK-CTR bones in Rain (Technically animator-facing, but rarely used)
			ik_ctr_bone = self.spine_ik_secondary.new(
				name				= ik_ctr_name
				,source				= fk_bone
				,custom_shape 		= self.load_widget("Oval")
			)
			if i >= len(self.org_spines)-2:	
				# Last two spine controls should be parented to the chest control.
				ik_ctr_bone.parent = self.mstr_chest
			else:
				# The rest to the torso root.
				ik_ctr_bone.parent = self.mstr_torso
			self.ik_ctr_chain.append(ik_ctr_bone)
		
		# Reverse IK (IK-R) chain. Damped track to IK-CTR of one lower index.
		next_parent = self.mstr_chest
		self.ik_r_chain = []
		for i, org_bone in enumerate(reversed(self.org_spines[1:])):	# We skip the first spine.
			fk_bone = org_bone.fk_bone
			index = len(self.org_spines)-i-2
			ik_r_name = fk_bone.name.replace("FK", "IK-R")
			org_bone.ik_r_bone = ik_r_bone = self.spine_mch.new(
				name		 = ik_r_name
				,source 	 = fk_bone
				,tail 		 = self.fk_chain[index].head.copy()
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			next_parent = ik_r_bone
			self.ik_r_chain.append(ik_r_bone)
			ik_r_bone.add_constraint('DAMPED_TRACK',
				subtarget = self.ik_ctr_chain[index].name
			)
		
		# IK chain
		next_parent = self.mstr_hips # First IK bone is parented to MSTR-Chest.
		self.ik_chain = []
		for i, org_bone in enumerate(self.org_spines):
			fk_bone = org_bone.fk_bone
			ik_name = fk_bone.name.replace("FK", "IK")
			org_bone.ik_bone = ik_bone = self.spine_mch.new(
				name		 = ik_name
				,source		 = fk_bone
				,head		 = self.fk_chain[i-1].head.copy() if i>0 else self.def_bones[0].head.copy()
				,tail		 = fk_bone.head
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			self.ik_chain.append(ik_bone)
			next_parent = ik_bone
			
			damped_track_target = self.ik_r_chain[0].name
			if i > 0:
				if i != len(self.org_spines)-1:
					damped_track_target = self.org_spines[i+1].ik_r_bone.name
				
				# IK Stretch Copy Location
				con_name = "Copy Location (Stretchy Spine)"
				str_con = ik_bone.add_constraint('COPY_LOCATION'
					,space	   = 'WORLD'
					,name	   = con_name
					,subtarget = org_bone.ik_r_bone.name
					,head_tail = 1
				)
				
				# Influence driver
				influence_unit = 1 / (len(self.org_spines)-1)
				influence = influence_unit * i

				str_con.drivers.append({
					'prop' : 'influence',
					'expression' : f"var * {influence}",
					'variables' : [
						(self.ikfk_properties_bone.name, self.ik_stretch_name)
					]
				})

				ik_bone.add_constraint('COPY_ROTATION'
					,space	   = 'WORLD'
					,subtarget = self.ik_ctr_chain[i-1].name
				)
				self.ik_ctr_chain[i-1].custom_shape_transform = ik_bone
			
			head_tail = 1
			if i == len(self.org_spines)-1:
				# Special treatment for last IK bone...
				damped_track_target = self.ik_ctr_chain[-1].name
				head_tail = 0
				self.mstr_chest.custom_shape_transform = ik_bone
				if self.params.CR_spine_double:
					self.mstr_chest.parent.custom_shape_transform = ik_bone

			ik_bone.add_constraint('DAMPED_TRACK',
				subtarget = damped_track_target,
				head_tail = head_tail
			)

		# Attach FK to IK
		for i, ik_bone in enumerate(self.ik_chain[1:]):
			fk_bone = self.fk_chain[i]
			con_name = "Copy Transforms IK"
			ct_con = fk_bone.add_constraint('COPY_TRANSFORMS'
				,space	   = 'WORLD'
				,name	   = con_name
				,subtarget = ik_bone.name
			)

			ct_con.drivers.append({
				'prop' : 'influence',
				'variables' : [(self.ikfk_properties_bone.name, self.ik_prop_name)]
			})
		
		# Store info for UI
		info = {
			"prop_bone"		: self.ikfk_properties_bone,
			"prop_id" 		: self.ik_stretch_name,
		}
		self.add_ui_data("ik_stretches", "spine", "Spine", info, default=1.0)

		info = {
			"prop_bone"		: self.ikfk_properties_bone,
			"prop_id"		: self.ik_prop_name,
		}
		self.add_ui_data("ik_switches", "spine", "Spine", info, default=0.0)

	@stage.prepare_bones
	def prepare_def_str_spine(self):
		# Tweak some display things
		for str_bone in self.str_bones:
			str_bone.use_custom_shape_bone_size = False
			str_bone.custom_shape_scale = 0.15
		
		if len(self.org_necks) > 0:
			# If there are any neck bones, set the last one's last def bone's easeout to 0.
			self.org_necks[-1].def_bones[-1].bbone_easeout = 0

	@stage.prepare_bones
	def prepare_org_spine(self):
		# Parent ORG to FK. This is only important because STR- bones are owned by ORG- bones.
		# We want each FK bone to control the STR- bone of one higher index, eg. FK-Spine0 would control STR-Spine1.
		for i, org_bone in enumerate(self.org_chain):
			if i == 0:
				# First STR bone should by owned by the hips.
				org_bone.parent = self.mstr_hips
			elif self.org_head and i == len(self.org_chain)-1:
				# Last ORG bone should be owned by the head, if there is one.
				org_bone.parent = self.fk_chain[-1]
			elif hasattr(self.fk_chain[i-1], 'fk_child'):
				# Otherwise, every ORG bone should be owned by the FK bone of one lower index.
				org_bone.parent = self.fk_chain[i-1].fk_child
			else:
				print("This shouldn't happen?")	# TODO This does happen
				org_bone.parent = self.fk_chain[i-1]
		
		if not self.org_head:
			# If there is no head, we need to parent the last ORG- bone to the last FK bone so any child rigs parented to this rig will behave as expected.
			self.org_chain[-1].parent = self.fk_chain[-1]
			self.str_bones[-2].parent = self.fk_chain[-2]
		
		# Change any ORG- children of the final spine bone to be owned by the neck bone instead. This is needed because of the index shift described above.
		new_parent = self.org_head
		if len(self.org_necks) > 0:
			new_parent = self.org_necks[0]
		if new_parent:
			for b in self.all_bones:
				if b.parent==self.org_spines[-1] and b.name.startswith("ORG-"):
					b.parent = new_parent

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		super().define_bone_sets(params)
		""" Create parameters for this rig's bone sets. """
		cls.define_bone_set(params, "Spine FK Controls",	  preset=1,  default_layers=[cls.default_layers('IK_MAIN')]		)
		cls.define_bone_set(params, "Spine Main Controls",	  preset=2,  default_layers=[cls.default_layers('IK_MAIN')]		)
		cls.define_bone_set(params, "Spine Parent Controls",  preset=8,  default_layers=[cls.default_layers('IK_MAIN')]		)
		cls.define_bone_set(params, "Spine IK Secondary",	  preset=10, default_layers=[cls.default_layers('IK_SECOND')]	)
		cls.define_bone_set(params, "Spine Mechanism",					 default_layers=[cls.default_layers('MCH')], 	  override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_spine_show_settings = BoolProperty(
			name="Spine Settings"
			,description = "Reveal settings for the cloud_spine rig type"
			)
		params.CR_spine_length = IntProperty(
			name		 = "Spine Length"
			,description = "Number of bones on the chain until the spine ends and the neck begins. The spine and neck can both be made up of an arbitrary number of bones. The final bone of the chain is always treated as the head."
			,default	 = 3
			,min		 = 3
			,max		 = 99
		)
		params.CR_spine_use_ik = BoolProperty(
			name		 = "Create IK Setup"
			,description = "If disabled, this spine rig will only have FK controls"
			,default	 = True
		)
		params.CR_spine_double = BoolProperty(
			name		 = "Double Controls"
			,description = "Make duplicates of the main spine controls"
			,default	 = True
		)

	@classmethod
	def bone_set_ui(cls, params, layout, set_info):
		if (set_info['name'] != "Spine IK Secondary" or params.CR_spine_use_ik) and \
			(set_info['name'] != "Spine Parent Controls" or params.CR_spine_double):
			super().bone_set_ui(params, layout, set_info)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().cloud_params_ui(layout, params)
		cls.disable_row('CR_chain_segments')

		if not cls.cloud_dropdown_ui(layout, params, "CR_spine_show_settings"): return layout

		layout.prop(params, "CR_spine_length")
		layout.prop(params, "CR_spine_use_ik")
		layout.prop(params, "CR_spine_double")

		return layout

class Rig(CloudSpineRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_spine")