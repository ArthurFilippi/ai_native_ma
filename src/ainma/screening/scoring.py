"""The one scoring function, mirrored in TypeScript and tested on `scoring_vectors.json`.

Rules (the vectors file repeats them):

- `score = sum(w * met) / sum(w over known criteria)`, `None` when no known weight.
- `coverage = known weight / total weight`, where the total counts only the criteria that apply to
  the card (a criterion without a result on the card does not apply, for example `ticket_fit` for
  a strategic buyer).
- `contributions[k] = w_k * met_k / sum(w over known)`, zero for unknown and not met criteria, so
  the contributions add up to the score.
- `dealbreakers` are the keys of dealbreaker criteria whose result is `not_met`, whatever their
  weight.
- Rank: cards without a dealbreaker first, then cards with one. Inside a group: score descending
  (`None` last), coverage descending, buyer id ascending. Scores and coverage are compared after
  rounding to nine decimals so that float noise never decides an order.
- A card that failed stage 1 is not scored and not ranked (score `None`, coverage 0, no
  contributions, rank `None`) and is listed after the ranked cards, by buyer id.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ainma.contracts import BuyerCard, Criterion, CriterionStatus

_ROUND = 9


def effective_weights(
    criteria: Sequence[Criterion], weights: Mapping[str, float]
) -> dict[str, float]:
    """Criterion weights with the user overrides applied. Overrides of unknown keys are ignored."""
    effective: dict[str, float] = {}
    for criterion in criteria:
        weight = weights.get(criterion.key, criterion.weight)
        if weight < 0:
            raise ValueError(f"negative weight for {criterion.key!r}: {weight}")
        effective[criterion.key] = weight
    return effective


def _score_one(
    card: BuyerCard, criteria: Sequence[Criterion], weights: Mapping[str, float]
) -> BuyerCard:
    if not card.stage1_passed:
        return card.model_copy(
            update={
                "score": None,
                "coverage": 0.0,
                "contributions": {},
                "dealbreakers": [],
                "rank": None,
            }
        )
    status: dict[str, CriterionStatus] = {}
    for result in card.results:
        if result.criterion_key in status:
            raise ValueError(f"duplicate result for {result.criterion_key!r} on {card.buyer.id}")
        status[result.criterion_key] = result.status

    applicable = [c.key for c in criteria if c.key in status]
    total = sum(weights[key] for key in applicable)
    known = sum(weights[key] for key in applicable if status[key] is not CriterionStatus.UNKNOWN)
    met = {key: weights[key] if status[key] is CriterionStatus.MET else 0.0 for key in applicable}
    score = sum(met.values()) / known if known > 0 else None
    contributions = {c.key: (met.get(c.key, 0.0) / known if known > 0 else 0.0) for c in criteria}
    dealbreakers = [
        c.key for c in criteria if c.dealbreaker and status.get(c.key) is CriterionStatus.NOT_MET
    ]
    return card.model_copy(
        update={
            "score": score,
            "coverage": known / total if total > 0 else 0.0,
            "contributions": contributions,
            "dealbreakers": dealbreakers,
            "rank": None,
        }
    )


def _order_key(card: BuyerCard) -> tuple[bool, bool, float, float, str]:
    score = card.score
    return (
        bool(card.dealbreakers),
        score is None,
        -round(score, _ROUND) if score is not None else 0.0,
        -round(card.coverage, _ROUND),
        card.buyer.id,
    )


def score_cards(
    criteria: Sequence[Criterion],
    cards: Sequence[BuyerCard],
    weights: Mapping[str, float],
) -> list[BuyerCard]:
    """Fill score, coverage, contributions, dealbreakers and rank. Inputs are not mutated.

    The result is ordered: ranked cards by rank, then stage 1 failures by buyer id.
    """
    effective = effective_weights(criteria, weights)
    scored = [_score_one(card, criteria, effective) for card in cards]
    ranked = sorted((c for c in scored if c.stage1_passed), key=_order_key)
    unranked = sorted((c for c in scored if not c.stage1_passed), key=lambda c: c.buyer.id)
    return [
        *(card.model_copy(update={"rank": position}) for position, card in enumerate(ranked, 1)),
        *unranked,
    ]
