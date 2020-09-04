import bpy

from . import regenerate_rigify_rigs
from . import refresh_drivers
from . import mirror_rigify
from . import flatten_chain

modules = [
	regenerate_rigify_rigs,
	refresh_drivers,
	mirror_rigify,
    flatten_chain
]

def register():
	from bpy.utils import register_class
	for m in modules:
		m.register()

def unregister():
	from bpy.utils import unregister_class
	for m in reversed(modules):
		m.unregister()
