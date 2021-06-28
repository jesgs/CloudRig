from . import generate_all_rigs
from . import refresh_drivers
from . import mirror_rigify
from . import flatten_chain
from . import toggle_metarig

modules = [
	generate_all_rigs,
	refresh_drivers,
	mirror_rigify,
    flatten_chain,
	toggle_metarig
]

def register():
	for m in modules:
		m.register()

def unregister():
	for m in reversed(modules):
		m.unregister()
