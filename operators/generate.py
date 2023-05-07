import bpy, sys, os, traceback
from bpy.types import Object, Operator
from bpy.props import BoolProperty

from rigify.utils.errors import MetarigError

from ..rig_component_features.ui import is_cloud_metarig
from ..rig_component_features.object import EnsureVisible

from ..generation.cloudrig import register_hotkey, is_active_cloud_metarig, is_active_cloudrig


def refresh_constraints(rig: Object):
    for pb in rig.pose.bones:
        for c in pb.constraints:
            if hasattr(c, 'target'):
                c.target = c.target
            if c.type == 'ARMATURE':
                for t in c.targets:
                    t.target = t.target

def is_single_cloud_metarig(context):
    """If there is only one CloudRig metarig in the scene, return it."""
    ret = None
    for o in context.scene.objects:
        if is_cloud_metarig(o):
            if not ret:
                ret = o
            else:
                return None
    return ret

class CLOUDRIG_OT_generate(Operator):
    """Generates a rig from the active metarig armature using the CloudRig generator"""

    bl_idname = "pose.cloudrig_generate"
    bl_label = "Generate CloudRig"
    bl_options = {'UNDO'}
    bl_description = 'Generates a rig from the active metarig armature using the CloudRig generator'

    focus_generated: BoolProperty(
        name = "Focus Generated"
        ,default = True
        ,description = "After successfully generating a single rig, hide the metarig, unhide the generated rig, enter the same mode as the current mode, and match bone selection states where possible"
    )

    @classmethod
    def poll(cls, context):
        return is_active_cloud_metarig(context) or is_active_cloudrig(context) or is_single_cloud_metarig(context)

    def execute(self, context):
        obj = context.object
        metarig = is_single_cloud_metarig(context)
        if not metarig:
            metarig = is_active_cloud_metarig(context)

        if not metarig and is_active_cloudrig(context):
            # Find the metarig referencing this rig
            for o in context.scene.objects:
                if o.type == 'ARMATURE' and o.data.rigify_target_rig == obj:
                    metarig = o
                    break

        if not metarig:
            self.report({'ERROR'}, "Could not find metarig.")
            return {'CANCELLED'}

        ### Save state so it can be restored for convenience
        state_mode = 'OBJECT'
        state_active_bone = context.active_pose_bone.name if context.active_pose_bone else ""
        state_selected_bones = [bone.name for bone in context.selected_pose_bones] if context.selected_pose_bones else []
        state_hide_bones = {bone.name : bone.hide for bone in metarig.data.bones}
        state_layers = metarig.data.layers[:]

        # Ensure required visibility and active states.
        meta_visible = EnsureVisible(metarig)
        target_rig = metarig.data.rigify_target_rig
        rig_visible = None
        if target_rig:
            rig_visible = EnsureVisible(target_rig)
        context.view_layer.objects.active = metarig

        # Generate, without halting execution on failure
        rig = self.generate_rig(context, metarig)

        if not rig:
            return {'FINISHED'}

        # Restore states.
        meta_visible.restore()
        if rig_visible:
            rig_visible.restore()

        if self.focus_generated:
            self.restore_state(context, metarig, state_mode, state_active_bone,
                        state_selected_bones, state_hide_bones, state_layers)

        return {'FINISHED'}

    def report_exception(self, exception):
        _exc_type, _exc_value, exc_traceback = sys.exc_info()
        fn = traceback.extract_tb(exc_traceback)[-1][0]
        fn = os.path.basename(fn)
        fn = os.path.splitext(fn)[0]
        message = [exception.message]

        self.report({'ERROR'}, '\n'.join(message))

    def generate_rig(self, context, metarig):
        """Generates a rig from a metarig."""
        meta_visible = EnsureVisible(metarig)
        target_rig = metarig.data.rigify_target_rig
        rig_visible = None
        if target_rig:
            rig_visible = EnsureVisible(target_rig)

        generator = CloudGenerator(context, metarig)
        try:
            generator.generate(context)
        except Exception as exc:
            # Cleanup if something goes wrong
            generator.restore_rig_states()
            generator.obj.name = "FAILED-" + generator.obj.name
            generator.obj.name = generator.obj.name.replace("NEW-", "")
            metarig['failed_rig'] = generator.obj
            if isinstance(exc, MetarigError):
                traceback.print_exc()
                self.report_exception(exc)
                return

            entry = generator.logger.log_bug(
                "Execution Failed!"
                ,description = f'Execution failed unexpectedly. This should never happen!'
                ,icon         = 'URL'
                ,operator     = 'wm.cloudrig_report_bug'
                ,note         = str(exc)
            )

            # Continue the exception
            raise exc

        meta_visible.restore()
        if rig_visible:
            rig_visible.restore()
        return target_rig

    def restore_state(self, context, metarig, mode, 
            active_bone_name="", selected_bone_names="", 
            hide_bones={}, layers=[]
        ):
        """Restore state for convenience."""
        metarig.hide_set(True)
        rig = metarig.data.rigify_target_rig
        rig.hide_set(False)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='OBJECT')
        rig.select_set(True)

        if mode in ['OBJECT', 'EDIT', 'POSE']:
            bpy.ops.object.mode_set(mode=mode)

        rig = context.object
        if active_bone_name in rig.pose.bones:
            rig.data.bones.active = rig.data.bones[active_bone_name]

        for bone_name in selected_bone_names:
            if bone_name in rig.data.bones:
                rig.data.bones[bone_name].select = True

        if layers:
            rig.data.layers = layers[:]

        for bone_name in hide_bones.keys():
            bone = rig.data.bones.get(bone_name)
            if not bone: continue
            bone.hide = hide_bones[bone_name]

registry = [
    CLOUDRIG_OT_generate,
]

def register():
    register_hotkey(CLOUDRIG_OT_generate.bl_idname
        ,hotkey_kwargs = {'type': "R", 'value': "PRESS", 'ctrl': True, 'alt': True}
        ,key_cat = "3D View"
        ,space_type = 'VIEW_3D'
    )