# fmt: off
"""
Generic Blender Python codebase quality tests.
Checks that apply to any well-maintained Blender Python add-on.
CloudRig-specific checks live in test_codebase_cloudrig.py.
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
FORBIDDEN_PYTHON_PATTERNS: dict[str, str] = {
    "Do not use 'bare excepts'":                                        r'''except:''',
    "Do not import wildcards":                                          r'''import \*''',
}
FORBIDDEN_TRANSLATION_PATTERNS: dict[str, str] = {
    "`report()` must not use f-string":                                 r'''report\([^)]*,\s*f["']''',
    "`report()` must not use .format() (unless already translated)":    r'''self\.report\((?![^)]*rpt_)[^)]*["']\s*\.format\(''',
    "`report()` must not combine strings without translation wrappers": r'''self\.report\(\{'\w+'\},\s*"[^"]*"\s*\+''',
    "`text` kwarg must not use f-string":                               r'''text\s*=\s*f"''',
    "'.format()' must be outside of translation function, not inside":  r'''(_|n_|iface_|tip_|rpt_|data_)\(.*?(?<!\))\.format''',
    "Do not call long version of translation functions":                r'''pgettext_[data|rpt|tip|iface|n]\(''',
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

def test_no_forbidden_patterns(codebase_files: list[Path]):
    """Assert that none of the forbidden patterns appear anywhere in the codebase."""
    failures = check_forbidden_patterns({**FORBIDDEN_PYTHON_PATTERNS, **FORBIDDEN_TRANSLATION_PATTERNS}, codebase_files)
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
                hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  class {node.name}")

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
            hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  {line_text}  ({hint})")

    if hits:
        pytest.fail("bpy.props declarations missing name= and/or description=:\n\n" + "\n".join(hits))


def test_no_bpy_context_in_functions_with_context_param(parsed_codebase: ParsedFiles):
    """Assert that functions with a `context` parameter do not use `bpy.context` internally."""

    def walk_within_function(node):
        """Yield child nodes without crossing into nested function definitions."""
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child
                yield from walk_within_function(child)

    hits: list[str] = []
    for path, (source, tree) in parsed_codebase.items():
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if not any(arg.arg == 'context' for arg in all_args):
                continue
            # Exempt functions where context=None default value is used.
            regular_args = node.args.posonlyargs + node.args.args
            args_with_defaults = zip(regular_args[len(regular_args) - len(node.args.defaults):], node.args.defaults)
            kwonly_with_defaults = zip(node.args.kwonlyargs, node.args.kw_defaults)
            context_has_none_default = any(
                arg.arg == 'context' and isinstance(default, ast.Constant) and default.value is None
                for arg, default in list(args_with_defaults) + list(kwonly_with_defaults)
                if default is not None
            )
            if context_has_none_default:
                continue

            for inner in walk_within_function(node):
                if (isinstance(inner, ast.Attribute)
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == 'bpy'
                        and inner.attr == 'context'):
                    rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                    line_text = source_lines[inner.lineno - 1].strip()
                    hits.append(f"    {_file_link(path, inner.lineno, f'{rel}:{inner.lineno}')}  →  {line_text}")

    if hits:
        pytest.fail("Use the `context` parameter instead of `bpy.context`:\n\n" + "\n".join(hits))


def test_no_any_all_with_list_comprehension(parsed_codebase: ParsedFiles):
    """Assert that any()/all() are not called with a list comprehension argument.
    Use a generator expression instead: any(x for x in y) not any((x for x in y)).
    """
    hits: list[str] = []
    for path, (source, tree) in parsed_codebase.items():
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ('any', 'all')
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.ListComp)):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                line_text = source_lines[node.lineno - 1].strip()
                hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  {line_text}")

    if hits:
        pytest.fail("Use a generator expression instead of a list comprehension with any()/all():\n\n" + "\n".join(hits))


def test_class_names(parsed_codebase: ParsedFiles):
    """Assert that Operator, Menu, etc subclasses follow Blender's naming convention.
    Violating this can cause Blender to print a warning on registration.
    """
    BLENDER_TYPES = {
        'Operator': 'OT',
        'Menu':     'MT',
        'Panel':    'PT',
        'Header':   'HT',
        'UIList':   'UL',
    }

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

            sep = next((BLENDER_TYPES[b] for b in base_names if b in BLENDER_TYPES), None)
            if sep is None:
                continue

            if not re.match(rf'^[A-Z][A-Z0-9_]*_{sep}_[a-z][a-z0-9_]*$', node.name):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  class {node.name}  (expected UPPER_{sep}_lower)")

    if hits:
        pytest.fail("Operator/Menu/Panel class names don't follow Blender's naming convention:\n\n" + "\n".join(hits))


def test_no_legacy_typing(parsed_codebase: ParsedFiles):
    """Assert that deprecated typing module generics are not used.
    Use native types instead: list, dict, tuple, set, X | None, X | Y, etc.
    """
    LEGACY_NAMES = {'Dict', 'List', 'Tuple', 'Set', 'FrozenSet', 'Type', 'Optional', 'Union'}

    hits: list[str] = []
    for path, (source, tree) in parsed_codebase.items():
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == 'typing'
                    and node.attr in LEGACY_NAMES):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  {source_lines[node.lineno - 1].strip()}")
            elif (isinstance(node, ast.ImportFrom)
                    and node.module == 'typing'
                    and any(alias.name in LEGACY_NAMES for alias in node.names)):
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                hits.append(f"    {_file_link(path, node.lineno, f'{rel}:{node.lineno}')}  →  {source_lines[node.lineno - 1].strip()}")

    if hits:
        pytest.fail("Use native types instead of typing.Dict/List/Tuple/etc.:\n\n" + "\n".join(hits))


def test_no_string_annotations(parsed_codebase: ParsedFiles):
    """Assert that type annotations are not written as strings.
    Use `from __future__ import annotations` for forward references instead.
    """
    def is_str_const(node) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str)

    hits: list[str] = []
    for path, (source, tree) in parsed_codebase.items():
        source_lines = source.splitlines()
        flagged_lines: set[int] = set()

        for node in ast.walk(tree):
            anno = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                anno = node.returns
            elif isinstance(node, ast.AnnAssign):
                anno = node.annotation
            elif isinstance(node, ast.arg):
                anno = node.annotation

            if anno is not None and is_str_const(anno) and anno.lineno not in flagged_lines:
                flagged_lines.add(anno.lineno)
                rel = path.relative_to(CODEBASE_ROOT.resolve().parent)
                hits.append(f"    {_file_link(path, anno.lineno, f'{rel}:{anno.lineno}')}  →  {source_lines[anno.lineno - 1].strip()}")

    if hits:
        pytest.fail("Use `from __future__ import annotations` instead of string annotations:\n\n" + "\n".join(hits))


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


def _file_link(path: Path, line_no: int, display: str) -> str:
    uri = f"vscode://file/{path.as_posix().lstrip('/')}:{line_no}:1"
    return f"\033]8;;{uri}\033\\{display}\033]8;;\033\\"


def check_forbidden_patterns(patterns: dict[str, str], files: list[Path]) -> list[str]:
    """Return formatted failure strings for any pattern that matches in the given files."""
    failures: list[str] = []
    repo_root = CODEBASE_ROOT.resolve().parent
    for description, pattern in patterns.items():
        matches = find_matches(pattern, files)
        if matches:
            lines = []
            for path, line_no, text in matches:
                rel = f"./{path.relative_to(repo_root)}:{line_no}"
                lines.append(f"    {_file_link(path, line_no, rel)}  →  {text}")
            failures.append(f"  {description}:\n" + "\n".join(lines))
    return failures


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
            hits.append((path, line_no, line_text))
    return hits
