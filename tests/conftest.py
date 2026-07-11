"""Hypothesis profiles for adversarial testing.

CI:     quick counterexample search (200 examples, no deadline)
Nightly: deep search (2000 examples, no deadline)

Usage:
    pytest tests/adversarial/ -v --hypothesis-profile=ci
    pytest tests/adversarial/ -v --hypothesis-profile=nightly

    # Override for a single run:
    pytest tests/adversarial/ -v --hypothesis-max-examples=5000
"""

_HYPOTHESIS_AVAILABLE = False
try:
    from hypothesis import HealthCheck, Phase, settings

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    pass

if _HYPOTHESIS_AVAILABLE:
    settings.register_profile(
        "ci",
        max_examples=200,
        deadline=None,
        phases=[Phase.generate, Phase.shrink],
    )
    settings.register_profile(
        "nightly",
        max_examples=2000,
        deadline=None,
        phases=[Phase.generate, Phase.shrink, Phase.explain],
    )
    settings.load_profile("ci")
