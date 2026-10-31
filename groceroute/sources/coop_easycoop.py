"""Coop Alleanza 3.0 via the EasyCoop Magento GraphQL endpoint (httpx)."""

from groceroute.sources.base import PriceObservation


class CoopEasyCoopSource:
    chain_id = "coop"

    async def fetch(self, query: str) -> list[PriceObservation]:
        raise NotImplementedError
