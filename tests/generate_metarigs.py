import bpy

assert bpy.ops.object.cloudrig_metarig_add(metarig_name="META-Cloud_Human") == {'FINISHED'}

assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
