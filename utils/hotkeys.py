from bpy.types import KeyMap, KeyMapItem

def find_matching_km_and_kmi(context, target_kc, src_km, src_kmi) -> tuple[KeyMap or None, KeyMapItem or None]:
    target_km = find_matching_keymap(context, target_kc, src_km)
    if not target_km:
        raise Exception(f"Failed to find KeyMap '{src_km.name}' in KeyConfig '{target_kc.name}'")
    kc_user = context.window_manager.keyconfigs.user
    # If we want to find a matching User KeyMapItem, that's easy, because that's what the API was meant for.
    if target_kc == kc_user:
        return target_km, target_km.keymap_items.find_match(src_km, src_kmi)

    user_km, user_kmi = src_km, src_kmi
    # If we want to find any other type of KeyMapItem, we have to do it indirectly, since we can only directly check for matches in the User KeyConfig.
    # So eg. if we want to find an Addon KeyMapItem based on a User KeyMapItem, we have to loop over all Addon KeyMapItems, and find which one matches with the given User KeyMapItem.
    for target_kmi in target_km.keymap_items:
        match = user_km.keymap_items.find_match(target_km, target_kmi)
        if match == src_kmi:
            return target_km, target_kmi
    
    # raise Exception(f"Failed to find KeyMapItem '{src_kmi.idname}' ({src_kmi.to_string()}) in KeyConfig '{target_kc.name}', KeyMap '{target_km.name}'")
    # We will return here eg. when looking for an add-on keymap in the default keyconfig.
    return None, None

def find_matching_keymap(context, target_kc, src_km):
    """Find the equivalent keymap in another keyconfig."""
    
    kc_user = context.window_manager.keyconfigs.user

    # If we want to find a matching User KeyMap, that's easy, because that's what the API was meant for.
    if target_kc == kc_user:
        match = target_kc.keymaps.find_match(src_km)
        assert match != src_km, "This is the same exact keymap already."
        return match

    # If we want to find any other type of KeyMap, we have to do it indirectly, since we can only directly check for matches in the User KeyConfig.
    # So eg. if we want to find an Addon KeyMap based on a User KeyMap, we have to loop over all Addon KeyMaps, and find which one matches with the given User KeyMap.
    for km in target_kc.keymaps:
        match = kc_user.keymaps.find_match(km)
        if match == src_km:
            return km
