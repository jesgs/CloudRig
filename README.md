# Installing into [Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/introduction.html)

1. Download CloudRig for your desired Blender version from the [**Releases**](https://gitlab.com/blender/CloudRig/-/releases) page. If there's no release for your version, use the download button in the top right of this page instead.
2. In Blender, open **Preferences->Addons->Rigify** and enable the addon. Rigify comes with Blender, so you don't need to download it.
3. In the Rigify addon preferences, click on **Rigify: External feature sets->Install Feature Set from File...** and browse the .zip you downloaded.

![](docs/featureset_load.gif)


# What is CloudRig?
CloudRig is a collection of customizable rig building blocks to extend the Rigify system. This feature set is being developed for and by the Blender Animation Studio, with the guidance of professional animators.

<details>
<summary>It is currently recommended not to mix CloudRig and Rigify elements.</summary>
Although technically possible and shouldn't cause any errors, the way core Rigify and CloudRig organize their bones and rig UI are quite different.
</details>

You can support the development of CloudRig by subscribing to the [Blender Studio](https://studio.blender.org/)!

# Getting Started
Add the pre-built human metarig via **Add->Armature->Cloud Humans -> Basic Human (Metarig)**.
Next, you can generate this rig via **Properties->Object Data->Rigify Buttons->Generate CloudRig**.
And bam, you have a rig!
![](docs/armature_generate.gif)

## Learning Resources
<ul>
<li>To learn how to actually customize the rig, you can check out the <a href="/../../../-/wikis/Home">wiki</a>.</li>
<li>The Blender Studio website hosts a <a href="https://studio.blender.org/training/blender-studio-rigging-tools/">video series</a> that covers most of what is on the wiki in video form. This is behind a paywall.</li>
<li>I have some <a href="https://www.youtube.com/watch?v=SB3qIbwvq8Y&list=PLav47HAVZMjnA3P7yQvneyQPiVxZ6erFS">live streams</a> of creating the rig for the free [Snow](https://studio.blender.org/characters/snow/v2/) character.
<li> <details><summary>Example Production Rigs (Click me)</summary>Since CloudRig is used to rig Blender Open Movie characters, and the resources of those movies are released to the public (sometimes behind a paywall, sometimes for free), there is a whole host of CloudRig character rigs available for you to download: 

#### Sprite Fright
- [Ellie](https://studio.blender.org/characters/ellie/)
- [Victoria](https://studio.blender.org/characters/victoria/)
- [Rex](https://studio.blender.org/characters/rex/)
- [Phil](https://studio.blender.org/characters/phil/)
- [Jay](https://studio.blender.org/characters/jay/)
- [Sprite](https://studio.blender.org/characters/sprite/)
- [Elder Sprite](https://studio.blender.org/characters/elder-sprite/)
- [Animals](https://studio.blender.org/characters/forest-animals/)

#### Settlers
- [Lunte](https://studio.blender.org/characters/lunte/)
- [Gabby](https://studio.blender.org/characters/gabby/)
- [Phileas](https://studio.blender.org/characters/phileas/)
- [Pip](https://studio.blender.org/characters/pip/)

</details></li>
</ul>





# Report problems
If you run into weird error messages or have suggestions on how something could be improved, feel free to [open an issue](/../issues/new?issuable_template=Bug).

# Contribute
Contributions are welcome! You may find some useful notes [here](/../../../-/wikis/Code)

# Show me your work!
If you use CloudRig in your project, I'd love to hear about it! Seeing people make use of my work, whether it's baby's first animation or some big production, is always a huge motivation and ego boost which I can always use. Chat me up on [blender.chat](https://blender.chat/direct/met) or Discord: Mets#3017!