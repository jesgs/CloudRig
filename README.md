## What is CloudRig?
CloudRig is a rig generation [extension](https://extensions.blender.org/add-ons/cloudrig/) for Blender, developed by the Blender Studio for our Open Movies.

You can support the development of CloudRig by [becoming a Blender Studio subscriber](https://studio.blender.org/)!

## Installation
You can install directly from within Blender, by searching for CloudRig inside the "Get Extensions" panel.

<details>
<summary><b>Bleeding Edge / Git Clone</b></summary>

To clone the repo, you must pass --recurse-submodules:  

`git clone --recurse-submodules git@git.blender.org:Mets/CloudRig.git`

Also, downloading the repo as a .zip will not work, as that will not include submodules.  
Then, you can symlink it to a folder which you've browsed in Blender as a local extension repository folder, or into your `user_default` extensions folder.
</details>

## Getting Started
Add the pre-built human metarig via **Add->Armature->CloudRig MetaRigs->Cloud Human**.
Generate the rig via **Properties->Object Data->CloudRig->Generate CloudRig**.
And bam, you have a rig!  

<video controls src="docs/metarig_generate.mp4" title="Spawning the basic human metarig and generating it"></video>

## Learning Resources
<ul>
<li>Check out the <a href="https://studio.blender.org/pipeline/addons/cloudrig/introduction">wiki</a>!</li>
<li>For Blender 3.6 and below, check out my old <a href="https://studio.blender.org/training/blender-studio-rigging-tools/">video documentation series</a>. (for Studio supporters)</li>
<li>I have some <a href="https://www.youtube.com/watch?v=SB3qIbwvq8Y&list=PLav47HAVZMjnA3P7yQvneyQPiVxZ6erFS">live streams</a> of creating the rig for the free <a href="https://studio.blender.org/characters/snow/">Snow</a> character.
<li> <details><summary>Example Production Rigs</summary>Since CloudRig is used to rig Blender Open Movie characters, and the resources of those movies are released to the public (sometimes for supporters, sometimes for everyone), there is a whole host of CloudRig character rigs available for you to download: 

- [Snow](https://studio.blender.org/characters/snow/) (Blender 4.1-4.5)
- [Storm](https://studio.blender.org/characters/storm/) (Blender 5.0. CloudRig only used for body rig.)

#### [Wing It!](https://www.youtube.com/watch?v=u9lj-c29dxI) (Blender 3.6)
- [Dog](https://studio.blender.org/characters/dog/)
- [Cat](https://studio.blender.org/characters/cat/)
- [Chicken & Sets](https://studio.blender.org/characters/wing-it-misc/)

#### [Charge](https://www.youtube.com/watch?v=UXqq0ZvbOnk) (Blender 3.5 - 3.6)
- [Einar](https://studio.blender.org/characters/einar/)

#### [Sprite Fright](https://www.youtube.com/watch?v=_cMxraX_5RE) (Blender 3.3 - 3.6)
- [Ellie](https://studio.blender.org/characters/ellie/)
- [Victoria](https://studio.blender.org/characters/victoria/)
- [Rex](https://studio.blender.org/characters/rex/)
- [Phil](https://studio.blender.org/characters/phil/)
- [Jay](https://studio.blender.org/characters/jay/)
- [Sprite](https://studio.blender.org/characters/sprite/)
- [Elder Sprite](https://studio.blender.org/characters/elder-sprite/)
- [Animals](https://studio.blender.org/characters/forest-animals/)

#### [Settlers](https://studio.blender.org/films/settlers/) (Blender 3.0 - 3.6)
- [Lunte](https://studio.blender.org/characters/lunte/)
- [Gabby](https://studio.blender.org/characters/gabby/)
- [Phileas](https://studio.blender.org/characters/phileas/)
- [Pip](https://studio.blender.org/characters/pip/)

</details></li>
</ul>

## Report problems
If you encounter a bug or have a suggestion, feel free to [open an issue](../../../issues/new).

## Contribute
Contributions are welcome! You may find some useful notes [here](https://studio.blender.org/tools/addons/cloudrig/code)

## Show me your work!
Seeing people use CloudRig is always a huge motivation boost! Whether it's baby's first animation or some big production, it doesn't matter. Chat me up on [chat.blender.org](https://chat.blender.org/#/room/#CloudRig:blender.org) or add `metemer` on Discord!