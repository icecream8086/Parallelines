class ParallelinesError(Exception):
    """Base exception for all Parallelines errors."""


class ConfigError(ParallelinesError):
    """Configuration loading or validation error."""


class ParseError(ParallelinesError):
    """File format parsing error."""


class AnalysisError(ParallelinesError):
    """Analysis runtime error."""
