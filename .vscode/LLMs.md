# LLMs.md

LLMs can be pointed at this file for quick instructions about the project.

## CloudRig

CloudRig is a Blender add-on for procedural rig generation from metarigs. It targets Blender 5.0+. Users author a "metarig" (an armature with bones named and configured according to CloudRig conventions), and the generator produces a fully-rigged character armature from it.

### Running Tests

For information on running tests, see `tests/ReadMe.md`.
Specifically, `test_codebase.py` and `test_codebase_cloudrig.py` are nice cheap tests to run to ensure adherence to code quality requirements.

## Code Style

- Make function & variable names descriptive and accurate.
- Be extra careful about making any potentially semantically significant changes that may seem like typo fixes, like changing an `if something` to `if something is not None`. If you do, explain why, and check callsites to verify logic doesn't break. If you're not confident, then don't do it.
- After making code changes, the linter will often have outdated warnings, as they are too slow. Ignore these.
- Avoid single-letter variable names except maybe `for i in range()` or similar ultra obvious cases.
- You may rename variables, but do not rename functions without asking.
- Flag longer functions for splitting up.
- Inner functions are acceptable.
- Code order should be high level code at the top (menus, then operators), helper functions underneath, and registration at the bottom. If this is not the case, do not fix it yourself, only flag it.
- Seek out opportunities for re-using code.
- Keep license headers consistent.
- Flag if you sense a mix-up of floats/ints, so when a `0` should be `0.0`.
- See also `pyproject.toml` and `.vscode/settings.json`.

#### Type Annotations
- All function parameters without default values must have type annotations.
    - But don't be stupid about it, this obviously excludes `self` and `cls`.
    - A default value of an empty list or None should still have type annotation.
- All functions that can return a non-None value must have return type annotations except `execute`, `invoke`, `poll`.
- Type annotations should be short, so `context: Context` instead of `context: bpy.types.Context`.
- Unused function variable names should always start with _, and still be type annotated.

#### Comments & Docstrings
- Avoid inserting comments that tell linters to ignore errors. Instead, notify the user about the linter's complaints, so user can decide what to do.
- Do NOT add docstrings for small functions that are aptly named.
- Flag comments you deem unnecessary, but NEVER remove existing comments out right.
- NEVER remove existing docstrings or comments. If a comment you inserted may have caused a pre-existing comment to become redundant, flag it.
- You may fix typos, also in variable names, but be sure to check scope. If scope is too big, flag the typo instead.
- You may suggest improved wording for docstrings, if you find it really necessary.
- Add missing docstrings to functions that are complex enough to warrant it. Use your best judgement.
- Avoid docstrings for rig component functions whose name starts with `draw`, or is `__init__` or `is_bone_set_used`.
- Avoid docstrings that are just a rewording of the function name!

#### Translatability

Most issues with translatability will be pointed out by tests, but for some cases we rely on LLM detection:
- Point out strings that look like they should be surrounded by a translation function, but aren't. This can happen when a string is first saved to a variable, before being sent to the UI.
- **Strings passed directly to native Blender functions do NOT need to be translated**.

## Architecture

### Generation Flow

1. User builds a **metarig** — an armature with bones named/configured per CloudRig conventions
2. `cloud_generator.py` (`CloudRig_Generator`) reads the metarig, instantiates components assigned to PoseBones by the user.
3. Each component's `create_bone_infos()` declares the bone structure using `BoneInfo` objects. These are essentially CloudRig's virtual bones, an abstraction layer. No Blender API calls yet.
4. Later generation steps convert real Blender bones (with constraints, drivers, and parenting) based on all BoneInfos prepared by the component instances.
5. Post-generation script runs, then `CloudLogManager` (in `troubleshooting.py`) sweeps the generated rig, searching for additional warnings/errors.

### Component System (`rig_components/`)

All rig components inherit from `Component_Base` (`cloud_base.py`). Each file exports a `RIG_COMPONENT_CLASS` variable and is dynamically loaded by `load_components()`. Component parameters are `bpy.props` PropertyGroups with update callbacks that dirty the Rig Preview Overlay (`overlay_painter.py`).

Mixins in `rig_component_features/` provide shared behaviour:
- `BoneSetMixin` — groups bones into sets with shared collection assignments and bone colors, which can be customized by the user.
- `CloudMechanismMixin` — driver and constraint helpers
- `CloudUIMixin` — parameter panel rendering
- `ParentingMixin` — parent-switching rig set-ups

### Registration (`__init__.py`)

The root `__init__.py` calls `recursive_register()` which searches the modules recursively for `registry` list of registerable classes and/or a `modules` list of sub-modules. Registration order can be load-order-sensitive, see code comments.

### Submodule

`blender_studio_utils/` (`bs_utils/`) is a git submodule shared across Blender Studio add-ons. Edit with care — changes affect other projects.

### cloudrig.py

`generation/cloudrig.py` is a large file which cannot be split up because it contains all the code which ships with any generated CloudRig rig. This script must be able to execute in Blender's text editor **without CloudRig installed**, ie. without any naive relative imports.
