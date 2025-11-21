import bpy
from .install_cloudrig import install_cloudrig
from .generate_metarigs import generate_metarigs

install_cloudrig(bpy.context)
generate_metarigs()