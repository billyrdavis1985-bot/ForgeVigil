"""Errors shared across modules."""


class ConfigError(Exception):
    """Startup configuration is unsafe; the component must not start."""
