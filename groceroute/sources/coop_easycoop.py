"""Coop Alleanza 3.0 via the EasyCoop Magento GraphQL endpoint (httpx).

No session or postcode is needed. Besides the standard Magento price fields, the useful data
lives in ``custom_attributesV2``:

- ``ean``: barcode (only in the unfiltered attribute list, hence the large payload);
- ``manufacturer``: brand;
- ``tipo_misura``: ``KG`` | ``LT`` | ``PZ``;
- ``misura_prezzo_chiaro``: net quantity in that unit;
- ``transparent_price``: price per unit x 100, already based on the final price;
- ``peso_variabile``: ``1`` for variable-weight items, whose ``misura_prezzo_chiaro`` is a
  placeholder ``1.000``: the quantity is derived from price / unit price.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from groceroute.sources.base import ObservationSource, PriceObservation, SourceError

ENDPOINT = "https://www.easycoop.com/graphql"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) GroceRoute/0.1 (personal use)"

QUERY = """
query Search($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    total_count
    page_info { current_page total_pages }
    items {
      sku
      name
      stock_status
      special_from_date
      special_to_date
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value }
        }
      }
      custom_attributesV2 {
        items {
          code
          ... on AttributeValue { value }
          ... on AttributeSelectedOptions { selected_options { label } }
        }
      }
    }
  }
}
"""

UNITS = {"KG": "kg", "LT": "l", "PZ": "pcs"}


class CoopEasyCoopSource:
    chain_id = "coop"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        page_size: int = 100,
        max_pages: int = 5,
        page_delay: float = 1.0,
    ) -> None:
        self._client = client
        self.page_size = page_size
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
        page, total_pages = 1, 1
        while page <= min(total_pages, self.max_pages):
            if page > 1:
                await asyncio.sleep(self.page_delay)
            payload = await self._request(client, query, page)
            products = payload["data"]["products"]
            total_pages = products["page_info"]["total_pages"] or 1
            observations.extend(parse_products(products["items"], observed_at))
            page += 1
        return observations

    async def _request(self, client: httpx.AsyncClient, query: str, page: int) -> dict[str, Any]:
        variables = {"search": query, "pageSize": self.page_size, "currentPage": page}
        try:
            # GET as the site does: the response is identical, and it is cacheable
            resp = await client.get(
                ENDPOINT, params={"query": QUERY, "variables": _json(variables)}
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"coop: request failed for {query!r} page {page}: {exc}") from exc
        if payload.get("errors"):
            raise SourceError(f"coop: GraphQL errors: {payload['errors']}")
        if not (payload.get("data") or {}).get("products"):
            raise SourceError("coop: response without data.products")
        return payload


def parse_products(items: list[dict[str, Any]], observed_at: datetime) -> list[PriceObservation]:
    """Turn GraphQL ``products.items`` into observations. Items without a price are skipped."""
    return [obs for item in items if (obs := _parse_item(item, observed_at)) is not None]


def _parse_item(item: dict[str, Any], observed_at: datetime) -> PriceObservation | None:
    prices = item["price_range"]["minimum_price"]
    final_price = _decimal(prices["final_price"]["value"])
    if final_price is None or final_price <= 0:
        return None
    regular_price = _decimal(prices["regular_price"]["value"])
    attrs = _attributes(item.get("custom_attributesV2"))

    unit = UNITS.get(_first(attrs.get("tipo_misura")) or "")
    unit_price = _decimal(attrs.get("transparent_price"))
    if unit_price is not None:
        unit_price = (unit_price / 100).quantize(Decimal("0.01"))
    qty_value = _decimal(attrs.get("misura_prezzo_chiaro"))
    if attrs.get("peso_variabile") == "1":
        # misura_prezzo_chiaro is a placeholder: estimate the weight from the €/kg
        qty_value = (final_price / unit_price).quantize(Decimal("0.001")) if unit_price else None

    on_promo = regular_price is not None and final_price < regular_price
    return PriceObservation(
        chain_id="coop",
        source_code=item["sku"],
        name=item["name"].strip(),
        source=ObservationSource.ONLINE,
        final_price=final_price,
        regular_price=regular_price,
        unit_price=unit_price,
        brand=_first(attrs.get("manufacturer")),
        ean=attrs.get("ean") or None,
        qty_value=qty_value,
        qty_unit=unit if qty_value is not None else None,
        promo_type="promo" if on_promo else None,
        # member-only prices: not observed so far (member_* attributes match the public ones)
        requires_card=None,
        valid_from=_date(item.get("special_from_date")) if on_promo else None,
        valid_to=_date(item.get("special_to_date")) if on_promo else None,
        observed_at=observed_at,
    )


def _attributes(block: dict[str, Any] | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for attr in (block or {}).get("items", []):
        if "selected_options" in attr:
            attrs[attr["code"]] = [o["label"] for o in attr["selected_options"] or []]
        else:
            attrs[attr["code"]] = attr.get("value")
    return attrs


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _date(value: str | None) -> date | None:
    """Magento dates look like ``2026-11-04 23:59:59``."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))
