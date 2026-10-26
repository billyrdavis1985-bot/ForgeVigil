"""ForgeVigil Checkpoint 01: fixture-mode protection slice.

One authenticated request -> fixed advisory assessment -> deterministic
permission -> at most one local outbox item -> durable receipt.
This package performs no model inference and no external delivery.
"""

from .versions import CODE_VERSION as __version__

__all__ = ["__version__"]
