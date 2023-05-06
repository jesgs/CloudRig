from typing import List, Dict

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
		if 'gizmo_interactions' not in self.obj.data:
			self.obj.data['gizmo_interactions'] = {}

		gizmo_dict = self.obj.data['gizmo_interactions'].to_dict()
		if operator not in gizmo_dict:
			op_data = gizmo_dict[operator] = []

		for key, value in op_kwargs.items():
			if type(value) == list:
				op_kwargs[key] = str(op_kwargs[key])

		op_data = gizmo_dict[operator]
		op_data.append((bone_names, op_kwargs))

		self.obj.data['gizmo_interactions'] = gizmo_dict

	def add_gizmo_interactions(self):
		"""CloudRig types can override this and make calls to 
		add_gizmo_interaction() from here. (Just for organization)
		"""
		pass