# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup, Panel, UIList, Operator, Object
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty

import bpy, os, traceback, sys
import json, webbrowser, time
import struct, platform, io, urllib.parse
import addon_utils

from ..rig_component_features.component_params_ui import draw_label_with_linebreak, is_advanced_mode
from ..generation.cloudrig import is_cloud_metarig
from ..operators.pie_bone_selection_ops import reveal_and_select

"""
Fatal errors can happen in 3 ways:
- Generic execution error anywhere throughout the generation process including asserts
    - Should never happen and should be reported as a bug.
    - User should see stack trace in both the pop-up and the Generation Log; The latter also provides a Report Bug button.
- Post-generation script error: This is a bug in the code written by the user, see execute_custom_script().
    - User should see a stack trace of only their script, both in the pop-up and the Generation Log.
- Metarig Error: This is a mistake in the MetaRig's bone setup, raised via self.raise_generation_error()
    - User gets no stack trace unless they look at the Generation Log with Advanced Mode enabled.

Common to all types:
    - Since these are fatal errors, any other rig errors are removed from the Generation Log.
    - All errors are caught and handled in generate_rig().
    - All errors should give the user useful information on how to proceed.
"""

"""
TODO: Symmetry warnings:
    - Symmetrical action setup's transform curves are actually asymmetrical
    - Symmetrically named rig owners have asymetrical children in the chain
    - Symmetrically named and transformed components have asymmetrical constraints
"""


class LoggerMixin:
    """Mix-in class for allowing a class to add entries to the Generation Log of an armature."""

    def add_log(
        self,
        description_short: str,
        *,
        base_bone_name="",
        trouble_bone="",
        description="No description.",
        display_stack_trace='NEVER',
        icon='ERROR',
        note="",
        note_icon='NONE',
        operator='',
        op_kwargs={},
        op_text="",
    ):
        if not base_bone_name and hasattr(self, 'metarig_base_pbone'):
            base_bone_name = self.metarig_base_pbone.name
        self.generator.logger.log(
            description_short,
            base_bone_name=base_bone_name,
            trouble_bone=trouble_bone,
            description=description,
            display_stack_trace=display_stack_trace,
            icon=icon,
            note=note,
            note_icon=note_icon,
            operator=operator,
            op_kwargs=op_kwargs,
            op_text=op_text
        )

    def raise_generation_error(self, description, **kwargs):
        """For raising non-bug errors that should be fixable by the user."""
        kwargs['base_bone_name'] = self.base_bone_name
        self.generator.raise_generation_error(description=description, **kwargs)


def cloudrig_last_modified() -> str:
    """Return the date at which the most recent CloudRig .py file was modified.

    Used in the bug report form pre-fill.
    """
    max_mtime = 0
    for dirname, subdirs, files in os.walk(os.path.dirname(__file__)):
        for fname in files:
            full_path = os.path.join(dirname, fname)
            mtime = os.path.getmtime(full_path)
            if mtime > max_mtime:
                max_mtime = mtime
                max_file = fname

    # For me this is in UTC, I can only hope it is for everyone.
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(max_mtime))


def url_prefill_from_cloudrig(stack_trace=""):
    op_sys = "%s %d Bits\n" % (
        platform.platform(),
        struct.calcsize("P") * 8,
    )
    blender_version = "%s, branch: %s, commit: [%s](https://projects.blender.org/blender/blender/commit/%s)\n" % (
        bpy.app.version_string,
        bpy.app.build_branch.decode('utf-8', 'replace'),
        bpy.app.build_commit_date.decode('utf-8', 'replace'),
        bpy.app.build_hash.decode('ascii'),
    )

    cloudrig_version = ""
    for addon_module in addon_utils.modules():
        if addon_module.bl_info['name'] == 'CloudRig':
            cloudrig_version = str(addon_module.bl_info['version'])

    return (
        "https://projects.blender.org/Mets/CloudRig/issues/new?template=.gitea/issue_template/bug.yaml"
        + "&field:body="
        + urllib.parse.quote("Description of the problem:  \n\n\nSteps to reproduce:  \n\n\nBlend file:")
        + "&field:stacktrace="
        + urllib.parse.quote(stack_trace)
        + "&field:cloudrig_ver="
        + urllib.parse.quote(cloudrig_version)
        + "&field:blender_ver="
        + urllib.parse.quote(blender_version)
        + "&field:op_sys="
        + urllib.parse.quote(op_sys)

    )


def get_pretty_stack() -> str:
    """Make a pretty looking string out of the current execution stack,
    or the exception stack if this is called from a stack which is handling an exception.
    (Python is cool in that way - We can tell when this function is being called by
    a stack which originated in a try/except block!)
    """
    ret = ""

    exc_type, exc_value, tb = sys.exc_info()
    if exc_value:
        # If the stack we're currently on is handling an exception,
        # use the stack of that exception instead of our stack
        stack = traceback.extract_tb(exc_value.__traceback__)
    else:
        stack = traceback.extract_stack()

    lines = []
    after_generator = False

    def get_short_filepath(i: int, frame) -> str:
        # Shorten the file name; Anything before the CloudRig extension folder is irrelevant.
        short_file = frame.filename
        if 'extensions' in short_file:
            short_file = os.sep.join(frame.filename.split("extensions")[1].split(os.sep)[3:])

        # Also avoid repeating the same filepath, put spaces instead.
        if i > 0 and frame.filename == stack[i - 1].filename:
            short_file = " " * int(len(short_file))

        return short_file

    longest_frame_name = max([len(frame.name) for frame in stack])
    longest_file_name = max([len(get_short_filepath(i, frame)) for i, frame in enumerate(stack)])
    for i, frame in enumerate(stack):
        if 'generator' in frame.filename:
            after_generator = True
        if not after_generator:
            continue
        if frame.name in (
            "log",
            "add_log",
            "log_fatal_error",
            "raise_generation_error",
        ):
            break

        short_file = get_short_filepath(i, frame)

        fill_file = " " * (longest_file_name - len(short_file))
        fill_frame = " " * (longest_frame_name - len(frame.name))
        right_arrow = chr(0x2192)
        first_arrow = right_arrow if frame.filename != stack[i - 1].filename else chr(0x2937)
        lines.append(f"{short_file}{fill_file} {first_arrow} {frame.name}{fill_frame} {right_arrow} line {frame.lineno}")

    ret += f" {chr(0x2936)}\n".join(lines)
    ret += f":\n          {frame.line}\n"
    if exc_value:
        ret += f"{exc_type.__name__}: {exc_value}"
    return ret


def get_datablock_type_icon(datablock):
    """Return the icon string representing a datablock type"""
    # It's beautiful.
    # There's no proper way to get the icon of a datablock, so we use the
    # RNA definition of the id_type property of the DriverTarget class,
    # which is an enum with a mapping of each datablock type to its icon.
    if not hasattr(datablock, "type"):
        # shape keys...
        return 'NONE'
    typ = datablock.type
    if datablock.type == 'SHADER':
        typ = 'NODETREE'
    return bpy.types.DriverTarget.bl_rna.properties['id_type'].enum_items[typ].icon


class CloudLogManager:
    """Class to manage CloudRigLogEntry CollectionProperty on metarigs.

    This class is instanced once per rig generation, by the CloudRig_Generator class.
    """

    def __init__(self, metarig: Object, rig: Object=None):
        self.metarig = metarig
        self.rig = rig

    def log(
        self,
        description_short: str,
        *,
        base_bone_name="",
        trouble_bone="",
        description="No description.",
        display_stack_trace='NEVER',
        icon='ERROR',
        note="",
        note_icon='NONE',
        operator='',
        op_kwargs={},
        op_text="",
        op_icon='BLANK1',
    ):
        """Low-level function to add a log entry to the metarig object's data."""
        entry = self.metarig.cloudrig.generator.logs.add()
        entry.pretty_stack = get_pretty_stack()
        entry.base_bone_name = base_bone_name
        entry.trouble_bone = trouble_bone
        # For searchability, set the name string to a combination of all the strings.
        entry.name = " ".join([base_bone_name, trouble_bone, description_short, note, description])
        entry.description_short = description_short
        entry.description = description
        entry.display_stack_trace = display_stack_trace
        entry.note = note
        entry.note_icon = note_icon
        entry.icon = icon
        entry.operator = operator
        entry.op_kwargs = json.dumps(op_kwargs)
        entry.op_text = op_text
        entry.op_icon = op_icon

        return entry

    def log_fatal_error(
        self, description_short: str, *, wipe_log=True, description="", **kwargs
    ):
        """
        Wipe all other log entries, and create a log entry for an error that has caused
        generation to halt.
        Halting of the generation and raising the exception is up to the caller.
        """
        if wipe_log:
            self.clear()
        entry = self.log(
            "(Fatal) " + description_short,
            description=description or description_short,
            display_stack_trace='ALWAYS',
            **kwargs,
        )

        return entry

    def clear(self):
        generator = self.metarig.cloudrig.generator
        generator.logs.clear()
        generator.active_log_index = 0

    ####################################################################
    # Functions for finding various issues at the end of rig generation.
    # For these, self.rig is expected to be set.

    def report_unused_bone_collections(self, metarig, target_rig):
        for coll in metarig.data.collections_all:
            target_coll = target_rig.data.collections_all.get(coll.name)
            if not target_coll or len(target_coll.bones_recursive) == 0:
                self.log(
                    "Unused Bone Collection",
                    note=coll.name,
                    icon='OUTLINER_COLLECTION',
                    description=f'Collection "{coll.name}" is not used by any bones.',
                    operator=CLOUDRIG_OT_delete_collection.bl_idname,
                    op_kwargs={'coll_name': coll.name},
                )

    def report_invalid_drivers_on_datablock(self, datablock, owner_datablock=None):
        if not datablock:
            return
        if not hasattr(datablock, "animation_data"):
            return
        if not datablock.animation_data:
            return
        for fcurve in datablock.animation_data.drivers:
            driver = fcurve.driver
            driver.type = driver.type
            if driver.is_valid:
                continue
            owner = owner_datablock or datablock

            base_bone_name = ""
            trouble_bone = ""
            if 'pose.bones' in fcurve.data_path:
                bone_name = fcurve.data_path.split('pose.bones["')[1].split('"]')[0]
                if (
                    type(datablock) == Object
                    and datablock.type == 'ARMATURE'
                    and datablock.cloudrig.generator.target_rig == self.rig
                ):
                    base_bone_name = bone_name
                elif datablock == self.rig:
                    trouble_bone = bone_name

            self.log(
                "Invalid Driver",
                description=f'Invalid driver:\nDatablock: "{owner.name}"\nData path: "{fcurve.data_path}"\nIndex: {fcurve.array_index}',
                icon='DRIVER',
                note=owner.name,
                note_icon=get_datablock_type_icon(datablock),
                base_bone_name=base_bone_name,
                trouble_bone=trouble_bone,
                operator='screen.drivers_editor_show',
            )

    def report_invalid_drivers_on_object_hierarchy(self, object: Object):
        """Create log entries for invalid drivers of the object or any of its children"""

        for obj in [object] + list(object.children_recursive):
            self.report_invalid_drivers_on_datablock(obj)
            if hasattr(obj, "data") and obj.data:
                self.report_invalid_drivers_on_datablock(obj.data, owner_datablock=obj)
            if obj.type == 'MESH':
                self.report_invalid_drivers_on_datablock(
                    obj.data.shape_keys, owner_datablock=obj
                )

            for ms in obj.material_slots:
                if ms.material:
                    self.report_invalid_drivers_on_datablock(ms.material)
                    self.report_invalid_drivers_on_datablock(
                        ms.material.node_tree, owner_datablock=ms.material
                    )

    def report_widgets(self, widget_collection):
        """Find and log unused and duplicate widgets."""

        widgets = widget_collection.all_objects

        used_widgets = []
        for pb in self.rig.pose.bones:
            if pb.custom_shape and pb.custom_shape.name not in used_widgets:
                used_widgets.append(pb.custom_shape.name)

        for widget in widgets:
            unprefixed = widget.name
            if widget.name[-4] == '.':
                unprefixed = widget.name[:-4]

            if widget.name not in used_widgets and unprefixed not in used_widgets:
                self.log(
                    "Unused Custom Shape",
                    note=widget.name,
                    icon='X',
                    description=f'Custom Shape "{widget.name}" is not used by any bones.',
                    operator=CLOUDRIG_OT_Unlink_Widget.bl_idname,
                    op_kwargs={'ob_name': widget.name},
                )

            if unprefixed != widget.name:
                if unprefixed in bpy.data.objects:
                    self.log(
                        "Duplicate Custom Shape",
                        note=widget.name,
                        icon='DUPLICATE',
                        description=f'There exists a custom shape called "{unprefixed}", that should be used instead of "{widget.name}".',
                        operator=CLOUDRIG_OT_Swap_Bone_Shape.bl_idname,
                        op_kwargs={'old_name': widget.name, 'new_name': unprefixed},
                    )
                else:
                    self.log(
                        "Custom Shape with number suffix",
                        note=widget.name,
                        icon='FILE_TEXT',
                        description=f'The "{widget.name[-4:]}" suffix in the name of this custom shape is not necessary.',
                        operator=CLOUDRIG_OT_Rename_Object.bl_idname,
                        op_kwargs={'old_name': widget.name, 'new_name': unprefixed},
                    )

    def report_actions(self):
        """Test that action ranges are whole numbers and the default pose frame
        has a keyframe and the keyframe has default transform values.
        """

        action_setups = self.metarig.cloudrig.generator.action_setups
        for i, action_setup in enumerate(action_setups):
            if not action_setup.enabled:
                continue
            action = action_setup.action
            if not action:
                # This is not worth a log entry imo, because it does no harm,
                # and is treated by all code as if the action set-up was simply disabled.
                continue
            if action_setup.trans_min == action_setup.trans_max:
                self.log(
                    "Action has no transform range",
                    note=action_setup.action.name,
                    icon='ACTION',
                    description=f'Action set-up "{action_setup.name}" has no transformation range. This will cause the action to always be in the same state!',
                    operator=CLOUDRIG_OT_Edit_Action_Setup.bl_idname,
                    op_kwargs={'action_setup_idx': i},
                )
            if action_setup.frame_start == action_setup.frame_end:
                self.log(
                    "Action has no frame range",
                    note=action_setup.action.name,
                    icon='ACTION',
                    description=f'Action set-up "{action_setup.name}" has no frame range. This will cause the action to always be in the same state!',
                    operator=CLOUDRIG_OT_Edit_Action_Setup.bl_idname,
                    op_kwargs={'action_setup_idx': i},
                )

            default_frame = int(action_setup.get_default_frame())
            if not action_setup.is_default_frame_integer():
                self.log(
                    "Action default frame must be whole",
                    note=action_setup.name,
                    icon='ACTION',
                    description=f'Action "{action_setup.name}" has a default frame of {default_frame}. The input parameters of the Action Set-up should be tweaked such that the "Default Frame" value is a whole number. On that frame, there should be a keyframe of all affected bones in the default position. Otherwise, the rig will be deformed in its default pose.',
                    operator=CLOUDRIG_OT_Edit_Action_Setup.bl_idname,
                    op_kwargs={'action_setup_idx': i},
                )

            ### Scan curves for issues. Not as expensive as I expected.
            # Storage for FCurves w/o a key on the default frame with default value.
            wrong_curves = []
            # Curves which only have one keyframe
            single_point_curves = []
            for fcurve in action_setup.channelbag.fcurves:
                transform = fcurve.data_path.split(".")[-1]
                if transform not in ['location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale']:
                    continue
                if len(fcurve.keyframe_points) < 2:
                    single_point_curves.append(fcurve)
                    continue

                default_value = 1.0 if transform == 'scale' else 0.0
                has_default_key = False
                for kp in fcurve.keyframe_points:
                    if kp.co[0] == default_frame and kp.co[1] == default_value:
                        has_default_key = True
                        break

                if not has_default_key:
                    wrong_curves.append(fcurve)

            if single_point_curves:
                self.log(
                    "Action with 1-key curves",
                    note=action_setup.action.name,
                    icon='ACTION',
                    description=f'Action slot "{action_setup.action.name}" has {len(single_point_curves)} curves with only a single keyframe. These curves will be ignored by the action set-up!',
                    operator=CLOUDRIG_OT_Clear_Single_Keyframes.bl_idname,
                    op_kwargs={'action_setup_idx': i},
                )
            if wrong_curves:
                self.log(
                    "Action affects rest pose",
                    note=action_setup.action.name,
                    icon='ACTION',
                    description=f'Action slot "{action_setup.action.name}" has {len(wrong_curves)} curves that are not keyframed to their default values on the default frame ({default_frame}).',
                    operator='object.cloudrig_jump_to_action_setup',
                    op_kwargs={'setup_id': action_setup.unique_id},
                )

    def report_drivers_targetting_armature_constraint(self, rig_obj):
        # NOTE: There is now a legitimate case where this could be intended,
        # so don't warn about it for now.
        return
        if not rig_obj or not rig_obj.animation_data:
            return
        for fc in rig_obj.animation_data.drivers:
            drv = fc.driver
            for var in drv.variables:
                if 'PROP' in var.type:
                    continue
                for target in var.targets:
                    if not target.id or not (
                        target.id.id_type == 'OBJECT'
                        and target.id.type == 'ARMATURE'
                        and target.bone_target
                    ):
                        continue
                    if target.transform_space != 'LOCAL_SPACE':
                        continue

                    target_bone = target.id.pose.bones.get(target.bone_target)
                    if not target_bone:
                        continue
                    if not any(
                        [con.type == 'ARMATURE' for con in target_bone.constraints]
                    ):
                        continue

                    self.log(
                        "Misleading Local Transforms",
                        note=target_bone.name,
                        trouble_bone=target_bone.name,
                        icon='DRIVER_TRANSFORM',
                        description=f'Driver `{fc.data_path}` is trying to read local transforms from bone "{target_bone.name}", but this bone has an Armature constraint, which moves its parenting matrix into its local matrix, making it unviable as a driver target. Move the Armature constraint to a parent, or remove the driver.',
                    )

    def report_sus_constraints(self, rig_obj):
        for pb in rig_obj.pose.bones:
            arm_con = None
            for con in pb.constraints:
                if con.type=='ARMATURE':
                    if not arm_con:
                        arm_con = con
                    else:
                        self.log(
                            "Multiple Armature Constraints",
                            note=pb.name,
                            trouble_bone=pb.name,
                            icon='CON_ARMATURE',
                            description=f'This bone has multiple Armature constraints, which is unlikely to be intentional.'
                        )
                        break


class CloudRigLogEntry(PropertyGroup):
    """Container for storing information about a single metarig warning/error.

    A CollectionProperty of CloudRigLogEntries are added to the armature datablock
    in cloud_generator.register().

    This CollectionProperty is then populated by a CloudLogManager instance created by
    CloudRig_Generator, which is created by the Generate operator.
    """

    icon: StringProperty(
        name="Icon", description="Icon for this log entry", default='ERROR'
    )
    base_bone_name: StringProperty(
        name="Rig Bone",
        description="Name of the bone on the metarig which owns the rig that created this entry",
        default="",
    )
    display_stack_trace: EnumProperty(
        items=[(s, s, s) for s in {'ADVANCED', 'NEVER', 'ALWAYS'}],
        description="Whether the stack trace for this log entry should be displayed never, always, or only when Advanced Mode is enabled",
    )
    note: StringProperty(
        name="Note",
        description="Extra note that gets displayed in the UIList when there's no owner bone",
        default="",
    )
    note_icon: StringProperty(
        name="Note Icon", description="Icon for the extra note", default='NONE'
    )
    trouble_bone: StringProperty(
        name="Problem Bone",
        description="Name of the bone on the generated rig which the entry relates to",
        default="",
    )
    description_short: StringProperty(
        name="Short Description", description="Something went wrong!", default=""
    )
    description: StringProperty(name="Description", description="", default="")
    pretty_stack: StringProperty(
        name="Pretty Stack",
        description="Stack trace in the code of where this log entry was added. For internal use only",
    )
    operator: StringProperty(
        name="Operator", description="Operator that can fix the issue", default=''
    )
    op_kwargs: StringProperty(
        name="Operator Arguments",
        description="Keyword arguments that will be passed to the operator. This should be a string that can be eval()'d into a python dict",
        default='',
    )
    op_text: StringProperty(
        name="Operator Text",
        description="Text to display on quick fix button",
        default='',
    )
    op_icon: StringProperty(
        name="Operator Icon",
        description="Icon to display on quick fix button",
        default='BLANK1',
    )


class CLOUDRIG_UL_log_entry_slots(UIList):
    """CloudRigLogEntries are displayed under Properties->Armature->CloudRig->Generation Log,
    when the active object is a CloudRig Metarig.
    """

    def draw_item(
        self, _context, layout, _data, item, icon_value, _active_data, _active_propname
    ):
        log = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(log, 'description_short', text="", icon=log.icon, emboss=False)
            if log.note != "":
                row.prop(
                    log, 'note', emboss=False, text="", icon=log.note_icon or 'NONE'
                )
            elif log.base_bone_name != "":
                row.prop(log, 'base_bone_name', text="", emboss=False, icon='BONE_DATA')

        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon_value)


class CLOUDRIG_PT_log(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_label = "Generation Log"
    bl_parent_id = "POSE_PT_CloudRig"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return is_cloud_metarig(context.object) and obj.mode in ('POSE', 'OBJECT')

    def draw_header(self, context):
        metarig = context.object
        generator = metarig.cloudrig.generator
        logs = generator.logs
        layout = self.layout

        if len(logs) == 0:
            layout.label(text="", icon='CHECKMARK')
        else:
            layout.label(text="", icon='ERROR')

    def draw(self, context):
        metarig = context.object
        generator = metarig.cloudrig.generator
        logs = generator.logs
        layout = self.layout

        if len(logs) == 0:
            layout.label(text="No generation issues detected!", icon='CHECKMARK')
            return

        row = layout.row()
        row.template_list(
            'CLOUDRIG_UL_log_entry_slots',
            '',
            generator,
            'logs',
            generator,
            'active_log_index',
        )

        log = generator.active_log

        layout.use_property_split = False

        # It is optional for the log entry to provide a bone from the metarig, in case
        # the log entry relates to a rig component.
        if log.base_bone_name != "":
            split = layout.row().split(factor=0.3)
            split.label(text="Rig Component:")
            main_row = split.column().row(align=True)
            row = main_row.row(align=True)
            row.prop_search(log, 'base_bone_name', metarig.data, 'bones', text="")
            row.enabled = False
            row = main_row.row(align=True)
            op = row.operator(
                CLOUDRIG_OT_Jump_To_Bone.bl_idname, text="", icon='LOOP_FORWARDS'
            )
            op.use_target_rig = False
            op.target_bone = log.base_bone_name

        if log.trouble_bone != "":
            split = layout.row().split(factor=0.3)
            split.label(text="Generated Bone:")
            main_row = split.column().row(align=True)
            row = main_row.row(align=True)
            row.prop_search(log, 'trouble_bone', metarig.data, 'bones', text="")
            row.enabled = False
            row = main_row.row(align=True)
            op = row.operator(
                CLOUDRIG_OT_Jump_To_Bone.bl_idname, text="", icon='LOOP_FORWARDS'
            )
            op.use_target_rig = True
            op.target_bone = log.trouble_bone

        desc = log.description_short
        if log.description != "":
            desc = log.description
        draw_label_with_linebreak(context, layout, desc)

        if log.operator != '':
            row = layout.row()
            split = row.split(factor=0.2)
            split.label(text="Quick Fix:")
            if log.op_text:
                op = split.operator(log.operator, text=log.op_text, icon=log.op_icon)
            else:
                op = split.operator(log.operator, icon=log.op_icon)
            kwargs = json.loads(log.op_kwargs)
            for key in kwargs.keys():
                setattr(op, key, kwargs[key])


class CLOUDRIG_PT_stack_trace(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_parent_id = 'CLOUDRIG_PT_log'
    bl_label = "Python Stack Trace"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        generator = context.object.cloudrig.generator
        if not generator.active_log:
            return False
        display_mode = generator.active_log.display_stack_trace
        return display_mode == 'ALWAYS' or (
            display_mode == 'ADVANCED' and is_advanced_mode(context)
        )

    def draw(self, context):
        generator = context.object.cloudrig.generator
        draw_label_with_linebreak(
            context, self.layout, generator.active_log.pretty_stack, alert=True
        )


########################################
######### Quick-Fix Operators ##########
########################################
class CLOUDRIG_OT_Jump_To_Bone(Operator):
    """Make a bone visible and active in the 3D View."""

    bl_idname = "armature.jump_to_bone"
    bl_label = "Jump to Bone"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    use_target_rig: BoolProperty(
        name="Jump to Target Rig",
        description="Toggle to the generated rig before focusing bone",
        default=False,
    )
    target_bone: StringProperty(
        name="Target Bone",
        description="Bone to jump to",
    )

    def execute(self, context):
        rig = context.object

        if self.use_target_rig and rig.cloudrig.generator.target_rig:
            rig = rig.cloudrig.generator.target_rig
            bpy.ops.object.cloudrig_metarig_toggle()

        bpy.ops.object.mode_set(mode='POSE')

        bone = rig.data.bones.get(self.target_bone)
        if not bone:
            self.report({'ERROR'}, f'Bone "{self.target_bone}" not in armature "{rig.name}".')
            return {'CANCELLED'}

        reveal_and_select(context, bone)

        return {'FINISHED'}

class CLOUDRIG_OT_Change_Rotation_Mode(Operator):
    """Change rotation mode of a bone"""

    bl_idname = "pose.cloudrig_troubleshoot_rotationmode"
    bl_label = "Change Rotation Mode"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    bone_name: StringProperty()

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        metarig = context.object
        pbone = metarig.pose.bones.get(self.bone_name)
        layout.prop(pbone, 'rotation_mode')

    def execute(self, context):
        metarig = context.object
        pbone = metarig.pose.bones.get(self.bone_name)
        if not pbone or pbone.rotation_mode == 'QUATERNION':
            return {'CANCELLED'}

        metarig.cloudrig.generator.remove_active_log()
        return {'FINISHED'}


class CLOUDRIG_OT_Report_Bug(Operator):
    """Report a bug on the CloudRig repository"""

    bl_idname = "wm.cloudrig_report_bug"
    bl_label = "Report Bug"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        active_obj = context.object
        pretty_stack = ""
        if active_obj and hasattr(active_obj, 'cloudrig'):
            active_log = active_obj.cloudrig.generator.active_log
            if active_log:
                pretty_stack = active_log.pretty_stack
        webbrowser.open(url_prefill_from_cloudrig(pretty_stack))

        return {'FINISHED'}


class CLOUDRIG_OT_Rename_Bone(Operator):
    """Rename a bone"""

    bl_idname = "object.cloudrig_rename_bone"
    bl_label = "Rename Bone"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    old_name: (
        StringProperty()
    )  # Should be provided to the operator by the UI, and not changed!
    new_name: StringProperty(name="Name")  # Exposed to user

    def invoke(self, context, event):
        wm = context.window_manager
        self.new_name = self.old_name
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        metarig = context.object
        if self.new_name in metarig.data.bones:
            layout.prop(self, 'new_name', icon='ERROR')
            layout.label(text="This bone name is taken!")
        else:
            layout.prop(self, 'new_name')
            layout.label(text="Bone name available!")

    def execute(self, context):
        metarig = context.object
        bone = metarig.data.bones.get(self.old_name)
        if self.new_name in metarig.data.bones:
            self.report({'ERROR'}, "That bone name is already taken.")
            return {'CANCELLED'}
        if not bone:
            self.report(
                {'ERROR'}, f'Old bone "{self.old_name}" not found or not provided.'
            )
            return {'CANCELLED'}

        bone.name = self.new_name
        if bone.name == self.new_name:
            metarig.cloudrig.generator.remove_active_log()
        return {'FINISHED'}


class CLOUDRIG_OT_Swap_Bone_Shape(Operator):
    """Redirect custom bone shape references from one object to another"""

    bl_idname = "object.cloudrig_swap_bone_shape"
    bl_label = "Swap Bone Shapes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Both of these should be provided by the UI.
    old_name: StringProperty()
    new_name: StringProperty()

    def execute(self, context):
        metarig = context.object
        old_obj = bpy.data.objects.get((self.old_name, None))
        new_obj = bpy.data.objects.get((self.new_name, None))

        if not old_obj and new_obj:
            self.report(
                {'ERROR'},
                f'Error: One of "{self.old_name}" or "{self.new_name}" was not found.',
            )
            return {'CANCELLED'}

        rigs = [metarig]

        rig = metarig.cloudrig.generator.target_rig
        if rig:
            rigs.append(rig)

        for rig in rigs:
            for pb in rig.pose.bones:
                if pb.custom_shape == old_obj:
                    pb.custom_shape = new_obj

        bpy.data.objects.remove(old_obj)
        widget_collection = metarig.cloudrig.generator.widget_collection
        if widget_collection and new_obj.name not in widget_collection.objects:
            widget_collection.objects.link(new_obj)

        metarig.cloudrig.generator.remove_active_log()
        self.report(
            {'INFO'},
            f'Replaced all references of "{self.old_name}" to "{self.new_name}".',
        )
        return {'FINISHED'}


class CLOUDRIG_OT_Rename_Object(Operator):
    """Rename an object"""

    bl_idname = "object.cloudrig_rename_object"
    bl_label = "Rename Object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    old_name: (
        StringProperty()
    )  # Should be provided to the operator by the UI, and not changed!
    new_name: StringProperty(name="Name")  # Exposed to user

    def invoke(self, context, event):
        wm = context.window_manager
        if self.new_name == '':
            self.new_name = self.old_name
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        if self.new_name in bpy.data.objects:
            layout.prop(self, 'new_name', icon='ERROR')
            layout.label(text="This object name is taken!")
        else:
            layout.prop(self, 'new_name')
            layout.label(text="Object name available!")

    def execute(self, context):
        metarig = context.object
        obj = bpy.data.objects.get((self.old_name, None))

        if self.new_name in bpy.data.objects:
            self.report({'ERROR'}, "That object name is already taken.")
            return {'CANCELLED'}

        if not obj:
            self.report(
                {'ERROR'},
                f'Error: Old object "{self.old_name}" not found or not provided.',
            )
            return {'CANCELLED'}

        obj.name = self.new_name
        if obj.name == self.new_name:
            metarig.cloudrig.generator.remove_active_log()
        return {'FINISHED'}


class CLOUDRIG_OT_Delete_Object(Operator):
    """Delete an object"""

    bl_idname = "object.cloudrig_delete_object"
    bl_label = "Delete Object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    ob_name: StringProperty()

    def execute(self, context):
        metarig = context.object
        ob = bpy.data.objects.get((self.ob_name, None))

        metarig.cloudrig.generator.remove_active_log()

        if not ob:
            self.report(
                {'WARNING'},
                f'"{self.ob_name}" not found. It must have already been deleted.',
            )
            return {'FINISHED'}

        bpy.data.objects.remove(ob)

        self.report({'INFO'}, f'Deleted "{self.ob_name}".')
        return {'FINISHED'}


class CLOUDRIG_OT_Unlink_Widget(Operator):
    """Unlink a custom shape from the Custom Shape Collection"""

    bl_idname = "object.cloudrig_unlink_widget"
    bl_label = "Unlink Custom Shape"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    ob_name: StringProperty()

    def execute(self, context):
        metarig = context.object
        widget_collection = metarig.cloudrig.generator.widget_collection

        metarig.cloudrig.generator.remove_active_log()

        if not widget_collection:
            self.report({'ERROR'}, "Custom Shape Collection had been removed.")
            return {'FINISHED'}

        obj = widget_collection.all_objects.get(self.ob_name)

        if not obj:
            self.report({'ERROR'}, "Object had already been removed.")
            return {'FINISHED'}
        
        for coll in [widget_collection] + widget_collection.children_recursive:
            if obj in set(coll.objects):
                coll.objects.unlink(obj)

        self.report({'INFO'}, f"Unlinked Custom Shape: {self.ob_name}")
        return {'FINISHED'}


class CLOUDRIG_OT_Clear_Pointer(Operator):
    """Set a datablock pointer parameter to None"""

    bl_idname = "object.cloudrig_clear_pointer_param"
    bl_label = "Clear Pointer Parameter"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    bone_name: StringProperty()
    param_name: StringProperty()

    def execute(self, context):
        metarig = context.object
        pbone = metarig.pose.bones.get(self.bone_name)
        param_split = self.param_name.split(".")
        param_category = getattr(pbone.cloudrig_component.params, param_split[0])
        old_ref = getattr(pbone.cloudrig_component.params, param_split[1])
        setattr(param_category, param_split[1], None)

        self.report(
            {'INFO'}, f'Cleared reference to "{old_ref.name}" on "{pbone.name}".'
        )
        metarig.cloudrig.generator.remove_active_log()
        return {'FINISHED'}


class CLOUDRIG_OT_Clear_Single_Keyframes(Operator):
    """Remove curves with only one keyframe"""

    bl_idname = "object.cloudrig_clear_single_keyframes"
    bl_label = "Remove Single Keyframes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    action_setup_idx: IntProperty(name="Action Set-up Index")

    def execute(self, context):
        metarig = context.object
        action_setups = metarig.cloudrig.generator.action_setups
        action_setup = action_setups[self.action_setup_idx]

        curves_removed = 0
        for fcurve in action_setup.channelbag.fcurves[:]:
            if len(fcurve.keyframe_points) < 2:
                action_setup.channelbag.fcurves.remove(fcurve)
                curves_removed += 1

        self.report({'INFO'}, f'Removed {curves_removed} curves.')
        metarig.cloudrig.generator.remove_active_log()
        return {'FINISHED'}


class CLOUDRIG_OT_Edit_Action_Setup(Operator):
    """Directly edit an action slot in a pop-up panel"""

    bl_idname = "object.cloudrig_edit_action_setup_popup"
    bl_label = "Edit Action Set-up"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    action_setup_idx: IntProperty(name="Action Set-up Index")

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        metarig = context.object
        rig = metarig.cloudrig.generator.target_rig

        action_setup = metarig.cloudrig.generator.active_action_setup

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        action_setup.draw_ui(layout, rig.data)

    def execute(self, context):
        return {'FINISHED'}


class CLOUDRIG_OT_delete_collection(Operator):
    """Remove a bone collection"""

    bl_idname = "object.cloudrig_delete_bone_collection"
    bl_label = "Delete Bone Collection"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Should be provided by the UI.
    coll_name: StringProperty()

    def execute(self, context):
        metarig = context.object
        if self.coll_name in metarig.data.collections_all:
            coll = metarig.data.collections_all.get(self.coll_name)
            metarig.data.collections.remove(coll)
            self.report({'INFO'}, f"Deleted '{self.coll_name}' collection.")
        else:
            self.report({'INFO'}, f"Collection {self.coll_name} not found.")

        metarig.cloudrig.generator.remove_active_log()

        return {'FINISHED'}


registry = [
    CLOUDRIG_UL_log_entry_slots,
    CloudRigLogEntry,
    CLOUDRIG_PT_log,
    CLOUDRIG_PT_stack_trace,
    CLOUDRIG_OT_Jump_To_Bone,
    CLOUDRIG_OT_Change_Rotation_Mode,
    CLOUDRIG_OT_Report_Bug,
    CLOUDRIG_OT_Rename_Bone,
    CLOUDRIG_OT_Swap_Bone_Shape,
    CLOUDRIG_OT_Rename_Object,
    CLOUDRIG_OT_Delete_Object,
    CLOUDRIG_OT_Unlink_Widget,
    CLOUDRIG_OT_Clear_Pointer,
    CLOUDRIG_OT_Clear_Single_Keyframes,
    CLOUDRIG_OT_Edit_Action_Setup,
    CLOUDRIG_OT_delete_collection,
]
