"""Where the buyer profiles come from.

The `Store` interface carries documents, not buyer profiles. A store that also implements
`list_buyers` is used as is, otherwise the caller passes the profiles (for example read from
`truth/buyers.json` with `load_buyers`). A missing universe is an error, never an empty list.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ainma.contracts import BuyerProfile
from ainma.store import Store


@runtime_checkable
class SupportsBuyers(Protocol):
    async def list_buyers(self) -> list[BuyerProfile]: ...


class BuyerUniverseUnavailable(RuntimeError):
    """No buyer profiles were given and the store cannot list them."""


def load_buyers(seed_dir: Path) -> list[BuyerProfile]:
    """Buyer profiles from `<seed_dir>/truth/buyers.json`."""
    raw = json.loads((seed_dir / "truth" / "buyers.json").read_text(encoding="utf-8"))
    return [BuyerProfile.model_validate(item) for item in raw]


async def resolve_buyers(store: Store, buyers: Sequence[BuyerProfile] | None) -> list[BuyerProfile]:
    if buyers is not None:
        return list(buyers)
    if isinstance(store, SupportsBuyers):
        return await store.list_buyers()
    raise BuyerUniverseUnavailable(
        "pass `buyers=` to run_screening: the store has no list_buyers (see load_buyers)"
    )
