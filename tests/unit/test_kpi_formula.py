from __future__ import annotations

import pytest

from ainma.contracts import KpiDef
from ainma.kpi.definitions import KPI_LABELS, kpi_definitions
from ainma.kpi.formula import (
    FormulaError,
    evaluate_formula,
    formula_names,
    topological_order,
)


@pytest.mark.parametrize(
    ("formula", "inputs", "expected"),
    [
        ("revenue - cogs", {"revenue": 182.4, "cogs": 112.2}, 70.2),
        ("(gross_profit / revenue) * 100", {"gross_profit": 70.2, "revenue": 182.4}, 38.486842105),
        ("-a + +b", {"a": 2.0, "b": 5.0}, 3.0),
        ("a ** 2 / 4", {"a": 6.0}, 9.0),
        ("100 - churn_rate", {"churn_rate": 3.5}, 96.5),
        ("1_000 * x", {"x": 2.0}, 2000.0),
    ],
)
def test_arithmetic_is_evaluated(formula: str, inputs: dict[str, float], expected: float) -> None:
    assert evaluate_formula(formula, inputs) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        ("__import__('os').system('echo x')", "Call is not allowed"),
        ("a.__class__", "Attribute is not allowed"),
        ("a[0]", "Subscript is not allowed"),
        ("a if b else 1", "IfExp is not allowed"),
        ("a < b", "Compare is not allowed"),
        ("a % b", "operator Mod is not allowed"),
        ("a // b", "operator FloorDiv is not allowed"),
        ("a @ b", "operator MatMult is not allowed"),
        ("~a", "operator Invert is not allowed"),
        ("'text'", "is not a number"),
        ("True + a", "is not a number"),
        ("1j * a", "is not a number"),
        ("lambda: 1", "Lambda is not allowed"),
        ("[a, b]", "List is not allowed"),
        ("(c := 1)", "NamedExpr is not allowed"),
        ("a +", "syntax error"),
        ("missing * 2", "unknown input 'missing'"),
    ],
)
def test_everything_but_arithmetic_is_rejected(formula: str, message: str) -> None:
    with pytest.raises(FormulaError, match=message):
        evaluate_formula(formula, {"a": 1.0, "b": 2.0})


def test_errors_point_at_the_offending_column() -> None:
    with pytest.raises(FormulaError, match="column 4"):
        evaluate_formula("a + abs(b)", {"a": 1.0, "b": 2.0})


@pytest.mark.parametrize("formula", ["a / 0", "a / (b - 2)", "a ** 1000", "9.0 ** 9 ** 9"])
def test_unsafe_arithmetic_raises_a_formula_error(formula: str) -> None:
    with pytest.raises(FormulaError):
        evaluate_formula(formula, {"a": 1.0, "b": 2.0})


def test_formula_names_validates_syntax() -> None:
    assert formula_names("(net_income / total_equity) * 100") == {"net_income", "total_equity"}
    with pytest.raises(FormulaError):
        formula_names("open('x')")


def _definition(kpi_id: str, depends_on: list[str]) -> KpiDef:
    return KpiDef(
        id=kpi_id,
        name=kpi_id,
        category="t",
        unit="x",
        kind="compute" if depends_on else "extract",
        formula=" + ".join(depends_on) or None,
        depends_on=depends_on,
    )


def test_topological_order_puts_dependencies_first() -> None:
    ordered = topological_order(
        [_definition("c", ["b", "a"]), _definition("b", ["a"]), _definition("a", [])]
    )
    assert [d.id for d in ordered] == ["a", "b", "c"]


def test_cycles_and_unknown_dependencies_are_detected() -> None:
    with pytest.raises(FormulaError, match="cycle: a -> b -> a"):
        topological_order([_definition("a", ["b"]), _definition("b", ["a"])])
    with pytest.raises(FormulaError, match="unknown KPI 'zzz'"):
        topological_order([_definition("a", ["zzz"])])
    with pytest.raises(FormulaError, match="duplicate"):
        topological_order([_definition("a", []), _definition("a", [])])


def test_default_definitions_are_consistent() -> None:
    definitions = kpi_definitions()
    assert 25 <= len(definitions) <= 35
    assert len(topological_order(definitions)) == len(definitions)
    assert set(KPI_LABELS) == {d.id for d in definitions}
    for definition in definitions:
        if definition.kind == "compute":
            assert definition.formula is not None
            assert formula_names(definition.formula) == set(definition.depends_on), definition.id
        else:
            assert definition.formula is None and not definition.depends_on
    # fresh copies, so a caller cannot corrupt the constants
    kpi_definitions()[0].name = "changed"
    assert kpi_definitions()[0].name == "Revenue"
