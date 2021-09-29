import importlib
from bpy.utils import register_class, unregister_class
from . import bone_gizmo_properties
from . import bone_gizmo
from . import bone_gizmo_ui
from . import bone_gizmo_group

modules = (
	bone_gizmo_properties,
	bone_gizmo,
	bone_gizmo_ui,
	bone_gizmo_group,
)

def register():
	for m in modules:
		importlib.reload(m)
		if hasattr(m, 'registry'):
			for c in m.registry:
				register_class(c)
		if hasattr(m, 'register'):
			m.register()

def unregister():
	for m in reversed(modules):
		if hasattr(m, 'unregister'):
			m.unregister()
		if hasattr(m, 'registry'):
			if hasattr(m, 'registry'):
				for c in m.registry:
					unregister_class(c)