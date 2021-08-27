from . import mirror_rigify
from . import flatten_chain
from . import toggle_metarig
from . import assign_bone_layers

modules = [
	mirror_rigify,
    flatten_chain,
	toggle_metarig,
	assign_bone_layers
]

def register():
	for m in modules:
		m.register()

def unregister():
	for m in reversed(modules):
		m.unregister()
