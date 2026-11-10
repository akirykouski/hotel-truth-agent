"""Безопасный вычислитель выражений для рецептов характеристик.

Рецепты пишет LLM, поэтому никакого eval: разбираем выражение в AST и пропускаем только
арифметику, сравнения, логику, доступ к полям, списки/словари, генераторы и белый список функций.
К полям результатов инструментов можно обращаться через точку: r.minutes_there, v.sunset[7].from_floor.
"""
import ast
import operator as op

FUNCS = {"len": len, "min": min, "max": max, "any": any, "all": all, "round": round, "str": str, "int": int,
         "float": float, "sum": sum, "sorted": sorted, "abs": abs, "bool": bool, "list": list, "set": set,
         "dict": dict, "range": range}
BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
       ast.Mod: op.mod, ast.Pow: op.pow}
CMP = {ast.Eq: op.eq, ast.NotEq: op.ne, ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge,
       ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b, ast.Is: op.is_, ast.IsNot: op.is_not}
SAFE_METHODS = {"get", "lower", "upper", "startswith", "endswith", "join", "keys", "values", "items", "count",
                "split", "strip", "replace", "format"}


class ExprError(ValueError):
    pass


class Obj(dict):
    """Словарь, к ключам которого можно обращаться через точку; отсутствующий ключ = None."""

    def __getattr__(self, k):
        v = self.get(k)
        if v is None and isinstance(k, str) and k.isdigit():
            v = self.get(int(k))
        return wrap(v)


def wrap(v):
    if isinstance(v, dict) and not isinstance(v, Obj):
        return Obj({k: v2 for k, v2 in v.items()})
    if isinstance(v, list):
        return [wrap(x) for x in v]
    return v


def evaluate(expr, env):
    try:
        tree = ast.parse(str(expr).strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"синтаксис: {e.msg}") from None
    return _ev(tree.body, {k: wrap(v) for k, v in env.items()})


def _ev(n, env):
    t = type(n)
    if t is ast.Constant:
        return n.value
    if t is ast.Name:
        if n.id in env:
            return env[n.id]
        if n.id in FUNCS:
            return FUNCS[n.id]
        if n.id in ("None", "True", "False"):
            return {"None": None, "True": True, "False": False}[n.id]
        raise ExprError(f"неизвестное имя {n.id}")
    if t is ast.Attribute:
        base = _ev(n.value, env)
        if isinstance(base, dict):
            if n.attr in SAFE_METHODS and n.attr not in base:
                return getattr(base, n.attr)
            return wrap(base.get(n.attr))
        if isinstance(base, str) and n.attr in SAFE_METHODS:
            return getattr(base, n.attr)
        if base is None:
            return None
        raise ExprError(f"поле .{n.attr} недоступно")
    if t is ast.Slice:
        return slice(*(None if x is None else _ev(x, env) for x in (n.lower, n.upper, n.step)))
    if t is ast.Subscript:
        base = _ev(n.value, env)
        key = _ev(n.slice, env)
        if isinstance(key, slice):
            return None if base is None else wrap(base[key])
        if base is None:
            return None
        try:
            if isinstance(base, dict):
                v = base.get(key)
                if v is None:
                    v = base.get(str(key)) if not isinstance(key, str) else (base.get(int(key)) if key.isdigit() else None)
                return wrap(v)
            return wrap(base[key])
        except (IndexError, TypeError, KeyError):
            return None
    if t is ast.BinOp:
        a, b = _ev(n.left, env), _ev(n.right, env)
        if a is None or b is None:
            return None
        return BIN[type(n.op)](a, b)
    if t is ast.UnaryOp:
        v = _ev(n.operand, env)
        if isinstance(n.op, ast.Not):
            return not v
        if isinstance(n.op, ast.USub):
            return None if v is None else -v
        return v
    if t is ast.BoolOp:
        vals = None
        if isinstance(n.op, ast.And):
            for x in n.values:
                vals = _ev(x, env)
                if not vals:
                    return vals
            return vals
        for x in n.values:
            vals = _ev(x, env)
            if vals:
                return vals
        return vals
    if t is ast.Compare:
        left = _ev(n.left, env)
        for o, c in zip(n.ops, n.comparators):
            right = _ev(c, env)
            if left is None or right is None:
                if type(o) not in (ast.Eq, ast.NotEq, ast.Is, ast.IsNot):
                    return None
            if not CMP[type(o)](left, right):
                return False
            left = right
        return True
    if t is ast.IfExp:
        return _ev(n.body, env) if _ev(n.test, env) else _ev(n.orelse, env)
    if t is ast.Call:
        f = _ev(n.func, env)
        if not callable(f):
            raise ExprError("вызов не функции")
        args = [_ev(a, env) for a in n.args]
        return f(*args, **{k.arg: _ev(k.value, env) for k in n.keywords})
    if t in (ast.List, ast.Tuple, ast.Set):
        return [_ev(x, env) for x in n.elts]
    if t is ast.Dict:
        return {_ev(k, env): _ev(v, env) for k, v in zip(n.keys, n.values)}
    if t is ast.JoinedStr:
        return "".join(str(_ev(v.value, env)) if isinstance(v, ast.FormattedValue) else v.value for v in n.values)
    if t in (ast.ListComp, ast.GeneratorExp, ast.SetComp):
        return _comp(n, env)
    raise ExprError(f"конструкция {t.__name__} запрещена")


def _comp(n, env):
    out = []

    def rec(i, scope):
        if i == len(n.generators):
            out.append(_ev(n.elt, scope))
            return
        g = n.generators[i]
        it = _ev(g.iter, scope) or []
        for item in it:
            s = dict(scope)
            if isinstance(g.target, ast.Name):
                s[g.target.id] = wrap(item)
            elif isinstance(g.target, ast.Tuple):
                for tn, val in zip(g.target.elts, item):
                    s[tn.id] = wrap(val)
            if all(_ev(c, s) for c in g.ifs):
                rec(i + 1, s)

    rec(0, env)
    return out
