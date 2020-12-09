# What is CloudRig?
CloudRig is a collection of customizable rig building blocks that can be added to the [Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/introduction.html) Blender addon/rigging system. This feature set is being developed for and by the Blender Animation Studio, with the guidance of professional animators.

You can support this work by subscribing to the [Blender Cloud](https://cloud.blender.org/)!


# Installation

Download this repository as a .zip.
In Blender, open **Preferences->Addons->Rigify** and enable the addon. Rigify comes with Blender, so you don't need to download it.
In the Rigify addon preferences, click on **Rigify: External feature sets->Install Feature Set from File...** and browse the .zip you downloaded.

![](docs/featureset_load.gif)


<details>
<summary> Supported Blender versions: 2.92 and above. </summary>
CloudRig is currently being developed right alongside Blender, so it should always work on the latest daily experimental Blender build.

For previous versions of Blender going back to 2.81, see the [Releases](/../../../-/releases) page.
</details>


# Using CloudRig
The easiest way to get started is to add the pre-built human metarig via **Add->Armature->Cloud Humans -> Basic Human (Metarig)**.
Next, you can generate this rig via **Properties->Object Data->Rigify Buttons->Generate CloudRig**.
And bam, you have a rig!
![](docs/armature_generate.gif)

You can try moving around the bones in the Metarig in edit mode, and then generating again, to see the rig re-generated to the new proportions.

Using Rigify and CloudRig mostly consists of creating such a metarig yourself, with the proportions and features that suits your character's needs. To learn more on how to do that, check out the [wiki](/../../../-/wikis/Home)!

# Report problems
If you run into weird error messages or have suggestions on how something could be improved, feel free to [open an issue](/../issues/new?issuable_template=Bug).

# Contribute
Contributions are welcome! You may find some useful notes [here](/../../../-/wikis/Code)