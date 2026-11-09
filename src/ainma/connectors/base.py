"""Market intelligence connector interface.

Only `SimulatedNewsConnector` exists. Real connectors (Tavily, Crunchbase, Mergermarket, PitchBook)
are interface-only: nothing in this package reaches them and none pretends to. A real connector
would implement `Connector` with `simulated = False`, and its items would be ingested with
`synthetic = False` and a real origin.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ainma.contracts import ConnectorItem


class Connector(Protocol):
    name: str
    simulated: bool

    async def fetch(self, *, entity: str, since: date) -> list[ConnectorItem]: ...
