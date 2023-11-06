from .bone import BoneInfo
from bpy.types import PropertyGroup
from bpy.props import EnumProperty, StringProperty
from mathutils import Vector


class CloudCustomPropertiesMixin:
    """Mix-in class for managing custom properties used by rig settings."""

    always_use_custom_props = False

    @property
    def properties_bone(self) -> BoneInfo:
        """Ensure that a Properties bone exists, and return it."""
        # This is a @property so if it's never called, the properties bone is not created.
        # https://en.wikipedia.org/wiki/Lazy_initialization

        if self.params.custom_props.props_storage == 'CUSTOM':
            prop_bone_name = self.params.custom_props.props_storage_bone
            properties_bone = self.generator.find_bone_info(prop_bone_name)
            if properties_bone:
                return properties_bone

            self.add_log(
                "Custom Property bone not found",
                trouble_bone=prop_bone_name,
                description=f'Custom Property bone named "{prop_bone_name}" not found, falling back to default Properties bone. If it exists, make sure it generates before this rig.',
            )
            self.params.custom_props.props_storage = 'DEFAULT'

        if self.params.custom_props.props_storage == 'DEFAULT':
            bone_name = self.generator.params.properties_bone
            properties_bone = self.generator.find_bone_info(bone_name)
            if properties_bone:
                return properties_bone

            return self.bone_sets['Mechanism Bones'].new(
                name=bone_name,
                head=Vector((0, self.scale * 2, 0)),
                tail=Vector((0, self.scale * 2, self.scale * 2)),
                bbone_width=1 / 8,
                custom_shape=self.ensure_widget("Cogwheel_Y"),
                use_custom_shape_bone_size=True,
            )
        elif self.params.custom_props.props_storage == 'GENERATED':
            # Create a bone at the base of the rig with a cogwheel shape.
            properties_bone = self.generate_properties_bone()
            # This block should only run once, so change the storage type to no longer be 'GENERATED'.
            self.params.custom_props.props_storage = 'CUSTOM'
            self.params.custom_props.props_storage_bone = properties_bone.name
            return properties_bone

    def generate_properties_bone(self) -> BoneInfo:
        org_bone = self.bones_org[0]
        properties_bone = self.bones_mch.new(
            name=org_bone.name.replace("ORG", "PRP"),
            source=org_bone,
            parent=org_bone,
            custom_shape=self.ensure_widget("Cogwheel_Y"),
            use_custom_shape_bone_size=True,
        )
        properties_bone.layers = self.metarig_base_pbone.bone.layers[:]
        return properties_bone

    @classmethod
    def is_using_custom_props(cls, context, params):
        """Determine whether the custom property storage UI should be drawn or not."""
        if cls.always_use_custom_props:
            return True
        if params.parenting.parent_switching:
            return True
        return False

    @classmethod
    def draw_custom_prop_params(cls, layout, context, params):
        metarig = context.object
        rig = metarig.data.rigify_target_rig

        cls.draw_prop(
            context, layout, params.custom_props, 'props_storage', expand=True
        )
        if params.CR_base_props_storage == 'CUSTOM':
            cls.draw_prop_search(
                context,
                layout,
                params.custom_props,
                'props_storage_bone',
                rig.pose,
                'bones',
            )
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
