import bpy, sys, os, traceback
from bpy.types import Object, Operator
from bpy.props import BoolProperty

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

    @staticmethod
    def get_metarig_to_generate(context):
        metarig = is_single_cloud_metarig(context)
        if not metarig:
            metarig = is_active_cloud_metarig(context)

        if not metarig and is_active_cloudrig(context):
            # Find the metarig referencing this rig
            for o in context.scene.objects:
                if o.type == 'ARMATURE' and o.data.rigify_target_rig == obj:
                    metarig = o
                    break

    @classmethod
    def poll(cls, context):
        return cls.get_metarig_to_generate(context)

    def execute(self, context):
        metarig = self.get_metarig_to_generate(context)

        # Save state so it can be restored for convenience.
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

        # Try to generate a rig based on the metarig. 
        rig = self.generate_rig(context, metarig)

        # Restore states.
        meta_visible.restore()
        if rig_visible:
            rig_visible.restore()

        if not rig:
            # This means an error has occurred. It was already handled in generate_rig().
            return {'FINISHED'}

        if self.focus_generated:
            self.restore_state(context, metarig, state_mode, state_active_bone,
                        state_selected_bones, state_hide_bones, state_layers)

        return {'FINISHED'}

    def generate_rig(self, context, metarig):
        """Generates a rig from a metarig.

        Encountering a rig generation error will not halt the execution of the operator.
        This is important because the user can make mistakes in the MetaRig set-up, 
        which cannot be detected until the rig is attempted to be fully generated.
        Such errors must be accounted for and handled gracefully.
        """

        generator = CloudGenerator(context, metarig)
        try:
            generator.generate(context)
        except Exception as exception:
            generator.restore_rig_states()
            generator.obj.name = "FAILED-" + generator.obj.name
            generator.obj.name = generator.obj.name.replace("NEW-", "")
            metarig['failed_rig'] = generator.obj

            traceback_str = "\n".join(str(traceback.format_exc()).split("\n")[3:])
            message = [exception.message]

            if isinstance(exception, CloudMetarigError):
                # A MetaRig error means the user didn't follow instructions correctly.
                # This is the only kind of Exception that is not a bug in CloudRig.
                _exc_type, _exc_value, exc_traceback = sys.exc_info()
                fn = traceback.extract_tb(exc_traceback)[-1][0]
                fn = os.path.basename(fn)
                fn = os.path.splitext(fn)[0]
                self.report({'ERROR'}, '\n'.join(message))
                return

            if generator.custom_script_failure:
                self.logger.log_fatal_error(
                    "Post-Generation Script failed."
                    ,description = f'Execution of post-generation script in text datablock "{script.name}" failed, see stack trace below.'
                    ,note         = str(e)
                )
                # The error occurred in the user's script.
                # execute_custom_script() has already created the log entry for us,
                # so we just want to keep raising the exception.
                raise e

            # Any other exception type is a bug. 
            # Let's invite the user to report the error they've encountered.
            generator.logger.log_fatal_error(
                "Execution Failed!",
                description = "Execution failed unexpectedly. This should never happen!",
                display_stack_trace = 'ALWAYS',
                icon = 'URL',
                note = str(exc),
                operator = 'wm.cloudrig_report_bug',
            )

            self.report({'ERROR'}, "A bug has occurred. You can report it through the Generation Log interface. \nStack Trace:\n", entry.op_kwargs['stack_trace'])

        return target_rig

    def restore_state(self, context, metarig, mode, 
            active_bone_name="", selected_bone_names="", 
            hide_bones={}, layers=[]
        ):
        """Restore state for convenience."""
        metarig.hide_set(True)
        rig = metarig.data.cloudrig.target_rig
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