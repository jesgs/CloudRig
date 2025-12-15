# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path

import bpy
import bpy.utils.previews  # Do not remove. Seems necessary for some python versions... Wtf.
from bpy.types import ImagePreview

EXTENSIONS = ("png", "svg")
ICON_STORAGE = {}

def get_cloudrig_icon_id(icon_name: str) -> int:
    icon_id = -1
    icon = ICON_STORAGE["default"].get(icon_name)
    if icon:
        icon_id = icon.icon_id
    return icon_id

def get_widget_icon_id(wgt_name: str) -> int:
    wgt_name = wgt_name.replace("WGT-", "").lower()
    icon_id = get_cloudrig_icon_id(wgt_name)
    if icon_id == -1:
        return get_cloudrig_icon_id('missing_icon')
    return icon_id

def get_icons(icon_map_name="default") -> dict[str, ImagePreview]:
    icon_map = ICON_STORAGE.get(icon_map_name)
    if icon_map:
        return icon_map.items()
    return {}

def ensure_icon(icon_name: str, dir_path="", icon_map_name="default") -> ImagePreview:
    if not dir_path:
        dir_path = os.path.dirname(__file__)

    icon_map = ICON_STORAGE.get(icon_map_name)
    if not icon_map:
        icon_map = ICON_STORAGE[icon_map_name] = bpy.utils.previews.new()

    if icon_name in icon_map:
        return icon_map[icon_name]

    full_path = ""
    for ext in EXTENSIONS:
        full_path = Path(dir_path) / Path(f"{icon_name}.{ext}")
        if full_path.is_file():
            break
    else:
        return ensure_icon("missing_icon", icon_map_name=icon_map_name)

    return icon_map.load(icon_name, full_path.as_posix(), 'IMAGE')

def ensure_icons_from_dir(dir_path: str|Path, icon_map_name="default") -> list[ImagePreview]:
    if type(dir_path) is str:
        dir_path = Path(dir_path)
    if not dir_path.exists():
        return

    icons = []
    for file_path in [f for f in dir_path.iterdir() if f.is_file()]:
        icons.append(ensure_icon(file_path.stem, dir_path=dir_path, icon_map_name=icon_map_name))

    return icons

def register():
    global ICON_STORAGE
    ensure_icon("vertical_twoway_arrows")
    ensure_icon("missing_icon")

def unregister():
    for pcoll in ICON_STORAGE.values():
        bpy.utils.previews.remove(pcoll)
    ICON_STORAGE.clear()
