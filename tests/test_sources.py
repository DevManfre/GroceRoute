from decimal import Decimal

import pytest

from groceroute.sources.base import ObservationSource, PriceObservation, Source
from groceroute.sources.coop_easycoop import CoopEasyCoopSource
from groceroute.sources.esselunga import EsselungaSource
from groceroute.sources.lidl_offers import LidlOffersSource
from groceroute.sources.lidl_receipts import LidlReceiptsSource
from groceroute.sources.receipt_photo import ReceiptPhotoSource


@pytest.mark.parametrize(
    "source_cls",
    [CoopEasyCoopSource, EsselungaSource, LidlOffersSource, LidlReceiptsSource, ReceiptPhotoSource],
)
def test_every_source_implements_the_interface(source_cls):
    assert isinstance(source_cls(), Source)


def test_price_observation_is_timestamped():
    obs = PriceObservation(
        chain_id="test",
        source_code="1",
        name="Test Tuna 3x80 g",
        source=ObservationSource.ONLINE,
        final_price=Decimal("1.23"),
    )
    assert obs.observed_at.tzinfo is not None
