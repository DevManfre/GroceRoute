"""Lidl current offers via the lidl.it public search API (httpx)."""

from groceroute.sources.base import PriceObservation


class LidlOffersSource:
    chain_id = "lidl"

    async def fetch(self, query: str) -> list[PriceObservation]:
        raise NotImplementedError
