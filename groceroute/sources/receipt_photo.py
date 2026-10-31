"""Photographed receipts (Esselunga, Coop): line extraction with LLM vision."""

from groceroute.sources.base import PriceObservation


class ReceiptPhotoSource:
    chain_id = ""  # set per receipt

    async def fetch(self, query: str) -> list[PriceObservation]:
        raise NotImplementedError
