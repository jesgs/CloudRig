# fmt: off
"""
Tests that certain patterns do not appear anywhere in the CloudRig codebase.
"""

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CODEBASE_ROOT = Path(__file__).parent / "../CloudRig"

# Only scan these file extensions (adjust as needed)
SCANNED_EXTENSIONS = {".py"}

# Files to exclude from scanning (matched by filename only, not full path)
IGNORED_FILES = [
    "cloud_jaw.py",
    "advanced_component.py",
    "minimal_component.py",
]

# Patterns that must not match anywhere in the codebase.
# Keys are human-readable descriptions; values are regex strings.
FORBIDDEN_PATTERNS: dict[str, str] = {
    # CODE QUALITY - GENERAL
    "Do not use 'bare excepts'":                                        r'''except:''',
    "Do not import wildcards":                                          r'''import \*''',
    # TRANSLATABILITY - GENERAL
    "`report()` must not use f-string":                                 r'''report\([^)]*,\s*f["']''',
    "`report()` must not use .format() (unless already translated)":    r'''self\.report\((?![^)]*rpt_)[^)]*["']\s*\.format\(''',
    "`report()` must not combine strings without translation wrappers": r'''self\.report\(\{'\w+'\},\s*"[^"]*"\s*\+''',
    "`text` kwarg must not use f-string":                               r'''text\s*=\s*f"''',
    "'.format()' must be outside of translation function, not inside":  r'''(_|n_|iface_|tip_|rpt_|data_)\(.*?(?<!\))\.format''',
    "Do not call long version of translation functions":                r'''pgettext_[data|rpt|tip|iface|n]\(''',
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

# bpy.props types that must have name= and description= kwargs.
BPY_PROPS = {
    'BoolProperty', 'IntProperty', 'FloatProperty', 'StringProperty',
    'EnumProperty', 'PointerProperty', 'CollectionProperty',
    'FloatVectorProperty', 'IntVectorProperty', 'BoolVectorProperty',
}

# These props are exempt from name=/description= if their type= class has a docstring.
POINTER_LIKE_PROPS = {'PointerProperty', 'CollectionProperty'}


ParsedFiles = dict[Path, tuple[str, ast.Module]]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def codebase_files() -> list[Path]:
    root = CODEBASE_ROOT.resolve()
    assert root.exists(), f"Codebase root not found: {root}"
    files = collect_files(root, SCANNED_EXTENSIONS)
    assert files, f"No {SCANNED_EXTENSIONS} files found under {root}"
    return files


@pytest.fixture(scope="session")
def parsed_codebase(codebase_files: list[Path]) -> ParsedFiles:
    parsed, syntax_errors = parse_files(codebase_files)
    if syntax_errors:
        rel = [str(p.relative_to(CODEBASE_ROOT.resolve().parent)) for p in syntax_errors]
        pytest.fail("Files with syntax errors:\n\n" + "\n".join(f"    {p}" for p in rel))
    return parsed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_forbidden_patterns(codebase_files: list[Path], parsed_codebase: ParsedFiles):
    """Assert that none of the forbidden patterns appear anywhere in the codebase."""
    failures: list[str] = []

    hits = find_bpy_types_outside_register(parsed_codebase)
    if hits:
        failures.append("  Do not write out `bpy.types.` outside of register()/unregister():\n" + "\n".join(hits))

    for description, pattern in FORBIDDEN_PATTERNS.items():
        matches = find_matches(pattern, codebase_files)
        if matches:
            lines = [f"    {path}:{line_no}  →  {text}" for path, line_no, text in matches]
            failures.append(f"  {description}:\n" + "\n".join(lines))

    if failures:
        pytest.fail("Forbidden patterns found:\n\n" + "\n\n".join(failures))


def test_operators_have_tooltips(parsed_codebase: ParsedFiles):
    """Assert that all concrete operators have a tooltip.
    A tooltip is any of: a class docstring, a bl_description assignment, or a description classmethod.
    Mixins (classes without bl_idname) are skipped.
    """
    hits: list[str] = []
    for path, (_, tree) in parsed_codebase.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            base_names = {
                base.id if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else ''
                for base in node.bases
            }
            if 'Operator' not in base_names:
                continue

            has_bl_idname = any(
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'bl_idname' for t in stmt.targets)
                for stmt in node.body
            )
            if not has_bl_idname:
                continue

            has_docstring = (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )
            has_bl_description = any(
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'bl_description' for t in stmt.targets)
                for stmt in node.body
            )
            has_description_method = any(
                isinstance(stmt, ast.FunctionDef)
                and stmt.name == 'description'
                and any(isinstance(d, ast.Name) and d.id == 'classmethod' for d in stmt.decorator_list)
                for stmt in node.body
            )

            if not (has_docstring or has_bl_description or has_description_method):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                hits.append(f"    {rel}:{node.lineno}  →  class {node.name}")

    if hits:
        pytest.fail("Operators missing a tooltip (docstring, bl_description, or description classmethod):\n\n" + "\n".join(hits))


def test_props_have_tooltips(parsed_codebase: ParsedFiles):
    """Assert that all bpy.props declarations have name= and description=.
    Declarations using **kwargs unpacking are skipped since they can't be checked statically.
    PointerProperty/CollectionProperty are exempt if their type= class has a docstring or __longdoc__.
    """
    # Build a map of class name -> is_documented across the whole codebase,
    # used to verify the type= exemption for pointer-like props.
    class_is_documented: dict[str, bool] = {}
    for _, (_, tree) in parsed_codebase.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                has_docstring = (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )
                has_longdoc = any(
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == '__longdoc__' for t in stmt.targets)
                    for stmt in node.body
                )
                class_is_documented[node.name] = has_docstring or has_longdoc

    hits: list[str] = []
    for path, (source, tree) in parsed_codebase.items():
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                value = node.value
            elif (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                value = node.value
            else:
                continue
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            prop_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if prop_name not in BPY_PROPS:
                continue
            # Skip if kwargs are unpacked — can't statically verify what's passed.
            if any(kw.arg is None for kw in value.keywords):
                continue
            kwarg_names = {kw.arg for kw in value.keywords}
            missing = [m for m in ('name', 'description') if m not in kwarg_names]
            if not missing:
                continue
            # PointerProperty/CollectionProperty are exempt if type= names a
            # locally-defined class that is documented.
            hint = None
            if prop_name in POINTER_LIKE_PROPS:
                type_kw = next((kw for kw in value.keywords if kw.arg == 'type'), None)
                if type_kw and isinstance(type_kw.value, ast.Name):
                    type_class_name = type_kw.value.id
                    if class_is_documented.get(type_class_name):
                        continue
                    if type_class_name in class_is_documented:
                        hint = f"add a docstring to {type_class_name}, or add name= and description="
            if hint is None:
                hint = "missing " + " and ".join(f"{m}=" for m in missing)
            rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
            line_text = source_lines[node.lineno - 1].strip()
            hits.append(f"    {rel}:{node.lineno}  →  {line_text}  ({hint})")

    if hits:
        pytest.fail("bpy.props declarations missing name= and/or description=:\n\n" + "\n".join(hits))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_files(root: Path, extensions: set[str]) -> list[Path]:
    return [
        p for p in root.rglob("*")
        if p.suffix in extensions and p.is_file() and p.name not in IGNORED_FILES
    ]


def parse_files(files: list[Path]) -> tuple[ParsedFiles, list[Path]]:
    """Read and parse all files, returning (parsed, syntax_error_paths).
    Files that cannot be read (OSError) are silently skipped.
    Files with syntax errors are collected separately so they can be reported.
    """
    parsed: ParsedFiles = {}
    syntax_errors: list[Path] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            parsed[path] = (source, ast.parse(source))
        except OSError:
            continue
        except SyntaxError:
            syntax_errors.append(path)
    return parsed, syntax_errors


def find_matches(pattern: str, files: list[Path]) -> list[tuple[Path, int, str]]:
    """Return a list of (file, line_number, line_text) for every match."""
    compiled = re.compile(pattern, re.MULTILINE)
    hits: list[tuple[Path, int, str]] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in compiled.finditer(source):
            line_no = source[: match.start()].count("\n") + 1
            line_text = source.splitlines()[line_no - 1].strip()
            hits.append((path.relative_to(CODEBASE_ROOT.resolve().parent), line_no, line_text))
    return hits


def find_bpy_types_outside_register(parsed: ParsedFiles) -> list[str]:
    """Return formatted hit strings for any `bpy.types.X` access outside register()/unregister()."""
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

    return hits
