"""Lidl Plus digital receipts via the unofficial lidl-plus library."""

from groceroute.sources.base import PriceObservation


class LidlReceiptsSource:
    chain_id = "lidl"

    async def fetch(self, query: str) -> list[PriceObservation]:
        raise NotImplementedError
