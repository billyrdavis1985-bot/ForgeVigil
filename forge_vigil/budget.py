"""Spend control arithmetic for live model calls.

Money is integer nano-USD (1e-9 USD), so accounting never rounds through
floats. Every model call reserves its worst-case cost against the operator's
cap *before* it is made (see `Store.reserve_spend`), then settles to the
provider-reported usage. A call whose usage is unknown keeps its reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from .assessment import NANOUSD_PER_USD
from .errors import ConfigError

# Byte-level BPE tokenizers emit at most one token per input byte; the
# headroom covers chat-template framing tokens.
INPUT_TOKEN_HEADROOM = 512


def _decimal(value: str, name: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ConfigError(f"{name} must be a decimal USD amount") from None
    if not amount.is_finite() or amount < 0:
        raise ConfigError(f"{name} must be a non-negative USD amount")
    return amount


def parse_usd(value: str, *, name: str) -> int:
    nanousd = _decimal(value, name) * NANOUSD_PER_USD
    if nanousd != nanousd.to_integral_value():
        raise ConfigError(f"{name} is more precise than 1e-9 USD")
    return int(nanousd)


@dataclass(frozen=True)
class Pricing:
    """Provider prices in USD per million tokens."""

    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    @classmethod
    def from_strings(cls, input_usd_per_million: str, output_usd_per_million: str) -> "Pricing":
        return cls(
            _decimal(input_usd_per_million, "input price per million tokens"),
            _decimal(output_usd_per_million, "output price per million tokens"),
        )

    def cost_nanousd(self, input_tokens: int, output_tokens: int) -> int:
        # 1 USD per million tokens == 1000 nano-USD per token. Rounded up.
        exact = (self.input_usd_per_million * input_tokens + self.output_usd_per_million * output_tokens) * 1000
        return int(exact.to_integral_value(rounding=ROUND_CEILING))


def worst_case_input_tokens(request_body: bytes) -> int:
    return len(request_body) + INPUT_TOKEN_HEADROOM
