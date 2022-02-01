# Installing into [Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/introduction.html)

1. Download CloudRig for your desired Blender version from the [**Releases**](https://gitlab.com/blender/CloudRig/-/releases) page.  
*If you want to go experimental and are using the [latest Alpha](https://builder.blender.org/download/daily/) version of Blender, then you should instead download the [latest commit of CloudRig](https://gitlab.com/blender/CloudRig/-/archive/master/CloudRig-master.zip) and hope for the best!*  
2. In Blender, open **Preferences->Addons->Rigify** and enable the addon. Rigify comes with Blender, so you don't need to download it.
3. In the Rigify addon preferences, click on **Rigify: External feature sets->Install Feature Set from File...** and browse the .zip you downloaded.

![](docs/featureset_load.gif)


# What is CloudRig?
CloudRig is a collection of customizable rig building blocks to extend the Rigify system. This feature set is being developed for and by the Blender Animation Studio, with the guidance of professional animators.

<details>
<summary>It is currently recommended not to mix CloudRig and Rigify elements.</summary>
To achive better compatibility, Rigify needs to catch-up, as it is outdated in many ways; bone organization systems and UX being the first ones. I am contributing to Rigify by pushing the best features of CloudRig upstream when I can, but it is a very slow process since Rigify has no full-time maintainers.
</details>

You can support the development of CloudRig by subscribing to the [Blender Studio](https://studio.blender.org/)!

# Using CloudRig
The easiest way to get started is to add the pre-built human metarig via **Add->Armature->Cloud Humans -> Basic Human (Metarig)**.
Next, you can generate this rig via **Properties->Object Data->Rigify Buttons->Generate CloudRig**.
And bam, you have a rig!
![](docs/armature_generate.gif)

To learn how to actually customize the rig, you can check out the [wiki](/../../../-/wikis/Home) or [this video series on the Blender Studio Website](https://studio.blender.org/training/blender-studio-rigging-tools/).

# Examples
For examples of characters rigged with CloudRig, check out the [Sprite Fright](https://studio.blender.org/characters/) and [Settlers](https://studio.blender.org/films/settlers/5e8f16fd9e1df355918c30e9/) characters.

# Report problems
If you run into weird error messages or have suggestions on how something could be improved, feel free to [open an issue](/../issues/new?issuable_template=Bug).

# Contribute
Contributions are welcome! You may find some useful notes [here](/../../../-/wikis/Code)

# Show me your work!
If you use CloudRig in your project, I'd love to hear about it! Seeing people make use of my work, whether it's baby's first animation or some big production, is always a huge motivation and ego boost which I can always use. Chat me up on [blender.chat](https://blender.chat/direct/met) or Discord: Mets#3017!