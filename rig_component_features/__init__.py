from . import parenting, bone_set, custom_props

modules = [
	parenting,
	bone_set
]

# Dictionary of modules that have a Params class, and want to register
# parameters.
component_feature_modules = {
	'parenting' : parenting,
	'custom_props' : custom_props,
}