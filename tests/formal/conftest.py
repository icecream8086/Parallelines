"""Shared fixtures and hypothesis profiles for formal verification tests."""

_HYPOTHESIS_AVAILABLE: bool = False
try:
    from hypothesis import HealthCheck, settings

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    pass

if _HYPOTHESIS_AVAILABLE:
    settings.register_profile(
        "ci",
        max_examples=500,
        deadline=2000,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.data_too_large,
        ],
    )
    settings.register_profile(
        "dev",
        max_examples=300,
        deadline=2000,
    )
    settings.register_profile(
        "overnight",
        max_examples=10_000,
        deadline=None,
    )
    settings.load_profile("dev")
