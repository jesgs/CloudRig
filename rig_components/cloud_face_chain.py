# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup
from bpy.props import BoolProperty
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from .cloud_chain import Component_ToonChain
from .cloud_chain_anchor import Component_FaceChainAnchor

MERGE_THRESHOLD = 0.000001
# TODO: Center merging probably doesn't work without an anchor, or when Smooth Spline is on. Need tests!


def has_tangent_helpers(rig) -> bool:
    return rig.params.chain.smooth_spline and rig.params.chain.bbone_density > 0


def parent_cluster_to_intersection(cluster: list[BoneInfo], intersection: BoneInfo):
    for str_bone in cluster:
        component = str_bone.owner_component
        str_bone.intersection_ctrl = intersection

        str_bone.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy STR-I Transforms",
            subtarget=intersection.name,
            target_space='LOCAL_OWNER_ORIENT',
        )
        str_bone.collections = component.bone_sets['Sub Controls'].collections
        str_bone.color_palette_base = component.bone_sets['Sub Controls'].color_palette


def get_bone_clusters(chain_rigs) -> list[list[BoneInfo]]:
    """Gather a list of lists of more than one STR bones that are in the same
    location as another STR bone from another face_chain rig with
    params.face_chain.merge==True.
    """

    clusters = []
    bones_in_a_cluster = []

    all_str_bones = []
    for rig in chain_rigs:
        if not rig.params.face_chain.merge:
            continue
        all_str_bones.extend(rig.main_str_bones)

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
    cluster: list[BoneInfo], intersection: BoneInfo, is_anchor=False
):
    # If bones are in the center, flatten them along the X axis to make sure
    # they produce a clean curvature. This is important for things like the
    # teeth or the lips, which are one rig element on each side that meet in
    # the center, and are expected to make a smooth curve.
    rig = cluster[0].owner_component

    pos_sum = cluster[0].head.copy()
    for c in cluster[1:]:
        pos_sum += c.head
    avg_pos = pos_sum / len(cluster)

    if not is_anchor:
        intersection.vector = Vector((0, 0, intersection.length))
        intersection.roll = 0
        intersection.roll_type = 'VECTOR'
        intersection.roll_vector = avg_pos

    for b in cluster:
        flipped_name = rig.naming.flipped_name(b)
        if flipped_name == b.name:
            continue
        opposite_bone = b.owner_component.generator.find_bone_info(flipped_name)
        if not opposite_bone:
            continue

        b.flatten(axis='X')
        if has_tangent_helpers(b.owner_component):
            b.tangent_helper.flatten(axis='X')
        if b.owner_component.params.chain.smooth_spline:
            if has_tangent_helpers(opposite_bone.owner_component):
                # Make the Damped Track constraint of the opposite TAN- bone aim
                # at this STR bone's Damped Track target.
                # This gets us a smooth curve across the two chains.
                # (This is also what would happen if it was just one longer smooth chain)
                b.tangent_helper.constraint_infos[1].subtarget = (
                    opposite_bone.tangent_helper.constraint_infos[0].subtarget
                )


class Component_FaceChain(Component_ToonChain):
    """Chain with cartoony squash and stretch controls, which supports intersecting bone chains."""

    ui_name = "Chain: Face Grid"

    # forced_params = {
    #     'chain.smooth_spline' : False
    # }

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        # Check the generator rig list to see if we are the last chain rig that will be generated.
        self.chain_rigs = []
        for component in self.generator.all_components:
            if any(
                [
                    class_name == type(component).__name__
                    for class_name in ["Component_FaceChain", "Component_Eyelid"]
                ]
            ):
                # NOTE: I don't know why isinstance() doesn't work here. It works when cloud_eyelid is testing itself, but not when cloud_face_chain is testing cloud_eyelid.
                self.chain_rigs.append(component)

        self.is_last_chain_rig = self == self.chain_rigs[-1]

        ### Following code is only run ONCE by the LAST face_chain_rig.
        if not self.is_last_chain_rig:
            return

        # Create and set up intersection controls.

        str_bone_clusters = get_bone_clusters(self.chain_rigs)
        self.intersection_bones = []
        for cluster in str_bone_clusters:
            self.intersection_bones.append(
                self.create_intersection_for_cluster(cluster)
            )
        self.setup_all_intersections()

    def setup_all_intersections(self):
        for intersection in self.intersection_bones:
            # Parenting must be done with an Armature constraint so that
            # transforms propagate to TAN bones.
            if intersection.parent and len(intersection.constraint_infos) == 0:
                intersection.add_constraint(
                    'ARMATURE', targets=[{'subtarget': intersection.parent}]
                )

            # Also, sub STR controls must have no parent at all,
            # otherwise they would double transform.
            for str_bone in intersection.str_bones:
                str_bone.parent = None
                str_bone.ignore_orphan = True

            # This is ugly, but any STR controls with the Smooth Spline param need
            # their tangent_helper to be parented to the intersection control's parent.
            # Nvm, Smooth Spline is just not supported for now.
            # for str_bone in intersection.str_bones:
            #     if has_tangent_helpers(str_bone.owner_component):
            #         str_bone.tangent_helper.parent = intersection.parent

        # HACK: We can't ensure that the last chain rig to be executed is a cloud_eyelid,
        # so we have to make sure the eyelid set-up function runs even when that's not the case...
        for chain_rig in self.chain_rigs:
            if hasattr(chain_rig, 'make_sticky_eyelid'):
                chain_rig.make_sticky_eyelid()

    def relink(self, last_chain_done=False):
        # Only relink all cloud_face_chain components when the last one is generating.
        if last_chain_done:
            super().relink()
            return
        elif not self.is_last_chain_rig:
            return

        for rig in self.chain_rigs:
            rig.relink(last_chain_done=True)

    def get_relink_target(self, org_i: int, con: ConstraintInfo):
        """Overrides cloud_chain. Only work when called by the last chain rig.
        Relink target should become the intersection control if there is one.
        """

        relink_bone = super().get_relink_target(org_i, con)

        is_intersection = False
        if hasattr(relink_bone, 'intersection_ctrl'):
            relink_bone = relink_bone.intersection_ctrl
            is_intersection = True

        if con.type == 'ARMATURE':
            if is_intersection:
                for i, con_info in enumerate(relink_bone.constraint_infos):
                    if con_info.type == 'ARMATURE':
                        relink_bone.constraint_infos.pop(i)
            if not hasattr(relink_bone, "parent_helper") and not is_intersection:
                relink_bone = relink_bone.parent_helper = self.create_parent_bone(
                    relink_bone, self.bones_mch
                )
            elif not is_intersection:
                relink_bone = relink_bone.parent_helper

        return relink_bone

    @staticmethod
    def create_intersection_for_cluster(cluster: list[BoneInfo]) -> BoneInfo:
        """Try to find a Component_FaceChainAnchor to parent the cluster to.
        If it doesn't exist, create one.
        """

        rig_component = cluster[0].owner_component

        intersection_control = None
        is_anchor = False
        # Search for an anchor rig
        anchor_components = [
            component
            for component in rig_component.generator.all_components
            if isinstance(component, Component_FaceChainAnchor)
        ]
        for anchor_rig in anchor_components:
            distance = (anchor_rig.bones_org[0].head - cluster[0].head).length
            if distance < 0.000001:
                intersection_control = anchor_rig.bones_org[0]
                is_anchor = True
                break

        if not intersection_control:
            combined_name = rig_component.naming.combine_names(cluster)

            slices = rig_component.naming.slice_name(combined_name)
            # Discard prefixes, put STR-I.
            bone_name = rig_component.naming.make_name(
                ["STR", "I"], slices[1], slices[2]
            )

            intersection_control = rig_component.bone_sets['Intersection Controls'].new(
                name=bone_name,
                source=cluster[0],
                roll_type='ALIGN',
                roll_bone=cluster[0],
                roll=0,
                custom_shape_name='Cube',
                custom_shape_scale=0.5,
            )

        if abs(intersection_control.head.x) < 0.001:
            do_centered_cluster(cluster, intersection_control, is_anchor)

        # Parent the bones
        parent_cluster_to_intersection(cluster, intersection_control)

        intersection_control.str_bones = cluster
        return intersection_control

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
        )

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_control_params(layout, context, params)
        cls.draw_prop(context, layout, params.face_chain, 'merge')


class Params(PropertyGroup):
    merge: BoolProperty(
        name="Merge Controls",
        description="If any controls of this rig intersect with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer",
        default=True,
    )


RIG_COMPONENT_CLASS = Component_FaceChain
