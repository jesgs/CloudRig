# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import BoolProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_chain import Component_ToonChain
from .cloud_chain_anchor import Component_FaceChainAnchor

MERGE_THRESHOLD = 0.000001
# TODO: Center merging probably doesn't work without an anchor, or when Smooth Spline is on. Need tests!


class Component_FaceChain(Component_ToonChain):
    """Chain with cartoony squash and stretch controls, which supports intersecting bone chains."""

    ui_name = "Chain: Face Grid"

    ##############################
    # Inherited functions.

    def create_component_interactions(self, context, last_chain_done=False):
        # Check the generator component list to see if we are the last chain component that will be generated.
        self.chain_components = []
        for component in self.generator.all_components:
            if type(component).__name__ in ["Component_FaceChain", "Component_Eyelid"]:
                # NOTE: I don't know why isinstance() doesn't work here.
                # It works when cloud_eyelid is testing itself, but not when cloud_face_chain is testing cloud_eyelid.
                self.chain_components.append(component)

        self.is_last_chain_comp = self == self.chain_components[-1]

        if last_chain_done:
            super().create_component_interactions(context)

        ### Following code is only run ONCE by the LAST face chain component.
        if self.is_last_chain_comp and not last_chain_done:
            self.fchain__create_and_setup_intersections(context)

    @no_overlay
    def base__relink(self, last_chain_done=False):
        # Only relink all cloud_face_chain components when the last one is generating.
        if last_chain_done:
            super().base__relink()
            return
        elif not self.is_last_chain_comp:
            return

        for comp in self.chain_components:
            comp.base__relink(last_chain_done=True)

    def base__relink_get_target(self, org_i: int, con: ConstraintInfo) -> BoneInfo:
        """Relink target should become the intersection control if there is one."""
        relink_tgt: BoneInfo = super().base__relink_get_target(org_i, con)

        is_intersection = False
        if hasattr(relink_tgt, 'intersection_ctrl') and relink_tgt.intersection_ctrl:
            relink_tgt = relink_tgt.intersection_ctrl
            is_intersection = True

        if con.type == 'ARMATURE':
            if not hasattr(relink_tgt, "parent_helper") and not is_intersection:
                relink_tgt = relink_tgt.parent_helper = self.create_parent_bone(
                    relink_tgt, self.bones_mch
                )
            elif not is_intersection and relink_tgt.parent_helper:
                relink_tgt = relink_tgt.parent_helper
            else:
                if 'NOHLP' not in con.name:
                    con.name += "_NOHLP"

        return relink_tgt

    ##############################
    # Face grid functions.

    def fchain__create_and_setup_intersections(self, context):
            # Create and set up intersection controls.

            str_bone_clusters = get_bone_clusters(self.chain_components)
            self.intersection_bones = []
            for cluster in str_bone_clusters:
                self.intersection_bones.append(
                    self.__create_intersection_for_cluster(cluster)
                )
            self.__setup_all_intersections()

            for comp in self.chain_components:
                comp.create_component_interactions(context, last_chain_done=True)

    def __create_intersection_for_cluster(self, cluster: list[BoneInfo]) -> BoneInfo:
        """Try to find a Component_FaceChainAnchor to parent the cluster to.
        If it doesn't exist, create one.
        """

        rig_component = cluster[0].owner_component

        intersection_control = None
        is_anchor = False
        # Search for an anchor component
        anchor_components = [
            component
            for component in rig_component.generator.all_components
            if isinstance(component, Component_FaceChainAnchor)
        ]
        for anchor_comp in anchor_components:
            distance = (anchor_comp.bones_org[0].head - cluster[0].head).length
            if distance < 0.000001:
                intersection_control = anchor_comp.bones_org[0]
                is_anchor = True
                break

        if not intersection_control:
            combined_name = rig_component.naming.combine_names(cluster)

            slices = rig_component.naming.slice_name(combined_name)
            # Discard prefixes, put STR-I.
            bone_name = rig_component.naming.make_name(["STR", "I"], slices[1], slices[2])

            intersection_control = rig_component.bone_sets['Intersection Controls'].new(
                name=bone_name,
                # STR bone won't have a parent helper when BBone Densitry is 0.
                source=cluster[0].parent_helper or cluster[0],
                parent=cluster[0].source,
                custom_shape_name=self.params.face_chain.shape_intersection.shape_name,
                custom_shape_scale_xyz=(1, 1, 1)
            )
            intersection_control.roll_align_other(cluster[0])

        if abs(intersection_control.head.x) < 0.001:
            do_centered_cluster(cluster, intersection_control, is_anchor)

        # Parent the bones
        parent_cluster_to_intersection(cluster, intersection_control)

        intersection_control.str_bones = cluster
        return intersection_control

    def __setup_all_intersections(self):
        for intersection in self.intersection_bones:
            # Parenting must be done with an Armature constraint so that
            # transforms propagate to TAN bones.
            continue
            if intersection.parent and len(intersection.constraint_infos) == 0:
                intersection.add_constraint(
                    'ARMATURE', targets=[{'subtarget': intersection.parent}]
                )
        # HACK: We can't ensure that the last chain component to be executed is a cloud_eyelid,
        # so we have to make sure the eyelid setup function runs even when that's not the case...
        for chain_comp in self.chain_components:
            if hasattr(chain_comp, 'eyelid__make_sticky_setup'):
                chain_comp.eyelid__make_sticky_setup()

    ##############################
    # Parameters
    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        # The sub_controls set is special in that its .new() function should never be
        # called, and therefore it never creates any bones. However, pre-existing
        # STR bones who then had a merged control created for them will be assigned
        # the bone group and layer of this BoneSet.
        cls.define_bone_set(
            'Sub Controls',
            color_palette='THEME02',
            collections=['Mechanism Bones'],
            is_advanced=True,
        )
        cls.define_bone_set(
            'Intersection Controls',
            color_palette='THEME09',
            collections=['Stretch Controls'],
            wire_width=1.5,
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params
        cls.draw_prop(context, layout, params.face_chain, 'merge')

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        cls.draw_prop_custom_shape(context, layout, params.face_chain, 'shape_intersection')


def has_tangent_helpers(component) -> bool:
    return component.params.chain.smooth_spline and component.params.chain.bbone_density > 0


def parent_cluster_to_intersection(cluster: list[BoneInfo], intersection: BoneInfo):
    for str_bone in cluster:
        component = str_bone.owner_component
        str_bone.intersection_ctrl = intersection

        if str_bone.owner_component.params.chain.bbone_density > 0:
            arm_con = next((con for con in str_bone.parent_helper.constraint_infos if con.type=='ARMATURE'), None)
            if arm_con:
                arm_con.targets = [intersection.name]
        else:
            # STR bone will have no parent helper when BBone Density is 0.
            str_bone.parent = intersection

        if str_bone.custom_shape_transform:
            str_bone.custom_shape_transform.add_constraint(
                'COPY_TRANSFORMS',
                name="Copy Anchor Transforms (Smooth Intersection)",
                index=3,
                subtarget=intersection,
                target_space='LOCAL_OWNER_ORIENT',
                mix_mode='BEFORE',
            )
            # This is horrendous, but I can't argue with the results.
            # The tangent helper must inherit rotation, otherwise it doesn't get affected by the root (very bad).
            # However, the current stack of constraints results in a double inheritance of just Y rotation,
            # because the Damped Track constraints are fully locking the X and Z rotations.
            str_bone.custom_shape_transform.add_constraint(
                'COPY_ROTATION',
                name="Counter Anchor Y Rot (Smooth Intersection)",
                index=4,
                subtarget=intersection,
                use_xyz=[False, True, False],
                invert_xyz=[False, True, False],
                target_space='LOCAL_OWNER_ORIENT',
                euler_order='YZX',
                mix_mode='BEFORE',
            )

        str_bone.collections = component.bone_sets['Sub Controls'].collections
        str_bone.color_palette_base = component.bone_sets['Sub Controls'].color_palette


def get_bone_clusters(chain_components: list[Component_ToonChain]) -> list[list[BoneInfo]]:
    """Gather a list of lists of more than one STR bones that are in the same
    location as another STR bone from another face_chain rig with
    params.face_chain.merge==True.
    """

    clusters = []
    bones_in_a_cluster = []

    all_str_bones = []
    for component in chain_components:
        if not component.params.face_chain.merge:
            continue
        all_str_bones.extend(component.main_str_bones)

    for str_bone in all_str_bones:
        if str_bone in bones_in_a_cluster:
            continue
        cluster = [str_bone]
        for other_str in all_str_bones:
            if other_str in bones_in_a_cluster:
                continue
            if str_bone == other_str:
                continue
            if (str_bone.head - other_str.head).length < MERGE_THRESHOLD:
                cluster.append(other_str)
        if len(cluster) > 1:
            clusters.append(cluster)
        bones_in_a_cluster.extend(cluster)

    return clusters


def do_centered_cluster(
    cluster: list[BoneInfo],
    intersection: BoneInfo,
    is_anchor=False
):
    # If bones are in the center, flatten them along the X axis to make sure
    # they produce a clean curvature. This is important for things like the
    # teeth or the lips, which are one rig component on each side that meet in
    # the center, and are expected to make a smooth curve.
    component = cluster[0].owner_component

    pos_sum = cluster[0].head.copy()
    for c in cluster[1:]:
        pos_sum += c.head
    avg_pos = pos_sum / len(cluster)

    if not is_anchor:
        intersection.vector = Vector((0, 0, intersection.length))
        intersection.roll_align_vector(avg_pos)

    for bone in cluster:
        flipped_name = component.naming.flip_name(bone)
        if flipped_name == bone.name:
            continue
        opposite_bone = bone.owner_component.generator.find_bone_info(flipped_name)
        if not opposite_bone:
            continue

        bone.flatten(axis='X')
        if has_tangent_helpers(bone.owner_component):
            bone.tangent_helper.flatten(axis='X')
        if bone.owner_component.params.chain.smooth_spline:
            if has_tangent_helpers(opposite_bone.owner_component):
                # Make the Damped Track constraint of the opposite TAN- bone aim
                # at this STR bone's Damped Track target.
                # This gets us a smooth curve across the two chains.
                # (This is also what would happen if it was just one longer smooth chain)
                bone.tangent_helper.constraint_infos[1].subtarget = (
                    opposite_bone.tangent_helper.constraint_infos[0].subtarget
                )


class Params(PropertyGroup):
    merge: BoolProperty(
        name="Merge Controls",
        description="If any controls of this rig intersect with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer",
        default=True,
    )

    shape_intersection: Component_ToonChain.make_custom_shape_params(
        identifier="Intersection",
        default="Cube"
    )


RIG_COMPONENT_CLASS = Component_FaceChain
