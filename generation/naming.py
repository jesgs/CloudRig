from typing import Any
import re

SEPARATORS = "._-"
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


class CloudNameManager:
    """Name management utilities with the convenience of being able to pass in
    anything that has a "name" attribute, or strings directly.
    """

    prefix_separator = PREFIX_SEPARATOR
    suffix_separator = SUFFIX_SEPARATOR

    def get_name(self, thing):
        return get_name(thing)

    def has_trailing_zeroes(self, thing):
        return has_trailing_zeroes(thing)

    def has_wrong_separator(self, thing):
        return has_wrong_separator(thing)

    def side_is_suffix(self, thing):
        return side_is_suffix(thing)

    def make_name(self, prefixes=[], base="", suffixes=[]) -> str:
        return make_name(prefixes, base, suffixes)

    def slice_name(self, thing) -> tuple[list[str], str, list[str]]:
        return slice_name(get_name(thing))

    def strip_trailing_numbers(self, thing) -> tuple[str, str]:
        return strip_trailing_numbers(get_name(thing))

    def flipped_name(self, thing) -> str:
        return flip_name(get_name(thing))

    def combine_names(self, things) -> str:
        names = []
        for thing in things:
            names.append(get_name(thing))

        return combine_bone_names(names)

    def side_is_left(self, thing) -> bool | None:
        return side_is_left(get_name(thing))

    def increment_name(self, thing, increment=1) -> str:
        name = get_name(thing)
        return increment_name(name, increment)

    def add_prefix(self, thing, new_prefix) -> str:
        """The most common case of making a bone name based on another one is to add a prefix to it."""
        name = get_name(thing)
        sliced_name = self.slice_name(name)
        sliced_name[0].append(new_prefix)
        return self.make_name(*sliced_name)


def get_name(thing: Any) -> str:
    """Return any PyObject's "name" attribute if it has one, else cast it to a string."""
    if hasattr(thing, 'name'):
        return thing.name
    else:
        return str(thing)


def make_name(prefixes=[], base="", suffixes=[]) -> str:
    """Make a name from a list of prefixes, a base, and a list of suffixes."""
    name = ""
    if type(prefixes) == str:
        prefixes = [prefixes]
    if type(suffixes) == str:
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


def slice_name(name: str):
    """Break up a name into its prefix, base, suffix components."""
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


def has_trailing_zeroes(thing: Any) -> bool:
    """Use regex to test if an object or string has .001 ending."""
    name = get_name(thing)
    regex = "\.[0-9]*$"
    search = re.search(regex, name)
    return search != None


def has_wrong_separator(thing: Any) -> bool:
    name = get_name(thing)

    for separator in ".-_":
        if separator not in name:
            continue
        split = name.split(separator)
        for s in split:
            if s in SIDE_INDICATORS:
                if separator != ".":
                    return True
    return False


def side_is_suffix(thing: Any) -> bool:
    """Return True when the name of a thing either does not contain a side indicator,
    or the side indicator is at the end of the name."""
    name = get_name(thing)

    for separator in SEPARATORS:
        if separator not in name:
            continue
        split = name.split(separator)
        for s in split:
            if s in SIDE_INDICATORS and s != split[-1]:
                return False

    return True


def strip_trailing_numbers(name: str) -> tuple[str, str]:
    if "." in name:
        # Check if there are only digits after the last period
        slices = name.split(".")
        after_last_period = slices[-1]
        before_last_period = ".".join(slices[:-1])

        # If there are only digits after the last period, discard them
        if all([c in "0123456789" for c in after_last_period]):
            return before_last_period, "." + after_last_period

    return name, ""


def combine_bone_names(names: str) -> str:
    """Combine multiple bone names into one by:
    - Removing duplicate pre and suffixes
    - Cancelling out left/right suffixes
    - Combining name bases separated by "+" while ignoring duplicate matching characters
    - Limiting to a max of 59 characters
    Eg., "Lip_Upper.L" + "Lip_Lower.R" -> "Lip_Upper+Lower")
    """

    slices = [slice_name(n) for n in names]

    prefixes = []
    for slice in slices:
        for prefix in slice[0]:
            if prefix not in prefixes:
                prefixes.append(prefix)

    suffixes = []
    for slice in slices:
        for suffix in slice[2]:
            if suffix not in suffixes:
                suffixes.append(suffix)

    bases = list(set([s[1] for s in slices]))

    # If matching pairs of side suffixes are in the suffix list, remove both.
    # For example, if L and R are both present, remove them.
    for suf in suffixes:
        flip_suf = flip_name(suf)
        if flip_suf != suf and flip_suf in suffixes:
            suffixes.remove(suf)
            suffixes.remove(flip_suf)

    ### Combine bases
    shortest_base = sorted(bases, key=lambda b: len(b))[
        0
    ]  # Sort by length and pick the first one.

    base_start = ""
    # Don't repeat matching characters, eg. "Lip_Top1" and "Lip_Bot1" should combine into "Lip_Top1+Bot1" instead of "Lip_Top1+Lip_Bot1"
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

    combined_name = make_name(prefixes, base_start + "+".join(bases), suffixes)

    if len(combined_name) > 59:
        raise ValueError(
            f'Intersection control bone name "{combined_name}" would be too long. Try using shorter bone names for face chain bones'
        )

    return combined_name


def get_side_lists(with_separators=False) -> tuple[list[str], list[str], list[str]]:
    left = [
        'left',
        'Left',
        'LEFT',
        'l',
        'L',
    ]
    right_placehold = ['*rgt*', '*Rgt*', '*RGT*', '*r*', '*R*']
    right = ['right', 'Right', 'RIGHT', 'r', 'R']

    # If the name is longer than 2 characters, only swap side identifiers if they
    # are next to a separator.
    if with_separators:
        for l in [left, right_placehold, right]:
            l_copy = l[:]
            for side in l_copy:
                if len(side) < 4:
                    l.remove(side)
                for sep in SEPARATORS:
                    l.append(side + sep)
                    l.append(sep + side)

    return left, right_placehold, right


def flip_name(from_name: str, ignore_base=True, must_change=False) -> str:
    """Turn a left-sided name into a right-sided one or vice versa.

    Based on BLI_string_flip_side_name:
    https://projects.blender.org/blender/blender/src/branch/main/source/blender/blenlib/intern/string_utils.c

    ignore_base: When True, ignore occurrences of side hints unless they're in
                             the beginning or end of the name string.
    must_change: When True, raise an error if the name couldn't be flipped.
    """

    # Handling .### cases
    stripped_name, number_suffix = strip_trailing_numbers(from_name)

    def flip_sides(list_from, list_to, name):
        for side_idx, side in enumerate(list_from):
            opp_side = list_to[side_idx]
            if ignore_base:
                # Only look at prefix/suffix.
                if name.startswith(side):
                    name = name[len(side) :] + opp_side
                    break
                elif name.endswith(side):
                    name = name[: -len(side)] + opp_side
                    break
            else:
                # When it comes to searching the middle of a string,
                # sides must strictly be a full word or separated with "."
                # otherwise we would catch stuff like "_leg" and turn it into "_reg".
                if not any([char not in side for char in "-_."]):
                    # Replace all occurences and continue checking for keywords.
                    name = name.replace(side, opp_side)
                    continue
        return name

    with_separators = len(stripped_name) > 2
    left, right_placehold, right = get_side_lists(with_separators)
    flipped_name = flip_sides(left, right_placehold, stripped_name)
    flipped_name = flip_sides(right, left, flipped_name)
    flipped_name = flip_sides(right_placehold, right, flipped_name)

    # Re-add trailing digits (.###)
    new_name = flipped_name + number_suffix

    if must_change:
        assert new_name != from_name, "Failed to flip string: " + from_name

    return new_name


def side_is_left(name) -> bool | None:
    """Identify whether a name belongs to the left or right side or neither."""

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


def increment_name(name: str, increment=1, default_zfill=1) -> str:
    # Increment LAST number in the name.
    # Negative numbers will be clamped to 0.
    # Digit length will be preserved, so 10 will decrement to 09.
    # 99 will increment to 100, not 00.

    # If no number was found, one will be added at the end of the base name.
    # The length of this in digits is set with the `default_zfill` param.

    numbers_in_name = re.findall(r'\d+', name)
    if not numbers_in_name:
        prefixes, base, suffixes = slice_name(name)
        base += str(max(0, increment)).zfill(default_zfill)
        return make_name(prefixes, base, suffixes)

    last = numbers_in_name[-1]
    incremented = str(max(0, int(last) + increment)).zfill(len(last))
    split = name.rsplit(last, 1)
    return incremented.join(split)


def strip_blender_zeroes(name):
    if name[-4] == ".":
        try:
            int(name[-3:])
        except:
            return name
        return name[:-4]
    return name


def uniqify(name, collprop: list, strip_first=True):
    if strip_first:
        name = strip_blender_zeroes(name)
    while name in collprop:
        name = increment_name(name)
    return name
