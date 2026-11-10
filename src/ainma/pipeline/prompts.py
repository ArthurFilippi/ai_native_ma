"""System prompts of the live tasks. The mock ignores them. Each ends with the JSON-only rule."""

JSON_ONLY = "Reply with one JSON object matching the schema and nothing else."

UNDERSTAND = (
    "You prepare a question about a company or a deal for retrieval. Split it into at most four "
    "self contained sub-questions, one per fact asked. List the entities, the financial metrics "
    "(snake_case keys such as revenue, gross_margin, ebitda) and the periods (FY2024, H1 2024). "
    "Never answer the question. " + JSON_ONLY
)

WRITE = (
    "You write claims for a banker from numbered passages only. Each claim is one sentence that "
    "a passage states. For every sourced claim give the passage numbers and an exact quote, "
    "copied character for character from the passage, that contains the figure or fact. Never "
    "use outside knowledge, never round or convert numbers. A claim that only combines sourced "
    "claims (a growth rate, a sum) has status inferred and lists the ids of the claims it "
    "derives from. A sub-question the passages do not answer goes in `missing`. " + JSON_ONLY
)

JUDGE = (
    "You check whether the quoted passage supports the claim. Answer `supported` only when every "
    "figure, entity and period of the claim is stated by the quote; `partial` when only part of "
    "the claim is; `unsupported` otherwise. " + JSON_ONLY
)

RELEVANCE = (
    "You rate from 0 to 1 how directly the answer addresses the question, ignoring correctness. "
    + JSON_ONLY
)

EXTRACT_FACTS = (
    "Extract every quantified fact of the text as (metric, period, value, unit, label). Use "
    "snake_case metric keys, normalise periods to FY2024, H1 2024 or Q3 2024, report money in "
    "millions and keep the quantity as written in `label`. Do not infer. " + JSON_ONLY
)
