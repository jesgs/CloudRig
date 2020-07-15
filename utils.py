import bpy
from mathutils import Vector
from math import atan2
from .rigs.cloud_utils import slice_name, make_name

def bounding_box(points):
	"""Return two vectors representing the lowest and highest coordinates of a the bounding box of the passed points."""

	lowest = points[0].copy()
	highest = points[0].copy()
	for p in points:
		for i in range(len(p)):
			if p[i] < lowest[i]:
				lowest[i] = p[i]
			if p[i] > highest[i]:
				highest[i] = p[i]
	
	return lowest, highest

def bounding_box_center(points):
    """Find the bounding box center of some points."""
    bbox_low, bbox_high = bounding_box(points)
    return bbox_low + (bbox_high-bbox_low)/2

def scale_points_from_center(points, scale):
	"""Scale some points from their bounding box center."""
	center = bounding_box_center(points)
	new_points = []
	for p in points:
		new_points.append(
			center + (center-p) * (scale)
		)
	return new_points

def project_points_on_plane (points, projection_axis):
	# Find two vectors(ie. a plane) that are perpendicular to the projection axis.
	projection_direction = projection_axis.normalized()
	plane_x = projection_direction.cross(Vector((0, 0, 1)))
	plane_y = projection_direction.cross(plane_x)

	projected_points = []
	points_sum = Vector()
	for point in points:
		points_sum += point

	points_center = bounding_box_center(points)

	bpy.context.scene.cursor.location = points_center

	for point in points:
		center_relative = point - points_center
		projected_point = Vector((center_relative.dot(plane_x), center_relative.dot(plane_y), 0))
		
		angle_from_axis = atan2(
            projected_point.x - plane_y.x,
            projected_point.y - plane_y.y
        )

		projected_points.append((projected_point, angle_from_axis))

	# Sort points by their angle from the projection axis
	projected_points.sort(key=lambda x: x[1])

	return [p[0] for p in projected_points]

left = 				['left',  'Left',  'LEFT', 	'.l', 	  '.L', 		'_l', 				'_L',				'-l',	   '-L', 	'l.', 	   'L.',	'l_', 			 'L_', 			  'l-', 	'L-']
right_placehold = 	['*rgt*', '*Rgt*', '*RGT*', '*dotl*', '*dotL*', 	'*underscorel*', 	'*underscoreL*', 	'*dashl*', '*dashL', '*ldot*', '*Ldot', '*lunderscore*', '*Lunderscore*', '*ldash*','*Ldash*']
right = 			['right', 'Right', 'RIGHT', '.r', 	  '.R', 		'_r', 				'_R',				'-r',	   '-R', 	'r.', 	   'R.',	'r_', 			 'R_', 			  'r-', 	'R-']

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