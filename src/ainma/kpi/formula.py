"""Safe evaluator for KPI formulas: arithmetic over named inputs, nothing else.

A formula is parsed with `ast` and walked by an explicit allow list: numeric constants, names that
are provided as inputs, unary plus and minus, and the operators `+ - * / **`. Everything else
(calls, attributes, subscripts, comparisons, strings, comprehensions) is rejected with a precise
error that names the node and its column. The formula text is never passed to `eval`.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping, Sequence

from ainma.contracts import KpiDef

MAX_EXPONENT = 64.0


class FormulaError(ValueError):
    """The formula is not allowed, refers to a missing input, or cannot be evaluated."""


_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _where(node: ast.AST) -> str:
    column = getattr(node, "col_offset", None)
    return f"at column {column}" if column is not None else "in the expression"


def _parse(formula: str) -> ast.Expression:
    try:
        return ast.parse(formula.strip(), mode="eval")
    except SyntaxError as error:
        raise FormulaError(f"syntax error in {formula!r}: {error.msg}") from error


def formula_names(formula: str) -> set[str]:
    """Names referenced by a formula (after validating that its syntax is allowed)."""
    tree = _parse(formula)
    _check(tree.body, allowed_names=None)
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _check(node: ast.AST, allowed_names: frozenset[str] | None) -> None:
    match node:
        case ast.Constant(value=value):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise FormulaError(f"constant {value!r} is not a number {_where(node)}")
        case ast.Name(id=name):
            if allowed_names is not None and name not in allowed_names:
                raise FormulaError(f"unknown input {name!r} {_where(node)}")
        case ast.UnaryOp(op=op, operand=operand):
            if type(op) not in _UNARY:
                raise FormulaError(f"operator {type(op).__name__} is not allowed {_where(node)}")
            _check(operand, allowed_names)
        case ast.BinOp(left=left, op=op, right=right):
            if type(op) not in _BINARY:
                raise FormulaError(f"operator {type(op).__name__} is not allowed {_where(node)}")
            _check(left, allowed_names)
            _check(right, allowed_names)
        case _:
            raise FormulaError(f"{type(node).__name__} is not allowed {_where(node)}")


def _evaluate(node: ast.AST, inputs: Mapping[str, float]) -> float:
    match node:
        case ast.Constant(value=int() | float() as value):
            return float(value)
        case ast.Name(id=name):
            return float(inputs[name])
        case ast.UnaryOp(op=op, operand=operand):
            return _UNARY[type(op)](_evaluate(operand, inputs))
        case ast.BinOp(left=left, op=op, right=right):
            lhs, rhs = _evaluate(left, inputs), _evaluate(right, inputs)
            if isinstance(op, ast.Div) and rhs == 0.0:
                raise FormulaError("division by zero")
            if isinstance(op, ast.Pow) and abs(rhs) > MAX_EXPONENT:
                raise FormulaError(f"exponent {rhs} exceeds the limit of {MAX_EXPONENT}")
            try:
                result = _BINARY[type(op)](lhs, rhs)
            except (OverflowError, ZeroDivisionError) as error:
                raise FormulaError(f"arithmetic error: {error}") from error
            if isinstance(result, complex) or not math.isfinite(result):
                raise FormulaError("the result is not a finite real number")
            return float(result)
    raise FormulaError(f"{type(node).__name__} is not allowed {_where(node)}")


def evaluate_formula(formula: str, inputs: Mapping[str, float]) -> float:
    """Evaluate `formula` over `inputs`. Raises `FormulaError` on anything but plain arithmetic."""
    tree = _parse(formula)
    _check(tree.body, frozenset(inputs))
    return _evaluate(tree.body, inputs)


def topological_order(definitions: Sequence[KpiDef]) -> list[KpiDef]:
    """Definitions ordered so that every KPI comes after the KPIs it depends on.

    Ties keep the input order. Raises `FormulaError` on an unknown dependency or a cycle.
    """
    by_id = {d.id: d for d in definitions}
    if len(by_id) != len(definitions):
        raise FormulaError("duplicate KPI ids")
    for definition in definitions:
        for dependency in definition.depends_on:
            if dependency not in by_id:
                raise FormulaError(f"{definition.id} depends on unknown KPI {dependency!r}")

    ordered: list[KpiDef] = []
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(kpi_id: str, path: tuple[str, ...]) -> None:
        if state.get(kpi_id) == 2:
            return
        if state.get(kpi_id) == 1:
            cycle = " -> ".join((*path[path.index(kpi_id) :], kpi_id))
            raise FormulaError(f"dependency cycle: {cycle}")
        state[kpi_id] = 1
        for dependency in by_id[kpi_id].depends_on:
            visit(dependency, (*path, kpi_id))
        state[kpi_id] = 2
        ordered.append(by_id[kpi_id])

    for definition in definitions:
        visit(definition.id, ())
    return ordered
