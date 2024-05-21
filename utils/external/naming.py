import enum
import collections
import re
from typing import Optional

NameParts = collections.namedtuple('NameParts', ['prefix', 'base', 'side_z', 'side', 'number'])

class Side(enum.IntEnum):
    LEFT = -1
    MIDDLE = 0
    RIGHT = 1

    @staticmethod
    def from_parts(parts: NameParts):
        if parts.side:
            if parts.side[1].lower() == 'l':
                return Side.LEFT
            else:
                return Side.RIGHT
        else:
            return Side.MIDDLE

    @staticmethod
    def to_string(parts: NameParts, side: 'Side'):
        if side != Side.MIDDLE:
            side_char = 'L' if side == Side.LEFT else 'R'
            side_str = parts.side or parts.side_z

            if side_str:
                sep, side_char2 = side_str[0:2]
                if side_char2.lower() == side_char2:
                    side_char = side_char.lower()
            else:
                sep = '.'

            return sep + side_char
        else:
            return ''

    @staticmethod
    def to_name(parts: NameParts, side: 'Side'):
        new_side = Side.to_string(parts, side)
        return combine_name(parts, side=new_side)


class SideZ(enum.IntEnum):
    TOP = 2
    MIDDLE = 0
    BOTTOM = -2

    @staticmethod
    def from_parts(parts: NameParts):
        if parts.side_z:
            if parts.side_z[1].lower() == 't':
                return SideZ.TOP
            else:
                return SideZ.BOTTOM
        else:
            return SideZ.MIDDLE

    @staticmethod
    def to_string(parts: NameParts, side: 'SideZ'):
        if side != SideZ.MIDDLE:
            side_char = 'T' if side == SideZ.TOP else 'B'
            side_str = parts.side_z or parts.side

            if side_str:
                sep, side_char2 = side_str[0:2]
                if side_char2.lower() == side_char2:
                    side_char = side_char.lower()
            else:
                sep = '.'

            return sep + side_char
        else:
            return ''

    @staticmethod
    def to_name(parts: NameParts, side: 'SideZ'):
        new_side = SideZ.to_string(parts, side)
        return combine_name(parts, side_z=new_side)


def get_name_side(name: str):
    return Side.from_parts(split_name(name))

def change_name_side(name: str,
                     side: Optional[Side] = None, *,
                     side_z: Optional[SideZ] = None):
    parts = split_name(name)
    new_side = None if side is None else Side.to_string(parts, side)
    new_side_z = None if side_z is None else SideZ.to_string(parts, side_z)
    return combine_name(parts, side=new_side, side_z=new_side_z)


def combine_name(parts: NameParts, *, prefix=None, base=None, side_z=None, side=None, number=None):
    eff_prefix = prefix if prefix is not None else parts.prefix
    eff_number = number if number is not None else parts.number
    if isinstance(eff_number, int):
        eff_number = '%03d' % eff_number

    return ''.join([
        eff_prefix+'-' if eff_prefix else '',
        base if base is not None else parts.base,
        side_z if side_z is not None else parts.side_z or '',
        side if side is not None else parts.side or '',
        '.'+eff_number if eff_number else '',
    ])


def split_name(name: str):
    name_parts = re.match(
        r'^(?:(ORG|MCH|DEF)-)?(.*?)([._-][tTbB])?([._-][lLrR])?(?:\.(\d+))?$', name)
    return NameParts(*name_parts.groups())
