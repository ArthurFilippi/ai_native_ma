"""Topics that are deliberately absent from the corpus (unanswerable questions).

`terms` must never occur in any document of the scope of the question; `generate` and `verify`
both check it. `hard` marks questions that share vocabulary with the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    question: str  # {E} is the entity name
    terms: tuple[str, ...]
    hard: bool


DEAL_TOPICS: list[Topic] = [
    Topic("ceo_compensation", "What is the total annual compensation of the CEO of {E}?",
          ("compensation", "salary", "remuneration", "bonus", "stock option", "pay package"), False),
    Topic("revenue_guidance_fy2026", "What revenue guidance did {E} give for FY2026?",
          ("guidance", "fy2026", "fiscal 2026"), True),
    Topic("ebitda_forecast_fy2027", "What EBITDA does {E} forecast for FY2027?",
          ("forecast", "fy2027", "fiscal 2027"), True),
    Topic("pending_litigation", "Is {E} involved in any pending lawsuits?",
          ("lawsuit", "litigation", "legal dispute", "pending claim"), False),
    Topic("pension_deficit", "What is the pension deficit of {E}?", ("pension",), False),
    Topic("patent_portfolio", "How many patents does {E} hold?", ("patent",), False),
    Topic("employee_attrition", "What was the employee attrition rate at {E} in FY2024?",
          ("attrition", "staff turnover", "employee turnover", "resignation"), True),
    Topic("environmental", "What environmental liabilities does {E} carry?",
          ("environmental", "emissions", "carbon"), False),
    Topic("credit_rating", "What credit rating does {E} have?", ("credit rating", "rating agency"), False),
    Topic("insurance", "What insurance coverage does {E} maintain?", ("insurance", "insured"), False),
    Topic("customer_churn", "What was the customer churn rate of {E} in FY2024?", ("churn",), True),
    Topic("dividend_policy", "What dividend did {E} pay for FY2024?", ("dividend",), True),
]

GENERAL_TOPICS: list[Topic] = [
    Topic("fee_schedule", "What fee does the bank charge for a sell-side mandate?",
          ("retainer", "success fee", "fee schedule", "mandate fee"), False),
    Topic("league_table", "Where does the bank rank in the 2024 league tables?",
          ("league table", "ranking"), False),
    Topic("law_firm", "Which law firm advised on the most recent precedent transaction?",
          ("law firm", "legal counsel"), True),
    Topic("fairness_fee", "What was the fairness opinion fee on the latest precedent transaction?",
          ("fairness opinion",), True),
    Topic("parental_leave", "What is the parental leave policy of the bank?", ("parental leave",), False),
    Topic("conflict_check", "How long does the conflict check take for a new mandate?",
          ("conflict check",), False),
]

BUYER_TOPICS: list[Topic] = [
    Topic("carried_interest", "What is the carried interest of {E}?",
          ("carried interest", "hurdle rate"), False),
    Topic("cio", "Who is the chief investment officer of {E}?", ("chief investment officer",), False),
    Topic("buyer_credit_rating", "What credit rating does {E} have?",
          ("credit rating", "rating agency"), False),
    Topic("esg_rating", "What is the ESG rating of {E}?", ("esg",), False),
    Topic("investor_base", "Who are the largest investors in {E}?",
          ("limited partner", "largest investor"), True),
    Topic("dividend_yield", "What is the dividend yield of {E}?", ("dividend",), True),
]
