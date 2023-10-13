from typing import List, Dict
from bpy.types import Object
from .bone import BoneInfo

def map_vgroups_to_most_significant_object(
		group_names: List[str]
		,objects: List[Object]
		) -> Dict[str, Object]:
	"""Create a dictionary, mapping each vertex group name to the object
	which has the vertex group with the most vertices in it.
	This is expected to be pretty damn slow.
	"""
	objects = [o for o in objects if o.type == 'MESH' and o.visible_get()]

	vgroup_map = {}
	# For each object, go through each of its vertex groups.
	for ob in objects:
		group_lookup = {g.index: g.name for g in ob.vertex_groups}
		vgroup_datas = {name: [] for name in group_lookup.values() if name in group_names}
		for v in ob.data.vertices:
			for g in v.groups:
				group_name = group_lookup[g.group]
				if g.weight > 0.1 and group_name in group_names:
					vgroup_datas[group_name].append(v.index)

		for vg_name, vg_verts in vgroup_datas.items():
			if (vg_name not in vgroup_map) or ( vgroup_map[vg_name][1] < len(vg_verts) ):
				vgroup_map[vg_name] = (ob, len(vg_verts))

	return {vg_name : tup[0] for vg_name, tup in vgroup_map.items()}

def auto_initialize_gizmos(target_rig: Object, bone_infos: List[BoneInfo]):
	"""Enable and set up custom gizmos for those bones whose BoneInfo
	contains the neccessary data.
	This is not done on a per-bone basis due to performance.
	"""

	# This function was an experiment, but it gives pretty bad results.

	object_candidates = target_rig.children[:]

	vgroup_names = set([bi.gizmo_vgroup for bi in bone_infos if bi.gizmo_vgroup != ""])

	vgroup_map = map_vgroups_to_most_significant_object(vgroup_names, object_candidates)

	pbones = target_rig.pose.bones
	for bi in bone_infos:
		vg_name = bi.gizmo_vgroup
		if vg_name not in vgroup_map:
			continue
		pb = pbones.get(bi.name)
		if pb.enable_bone_gizmo:
			continue
		assert pb

		gizmo_props = pb.bone_gizmo
		pb.enable_bone_gizmo = True
		gizmo_props.shape_object = vgroup_map[vg_name]
		gizmo_props.vertex_group_name = vg_name
		gizmo_props.operator = bi.gizmo_operator
		# TODO: color gizmo based on bone color.

class BoneGizmoMixin:
	"""Mix-in class for interfacing with the BoneGizmos addon."""
	# https://developer.blender.org/diffusion/BSTS/browse/master/bone-gizmos/

	def add_gizmo_interaction(
			self
			,bone_names: List[str]
			,operator: str
			,op_kwargs: Dict
		):
		"""Whenever any of this list of bone names are interacted with through 
		BoneGizmos addon, execute an operator with the given arguments.
		Useful eg., for automatic IK/FK switching.
		"""
		if 'gizmo_interactions' not in self.target_rig.data:
			self.target_rig.data['gizmo_interactions'] = {}

		gizmo_dict = self.target_rig.data['gizmo_interactions'].to_dict()
		if operator not in gizmo_dict:
			op_data = gizmo_dict[operator] = []

		for key, value in op_kwargs.items():
			if type(value) == list:
				op_kwargs[key] = str(op_kwargs[key])

		op_data = gizmo_dict[operator]
		op_data.append((bone_names, op_kwargs))

		self.target_rig.data['gizmo_interactions'] = gizmo_dict

	def add_gizmo_interactions(self):
		"""CloudRig types can override this and make calls to 
		add_gizmo_interaction() from here. (Just for organization)
		"""
		pass