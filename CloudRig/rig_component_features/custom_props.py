# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import EnumProperty, StringProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from .bone_info import BoneInfo


class CloudCustomPropertiesMixin:
    """Mix-in class for managing custom properties used by rig settings."""

    always_use_custom_props = False

    @property
    def properties_bone(self) -> BoneInfo:
        """Ensure that a Properties bone exists, and return it."""
        # This is a @property so if it's never called, the properties bone is not created.
        # https://en.wikipedia.org/wiki/Lazy_initialization

        storage = self.params.custom_props.props_storage

        if storage == 'CUSTOM':
            prop_bone_name = self.params.custom_props.props_storage_bone
            properties_bone = self.generator.find_bone_info(prop_bone_name)
            if properties_bone:
                return properties_bone

            self.add_log(
                "Custom Property bone not found",
                trouble_bone=prop_bone_name,
                description=f'Custom Property bone named "{prop_bone_name}" not found, falling back to ' \
                            'default Properties bone. If it exists, make sure it generates before this rig.',
            )
            storage = 'DEFAULT'

        if storage == 'DEFAULT':
            bone_name = self.generator.params.properties_bone
            if not bone_name:
                # User has cleared the input field.
                # Default Properties bone is the last fallback, so clearing it is not allowed.
                self.generator.params.properties_bone = "Properties"
            properties_bone = self.generator.find_bone_info(bone_name)
            if properties_bone:
                return properties_bone

            return self.bone_sets['Mechanism Bones'].new(
                name=bone_name,
                head=Vector((0, self.scale * 2, 0)),
                tail=Vector((0, self.scale * 2, self.scale * 2)),
                bbone_width=1 / 8,
                custom_shape_name="Cog",
                use_custom_shape_bone_size=True,
            )
        elif storage == 'GENERATED':
            # Create a bone at the base of the rig with a cogwheel shape.
            return self.base__create_properties_bone()

    def base__create_properties_bone(self, source: BoneInfo = None) -> BoneInfo:
        if not source:
            source = self.bones_org[0]
        prop_bone_name = self.naming.add_prefix(source, "PRP")
        prop_bone = self.generator.find_bone_info(prop_bone_name)
        if prop_bone:
            return prop_bone

        prop_bone = self.bones_mch.new(
            name=prop_bone_name,
            source=source,
            parent=source,
            custom_shape_name="Cog",
            use_custom_shape_bone_size=True,
        )
        prop_bone.collections = [
            coll.name for coll in self.metarig_base_pbone.bone.collections
        ]
        return prop_bone

    @classmethod
    def base__is_using_custom_props(cls, context, params):
        """Determine whether the custom property storage UI should be drawn or not."""
        if cls.always_use_custom_props:
            return True
        if params.parenting.parent_switching:
            return True
        return False

    @classmethod
    def draw_custom_prop_params(cls, layout, context, params):
        metarig = context.object
        rig = metarig.cloudrig.generator.target_rig

        cls.draw_prop(
            context, layout, params.custom_props, 'props_storage', expand=True, text="Storage Bone"
        )
        if params.custom_props.props_storage == 'CUSTOM':
            if rig:
                cls.draw_prop_search(
                    context,
                    layout,
                    params.custom_props,
                    'props_storage_bone',
                    rig.pose,
                    'bones',
                )
            else:
                row = layout.row()
                row.enabled = False
                cls.draw_prop(context, row, params.custom_props, 'props_storage_bone', icon='BONE_DATA')
        return layout


class Params(PropertyGroup):
    props_storage: EnumProperty(
        name="Custom Property Storage",
        items=[
            ('DEFAULT', "Shared", 'Use a shared bone called "Properties"'),
            ('CUSTOM', "Picked", "Select an existing bone"),
            (
                'GENERATED',
                "Generated",
                'Generate a bone specifically for this rig component, prefixed "PRP-"',
            ),
        ],
        description="Where to store the custom properties needed for this rig component",
    )
    props_storage_bone: StringProperty(
        name="Properties Bone",
        description='Store custom properties in the chosen bone. If empty, will fall back to a bone called "Properties"',
        default="",
    )
