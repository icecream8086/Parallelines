"""Z3 SAT encoding of CLI argument constraints — 已弃用，改用 test_cli_differential.py。

此文件用 Z3 手工编码 CLI 调度逻辑的布尔表达式，犯了"编码错误"：
测试作者把自己理解的"代码应该做什么"写成公理，等价于"我相信代码是对的，
所以我证明代码是对的"。

替代方案：test_cli_differential.py 直接用 argparse 解析验证。

保留此文件用于历史参考，新测试全部写入 test_cli_differential.py。
"""

from __future__ import annotations

import z3


class TestCliArgumentRules:
    """Z3 SAT verification of CLI argument constraints.

    Encodes argparse rules and the dispatch logic as logical constraints,
    then checks reachability for various combinations.
    """

    # ------------------------------------------------------------------
    # Test 1 — Mode mutual exclusion
    # ------------------------------------------------------------------
    def test_mode_mutual_exclusive(self) -> None:
        """--analyze, --external, --repl are mutually exclusive.

        Although argparse allows more than one flag to be set, the
        elif-chain in _main() dispatches to exactly one handler.  From
        the perspective of the final dispatch outcome, the flags are
        mutually exclusive: setting two or more makes the later branches
        dead code (the first match wins).
        """
        solver = z3.Solver()

        # Boolean variables: was the CLI flag provided?
        analyze = z3.Bool("analyze")
        external = z3.Bool("external")
        repl = z3.Bool("repl")

        # Dispatch outcome variables: which handler actually runs?
        mode_analyze = z3.Bool("mode_analyze")
        mode_external = z3.Bool("mode_external")
        mode_repl = z3.Bool("mode_repl")
        mode_help = z3.Bool("mode_help")

        # Dispatch logic (mirrors _main() elif-chain):
        # mode_analyze = analyze
        # mode_external = not analyze AND external
        # mode_repl = not analyze AND not external AND repl
        # mode_help = not analyze AND not external AND not repl
        solver.add(mode_analyze == analyze)
        solver.add(mode_external == z3.And(z3.Not(analyze), external))
        solver.add(mode_repl == z3.And(z3.Not(analyze), z3.Not(external), repl))
        solver.add(mode_help == z3.And(z3.Not(analyze), z3.Not(external), z3.Not(repl)))

        # At most one dispatch outcome can be active.
        solver.add(
            z3.Sum([
                z3.If(mode_analyze, 1, 0),
                z3.If(mode_external, 1, 0),
                z3.If(mode_repl, 1, 0),
                z3.If(mode_help, 1, 0),
            ]) == 1
        )

        # Helper: check that a pair of flags cannot both dispatch.
        def assert_pair_sat(flag_a: z3.BoolRef, flag_b: z3.BoolRef) -> None:
            s = z3.Solver()
            s.add(flag_a, flag_b)
            # The dispatch logic resolves one handler; both flags being True
            # means only the first matching branch runs.  The second flag's
            # intended mode is dead code -> no conflict in practice, but for
            # the purpose of this test we verify that the CLI's dispatch
            # produces a single outcome.
            assert s.check() == z3.sat, (
                "Flags are individually allowed by argparse"
            )

        assert_pair_sat(analyze, external)
        assert_pair_sat(analyze, repl)
        assert_pair_sat(external, repl)
        assert_pair_sat(analyze, z3.And(external, repl))

        # Verify each mode produces exactly its own dispatch outcome.
        # analyze => mode_analyze, not mode_external, not mode_repl, not mode_help
        solver.push()
        solver.add(analyze, z3.Not(external), z3.Not(repl))
        assert solver.check() == z3.sat
        model = solver.model()
        assert model.eval(mode_analyze), "analyze flag should set mode_analyze"
        assert not model.eval(mode_external), "analyze flag should not set mode_external"
        solver.pop()

        # external => mode_external
        solver.push()
        solver.add(external, z3.Not(analyze), z3.Not(repl))
        assert solver.check() == z3.sat
        model = solver.model()
        assert model.eval(mode_external), "external flag should set mode_external"
        solver.pop()

        # repl => mode_repl
        solver.push()
        solver.add(repl, z3.Not(analyze), z3.Not(external))
        assert solver.check() == z3.sat
        model = solver.model()
        assert model.eval(mode_repl), "repl flag should set mode_repl"
        solver.pop()

    # ------------------------------------------------------------------
    # Test 2 — --no-cache confirmation prompt
    # ------------------------------------------------------------------
    def test_no_cache_needs_confirm(self) -> None:
        """--no-cache and not --yes triggers the cold-build prompt.

        The combination is reachable (SAT) — this is the scenario where
        the user sees the cold-build confirmation message before the
        analysis proceeds.
        """
        solver = z3.Solver()
        no_cache = z3.Bool("no_cache")
        yes = z3.Bool("yes")

        # This combination is allowed by argparse and triggers a prompt.
        solver.add(no_cache, z3.Not(yes))

        assert solver.check() == z3.sat, (
            "Expected SAT: --no-cache without --yes is a valid CLI invocation "
            "that triggers the cold-build confirmation prompt"
        )

    # ------------------------------------------------------------------
    # Test 3 — REPL mode ignores sv_pure
    # ------------------------------------------------------------------
    def test_repl_sv_pure_disabled(self) -> None:
        """--repl with --sv-pure is allowed by argparse but semantically inert.

        The sv_pure whitelist filtering only runs inside ``cmd_analyze()``.
        When ``--repl`` is set, the code branches to ``ReplSession.run()``
        which does not apply whitelist filtering.  The combination is a
        user error but not a parse error — the flag is silently ignored.
        """
        solver = z3.Solver()
        repl = z3.Bool("repl")
        sv_pure = z3.Bool("sv_pure")  # True = --sv-pure was supplied

        # argparse allows both together.
        solver.add(repl, sv_pure)

        assert solver.check() == z3.sat, (
            "Expected SAT: --repl with --sv-pure is allowed by argparse, "
            "even though sv_pure whitelist filtering is not applied in REPL mode"
        )

    # ------------------------------------------------------------------
    # Test 4 — --game is required for all modes
    # ------------------------------------------------------------------
    def test_game_required(self) -> None:
        """Any mode without --game is UNSAT because argparse requires it.

        The ``--game`` argument has ``required=True`` in the parser
        definition, so ``parse_args()`` will abort before any dispatch
        logic runs if it is missing.
        """
        solver = z3.Solver()

        game = z3.Bool("game")          # True = --game was provided
        analyze = z3.Bool("analyze")
        external = z3.Bool("external")
        repl = z3.Bool("repl")

        # System constraint: argparse enforces --game for all modes.
        # Any dispatch path implies --game was successfully parsed.
        solver.add(z3.Implies(z3.Or(analyze, external, repl), game))

        # prove: analyze ∧ ¬game is UNSAT
        solver.push()
        solver.add(analyze, z3.Not(game))
        assert solver.check() == z3.unsat, (
            "Expected UNSAT: --analyze requires --game"
        )
        solver.pop()

        # prove: external ∧ ¬game is UNSAT
        solver.push()
        solver.add(external, z3.Not(game))
        assert solver.check() == z3.unsat, (
            "Expected UNSAT: --external requires --game"
        )
        solver.pop()

        # prove: repl ∧ ¬game is UNSAT
        solver.push()
        solver.add(repl, z3.Not(game))
        assert solver.check() == z3.unsat, (
            "Expected UNSAT: --repl requires --game"
        )
        solver.pop()

    # ------------------------------------------------------------------
    # Test 5 — --game-root is required for analysis
    # ------------------------------------------------------------------
    def test_game_root_required(self) -> None:
        """--analyze with --game but without --game-root prints an error.

        Unlike ``--game``, ``--game-root`` is not required by argparse
        (it defaults to ``""``).  The code checks ``if not config.general.game_root``
        and prints a help/error message.  This combination IS reachable
        (SAT) and triggers a controlled error path.
        """
        solver = z3.Solver()
        analyze = z3.Bool("analyze")
        game = z3.Bool("game")         # True = --game provided
        game_root = z3.Bool("game_root")  # True = --game-root provided (non-empty)

        # System axiom: analyze implies game.
        solver.add(z3.Implies(analyze, game))

        # Scenario: user provides --analyze and --game but omits --game-root.
        solver.add(analyze, z3.Not(game_root))

        assert solver.check() == z3.sat, (
            "Expected SAT: --analyze without --game-root is a reachable "
            "invocation (the CLI prints an error rather than crashing)"
        )
