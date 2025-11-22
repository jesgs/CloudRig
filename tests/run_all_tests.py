import bpy
from .install_this import install_this
from .generate_metarigs import generate_metarigs
from time import time

context = bpy.context

start = time()

install_this(context)
assert hasattr(bpy.types.Object, 'cloudrig')

generate_metarigs(context)

duration = time()-start
print(f"Tests completed in {duration:.2f}s")