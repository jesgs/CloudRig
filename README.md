# Installing into [Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/introduction.html)

1. Download CloudRig for your desired Blender version from the [**Releases**](https://gitlab.com/blender/CloudRig/-/releases) page*.  
2. In Blender, open **Preferences->Addons->Rigify** and enable the addon. Rigify comes with Blender, so you don't need to download it.
3. In the Rigify addon preferences, click on **Rigify: External feature sets->Install Feature Set from File...** and browse the .zip you downloaded.

![](docs/featureset_load.gif)

**: If you like to live dangerously and are using the latest [Daily Blender](https://builder.blender.org/download/daily/), you can get the [latest commit of CloudRig](https://gitlab.com/blender/CloudRig/-/archive/master/CloudRig-master.zip) for maximum instability!*

# What is CloudRig?
CloudRig is a collection of customizable rig building blocks to extend the Rigify system. This feature set is being developed for and by the Blender Animation Studio, with the guidance of professional animators.

<details>
<summary>It is currently recommended not to mix CloudRig and Rigify elements.</summary>
To achive better compatibility, Rigify needs to catch-up, as it is outdated in many ways; bone organization systems and UX being the first ones. I am contributing to Rigify by pushing the best features of CloudRig upstream when I can, but it is a very slow process since Rigify has no full-time maintainers.
</details>

You can support the development of CloudRig by subscribing to the [Blender Cloud](https://cloud.blender.org/)!

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