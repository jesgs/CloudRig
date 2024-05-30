from typing import Dict, Any
from bpy.types import Object

from ..utils.misc import get_addon_prefs
from .bone import BoneInfo, ensure_custom_property

from collections import OrderedDict
import bpy, sys, os
import json

from ..generation.cloudrig import is_cloud_metarig, tuples_to_dict, dict_to_tuples


class CloudUIMixin:
    forced_params = dict()

    def add_bone_property_with_ui(
        self,
        prop_bone: BoneInfo,
        prop_id: str,

        *,

        panel_name="Settings",
        label_name="",
        row_name="",
        slider_name="",
        texts=[],

        custom_prop_settings={},
        operator="",
        op_icon='BLANK1',
        op_kwargs={},

        parent_id="",
    ) -> OrderedDict:
        ensure_custom_property(prop_bone, prop_id, **custom_prop_settings)

        op_kwargs.update({'prop_bone': prop_bone.name, 'prop_id': prop_id})

        if not slider_name:
            slider_name = prop_id

        return add_ui_data(
            self.target_rig,
            owner_path=f'pose.bones["{prop_bone.name}"]',
            prop_name=f'["{prop_id}"]',
            texts={i: value for i, value in enumerate(texts)},

            panel_name=panel_name,
            label_name=label_name,
            row_name=row_name,
            slider_name=slider_name,

            operator=operator,
            op_icon=op_icon,
            op_kwargs=op_kwargs,

            parent_id=parent_id,
        )

    @staticmethod
    def draw_control_label(layout, text=""):
        split = layout.split(factor=0.4)
        split.row()
        split.label(text=text + ":")

    @staticmethod
    def is_advanced_mode(context):
        return is_advanced_mode(context)

    @classmethod
    def is_forced_param(cls, prop_name):
        for forced_param_name, value in cls.forced_params.items():
            if forced_param_name.endswith(prop_name):
                return True
        return False

    @classmethod
    def draw_prop(cls, context, layout, prop_owner, prop_name, enabled=True, **kwargs):
        is_forced = cls.is_forced_param(prop_name)
        if is_forced and not cls.is_advanced_mode(context):
            return

        row = draw_prop(layout, prop_owner, prop_name, enabled=enabled, **kwargs)
        if is_forced:
            row.enabled = False

        return row

    @classmethod
    def draw_prop_search(
        cls,
        context,
        layout,
        prop_owner,
        prop_name,
        collection,
        coll_prop_name,
        **kwargs,
    ):
        is_forced = cls.is_forced_param(prop_name)
        if is_forced and not cls.is_advanced_mode(context):
            return

        row = draw_prop_search(
            layout, prop_owner, prop_name, collection, coll_prop_name, **kwargs
        )

        if is_forced:
            row.enabled = False

        return row


def is_advanced_mode(context):
    if not is_cloud_metarig(context.object):
        return False
    return get_addon_prefs(context).advanced_mode


def draw_label_with_linebreak(context, layout, text, alert=False, align_split=False):
    """Attempt to simulate a proper textbox by only displaying as many
    characters in a single label as fits in the UI.
    This only works well on specific UI zoom levels.
    """

    if text == "":
        return
    col = layout.column(align=True)
    col.alert = alert
    if align_split:
        split = col.split(factor=0.2)
        split.row()
        col = split.row().column()
    paragraphs = text.split("\n")

    # Try to determine maximum allowed characters per line, based on pixel width of the area.
    # Not a great metric, but I couldn't find anything better.
    max_line_length = context.area.width / 8
    if align_split:
        max_line_length *= 0.95
    for p in paragraphs:
        lines = [""]
        for word in p.split(" "):
            if len(lines[-1]) + len(word) + 1 > max_line_length:
                lines.append("")
            lines[-1] += word + " "

        for line in lines:
            col.label(text=line)
    return col


def draw_prop(layout, prop_owner, prop_name, enabled=True, **kwargs):
    row = layout.row(align=True)
    row.prop(prop_owner, prop_name, **kwargs)
    row.enabled = enabled
    return row


def draw_prop_search(
    layout, prop_owner, prop_name, collection, coll_prop_name, **kwargs
):
    row = layout.row()
    row.prop_search(prop_owner, prop_name, collection, coll_prop_name, **kwargs)
    return row


def add_ui_data(
    obj,
    owner_path: str,
    prop_name: str,
    *,
    texts={},
    children={},

    panel_name: str,
    label_name="",
    row_name="",
    slider_name="",

    operator="",
    op_icon='BLANK1',
    op_kwargs={},

    parent_id="",
) -> OrderedDict:
    # Convert existing UI data to an OrderedDict for easy operations.
    if 'ui_data' not in obj.data:
        obj.data['ui_data'] = {'panels' : []}
    panels = obj.data['ui_data'].to_dict()['panels']
    panels = tuples_to_dict(panels)

    panel = panels.setdefault(panel_name, OrderedDict())
    panel['parent_id'] = parent_id
    header = panel.setdefault(label_name, OrderedDict())
    row = header.setdefault(row_name, OrderedDict())

    if not slider_name:
        slider_name = prop_name

    texts = {str(key): value for key, value in texts.items()}
    children = {str(key): value for key, value in children.items()}
    row[slider_name] = {'owner_path':owner_path, 'prop_name':prop_name, 'texts':texts, 'children':children, 'operator': operator, 'op_icon': op_icon, 'op_kwargs': op_kwargs}

    # Convert back to a list of tuples so Blender can store it without mangling it.
    panels = {'panels' : dict_to_tuples(panels)}
    obj.data['ui_data'] = panels

    return panels

class HiddenPrints:
    def write(*args):
        # This is a workaround to /issues/83 based on
        # https://stackoverflow.com/questions/6735917/redirecting-stdout-to-nothing-in-python
        pass

    def __enter__(self):
        self._original_stdout = sys.stdout
        try:
            sys.stdout = open(os.devnull, 'w')
        except FileNotFoundError:
            # Workaround, relies on this class having a write() method.
            sys.stdout = self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout


def redraw_viewport():
    with HiddenPrints():
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
