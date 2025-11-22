import bpy
from .install_this import install_this
from .test_generate_metarigs import test_generate_metarigs
from time import time

context = bpy.context

start = time()

install_this(context)
assert hasattr(bpy.types.Object, 'cloudrig')

test_generate_metarigs(context)

duration = time()-start
print(f"Tests completed in {duration:.2f}s")