# fmt: off
"""
CloudRig-specific codebase quality tests.
Generic checks that apply to any Blender add-on live in test_codebase.py.
"""

import ast

import pytest

from .test_codebase import (
    CODEBASE_ROOT,
    SCANNED_EXTENSIONS,
    check_forbidden_patterns,
    collect_files,
    parse_files,
)

# Patterns that must not match anywhere in the CloudRig codebase.
# Keys are human-readable descriptions; values are regex strings.
CLOUDRIG_FORBIDDEN_PATTERNS: dict[str, str] = {
    # TRANSLATABILITY - CLOUDRIG-SPECIFIC
    "`log()` first argument must be wrapped by `rpt_()`":               r'''log\([\n\s]*f?"''',
    "`description` must be wrapped by `tip_()`":                        r'''['"]description['"]:[\s]*f?['"]''',
    "`description` must not use f-string":                              r'''description\s*=[\n\s\(]*f''',
    "`raise_generation_error()` 1st arg must be wrapped by `rpt_()`":   r'''raise_generation_error\([\s\nf]*"''',
    "`draw_control_label()` 2nd arg must be wrapped by `iface_()`":     r'''\.draw_control_label\(.*,[\s\n]*f?"''',
    "`parent_switch_behaviour` must be wrapped by `n_()`":              r'''parent_switch_behaviour\s*=\s*f?["']''',
    "`define_bone_set()` 1st arg must be wrapped in `iface_()`":        r'''define_bone_set\(([\n\s]*)["|'](.*?)["|']''',
    "`label_name` or `panel_name` must be wrapped in `n_()`":           r'''(label_name|panel_name)\s*=\s*"(.+)"''',
    "`aligned_label(text=` kwarg must be wrapped by `iface_()`":        r'''aligned_label.*text=f?"''',
}


def test_no_bpy_types_outside_register():
    """Assert that `bpy.types.X` is not written out in full outside of register()/unregister()."""
    files = collect_files(CODEBASE_ROOT.resolve(), SCANNED_EXTENSIONS)
    parsed, _ = parse_files(files)
    hits: list[str] = []
    for path, (source, tree) in parsed.items():
        exempt: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ('register', 'unregister'):
                exempt.update(range(node.lineno, node.end_lineno + 1))

        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == 'bpy'
                    and node.value.attr == 'types'
                    and node.lineno not in exempt):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                line_text = source_lines[node.lineno - 1].strip()
                hits.append(f"    {rel}:{node.lineno}  →  {line_text}")

    if hits:
        pytest.fail("Do not write out `bpy.types.` outside of register()/unregister():\n\n" + "\n".join(hits))


def test_no_cloudrig_forbidden_patterns():
    """Assert that none of the CloudRig-specific forbidden patterns appear in the codebase."""
    files = collect_files(CODEBASE_ROOT.resolve(), SCANNED_EXTENSIONS)
    failures = check_forbidden_patterns(CLOUDRIG_FORBIDDEN_PATTERNS, files)
    if failures:
        pytest.fail("Forbidden patterns found:\n\n" + "\n\n".join(failures))
