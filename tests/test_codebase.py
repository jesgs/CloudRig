# fmt: off
"""
Tests that certain regex patterns do not appear anywhere in the CloudRig codebase.
"""

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
    "`report()` must not use f-string":                                 r'''report\([^)]*,\s*f["']''',
    "`report()` must not use .format() (unless already translated)":    r'''self\.report\((?![^)]*rpt_)[^)]*["']\s*\.format\(''',
    "`report()` must not combine strings without translation wrappers": r'''self\.report\(\{'\w+'\},\s*"[^"]*"\s*\+''',
    "`aligned_label(text=` kwarg must be wrapped by `iface_()`":        r'''aligned_label.*text=f?"''',
    "`log()` first argument must be wrapped by `rpt_()`":               r'''log\([\n\s]*f?"''',
    "`description` must be wrapped by `tip_()`":                        r'''['"]description['"]:[\s]*f?['"]''',
    "`description` must not use f-string":                              r'''description\s*=[\n\s\(]*f''',
    "`raise_generation_error()` 1st arg must be wrapped by `rpt_()`":   r'''raise_generation_error\([\s\nf]*"''',
    "`draw_control_label()` 2nd arg must be wrapped by `iface_()`":     r'''\.draw_control_label\(.*,[\s\n]*f?"''',
    "`text` kwarg must not use f-string":                               r'''text\s*=\s*f"''',
    "`parent_switch_behaviour` must be wrapped by `n_()`":              r'''parent_switch_behaviour\s*=\s*f?["']''',
    "`define_bone_set()` 1st arg must be wrapped in `iface_()`":        r'''define_bone_set\(([\n\s]*)["|'](.*?)["|']''',
    "`label_name` or `panel_name` must be wrapped in `n_()`":           r'''(label_name|panel_name)\s*=\s*"(.+)"''',
    "'.format()' must be outside of translation function, not inside":  r'''(_|n_|iface_|tip_|rpt_|data_)\(.*?(?<!\))\.format''',
    "Do not call long version of translation functions":                r'''pgettext_[data|rpt|tip|iface|n]\(''',
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_files(root: Path, extensions: set[str]) -> list[Path]:
    return [
        p for p in root.rglob("*")
        if p.suffix in extensions and p.is_file() and p.name not in IGNORED_FILES
    ]


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_forbidden_patterns(codebase_files: list[Path]):
    """Assert that none of the forbidden patterns appear anywhere in the codebase."""
    failures: list[str] = []

    for description, pattern in FORBIDDEN_PATTERNS.items():
        matches = find_matches(pattern, codebase_files)
        if matches:
            lines = [f"    {path}:{line_no}  →  {text}" for path, line_no, text in matches]
            failures.append(f"  {description}:\n" + "\n".join(lines))

    if failures:
        pytest.fail("Forbidden patterns found:\n\n" + "\n\n".join(failures))
