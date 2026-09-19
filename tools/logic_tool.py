"""check_logic: local propositional-logic checker (zero LLM calls).

Free-tier safe: pure stdlib, no model, no network, no embeddings.
Two operations (like csv_inspect):
- table: truth table for one formula.
- valid: check whether premises entail a conclusion, with a
  counterexample assignment when invalid.

Syntax (case-insensitive words, symbolic forms):
  NOT:  !  ~  NOT
  AND:  &  &&  AND
  OR:   |  ||  OR
  IMPLIES:  ->  =>  IMPLIES
  IFF:  <->  <=>  IFF
  parens ( ) and variables [A-Za-z][A-Za-z0-9_]* (True/False constants ok).

Bounds live in services.limits (MAX_LOGIC_*): formula length, var count
(2**n rows explode, so max 6 vars = 64 rows), premise count. Every
failure returns a STATUS= marker, never raises into the tool loop.
"""

import re
from typing import Dict, List, Tuple

from langchain_core.tools import tool

from services.limits import (
    MAX_LOGIC_FORMULA_CHARS,
    MAX_LOGIC_PREMISES,
    MAX_LOGIC_VARS,
)

_LOGIC_OPS = ("table", "valid")
_LOGIC_OUT_CHARS = 4000

_RESERVED = {"and", "or", "not", "implies", "iff", "true", "false"}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<iff><->|<=>)
    |(?P<implies>->|=>)
    |(?P<and>&&|&)
    |(?P<or>\|\||\|)
    |(?P<not>[!~])
    |(?P<lparen>\()
    |(?P<rparen>\))
    |(?P<word>[A-Za-z][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)

_PRECEDENCE = {"not": 4, "and": 3, "or": 2, "implies": 1, "iff": 0}
_RIGHT_ASSOC = {"not", "implies"}


def _cap(text: str) -> str:
    if len(text) > _LOGIC_OUT_CHARS:
        return text[:_LOGIC_OUT_CHARS] + "\n[Note: output truncated.]"
    return text


def _tokenize(formula: str) -> Tuple[List[Tuple[str, str]], str]:
    """Tokenize; returns (tokens, error). Tokens are (kind, value)."""
    tokens: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(formula):
        m = _TOKEN_RE.match(formula, pos)
        if not m:
            return [], f"unexpected character {formula[pos]!r} at position {pos}."
        pos = m.end()
        kind = m.lastgroup or ""
        val = m.group(0)
        if kind == "ws":
            continue
        if kind == "word":
            low = val.lower()
            if low in ("and",):
                tokens.append(("and", low))
            elif low in ("or",):
                tokens.append(("or", low))
            elif low in ("not",):
                tokens.append(("not", low))
            elif low in ("implies",):
                tokens.append(("implies", low))
            elif low in ("iff",):
                tokens.append(("iff", low))
            elif low in ("true", "false"):
                tokens.append(("const", "1" if low == "true" else "0"))
            elif low in ("t", "f"):
                # Single letters t/f collide with variables; keep as vars.
                tokens.append(("var", val))
            else:
                tokens.append(("var", val))
            continue
        if kind in ("iff", "implies", "and", "or", "not", "lparen", "rparen"):
            tokens.append((kind, val))
            continue
        return [], f"unexpected input near {val!r}."
    return tokens, ""


def _to_rpn(tokens: List[Tuple[str, str]]) -> Tuple[List[Tuple[str, str]], str]:
    """Shunting-yard to RPN; returns (rpn, error)."""
    out: List[Tuple[str, str]] = []
    stack: List[Tuple[str, str]] = []
    prev: str = ""
    for kind, val in tokens:
        if kind in ("var", "const"):
            if prev in ("var", "const", "rparen"):
                return [], "missing operator between terms."
            out.append((kind, val))
            prev = kind
        elif kind == "not":
            stack.append((kind, val))
            prev = kind
        elif kind in ("and", "or", "implies", "iff"):
            if prev in ("", "and", "or", "implies", "iff", "not", "lparen"):
                return [], f"missing operand before '{val}'."
            while stack:
                top = stack[-1][0]
                if top == "lparen":
                    break
                if (_PRECEDENCE[top] > _PRECEDENCE[kind] or (
                    _PRECEDENCE[top] == _PRECEDENCE[kind]
                    and kind not in _RIGHT_ASSOC
                )):
                    out.append(stack.pop())
                else:
                    break
            stack.append((kind, val))
            prev = kind
        elif kind == "lparen":
            if prev in ("var", "const", "rparen"):
                return [], "missing operator before '('."
            stack.append((kind, val))
            prev = kind
        elif kind == "rparen":
            if prev in ("", "and", "or", "implies", "iff", "not", "lparen"):
                return [], "missing operand before ')'."
            found = False
            while stack:
                top = stack.pop()
                if top[0] == "lparen":
                    found = True
                    break
                out.append(top)
            if not found:
                return [], "mismatched parenthesis."
            prev = "rparen"
    if prev in ("and", "or", "implies", "iff", "not", "lparen", ""):
        return [], "incomplete formula (trailing operator)."
    while stack:
        top = stack.pop()
        if top[0] in ("lparen", "rparen"):
            return [], "mismatched parenthesis."
        out.append(top)
    return out, ""


def _eval_rpn(rpn: List[Tuple[str, str]], env: Dict[str, bool]) -> bool:
    """Evaluate RPN under env. Raises ValueError on internal mismatch."""
    stack: List[bool] = []
    for kind, val in rpn:
        if kind == "var":
            stack.append(bool(env.get(val, False)))
        elif kind == "const":
            stack.append(val == "1")
        elif kind == "not":
            a = stack.pop()
            stack.append(not a)
        else:
            b = stack.pop()
            a = stack.pop()
            if kind == "and":
                stack.append(a and b)
            elif kind == "or":
                stack.append(a or b)
            elif kind == "implies":
                stack.append((not a) or b)
            elif kind == "iff":
                stack.append(a == b)
    if len(stack) != 1:
        raise ValueError("bad expression")
    return stack[0]


def _compile(formula: str) -> Tuple[List[Tuple[str, str]], List[str], str]:
    """Validate + compile; returns (rpn, sorted_vars, error)."""
    text = str(formula or "").strip()
    if not text:
        return [], [], "empty formula."
    if len(text) > MAX_LOGIC_FORMULA_CHARS:
        return [], [], (
            f"formula too long ({len(text)} chars, limit {MAX_LOGIC_FORMULA_CHARS})."
        )
    tokens, err = _tokenize(text)
    if err:
        return [], [], err
    if not tokens:
        return [], [], "empty formula."
    rpn, err2 = _to_rpn(tokens)
    if err2:
        return [], [], err2
    seen: Dict[str, None] = {}
    for kind, val in tokens:
        if kind == "var" and val not in seen:
            seen[val] = None
    var_list = sorted(seen)
    if len(var_list) > MAX_LOGIC_VARS:
        return [], [], (
            f"too many variables ({len(var_list)} > {MAX_LOGIC_VARS}); "
            "use fewer distinct letters."
        )
    return rpn, var_list, ""


def _split_premises(raw: str) -> List[str]:
    parts: List[str] = []
    for chunk in str(raw or "").replace("\r", "\n").split("\n"):
        for bit in chunk.split(";"):
            bit = bit.strip()
            if bit:
                parts.append(bit)
    return parts


@tool
def check_logic(
    operation: str = "table",
    formula: str = "",
    premises: str = "",
    conclusion: str = "",
) -> str:
    """Check propositional logic locally (no model, no network).

    Operations:
    - table: truth table for one formula. Args: formula="p -> q".
    - valid: do premises entail conclusion? Args: premises="p -> q\\np"
      (newline or ';' separated), conclusion="q". Reports VALID or
      INVALID with a counterexample assignment.

    Operators: ! ~ NOT, & && AND, | || OR, -> => IMPLIES, <-> <=> IFF,
    parens, variables (letters). Max 6 distinct variables (64 rows).

    Returns:
        Table or verdict text, or a STATUS= error marker.
    """
    op = str(operation or "").strip().lower()
    if op not in _LOGIC_OPS:
        return (
            f"STATUS=INVALID tool=check_logic: unknown operation '{operation}'. "
            f"Supported: {', '.join(_LOGIC_OPS)}."
        )
    try:
        if op == "table":
            rpn, var_list, err = _compile(formula)
            if err:
                return f"STATUS=INVALID tool=check_logic: {err}"
            n = len(var_list)
            lines = [f"Variables: {', '.join(var_list) if var_list else '(none, constant)'}"]
            header = " | ".join(var_list + ["result"]) if var_list else "result"
            lines.append(header)
            total = 2 ** n if n else 1
            for row in range(total):
                env = {v: bool((row >> (n - 1 - i)) & 1) for i, v in enumerate(var_list)}
                try:
                    val = _eval_rpn(rpn, env)
                except Exception as e:
                    return f"STATUS=FAILED tool=check_logic: evaluation failed ({str(e)[:120]})."
                if var_list:
                    bits = " | ".join("T" if env[v] else "F" for v in var_list)
                    lines.append(f"{bits} | {'T' if val else 'F'}")
                else:
                    lines.append("T" if val else "F")
            lines.append(f"Rows: {total}. T=true, F=false.")
            return _cap("\n".join(lines))

        # op == "valid"
        prem_list = _split_premises(premises)
        concl = str(conclusion or "").strip()
        if not prem_list:
            return "STATUS=INVALID tool=check_logic: valid needs premises (newline or ';' separated)."
        if not concl:
            return "STATUS=INVALID tool=check_logic: valid needs a conclusion."
        if len(prem_list) > MAX_LOGIC_PREMISES:
            return (
                f"STATUS=INVALID tool=check_logic: too many premises "
                f"({len(prem_list)} > {MAX_LOGIC_PREMISES})."
            )
        compiled = []
        all_vars: Dict[str, None] = {}
        for p in prem_list:
            rpn, var_list, err = _compile(p)
            if err:
                return f"STATUS=INVALID tool=check_logic: bad premise {p!r}: {err}"
            compiled.append(rpn)
            for v in var_list:
                all_vars[v] = None
        rpn_c, var_c, err_c = _compile(concl)
        if err_c:
            return f"STATUS=INVALID tool=check_logic: bad conclusion: {err_c}"
        for v in var_c:
            all_vars[v] = None
        var_list = sorted(all_vars)
        if len(var_list) > MAX_LOGIC_VARS:
            return (
                f"STATUS=INVALID tool=check_logic: too many variables "
                f"({len(var_list)} > {MAX_LOGIC_VARS})."
            )
        n = len(var_list)
        total = 2 ** n if n else 1
        for row in range(total):
            env = {v: bool((row >> (n - 1 - i)) & 1) for i, v in enumerate(var_list)}
            try:
                pre_vals = [_eval_rpn(r, env) for r in compiled]
                c_val = _eval_rpn(rpn_c, env)
            except Exception as e:
                return f"STATUS=FAILED tool=check_logic: evaluation failed ({str(e)[:120]})."
            if all(pre_vals) and not c_val:
                show = ", ".join(f"{v}={'T' if env[v] else 'F'}" for v in var_list)
                return (
                    "STATUS=OK tool=check_logic: INVALID — premises do not entail "
                    f"the conclusion. Counterexample: {show} "
                    "(all premises true, conclusion false)."
                )
        return (
            "STATUS=OK tool=check_logic: VALID — every assignment making "
            f"all {len(prem_list)} premise(s) true also makes the conclusion true "
            f"(checked {total} row(s))."
        )
    except Exception as e:
        return f"STATUS=FAILED tool=check_logic: {str(e)[:200]}"
