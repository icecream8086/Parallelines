"""Shared fixtures and hypothesis profiles for formal verification tests."""

from hypothesis import settings, HealthCheck

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
