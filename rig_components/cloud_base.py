# Typing
import bpy
from bpy.types import Object
from typing import List, Tuple, Dict

# Component_Base parent classes
from ..generation.troubleshooting import LoggerMixin
from ..rig_component_features.bone_set import BoneSetMixin
from ..rig_component_features.bone import BoneInfo
from ..rig_component_features.bone_gizmos import BoneGizmoMixin
from ..rig_component_features.ui import CloudUIMixin
from ..rig_component_features.mechanism import CloudMechanismMixin
from ..rig_component_features.object import CloudObjectUtilitiesMixin
from ..rig_component_features.parenting import CloudParentingMixin
from ..rig_component_features.custom_props import CloudCustomPropertiesMixin


class Component_Base(
    LoggerMixin,
    CloudParentingMixin,
    CloudMechanismMixin,
    CloudObjectUtilitiesMixin,
    CloudCustomPropertiesMixin,
    CloudUIMixin,
    BoneSetMixin,
    BoneGizmoMixin,
):
    """Base class that all CloudRig components should inherit from."""

    # Strings to try to communicate obscure behaviours of this rig type in the params UI.
    relinking_behaviour = ""
    parent_switch_behaviour = "The active parent will own the rig's root bone."
    parent_switch_overwrites_root_parent = True
    chain_must_be_connected = True

    ui_name = "Cloud Base (Should not be visible in UI!)"

    def __init__(
        self, generator: 'CloudRig_Generator', bone_name: str, parent_instance=None
    ):
        self.generator = generator

        self.target_rig = generator.target_rig
        self.metarig = generator.metarig
        self.base_bone_name = bone_name

        pose_bone = self.metarig.pose.bones.get(bone_name)
        self.params = pose_bone.cloudrig_component.params

        self.parent_component = parent_instance
        if parent_instance:
            parent_instance.child_components.append(self)
        self.child_components = []

        self.initialize()  # TODO 4.0: __init__ and initialize() should probably be merged.

    def initialize(self):
        """First Rigify stage, called by the Generator.
        https://wiki.blender.org/wiki/Process/Addons/Rigify/RigClass
        """
        self.bone_count = len(self.get_component_bone_chain())

        ### Quick access to the generator's log manager
        self.logger = self.generator.logger

        ### Quick access to the generator's name manager
        self.naming = self.generator.naming

        # Determine Suffix/Prefix
        self.side_suffix = ""
        self.side_prefix = ""
        is_left = self.naming.side_is_left(self.base_bone_name)
        if is_left:
            self.side_suffix = "L"
            self.side_prefix = "Left"
        elif is_left == False:
            self.side_suffix = "R"
            self.side_prefix = "Right"

        self.generator_params = self.generator.params
        self.defaults = dict(self.generator.defaults)

        self.scale = self.generator.scale

        # Reference to this component's root bone info which should be set in create_bone_infos()
        # Used for the "Custom Root Parent" feature.
        self.root_bone = None

        self.force_parameters(self.metarig_base_pbone, self.params)

        # Prepare Bone Sets
        self.bone_sets = dict()
        self.init_bone_sets()

        # Quick access to the basic important bone sets
        self.bones_org = self.bone_sets['Original Bones']
        self.bones_def = self.bone_sets['Deform Bones']
        self.bones_mch = self.bone_sets['Mechanism Bones']

    def load_metarig_bone_infos(self, metarig: Object) -> Dict[str, BoneInfo]:
        """Read ORG bones into BoneInfo instances in self.bones_org
        which will be turned into real bones by the CloudRig generator.

        This function requires the metarig in edit mode.
        TODO RNA: Once component types are entirely on rna, they can access the metarig via self.id_data.
        """

        assert (
            metarig.type == 'ARMATURE' and metarig.mode == 'EDIT'
        ), "Metarig must be an edit mode armature."

        bone_infos = {}
        for pbone in self.get_component_bone_chain():
            ebone = metarig.data.edit_bones.get(pbone.name)
            ebone.use_connect = False

            if self.naming.has_trailing_zeroes(pbone):
                self.add_log(
                    "Trailing zeroes",
                    trouble_bone=ebone.name,
                    description="Trailing zeroes in the metarig can cause bone name clashes and should be avoided.",
                    operator='object.cloudrig_rename_bone',
                    op_kwargs={'old_name': pbone.name},
                )
            if self.naming.has_wrong_separator(pbone):
                self.raise_generation_error(
                    "Wrong separator",
                    note=pbone.name,
                    description=f"{pbone.name}: CloudRig requires the side indicator in the bone's name to be separated by a period(`.`).",
                    operator='object.cloudrig_rename_bone',
                    op_kwargs={'old_name': pbone.name},
                )
            if not self.naming.side_is_suffix(pbone):
                self.raise_generation_error(
                    "Side indicator must be suffix",
                    note=pbone.name,
                    description=f"{pbone.name}: CloudRig requires the side indicator in the bone's name to be at the end of the bone name.",
                    operator='object.cloudrig_rename_bone',
                    op_kwargs={'old_name': pbone.name},
                )

            # TODO: While it currently shouldn't be possible for a single bone to belong to multiple components,
            # if we wanted to support that (and maybe we do), we should check if a BoneInfo for this bone already
            # exists on any other component of this metarig.
            bone_info = self.bones_org.new_from_real(
                self.metarig, ebone, keep_collections=False, keep_colors=False
            )
            if not bone_info:
                self.raise_generation_error(
                    description_short=f'Bone name "{bone_info.name}" was used twice!',
                    description="Make sure your bone names are unique and do not have trailing zeroes!",
                )
            bone_info.bbone_width = ebone.bbone_x / self.scale
            bone_infos[bone_info.name] = bone_info

        return bone_infos

    ### Functions called by the CloudRig Generator.
    def create_bone_infos(self, context):
        self.root_bone = self.bones_org[0]

    def create_component_interactions(self):
        skip_root_parenting = (
            self.parent_switch_overwrites_root_parent
            and self.params.parenting.parent_switching
        )
        if not skip_root_parenting and self.params.parenting.root_parent != "":
            self.apply_custom_root_parent()
        if self.params.parenting.parent_switching:
            self.apply_parent_switching(self.params.parenting.parent_slots)
        self.relink()
        self.add_gizmo_interactions()

    def create_helper_objects(self, context):
        # Called by the generator. Subclasses can use this to create
        # helpers like curves, empties, lattices.
        pass

    # Other functions
    def relink(self):
        # Relink the base bone.
        bi = self.root_bone
        bi.relink()

    ##############################
    # Parameters

    def force_parameters(self, metarig_base_pbone, params):
        """Allows the class to force certain parameter values for its instances."""
        clas = type(self)
        for param in clas.forced_params.keys():
            forced_value = clas.forced_params[param]
            if forced_value != 'NOFORCE':
                metarig_base_pbone.cloudrig_component.params[param] = forced_value
                setattr(params, param, forced_value)

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Deform Bones', is_advanced=True)
        cls.define_bone_set('Mechanism Bones', is_advanced=True)
        cls.define_bone_set('Original Bones', is_advanced=True)

    @classmethod
    def make_rotation_mode_param(
        cls,
        name="Rotation Mode",
        description="Set the rotation mode of the controls",
        can_propagate=True,
        default='XYZ',
    ):
        items = [
            ('XYZ', 'XYZ Euler', ''),
            ('XZY', 'XZY Euler', ''),
            ('YXZ', 'YXZ Euler', ''),
            ('YZX', 'YZX Euler', ''),
            ('ZXY', 'ZXY Euler', ''),
            ('ZYX', 'ZYX Euler', ''),
            ('AXIS_ANGLE', 'Axis Angle', ''),
            ('QUATERNION', 'Quaternion', ''),
        ]
        if can_propagate:
            items.append(
                (
                    'PROPAGATE',
                    'Propagate',
                    'Propagate rotation mode from each meta bone to its corresponding control',
                ),
            )

        return bpy.props.EnumProperty(
            name=name, description=description, items=items, default=default
        )

    @classmethod
    def make_inherit_scale_param(
        cls,
        name="Inherit Scale",
        description="Set the scale inheritance mode for the controls",
        can_propagate=True,
        default='FULL',
    ):
        items = [
            ('FULL', 'Full', 'Inherit all effects of parent scaling'),
            (
                'FIX_SHEAR',
                'Fix Shear',
                'Inherit scaling, but remove shearing of the child in the rest orientation',
            ),
            (
                'ALIGNED',
                'Aligned',
                'Rotate non-uniform parent scaling to align with the child, applying parent X scale to child X axis, and so forth',
            ),
            (
                'AVERAGE',
                'Average',
                'Inherit uniform scaling representing the overall change in the volume of the parent',
            ),
            ('NONE', 'None', 'Completely ignore parent scaling'),
        ]
        if can_propagate:
            items.append(
                (
                    'PROPAGATE',
                    'Propagate',
                    'Propagate scale inheritance mode from each meta bone to its corresponding control',
                )
            )

        return bpy.props.EnumProperty(
            name=name, description=description, items=items, default=default
        )
