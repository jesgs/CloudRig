left = 				['left',  'Left',  'LEFT', 	'.l', 	  '.L', 		'_l', 				'_L',				'-l',	   '-L', 	'l.', 	   'L.',	'l_', 			 'L_', 			  'l-', 	'L-']
right_placehold = 	['*rgt*', '*Rgt*', '*RGT*', '*dotl*', '*dotL*', 	'*underscorel*', 	'*underscoreL*', 	'*dashl*', '*dashL', '*ldot*', '*Ldot', '*lunderscore*', '*Lunderscore*', '*ldash*','*Ldash*']
right = 			['right', 'Right', 'RIGHT', '.r', 	  '.R', 		'_r', 				'_R',				'-r',	   '-R', 	'r.', 	   'R.',	'r_', 			 'R_', 			  'r-', 	'R-']

def get_name(thing):
	if hasattr(thing, 'name'):
		return thing.name
	else:
		return str(thing)

class CloudNamingUtilitiesMixin:
	"""Name management utilities with the convenience of being able to pass in anything that has a "name" attribute, or strings directly."""

	def get_separators(self) -> (str, str):
		prefix_separator = "-"
		suffix_separator = "."
		if hasattr(self, 'generator'):
			if hasattr(self.generator, 'prefix_separator'):
				prefix_separator = self.generator.prefix_separator
			if hasattr(self.generator, 'suffix_separator'):
				suffix_separator = self.generator.suffix_separator

		return (prefix_separator, suffix_separator)
	
	def make_name(self, prefixes=[], base="", suffixes=[]) -> str:
		prefix_separator, suffix_separator = self.get_separators()
		return make_name(prefixes, base, suffixes, prefix_separator, suffix_separator)

	def slice_name(self, thing) -> ([str], str, [str]):
		prefix_separator, suffix_separator = self.get_separators()
		name = get_name(thing)

		return slice_name(name, prefix_separator, suffix_separator)

	def strip_trailing_numbers(self, thing) -> str:
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

	def side_is_left(self, thing) -> bool or None:
		return name_side_is_left(get_name(thing))

def make_name(prefixes=[], base="", suffixes=[], prefix_separator="-", suffix_separator="."):
	# In our naming convention, prefixes are separated by dashes and suffixes by periods, eg: DSP-FK-UpperArm_Parent.L.001
	name = ""
	for pre in prefixes:
		if pre=="": continue
		name += pre + prefix_separator
	name += base
	for suf in suffixes:
		if suf=="": continue
		name += suffix_separator + suf
	return name

def slice_name(name, prefix_separator="-", suffix_separator="."):
	prefixes = name.split(prefix_separator)[:-1]
	suffixes = name.split(suffix_separator)[1:]
	base = name.split(prefix_separator)[-1].split(suffix_separator)[0]
	return [prefixes, base, suffixes]

def strip_trailing_numbers(name):
	if "." in name:
		# Check if there are only digits after the last period
		slices = name.split(".")
		after_last_period = slices[-1]
		before_last_period = ".".join(slices[:-1])

		# If there are only digits after the last period, discard them
		if all([c in "0123456789" for c in after_last_period]):
			return before_last_period, "."+after_last_period

	return name, ""

def flip_name(from_name, ignore_base=True, must_change=False):
	# based on BLI_string_flip_side_name in https://developer.blender.org/diffusion/B/browse/master/source/blender/blenlib/intern/string_utils.c
	# If ignore_base==True, ignore occurrences of side hints unless they're in the beginning or end of the name string.
	# if must_change==True, raise an error if the string couldn't be flipped.

	# Handling .### cases
	stripped_name, number_suffix = strip_trailing_numbers(from_name)

	def flip_sides(list_from, list_to, name):
		for side_idx, side in enumerate(list_from):
			opp_side = list_to[side_idx]
			if(ignore_base):
				# Only look at prefix/suffix.
				if(name.startswith(side)):
					name = name[len(side):]+opp_side
					break
				elif(name.endswith(side)):
					name = name[:-len(side)]+opp_side
					break
			else:
				if not any([char not in side for char in "-_."]):	# When it comes to searching the middle of a string, sides must Strictly a full word or separated with . otherwise we would catch stuff like "_leg" and turn it into "_reg".
					# Replace all occurences and continue checking for keywords.
					name = name.replace(side, opp_side)
					continue
		return name
	
	flipped_name = flip_sides(left, right_placehold, stripped_name)
	flipped_name = flip_sides(right, left, flipped_name)
	flipped_name = flip_sides(right_placehold, right, flipped_name)
	
	# Re-add trailing digits (.###)
	new_name = flipped_name + number_suffix

	if(must_change):
		assert new_name != from_name, "Failed to flip string: " + from_name
	
	return new_name

def combine_bone_names(rig, names):
	"""Combine multiple bone names into one."""
	# This is the most terrible code I have ever written.

	side_suf = rig.generator.suffix_separator + rig.side_suffix
	side_pref = rig.side_prefix + rig.generator.prefix_separator

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
	for i, base in enumerate(bases_cropped):
		if base!="":
			if i!=0:
				final_base += "+"
			final_base += base

	### Combine suffixes
	suffixes_nonunique = [slice_name(n)[2] for n in names]
	suffixes = []
	for suf_list in suffixes_nonunique:
		for suf in suf_list:
			if suf not in suffixes:
				suffixes.append(suf)

	opp_suf = flip_name(side_suf)
	if side_suf[1:] in suffixes and opp_suf[1:] in suffixes:
		suffixes = [suf for suf in suffixes if suf not in (side_suf[1:], opp_suf[1:])]

	### Combine prefixes
	prefixes_nonunique = [slice_name(n)[0] for n in names]
	prefixes = []
	for pre_list in prefixes_nonunique:
		for pre in pre_list:
			if pre not in prefixes:
				prefixes.append(pre)
	# If the prefixes contain both side prefixes, remove both!
	opp_pre = flip_name(side_pref)
	if side_pref[:-1] in prefixes and opp_pre[:-1] in prefixes:
		prefixes = [pre for pre in prefixes if pre not in (side_pref[:-1], opp_pre[:-1])]

	### Combine and return the result
	return make_name(prefixes, final_base, suffixes)

def name_side_is_left(name):
	"""Identify whether a name belongs to the left or right side or neither."""

	flipped_name = flip_name(name)
	if flipped_name==name: return	# Return None to indicate neither side.

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
	any_right = any([side in name for side in left])
	if any_left and not any_right:
		return True
	if any_right and not any_left:
		return False

	# If left and right were both found somewhere, I give up.
	return None