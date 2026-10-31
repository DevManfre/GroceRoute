"""Esselunga a casa search, intercepting the app's JSON responses with Playwright."""

from groceroute.sources.base import PriceObservation


class EsselungaSource:
    chain_id = "esselunga"

    async def fetch(self, query: str) -> list[PriceObservation]:
        raise NotImplementedError
