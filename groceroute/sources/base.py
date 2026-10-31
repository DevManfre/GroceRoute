"""Common interface for all price sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ObservationSource(StrEnum):
    """Where a price comes from, from most to least reliable."""

    RECEIPT = "receipt"  # actually paid in that store
    PROMO_API = "promo_api"  # current offer
    ONLINE = "online"  # e-commerce catalog


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """A price seen for a product at a given moment, with its provenance."""

    chain_id: str
    source_code: str
    name: str
    source: ObservationSource
    final_price: Decimal
    regular_price: Decimal | None = None
    unit_price: Decimal | None = None  # normalized €/kg or €/l
    brand: str | None = None
    ean: str | None = None
    qty_value: Decimal | None = None
    qty_unit: str | None = None  # 'kg' | 'l' | 'pcs'
    promo_type: str | None = None
    requires_card: bool | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class Source(Protocol):
    """A chain-specific data source."""

    chain_id: str

    async def fetch(self, query: str) -> list[PriceObservation]:
        """Search the source for `query` and return the prices found."""
        ...
