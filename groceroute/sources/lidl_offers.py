"""Lidl current offers via the lidl.it public search API (httpx).

Only the current flyer assortment is searchable (food and non-food mixed), so prices are
recorded as ``promo_api`` observations with the in-store validity window. Useful fields in
``items[].gridbox.data``:

- ``price.price`` / ``price.oldPrice``: current price and price before the discount;
- ``price.basePrice.text``: ``"1 kg = 7.24 €"`` (decimal point or comma);
- ``price.packaging.text``: ``"145 g confezione"``, ``"2x 125 g confezione"``;
- ``storeStartDate`` / ``storeEndDate``: in-store validity, Unix seconds (Europe/Rome);
- ``regionsV2`` / ``regionsPrices``: per-region prices. Every region pointed at the same price
  list when this was written (2026-11-01), but a ``region_id`` can be passed to pick its list.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from groceroute.sources.base import ObservationSource, PriceObservation, SourceError

ENDPOINT = "https://www.lidl.it/q/api/search"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) GroceRoute/0.1 (personal use)"
ROME = ZoneInfo("Europe/Rome")

# "145 g", "2x 125 g", "1 l", "1,5 kg". Multi-size packs ("300/400/500 g") do not match.
PACKAGING_RE = re.compile(r"^\s*(?:(\d+)\s*x\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.IGNORECASE)
# "1 kg = 7.24 €", "1 l = 3,73 €". Multi-size prices ("9.97/7.48/5.98 €") do not match.
BASE_PRICE_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\s*=\s*(\d+(?:[.,]\d+)?)\s*€?\s*$", re.IGNORECASE
)
TO_BASE_UNIT = {"kg": ("kg", 1), "g": ("kg", 1000), "l": ("l", 1), "ml": ("l", 1000)}


class LidlOffersSource:
    chain_id = "lidl"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        region_id: str | None = None,
        fetch_size: int = 48,
        max_pages: int = 5,
        page_delay: float = 1.0,
    ) -> None:
        self._client = client
        self.region_id = region_id
        self.fetch_size = fetch_size
        self.max_pages = max_pages
        self.page_delay = page_delay

    async def fetch(self, query: str) -> list[PriceObservation]:
        if self._client is not None:
            return await self._fetch(self._client, query)
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            return await self._fetch(client, query)

    async def _fetch(self, client: httpx.AsyncClient, query: str) -> list[PriceObservation]:
        observed_at = datetime.now().astimezone()
        observations: list[PriceObservation] = []
        offset, found = 0, 1
        for page in range(self.max_pages):
            if offset >= found:
                break
            if page:
                await asyncio.sleep(self.page_delay)
            payload = await self._request(client, query, offset)
            items = payload["items"]
            found = int(payload.get("numFound") or 0)
            observations.extend(parse_items(items, observed_at, self.region_id))
            if not items:
                break
            offset += len(items)
        return observations

    async def _request(self, client: httpx.AsyncClient, query: str, offset: int) -> dict[str, Any]:
        params = {
            "q": query,
            "offset": offset,
            "fetchsize": self.fetch_size,
            "locale": "it_IT",
            "assortment": "IT",
            "version": "v2.0.0",
        }
        try:
            resp = await client.get(ENDPOINT, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"lidl: request failed for {query!r} offset {offset}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise SourceError("lidl: response without an items list")
        return payload


def parse_items(
    items: list[dict[str, Any]], observed_at: datetime, region_id: str | None = None
) -> list[PriceObservation]:
    """Turn search ``items`` into observations, skipping non-products and unpriced items."""
    return [obs for item in items if (obs := _parse_item(item, observed_at, region_id)) is not None]


def _parse_item(
    item: dict[str, Any], observed_at: datetime, region_id: str | None
) -> PriceObservation | None:
    data = (item.get("gridbox") or {}).get("data")
    if item.get("type") != "product" or not data:
        return None
    price = _region_price(data, region_id)
    final_price = _decimal(price.get("price"))
    if final_price is None or final_price <= 0:
        return None
    old_price = _decimal(price.get("oldPrice"))
    on_promo = old_price is not None and old_price > final_price

    qty_value, qty_unit = parse_packaging((price.get("packaging") or {}).get("text"))
    unit_price = parse_base_price((price.get("basePrice") or {}).get("text"))
    if unit_price is None and qty_value and qty_unit in ("kg", "l"):
        unit_price = (final_price / qty_value).quantize(Decimal("0.01"))

    return PriceObservation(
        chain_id="lidl",
        source_code=str(item.get("code") or data["erpNumber"]),
        name=(data.get("fullTitle") or data.get("title") or "").strip(),
        source=ObservationSource.PROMO_API,
        final_price=final_price,
        regular_price=old_price if on_promo else final_price,
        unit_price=unit_price,
        brand=(data.get("brand") or {}).get("name"),
        ean=None,  # not exposed by the search API
        qty_value=qty_value,
        qty_unit=qty_unit,
        promo_type="promo" if on_promo else None,
        requires_card=None,  # Lidl Plus-only prices not observed yet (`lidlPlus` was always empty)
        valid_from=_date(data.get("storeStartDate")),
        valid_to=_date(data.get("storeEndDate")),
        observed_at=observed_at,
    )


def _region_price(data: dict[str, Any], region_id: str | None) -> dict[str, Any]:
    if region_id:
        region = (data.get("regionsV2") or {}).get(str(region_id)) or {}
        regional = (data.get("regionsPrices") or {}).get(str(region.get("regionPriceId")))
        if regional and regional.get("currentPrice"):
            return regional["currentPrice"]
    return data.get("price") or {}


def parse_packaging(text: str | None) -> tuple[Decimal | None, str | None]:
    """``"2x 125 g confezione"`` -> ``(Decimal("0.250"), "kg")``; unknown -> ``(None, None)``."""
    match = PACKAGING_RE.match(text or "")
    if not match:
        return None, None
    count, amount, unit = match.groups()
    base_unit, divisor = TO_BASE_UNIT[unit.lower()]
    value = _decimal(amount.replace(",", "."))
    if value is None:
        return None, None
    total = value * int(count or 1) / divisor
    return total.quantize(Decimal("0.001")), base_unit


def parse_base_price(text: str | None) -> Decimal | None:
    """``"1 kg = 7,24 €"`` -> ``Decimal("7.24")`` (€/kg or €/l). Unknown formats -> ``None``."""
    match = BASE_PRICE_RE.match(text or "")
    if not match:
        return None
    amount, unit, price = match.groups()
    base_unit_divisor = TO_BASE_UNIT[unit.lower()][1]
    amount_value = _decimal(amount.replace(",", "."))
    price_value = _decimal(price.replace(",", "."))
    if not amount_value or price_value is None:
        return None
    per_base_unit = price_value / (amount_value / base_unit_divisor)
    return per_base_unit.quantize(Decimal("0.01"))


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _date(timestamp: Any) -> date | None:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), ROME).date()
    except (TypeError, ValueError, OverflowError):
        return None
