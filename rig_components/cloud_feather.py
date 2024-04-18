from .cloud_fk_chain import Component_Chain_FK


class Component_Feather(Component_Chain_FK):
    """Single-bone rig for a simple feather."""

    ui_name = "Feather"
    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.display_center': False,
    }

    def initialize(self):
        super().initialize()

        if self.bone_count != 1:
            self.raise_generation_error("Feather rig must consist of exactly 1 bone.")

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        first_fk = self.bone_sets['FK Controls'][0]
        first_fk.custom_shape_name = "Feather"
        first_fk.custom_shape_along_length = 1

        # Create a new bone parented to ORG, and parent the tip control to it.
        org = self.bones_org[0]
        bend_ctr = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org.name, "BEND"),
            source=org,
            parent=org,
            custom_shape_name="Feather",
        )
        self.main_str_bones[-1].parent = bend_ctr
        bend_ctr.custom_shape_along_length = 0.95

        # Create a visual helper line from the bend to the FK control's display positions.
        line = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org.name, "LINE-BEND"),
            source=bend_ctr,
            parent=bend_ctr,
            head=bend_ctr.head + bend_ctr.vector * 0.95,
            tail=bend_ctr.tail,
            custom_shape_name="Line",
            use_custom_shape_bone_size=True,
        )
        bend_ctr.collections = line.collections = self.bone_sets[
            'Stretch Controls'
        ].collections
        line.bbone_width *= 0.2
        line.hide_select = True

        line.add_constraint('STRETCH_TO', subtarget=first_fk.name, head_tail=1)

        # Make the tip control copy partial rotation of the bend control
        self.main_str_bones[-1].add_constraint(
            'COPY_ROTATION', subtarget=bend_ctr.name, influence=0.4
        )

    ##############################
    # No parameters for this rig type.


RIG_COMPONENT_CLASS = Component_Feather
