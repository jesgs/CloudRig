# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..rig_component_features.bone_set import BoneInfo

from bpy.types import PropertyGroup
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector

from .cloud_base import Component_Base


class Component_CopyBone(Component_Base):
    """Copy this bone to the generated rig."""

    ui_name = "Bone Copy"
    always_use_custom_props = True

    forced_params = {
        'custom_props.props_storage': 'CUSTOM',
        'custom_props.props_storage_bone': "",
    }

    keep_original_bones_collections = True
    keep_original_bones_colors = False

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.params.custom_props.props_storage_bone = self.base_bone_name

        # If the metarig bone has a Child Of or Armature constraint, don't do any parenting logic.
        self.do_parenting = True
        for c in self.metarig_base_pbone.constraints:
            if c.type in ('CHILD_OF', 'ARMATURE'):
                self.do_parenting = False

        self.bones_org.collections = [
            coll.name for coll in self.metarig_base_pbone.bone.collections
        ]

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        for pbone, bone_info in zip(self.get_component_pbone_chain(), self.bones_org):
            if (not bone_info.use_custom_shape_bone_size):  
                bone_info.custom_shape_scale_xyz /= (
                    bone_info.bbone_width * 10 * self.scale
                )

            # NOTE: Custom colors are deliberately not supported here.
            for color, prop_name in zip([pbone.bone.color, pbone.color], ["color_palette_base", "color_palette_pose"]):
                if color.palette == 'DEFAULT':
                    continue
                if color.palette == 'CUSTOM':
                    self.add_log("Custom Colors are forbidden!", icon='COLORSET_01_VEC', trouble_bone=bone_info.name, description="Custom Colors are not supported in Metarigs. Please choose one of the preset colors. If you hate them, try applying the CloudRig presets in the Preferences.")
                    continue
                setattr(bone_info, prop_name, color.palette)

            if bone_info.custom_shape:
                self.add_to_widget_collection(context, bone_info.custom_shape)

            if bone_info.rotation_mode == 'QUATERNION':
                self.add_log(
                    "Quaternion rotation",
                    trouble_bone=self.base_bone_name,
                    description=f'"{bone_info.name}" is on Quaternion rotation mode. This is unfriendly for animators who use the Graph Editor!',
                    icon='GIZMO',
                    operator='pose.cloudrig_troubleshoot_rotationmode',
                    op_kwargs={'bone_name': self.base_bone_name},
                    op_text=f"Set {bone_info.name} to Euler",
                )
                bone_info.rotation_mode = 'XYZ'

            if self.params.copy.create_deform:
                # Make a copy with DEF- prefix, as our deform bone.
                def_bone = self.make_def_bone(bone_info, self.bones_def)
                def_bone.parent = bone_info

            if self.params.copy.property_ui_subpanel:
                self.copy__add_ui_data_of_bone(
                    bone_info,
                    self.params.copy.property_ui_subpanel,
                    self.params.copy.property_ui_label,
                )

        first_bone = self.root_bone = self.bones_org[0]
        if self.params.copy.custom_pivot:
            self.root_bone = self.copy__make_custom_pivot(first_bone, bone_set=self.bone_sets['Pivot Control'])

        if self.params.copy.ensure_free and len(first_bone.constraint_infos) > 0:
            self.root_bone = self.create_parent_constraint_holder(first_bone, bone_set=self.bone_sets['Mechanism Bones'])

    ##############################
    # Bone Copy functions.

    def copy__make_custom_pivot(self, boneinfo, bone_set=None):
        if not bone_set:
            bone_set = boneinfo.bone_set
        pivot = self.create_parent_bone(boneinfo, bone_set)
        pivot.name = pivot.name.replace("P-", "PVT-")
        boneinfo.add_constraint(
            'COPY_LOCATION', subtarget=pivot, invert_xyz=[True, True, True]
        )
        pivot.custom_shape_name = self.params.copy.shape_pivot.shape_name
        pivot.custom_shape_scale_xyz = Vector(
            [max(boneinfo.custom_shape_scale_xyz)] * 3
        )
        pivot.custom_shape_translation = (0, 0, 0)
        pivot.custom_shape_rotation_euler = (0, 0, 0)
        pivot.collections = boneinfo.collections
        pivot.color_palette_base = boneinfo.color_palette_base
        pivot.color_palette_pose = boneinfo.color_palette_pose
        return pivot

    def copy__add_ui_data_of_bone(self, bone: BoneInfo, panel_name: str, label_name=""):
        """Add the UI data of a single BoneInfo's custom props to the rig's UI data.
        Properties of the bone will be displayed under the provided sub-panel and label.
        This will be displayed in the Sidebar->CloudRig->Settings.
        """
        for prop_name, prop_settings in bone.custom_props.items():
            if prop_name.startswith("_"):
                # In the past, underscore indicated that this is a value for a preset.
                # Now, let's just say underscore means don't draw this property.
                continue
            # For the row names, we want each property to have its own row,
            # but matching properties from opposite side bones should be in
            # the same row.
            base_name = self.naming.slice_name(bone.name)[1]
            row_name = base_name + "_" + prop_name

            entry_name = prop_name
            flipped_name = self.naming.flip_name(bone.name)
            opposite_bone = self.generator.metarig.data.bones.get(flipped_name)
            if flipped_name != bone.name and opposite_bone:
                # We also want to make sure the "entry name" is unique.
                # (User should NOT add a side indicator to the property name!)
                entry_name = self.side_prefix + " " + prop_name

            texts = []
            if "$" + prop_name in self.metarig_base_pbone:
                # Rigger can specify strings for integer properties with a
                # property whose name starts with $. This property is expected
                # to be a list of strings, where the first strings matches with the value 0.
                # Negative integers are not supported for this.
                texts = self.metarig_base_pbone["$" + prop_name]

            self.rig_ui__add_bone_property(
                prop_bone=bone,
                prop_id=prop_name,
                panel_name=panel_name,
                label_name=label_name,
                row_name=row_name,
                slider_name=entry_name,
                texts=texts,
                custom_prop_settings=prop_settings
            )

    ##############################
    # Parameters

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        cls.draw_prop(context, layout, params.copy, 'ensure_free')
        cls.draw_prop(context, layout, params.copy, 'custom_pivot')
        cls.draw_prop(context, layout, params.copy, 'create_deform')

    @classmethod
    def draw_custom_prop_params(cls, layout, context, params):
        layout = super().draw_custom_prop_params(layout, context, params)
        layout.separator()

        cls.draw_prop(context, layout, params.copy, 'property_ui_subpanel')
        row = layout.row()
        row.enabled = bool(params.copy.property_ui_subpanel)
        cls.draw_prop(context, row, params.copy, 'property_ui_label')
        return layout

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'deform_bones':
            return params.copy.create_deform

        if set_name == 'mechanism_bones':
            return params.copy.ensure_free or params.parenting.parent_switching

        if set_name == 'pivot_control':
            return params.copy.custom_pivot

        if set_name == 'original_bones':
            return False

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        if params.copy.custom_pivot:
            cls.draw_prop_custom_shape(context, layout, params.copy, 'shape_pivot')

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Pivot Control', color_palette='THEME02')

class Params(PropertyGroup):
    create_deform: BoolProperty(
        name="Create Deform",
        description='Create a deforming child bone for this bone, prefixed with "DEF-"',
        default=False,
    )
    custom_pivot: BoolProperty(
        name="Create Custom Pivot",
        description="Create a parent control whose local translation is not propagated to the main control, but its rotation and scale are",
        default=False,
    )
    ensure_free: BoolProperty(
        name="Move Constraints To Parent",
        description='If this bone has any constraints, move them to a parent bone prefixed with "CON", unless the constraint name starts with "KEEP"',
        default=False,
    )
    property_ui_subpanel: StringProperty(
        name="UI Sub-panel",
        description="Choose which sub-panel the custom properties should be displayed in. If empty, the properties won't appear in the rig UI",
    )
    property_ui_label: StringProperty(
        name="UI Label",
        description="Choose which label the custom properties should be displayed under. If empty, the properties will display at the top of the subpanel",
    )

    shape_pivot: Component_Base.make_custom_shape_params(
        identifier="Pivot",
        default="Axes_6"
    )


RIG_COMPONENT_CLASS = Component_CopyBone
