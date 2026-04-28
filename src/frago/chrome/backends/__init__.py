from .base import ChromeBackend
from .cdp import CDPChromeBackend
from .extension import ExtensionChromeBackend

DEFAULT_BACKEND = "cdp"


def get_backend(name: str = DEFAULT_BACKEND, **kwargs) -> ChromeBackend:
    """Factory for ChromeBackend instances.

    ``name`` ∈ {"cdp", "extension"}. Extra kwargs are forwarded to the
    backend constructor.
    """
    if name == "cdp":
        return CDPChromeBackend(**kwargs)
    if name == "extension":
        return ExtensionChromeBackend(**kwargs)
    raise ValueError(f"unknown backend: {name}")


__all__ = [
    "ChromeBackend",
    "CDPChromeBackend",
    "ExtensionChromeBackend",
    "get_backend",
    "DEFAULT_BACKEND",
]
