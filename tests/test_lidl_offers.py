import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from groceroute.sources.base import ObservationSource, SourceError
from groceroute.sources.lidl_offers import (
    ENDPOINT,
    LidlOffersSource,
    parse_base_price,
    parse_items,
    parse_packaging,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 6, 6, 0, tzinfo=UTC)


def load(page: int) -> dict:
    return json.loads((FIXTURES / f"lidl_offers_search_page{page}.json").read_text())


def by_code(observations):
    return {o.source_code: o for o in observations}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("145 g confezione", (Decimal("0.145"), "kg")),
        ("2x 125 g confezione", (Decimal("0.250"), "kg")),
        ("1 l confezione", (Decimal("1.000"), "l")),
        ("2x 200 ml confezione", (Decimal("0.400"), "l")),
        ("1,5 kg", (Decimal("1.500"), "kg")),
        ("300/400/500 g confezione", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_packaging(text, expected):
    assert parse_packaging(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 kg = 7.24 €", Decimal("7.24")),
        ("1 kg = 11,92 €", Decimal("11.92")),
        ("1 l = 3.73 €", Decimal("3.73")),
        ("100 g = 1.20 €", Decimal("12.00")),
        ("1 kg = 9.97/7.48/5.98 €", None),
        (None, None),
    ],
)
def test_parse_base_price(text, expected):
    assert parse_base_price(text) == expected


def test_promo_product():
    obs = by_code(parse_items(load(1)["items"], NOW))["90000001"]
    assert obs.chain_id == "lidl"
    assert obs.source is ObservationSource.PROMO_API
    assert obs.name == "TESTMARE Tonno all'olio d'oliva"
    assert obs.brand == "Testmare"
    assert (obs.final_price, obs.regular_price) == (Decimal("1.0"), Decimal("1.5"))
    assert obs.promo_type == "promo"
    assert obs.unit_price == Decimal("6.25")
    assert (obs.qty_value, obs.qty_unit) == (Decimal("0.160"), "kg")
    assert (obs.valid_from, obs.valid_to) == (date(2026, 1, 5), date(2026, 1, 11))
    assert obs.ean is None
    assert obs.observed_at == NOW


def test_flyer_product_without_discount_or_end_date():
    obs = by_code(parse_items(load(1)["items"], NOW))["90000002"]
    assert obs.final_price == obs.regular_price == Decimal("1.29")
    assert obs.promo_type is None
    assert obs.unit_price == Decimal("10.32")
    assert (obs.valid_from, obs.valid_to) == (date(2026, 1, 5), None)


def test_non_food_has_no_quantity():
    obs = by_code(parse_items(load(1)["items"], NOW))["90000003"]
    assert (obs.qty_value, obs.qty_unit, obs.unit_price) == (None, None, None)


def test_unit_price_is_computed_when_missing_and_teasers_are_skipped():
    observations = by_code(parse_items(load(2)["items"], NOW))
    assert set(observations) == {"90000004", "90000005"}
    assert observations["90000004"].unit_price == Decimal("1.09")
    assert observations["90000005"].unit_price is None  # multi-size pack


def test_region_price_list():
    items = load(2)["items"]
    default = by_code(parse_items(items, NOW))["90000005"]
    emilia = by_code(parse_items(items, NOW, region_id="301"))["90000005"]
    unknown = by_code(parse_items(items, NOW, region_id="999"))["90000005"]
    assert default.final_price == unknown.final_price == Decimal("2.99")
    assert emilia.final_price == Decimal("2.49")
    assert (emilia.qty_value, emilia.unit_price) == (Decimal("1.000"), Decimal("2.49"))


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_walks_all_pages():
    offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ENDPOINT)
        params = request.url.params
        assert (params["q"], params["locale"], params["assortment"]) == ("test", "it_IT", "IT")
        offsets.append(int(params["offset"]))
        return httpx.Response(200, json=load(1 if params["offset"] == "0" else 2))

    async with mock_client(handler) as client:
        observations = await LidlOffersSource(client, fetch_size=3, page_delay=0).fetch("test")

    assert offsets == [0, 3]
    assert len(observations) == 5


async def test_fetch_stops_at_max_pages():
    async with mock_client(lambda r: httpx.Response(200, json=load(1))) as client:
        source = LidlOffersSource(client, fetch_size=3, max_pages=1, page_delay=0)
        assert len(await source.fetch("x")) == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="unavailable"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"type": "search"}),
    ],
)
async def test_fetch_raises_source_error_on_bad_responses(response):
    async with mock_client(lambda r: response) as client:
        with pytest.raises(SourceError):
            await LidlOffersSource(client, page_delay=0).fetch("x")
