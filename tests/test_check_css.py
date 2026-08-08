from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_css.py"
SPEC = importlib.util.spec_from_file_location("check_css", SCRIPT_PATH)
assert SPEC is not None
check_css = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = check_css
SPEC.loader.exec_module(check_css)


def test_declared_but_unreferenced_custom_property_is_reported():
    # PR #68 declared 13 tokens and referenced 2 of them.
    css = """
    :root {
      --used: 4px;
      --dead: 8px;
    }
    .thing { padding: var(--used); }
    """
    assert check_css.unused_custom_properties(css) == ["--dead"]


def test_referenced_custom_property_is_accepted_with_flexible_spacing():
    css = """
    :root { --gap: 8px; }
    .thing { gap: var( --gap ); }
    """
    assert check_css.unused_custom_properties(css) == []


def test_reference_inside_a_comment_does_not_count_as_usage():
    css = """
    :root { --dead: 8px; }
    /* someday: gap: var(--dead); */
    """
    assert check_css.unused_custom_properties(css) == ["--dead"]


def test_unitless_time_is_reported_because_browsers_drop_it():
    css = """
    @media (prefers-reduced-motion: reduce) {
      * {
        animation-duration: 0 !important;
        transition-duration: 0 !important;
      }
    }
    """
    assert check_css.unitless_time_values(css) == [
        "animation-duration: 0",
        "transition-duration: 0",
    ]


def test_time_with_a_unit_or_a_variable_is_accepted():
    css = """
    .a { transition-duration: 0s; }
    .b { animation-delay: 250ms; }
    .c { animation-duration: var(--motion-duration); }
    """
    assert check_css.unitless_time_values(css) == []


def test_multi_value_time_list_flags_only_the_unitless_entry():
    css = ".a { transition-duration: 0.2s, 0; }"
    assert check_css.unitless_time_values(css) == ["transition-duration: 0"]


def test_lint_messages_name_the_property_and_the_fix():
    problems = check_css.lint(":root { --dead: 1px; }\n.a { transition-duration: 0; }")
    assert any("--dead" in problem and "never referenced" in problem for problem in problems)
    assert any("0s" in problem for problem in problems)


def test_the_shipped_stylesheet_is_clean():
    assert check_css.lint(check_css.DEFAULT_STYLESHEET.read_text(encoding="utf-8")) == []
