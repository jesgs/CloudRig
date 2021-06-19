from typing import Tuple, List, Optional
import re

SEPARATORS = "-_."
PREFIX_SEPARATOR = "-"
SUFFIX_SEPARATOR = "."

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

	def make_name(self, prefixes=[], base="", suffixes=[]) -> str:
		return make_name(prefixes, base, suffixes)

	def slice_name(self, thing) -> Tuple[ List[str], str, List[str] ]:
		return slice_name(get_name(thing))

	def strip_trailing_numbers(self, thing) -> Tuple[str, str]:
		return strip_trailing_numbers(get_name(thing))

	def flipped_name(self, thing) -> str:
		return flip_name(get_name(thing))

	def combine_names(self, things) -> str:
		names = []
		for t in things:
			if hasattr(t, 'name'):
				names.append(t.name)
			else:
				names.append(str(t))

		return combine_bone_names(names)

	def side_is_left(self, thing) -> Optional[bool]:
		return side_is_left(get_name(thing))

	def add_prefix(self, thing, new_prefix) -> str:
		"""The most common case of making a bone name based on another one is to add a prefix to it."""
		name = get_name(thing)
		sliced_name = self.slice_name(name)
		sliced_name[0].append(new_prefix)
		return self.make_name(*sliced_name)

	def strip_org(self, thing):
		from rigify.utils.naming import strip_org
		name = get_name(thing)
		return strip_org(name)

def get_name(thing) -> str:
	if hasattr(thing, 'name'):
		return thing.name
	else:
		return str(thing)


def make_name(prefixes=[], base="", suffixes=[]) -> str:
	"""Make a name from a list of prefixes, a base, and a list of suffixes."""
	name = ""
	for pre in prefixes:
		if pre=="": continue
		name += pre + PREFIX_SEPARATOR
	name += base
	for suf in suffixes:
		if suf=="": continue
		name += SUFFIX_SEPARATOR + suf
	return name

def slice_name(name):
	"""Break up a name into its prefix, base, suffix components."""
	prefixes = name.split(PREFIX_SEPARATOR)[:-1]
	suffixes = name.split(SUFFIX_SEPARATOR)[1:]
	base = name.split(PREFIX_SEPARATOR)[-1].split(SUFFIX_SEPARATOR)[0]
	return [prefixes, base, suffixes]


def has_trailing_zeroes(thing):
	name = get_name(thing)
	regex = "\.[0-9][0-9][0-9]$"
	search = re.search(regex, name)
	return search != None

def strip_trailing_numbers(name) -> Tuple[str, str]:
	if "." in name:
		# Check if there are only digits after the last period
		slices = name.split(".")
		after_last_period = slices[-1]
		before_last_period = ".".join(slices[:-1])

		# If there are only digits after the last period, discard them
		if all([c in "0123456789" for c in after_last_period]):
			return before_last_period, "."+after_last_period

	return name, ""


def combine_bone_names(names) -> str:
	"""Combine multiple bone names into one."""

	### Combine bases
	bases_nonunique = [slice_name(n)[1] for n in names]
	bases = set(bases_nonunique)
	bases_cropped = list(bases)

	shortest_base = sorted(bases, key=lambda b: len(b))[0]	# Sort by length and pick the first one.

	base_start = ""
	# Don't repeat matching characters, eg. "Lip_Top1" and "Lip_Bot1" should combine into "Lip_Top1+Bot1" instead of "Lip_Top1+Lip_Bot1"
	for i, char in enumerate(shortest_base):
		matching=True
		for base in bases:
			if char!=base[i]:
				matching=False
				break
		if matching:
			base_start += char
			bases_cropped = [base[1:] for base in bases_cropped]
			i-=1
		else:
			break
	final_base = base_start
	for i, base in enumerate(sorted(bases_cropped)):
		if base!="":
			if i!=0:
				final_base += "+"
			final_base += base

	def combine_extensions(list_of_extensions: List[List[str]]) -> List[str]:
		"""Combine a list of suffixes or prefixes by removing duplicates
		and then removing matching side pairs.

		Eg. for the input ["Left", "Left", "Right", "STR", "STR", "I"]
		return ["STR", "I"].
		"""

		# Remove duplicates
		nonunique = [slice_name(n)[2] for n in names]
		unique: List[str] = []
		for extensions in list_of_extensions:
			for ext in extensions:
				if ext not in unique:
					unique.append(ext)

		# If matching pairs of side suffixes are in the suffix list, remove both.
		# For example, if L and R are both present, remove them.
		for ext in unique:
			flip_ext = flip_name(ext)
			if flip_ext != ext and flip_ext in unique:
				unique.remove(ext)
				unique.remove(flip_ext)

		return unique

	### Combine suffixes
	suffixes = combine_extensions([slice_name(n)[2] for n in names])

	### Combine prefixes
	prefixes = combine_extensions([slice_name(n)[0] for n in names])

	### Combine and return the result
	return make_name(prefixes, final_base, suffixes)


def get_side_lists(with_separators=False) -> Tuple[List[str], List[str], List[str]]:
	left = 				['left',  'Left',  'LEFT', 	'l', 	'L',]
	right_placehold = 	['*rgt*', '*Rgt*', '*RGT*', '*r*',	'*R*']
	right = 			['right', 'Right', 'RIGHT', 'r', 	'R']

	# If the name is longer than 2 characters, only swap side identifiers if they
	# are next to a separator.
	if with_separators:
		for l in [left, right_placehold, right]:
			l_copy = l[:]
			for side in l_copy:
				if len(side)<4:
					l.remove(side)
				for sep in SEPARATORS:
					l.append(side+sep)
					l.append(sep+side)

	return left, right_placehold, right

def flip_name(from_name, ignore_base=True, must_change=False) -> str:
	"""Turn a left-sided name into a right-sided one or vice versa.

	Based on BLI_string_flip_side_name:
	https://developer.blender.org/diffusion/B/browse/master/source/blender/blenlib/intern/string_utils.c

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
					name = name[len(side):]+opp_side
					break
				elif name.endswith(side):
					name = name[:-len(side)]+opp_side
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

	with_separators = len(stripped_name)>2
	left, right_placehold, right = get_side_lists(with_separators)
	flipped_name = flip_sides(left, right_placehold, stripped_name)
	flipped_name = flip_sides(right, left, flipped_name)
	flipped_name = flip_sides(right_placehold, right, flipped_name)

	# Re-add trailing digits (.###)
	new_name = flipped_name + number_suffix

	if must_change:
		assert new_name != from_name, "Failed to flip string: " + from_name

	return new_name

def side_is_left(name) -> Optional[bool]:
	"""Identify whether a name belongs to the left or right side or neither."""

	flipped_name = flip_name(name)
	if flipped_name==name: return None	# Return None to indicate neither side.

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