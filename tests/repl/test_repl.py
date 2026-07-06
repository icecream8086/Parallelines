"""Tests for the REPL interactive mode."""

from __future__ import annotations

from unittest.mock import MagicMock

from parallelines.repl.commands import COMMANDS
from parallelines.repl.formatter import format_result
from parallelines.repl.prompt import make_prompt
from parallelines.engine.store import Relation


# ── Prompt tests ────────────────────────────────────────────────


class TestPrompt:
    def test_make_prompt_basic(self):
        prompt = str(make_prompt("l4d2"))
        assert "l4d2" in prompt

    def test_make_prompt_with_externals(self):
        prompt = str(make_prompt("l4d2", ["pesaro"]))
        assert "l4d2" in prompt
        assert "pesaro" in prompt

    def test_make_prompt_multiple_externals(self):
        prompt = str(make_prompt("l4d2", ["pesaro", "new_mod"]))
        assert "pesaro" in prompt
        assert "new_mod" in prompt


# ── Formatter tests ─────────────────────────────────────────────


class TestFormatter:
    def test_format_empty(self):
        rel = Relation("test", ("col",), [])
        result = format_result(rel)
        assert "Empty set" in result

    def test_format_table(self):
        rel = Relation("test", ("col",), [("val1",), ("val2",)])
        result = format_result(rel, "table")
        assert "col" in result
        assert "val1" in result
        assert "val2" in result

    def test_format_json(self):
        rel = Relation("test", ("col",), [("val1",), ("val2",)])
        result = format_result(rel, "json")
        import json

        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["col"] == "val1"

    def test_format_csv(self):
        rel = Relation("test", ("col",), [("val1",), ("val2",)])
        result = format_result(rel, "csv")
        assert "col" in result
        assert "val1" in result

    def test_format_vertical(self):
        rel = Relation("test", ("col",), [("val1",)])
        result = format_result(rel, "vertical")
        assert "row" in result
        assert "col: val1" in result

    def test_format_no_rows_vertical(self):
        rel = Relation("test", ("col",), [])
        result = format_result(rel, "vertical")
        assert "Empty set" in result

    def test_format_no_rows_json(self):
        rel = Relation("test", ("col",), [])
        result = format_result(rel, "json")
        assert "Empty set" in result


# ── Command tests ───────────────────────────────────────────────


class TestCommands:
    def test_help(self):
        session = MagicMock()
        assert COMMANDS["help"](session, "") is True

    def test_tables_no_store(self):
        session = MagicMock()
        session.store = None
        assert COMMANDS["tables"](session, "") is True

    def test_exit_returns_false(self):
        session = MagicMock()
        assert COMMANDS["exit"](session, "") is False

    def test_quit_returns_false(self):
        session = MagicMock()
        assert COMMANDS["quit"](session, "") is False

    def test_mode_valid_table(self):
        session = MagicMock()
        COMMANDS["mode"](session, "table")
        assert session.output_mode == "table"

    def test_mode_valid_json(self):
        session = MagicMock()
        COMMANDS["mode"](session, "json")
        assert session.output_mode == "json"

    def test_mode_invalid(self):
        session = MagicMock()
        session.output_mode = "table"
        COMMANDS["mode"](session, "bogus")
        assert session.output_mode == "table"

    def test_pager_toggle(self):
        session = MagicMock()
        session.pager_enabled = True
        COMMANDS["pager"](session, "off")
        assert session.pager_enabled is False

    def test_pager_enable(self):
        session = MagicMock()
        session.pager_enabled = False
        COMMANDS["pager"](session, "on")
        assert session.pager_enabled is True

    def test_print_toggle(self):
        session = MagicMock()
        session.print_enabled = True
        COMMANDS["print"](session, "off")
        assert session.print_enabled is False

    def test_echo_toggle(self):
        session = MagicMock()
        session.echo_enabled = False
        COMMANDS["echo"](session, "on")
        assert session.echo_enabled is True

    def test_schema_no_store(self):
        session = MagicMock()
        session.store = None
        COMMANDS["schema"](session, "files")

    def test_save_no_store(self):
        session = MagicMock()
        session.store = None
        COMMANDS["save"](session, "out.json")

    def test_schema_no_table_name(self):
        session = MagicMock()
        COMMANDS["schema"](session, "")


# ── Dispatch tests ──────────────────────────────────────────────


class TestDispatch:
    def test_empty_line(self):
        session = MagicMock()
        session._dispatch("")
        session._dispatch("  ")
        session._dispatch("# comment")

    def test_meta_command_dispatched(self):
        session = MagicMock()
        session._dispatch(".help")

    def test_exit_command(self):
        session = MagicMock()
        session._dispatch(".exit")

    def test_query_not_json(self):
        session = MagicMock()
        session._dispatch("{bad json}")


# ── Error resilience tests ──────────────────────────────────────


class TestErrorResilience:
    def test_bad_json_does_not_crash(self):
        session = MagicMock()
        session._dispatch("{bad json}") is not None

    def test_unknown_meta_does_not_crash(self):
        session = MagicMock()
        session._dispatch(".unknown_cmd_xyz") is not None

    def test_empty_inputs(self):
        session = MagicMock()
        for inp in ["", " ", "\t", "# comment", "#{json}"]:
            session._dispatch(inp) is None
