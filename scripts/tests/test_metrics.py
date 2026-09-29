"""Does the measuring code count what it claims to count?"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_evolve import patch_cost  # noqa: E402
from metrics import _sections, code_lines_in  # noqa: E402

PY = '''"""Module docstring,
spanning lines."""

import os  # trailing comment stays code

# a comment
def f(x):
    """One-line docstring."""
    return x


class C:
    """Class docstring."""

    y = "not a docstring"
'''


def test_python_blanks_comments_and_docstrings_are_not_code() -> None:
    assert code_lines_in(PY, ".py") == [
        "import os  # trailing comment stays code",
        "def f(x):",
        "return x",
        "class C:",
        'y = "not a docstring"',
    ]


def test_typescript_block_and_line_comments() -> None:
    ts = "/* header\n spans */\nconst a = 1; // keep\n// drop\n\nexport const b = 2;\n"
    assert code_lines_in(ts, ".ts") == ["const a = 1; // keep", "export const b = 2;"]


def test_sections_split_at_headers(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("import x\n\n# ---------- the pipeline\na = 1\nb = 2\n# ---------- API\nc = 3\n")
    assert _sections(src) == {"": 1, "the pipeline": 2, "API": 1}


def test_patch_cost_counts_added_code_lines_per_file(tmp_path: Path, monkeypatch) -> None:
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,4 @@\n"
        " keep = 1\n+# a comment is not code\n+added = 2\n+\n-removed = 3\n"
    )
    import bench_evolve

    monkeypatch.setattr(bench_evolve, "EVOLVE", tmp_path)
    cost = patch_cost("x.patch")
    assert cost == {"files_touched": 1, "lines_added": 1, "lines_removed": 1, "files": {"m.py": {"added": 1, "removed": 1}}}
