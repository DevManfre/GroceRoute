import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from groceroute.sources.base import ObservationSource, SourceError
from groceroute.sources.coop_easycoop import ENDPOINT, CoopEasyCoopSource, parse_products

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 10, 6, 0, tzinfo=UTC)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def items(page: int = 1) -> list[dict]:
    return load(f"coop_easycoop_search_page{page}.json")["data"]["products"]["items"]


def by_sku(observations):
    return {o.source_code: o for o in observations}


def test_regular_product():
    obs = by_sku(parse_products(items(1), NOW))["9000001"]
    assert obs.chain_id == "coop"
    assert obs.source is ObservationSource.ONLINE
    assert obs.name == "Testmare Tonno All'olio Di Oliva 3 X 80 G"
    assert obs.brand == "TESTMARE"
    assert obs.ean == "0000000000017"
    assert obs.final_price == obs.regular_price == Decimal("3.6")
    assert obs.unit_price == Decimal("15.00")
    assert (obs.qty_value, obs.qty_unit) == (Decimal("0.240"), "kg")
    assert obs.promo_type is None and obs.valid_from is None and obs.valid_to is None
    assert obs.observed_at == NOW


def test_promo_product_has_validity_dates():
    obs = by_sku(parse_products(items(1), NOW))["9000002"]
    assert obs.regular_price == Decimal("1.2")
    assert obs.final_price == Decimal("0.84")
    assert obs.unit_price == Decimal("1.68")
    assert obs.promo_type == "promo"
    assert (obs.valid_from, obs.valid_to) == (date(2026, 1, 5), date(2026, 1, 18))


def test_variable_weight_quantity_is_derived_from_unit_price():
    obs = by_sku(parse_products(items(1), NOW))["9000003"]
    assert obs.unit_price == Decimal("30.00")
    assert (obs.qty_value, obs.qty_unit) == (Decimal("0.150"), "kg")
    assert obs.ean is None


def test_litres_and_items_without_price():
    observations = by_sku(parse_products(items(2), NOW))
    assert (observations["9000004"].qty_value, observations["9000004"].qty_unit) == (
        Decimal("1.000"),
        "l",
    )
    assert "9000005" not in observations


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_walks_all_pages():
    seen_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ENDPOINT)
        variables = json.loads(request.url.params["variables"])
        assert variables["search"] == "test"
        seen_pages.append(variables["currentPage"])
        return httpx.Response(
            200, json=load(f"coop_easycoop_search_page{variables['currentPage']}.json")
        )

    async with mock_client(handler) as client:
        source = CoopEasyCoopSource(client, page_delay=0)
        observations = await source.fetch("test")

    assert seen_pages == [1, 2]
    assert [o.source_code for o in observations] == ["9000001", "9000002", "9000003", "9000004"]


async def test_fetch_stops_at_max_pages():
    async with mock_client(
        lambda r: httpx.Response(200, json=load("coop_easycoop_search_page1.json"))
    ) as client:
        observations = await CoopEasyCoopSource(client, max_pages=1, page_delay=0).fetch("x")
    assert len(observations) == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"errors": [{"message": "Syntax Error"}]}),
        httpx.Response(200, json={"data": {"products": None}}),
    ],
)
async def test_fetch_raises_source_error_on_bad_responses(response):
    async with mock_client(lambda r: response) as client:
        with pytest.raises(SourceError):
            await CoopEasyCoopSource(client, page_delay=0).fetch("x")
