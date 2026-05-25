# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from bpy.types import Operator

from ..generation.cloudrig import is_cloud_metarig
from ..utils.misc import load_script


class WM_OT_cloudrig_template_script_create(Operator):
    """Initialize a template post-generation script."""

    bl_idname = "wm.cloudrig_template_script_create"
    bl_label = "Create Post-Gen Template"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_cloud_metarig(context.active_object)

    def execute(self, context):
        metarig = context.object
        filepath = Path(__file__).parent.as_posix()
        text = load_script(filepath, "post_gen_template.py", execute=False)
        text.name = metarig.name.replace("META-", "") + "_post_gen.py"
        metarig.cloudrig.generator.custom_script = text

        text_editor = next((a for a in context.screen.areas if a.type == 'TEXT_EDITOR'), None)
        msg = f"Find \"{text.name}\" in Blender's Text Editor."
        if text_editor:
            text_editor.spaces.active.text = text
            msg = f"See \"{text.name}\" in the Text Editor."

        self.report({'INFO'}, msg)
        return {'FINISHED'}


registry = [WM_OT_cloudrig_template_script_create]
