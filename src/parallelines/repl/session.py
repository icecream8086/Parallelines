"""REPL session — lifecycle, dispatch loop, error handling."""
from __future__ import annotations
import json
import time
import traceback
from pathlib import Path

from parallelines.pipeline import build_store, print_summary_from_store
from parallelines.query_cli import resolve_query
from parallelines.config import AppConfig
from parallelines.engine.query_parser import QueryParseError
from parallelines.engine.query_validator import QueryValidationError
from parallelines.exceptions import ParallelinesError
from parallelines.repl.commands import COMMANDS
from parallelines.repl.completer import build_completer
from parallelines.repl.formatter import OutputMode, format_result, pager
from parallelines.repl.prompt import _get_session, make_prompt, _HAS_PT


class ReplSession:
    """Interactive REPL session for querying a ResultStore."""

    def __init__(self, config: AppConfig, args):
        self.config = config
        self.args = args
        self.store = None
        self.game = config.general.game or getattr(args, "game", "l4d2")
        self.externals: list[str] = []
        self.debug = getattr(args, "debug", False)
        self.output_mode: OutputMode = "table"
        self.pager_enabled = True
        self.print_enabled = True
        self.echo_enabled = False
        self.last_result = None
        self._prompt_session = None
        self._completer = None

    # ── lifecycle ──────────────────────────────────────────

    def run(self) -> int:
        store, _vfs = build_store(self.config, self.args)
        if store is None:
            return 1
        self.store = store

        ext_path = getattr(self.args, "external", None)
        if ext_path:
            self.load_external_vpk(ext_path)

        print_summary_from_store(store)
        print()
        print("Type .help for help, .exit to quit.")
        print()

        self._completer = build_completer(store)
        has_pt = _HAS_PT
        self._prompt_session = None
        try:
            self._prompt_session = _get_session(self._completer)
        except Exception:
            # prompt_toolkit can fail at runtime in non-standard terminals
            # (e.g. frozen build in git bash / subprocess without Windows console).
            # Fall back to plain input().
            has_pt = False

        while True:
            try:
                if has_pt and self._prompt_session is not None:
                    line = self._prompt_session.prompt(
                        make_prompt(self.game, self.externals)
                    )
                else:
                    base = self.game
                    if self.externals:
                        base += f" (ref:{'+'.join(self.externals)})"
                    line = input(f"{base}> ")
                if not self._dispatch(line):
                    return 0
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                print()
                return 0
            except Exception:
                if self.debug:
                    print(f"Unexpected error: {traceback.format_exc()}")
                else:
                    print("Unexpected error. Use --debug for details.")
        return 0

    # ── dispatch ───────────────────────────────────────────

    def _dispatch(self, line: str) -> bool:
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        if line.startswith("."):
            return self._handle_meta(line)
        return self._handle_query(line)

    def _handle_meta(self, line: str) -> bool:
        parts = line[1:].strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        handler = COMMANDS.get(cmd)
        if handler is None:
            print(f"Unknown command: .{cmd}  (type .help for available commands)")
            return True
        try:
            return handler(self, arg)
        except Exception as e:
            print(f"Command error: {e}")
            if self.debug:
                traceback.print_exc()
            return True

    def _handle_query(self, line: str) -> bool:
        if self.store is None:
            print("No store loaded.")
            return True
        try:
            t0 = time.perf_counter()
            qd = resolve_query(line)
            if self.echo_enabled:
                print(f"Query: {json.dumps(qd)}")
            result = self.store.execute(qd)
            elapsed = time.perf_counter() - t0
            self.last_result = result
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            return True
        except QueryParseError as e:
            print(f"Query syntax error: {e}")
            return True
        except QueryValidationError as e:
            print("Query validation failed:")
            for err in e.errors:
                print(f"  - {err}")
            return True
        except ParallelinesError as e:
            print(f"Analysis error: {e}")
            return True
        except Exception as e:
            print(f"Unexpected error: {e}")
            if self.debug:
                traceback.print_exc()
            return True

        if not self.print_enabled:
            return True

        n = len(result)
        label = "Empty set" if n == 0 else f"{n} rows"
        print()
        if n > 0:
            text = format_result(result, self.output_mode)
            (pager if self.pager_enabled else print)(text)
        print(f"{label} in set ({elapsed:.3f}s)")
        print()
        return True

    # ── helpers used by commands ───────────────────────────

    def load_external_vpk(self, vpk_path: str, replace: bool = False) -> None:
        """Parse an external VPK and load it into the store for comparison."""
        if self.store is None:
            raise RuntimeError("No store loaded. Run .analyze first.")
        p = Path(vpk_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"VPK not found: {p}")
        ref = p.stem
        if replace:
            self.externals = []
        self.store.load_reference(ref, str(p), priority=2000)
        if ref not in self.externals:
            self.externals.append(ref)
        print(f"Loaded external VPK: {p.name} (ref:{ref}, priority=2000)")

    def refresh_completer(self) -> None:
        """Rebuild tab completer after store changes (e.g. .external, .analyze)."""
        self._completer = build_completer(self.store)
        self._prompt_session.completer = self._completer
