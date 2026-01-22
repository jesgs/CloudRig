# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Any

import bpy
from bpy.types import Bone, EditBone, Object, PoseBone
from bpy.utils import flip_name as bpy_flip_name

SEPARATORS = " ._-"
PREFIX_SEPARATOR = "-"
SUFFIX_SEPARATOR = "."
SIDE_INDICATORS = [
    "L",
    "l",
    "Left",
    "left",
    "LEFT",
    "R",
    "r",
    "Right",
    "right",
    "RIGHT",
]


#################################
### Symmetry ###################
#################################

def flip_name(thing: Any) -> str:
    return bpy_flip_name(get_name(thing))


def get_side_lists(with_separators=False) -> tuple[list[str], list[str], list[str]]:
    left = [
        "left",
        "Left",
        "LEFT",
        "l",
        "L",
    ]
    right_placehold = ["*rgt*", "*Rgt*", "*RGT*", "*r*", "*R*"]
    right = ["right", "Right", "RIGHT", "r", "R"]

    # If the name is longer than 2 characters, only swap side identifiers if they
    # are next to a separator.
    if with_separators:
        for list_to_modify in [left, right_placehold, right]:
            list_copy = list_to_modify[:]
            for side in list_copy:
                if len(side) < 4:
                    list_to_modify.remove(side)
                for sep in SEPARATORS:
                    list_to_modify.append(side + sep)
                    list_to_modify.append(sep + side)

    return left, right_placehold, right


def side_is_left(thing: Any) -> bool | None:
    """Identify whether a name belongs to the left or right side or neither."""
    name = get_name(thing)

    flipped_name = flip_name(name)
    if flipped_name == name:
        return None  # Return None to indicate neither side.

    stripped_name, number_suffix = strip_trailing_numbers(name)

    def check_start_side(side_list, name):
        for side in side_list:
            if name.startswith(side):
                return True
        return False

    def check_end_side(side_list, name):
        for side in side_list:
            if name.endswith(side):
                return True
        return False

    left, right_placehold, right = get_side_lists(with_separators=True)

    is_left_prefix = check_start_side(left, stripped_name)
    is_left_suffix = check_end_side(left, stripped_name)

    is_right_prefix = check_start_side(right, stripped_name)
    is_right_suffix = check_end_side(right, stripped_name)

    # Prioritize suffix for determining the name's side.
    if is_left_suffix or is_right_suffix:
        return is_left_suffix

    # If no relevant suffix found, try prefix.
    if is_left_prefix or is_right_prefix:
        return is_left_prefix

    # If no relevant suffix or prefix found, try anywhere.
    any_left = any([side in name for side in left])
    any_right = any([side in name for side in right])
    if not any_left and not any_right:
        # If neither side found, return None.
        return None
    if any_left and not any_right:
        return True
    if any_right and not any_left:
        return False

    # If left and right were both found somewhere, I give up.
    return None


#################################
### Numbering ###################
#################################
# TODO: These functions are all over the place and should be unified.

def increment_name(thing: Any, increment=1, default_zfill=1) -> str:
    # Increment LAST number in the name.
    # Negative numbers will be clamped to 0.
    # Digit length will be preserved, so 10 will decrement to 09.
    # 99 will increment to 100, not 00.

    # If no number was found, one will be added at the end of the base name.
    # The length of this in digits is set with the `default_zfill` param.
    name = get_name(thing)

    numbers_in_name = re.findall(r"\d+", name)
    if not numbers_in_name:
        prefixes, base, suffixes = slice_name(name)
        base += str(max(0, increment)).zfill(default_zfill)
        return make_name(prefixes, base, suffixes)

    last = numbers_in_name[-1]
    incremented = str(max(0, int(last) + increment)).zfill(len(last))
    split = name.rsplit(last, 1)
    return incremented.join(split)


def strip_trailing_numbers(thing: Any) -> tuple[str, str]:
    name = get_name(thing)
    if "." in name:
        # Check if there are only digits after the last period
        slices = name.split(".")
        after_last_period = slices[-1]
        before_last_period = ".".join(slices[:-1])

        # If there are only digits after the last period, discard them
        if all([c in "0123456789" for c in after_last_period]):
            return before_last_period, "." + after_last_period

    return name, ""


def strip_blender_zeroes(thing: Any) -> str:
    name = get_name(thing)
    if len(name) < 5:
        return name

    if name[-4] == ".":
        try:
            int(name[-3:])
        except ValueError:
            return name
        return name[:-4]
    return name


def has_trailing_numbers(thing: Any) -> bool:
    """Use regex to test if an object or string has .001 ending."""
    name = get_name(thing)
    regex = r"\.[0-9]*$"
    search = re.search(regex, name)
    return search is not None


def get_blender_zeroes(thing: Any) -> str:
    # TODO: This currently assumes number is <1000.
    name = get_name(thing)
    if len(name) < 5:
        return ""

    if name[-4] == ".":
        try:
            int(name[-3:])
        except ValueError:
            return ""
        return name[-4:]
    return ""


#################################
### New Bones ###################
#################################

def get_name_parts(thing: Any) -> tuple[str, str, str, str]:
    """Return side_prefix, base, side_suffix, blender_zeroes.

    This tries to synergize with Blender's built-in name flipping logic, which
    means only ONE side indicator will be acknowledged, prioritizing prefixes.
    So, a bone name like "L-hand_right.R.001" is expected to return ("L-", "hand_right.R", "", ".001").
    """
    name = get_name(thing)
    blender_zeroes = get_blender_zeroes(name)
    if blender_zeroes:
        name = name[:-len(blender_zeroes)]
    prefix = ""
    suffix = ""
    possible_prefixes = ["l"+sep for sep in SEPARATORS] + ["r"+sep for sep in SEPARATORS] + ["left", "right"]
    for possible_prefix in possible_prefixes:
        if name.lower().startswith(possible_prefix):
            prefix = name[:len(possible_prefix)]
            name = name[len(possible_prefix):]
            break

    if not prefix:
        possible_suffixes = [sep+"l" for sep in SEPARATORS] + [sep+"r" for sep in SEPARATORS] + ["left", "right"]
        for possible_suffix in possible_suffixes:
            if name.lower().endswith(possible_suffix):
                suffix = name[-len(possible_suffix):]
                name = name[:-len(possible_suffix)]
                break

    if prefix.lower() in ("left", "right") and name[0] in SEPARATORS:
        # If a full-word side prefix is followed by a separator character,
        # include that in the prefix part.
        prefix += name[0]
        name = name[1:]

    return prefix, name, suffix, blender_zeroes


def prepend_base_name(thing: Any, addition: str) -> str:
    """Prepend a prefix to the name of a thing.
    Preserving any left/right side indicator in case the name starts with that.

    Eg. prepend_base_name("Left Leg.001", "Knee ") == "Left Knee Leg.001"
    """

    prefix, base, suffix, blender_zeroes = get_name_parts(thing)
    return prefix + addition + base + suffix + blender_zeroes


def suffix_base_name(thing: Any, addition: str) -> str:
    """Append a suffix to the name of a thing.
    Preserving any left/right side indicator and blender zeroes in case the name
    ends with those.

    Eg. suffix_base_name("Knee-left.001", "_01") == "Knee_01-left.001"
    """
    prefix, base, suffix, blender_zeroes = get_name_parts(thing)
    return prefix + base + addition + suffix + blender_zeroes


def add_prefix(thing: Any, new_prefix: str) -> str:
    return prepend_base_name(thing, new_prefix+PREFIX_SEPARATOR)


#################################
### Uniqueness ##################
#################################

def uniqify(thing: Any, collprop: list=None, strip_first=True, id=None) -> str:
    if not collprop:
        if isinstance(thing, PoseBone):
            collprop = thing.id_data.pose.bones
        elif isinstance(thing, Bone):
            collprop = thing.id_data.bones
        elif isinstance(thing, EditBone):
            collprop = thing.id_data.edit_bones
        elif isinstance(thing, Object):
            collprop = bpy.data.objects
        else:
            raise ValueError(f"Collprop must be passed for {thing}")
    name = get_name(thing)
    if strip_first:
        name = strip_blender_zeroes(name)
    while name in collprop:
        if collprop.get(name) == id:
            return name
        name = increment_name(name)
    return name


#################################
### Misc ########################
#################################


def get_name(thing: Any) -> str:
    """Return any PyObject's "name" attribute if it has one, else cast it to a string."""
    if type(thing) is str:
        return thing
    elif hasattr(thing, "name"):
        return thing.name
    elif "name" in thing:
        return thing["name"]
    else:
        return str(thing)


def combine_names(things: list[Any]) -> str:
    """Combine multiple bone names into one by:
    - Removing duplicate pre and suffixes
    - Cancelling out left/right suffixes
    - Combining name bases separated by "+" while ignoring duplicate matching characters
    - Limiting to a max of 59 characters
    Eg., "Lip_Upper.L" + "Lip_Lower.R" -> "Lip_Upper+Lower")
    """

    names = [get_name(thing) for thing in things]
    prefix = ""
    suffix = ""
    zeroes = ""

    sliced_names = [get_name_parts(n) for n in names]

    any_left = any([side_is_left(name) is True for name in names])
    any_right = any([side_is_left(name) is False for name in names])
    if any_left and any_right:
        # Discard all side indicators.
        new_names = []
        for name in names:
            prefix, base, suffix, zeroes = get_name_parts(name)
            new_names.append(base+zeroes)
        names = new_names
    elif any_left or any_right:
        for slices in sliced_names:
            if slices[0]:
                prefix = slices[0]
                break
            elif slices[2]:
                suffix = slices[2]
                break

    bases = list(set([s[1] for s in sliced_names]))

    ### Combine bases
    # Sort by length and pick the first one.
    shortest_base = sorted(bases, key=lambda b: len(b))[0]

    base_start = ""
    # Don't repeat matching characters, eg. "Lip_Top1" and "Lip_Bot1" should combine
    # into "Lip_Top1+Bot1" instead of "Lip_Top1+Lip_Bot1"
    for i, char in enumerate(shortest_base):
        matching = all([base[i] == char for base in bases])
        if matching:
            base_start += char
            continue
        else:
            break

    # Make sure total name length doesn't exceed 59 characters.
    bases = [base[len(base_start) :] for base in bases]

    bases.sort(reverse=True)

    combined_name = prefix + base_start + "+".join(bases) + suffix

    if len(combined_name) > 59:
        raise ValueError(
            f'Intersection control bone name "{combined_name}" would be too long. Try using shorter bone names for face chain bones'
        )

    return combined_name


#################################
### DEPRECATED FUNCTIONS ########
#################################
# TODO: These functions should no longer be used and should be removed,
# because it relies on too many assumptions, leading to a strict
# bone naming convention requirement.

def make_name(prefixes: list[str] = [], base="", suffixes: list[str] = []) -> str:
    """Make a name from a list of prefixes, a base, and a list of suffixes."""
    name = ""
    if type(prefixes) is str:
        prefixes = [prefixes]
    if type(suffixes) is str:
        suffixes = [suffixes]

    for pre in prefixes:
        if pre == "":
            continue
        name += pre + PREFIX_SEPARATOR
    name += base
    for suf in suffixes:
        if suf == "":
            continue
        name += SUFFIX_SEPARATOR + suf

    return name


def slice_name(thing: Any):
    """Break up a name into its prefix, base, suffix components."""
    name = get_name(thing)
    prefixes = name.split(PREFIX_SEPARATOR)[:-1]
    suffixes = name.split(SUFFIX_SEPARATOR)[1:]
    base = name.split(PREFIX_SEPARATOR)[-1].split(SUFFIX_SEPARATOR)[0]
    if not suffixes and "_" in base:
        # Support underscore as a suffix separator, only for side indicators.
        suffix = name.split("_")[-1]
        if suffix in SIDE_INDICATORS:
            suffixes = [suffix]
            base = base.replace("_" + suffix, "")
    return [prefixes, base, suffixes]
