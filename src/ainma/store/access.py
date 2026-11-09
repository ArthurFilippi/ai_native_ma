"""The access predicate as SQL, built in one place so it cannot drift between queries."""

from __future__ import annotations

from ainma.contracts import AccessContext


def access_clause(access: AccessContext, column: str = "deal_id") -> tuple[str, list[object]]:
    """`deal_id in allowed or (deal_id is null and include_general_layer)`."""
    allowed = sorted(access.allowed_deal_ids)
    parts: list[str] = []
    params: list[object] = []
    if allowed:
        marks = ",".join("?" for _ in allowed)
        parts.append(f"{column} IN ({marks})")
        params.extend(allowed)
    if access.include_general_layer:
        parts.append(f"{column} IS NULL")
    if not parts:
        return "0", []
    return "(" + " OR ".join(parts) + ")", params


def scope_clause(deal_id: str | None, column: str = "deal_id") -> tuple[str, list[object]]:
    """Requested scope: the deal (when given) and the general layer."""
    if deal_id is None:
        return f"{column} IS NULL", []
    return f"({column} = ? OR {column} IS NULL)", [deal_id]
