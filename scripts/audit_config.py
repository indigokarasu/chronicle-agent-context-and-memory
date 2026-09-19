#!/usr/bin/env python3
"""
Chronicle config audit (§A12) — every DEFAULTS key vs. the code that reads it.

Chronicle's premise is that config never promises what code does not deliver.
This script is the mechanical check of that promise: it walks every leaf key in
`engine.config.DEFAULTS` and decides, from the AST of the shipped source, one of

    WIRED    — some module actually reads this key
    DORMANT  — nothing reads it AND `engine.config.DECLARED_DORMANT` says so,
               with a stated reason (an admitted gap, not a surprise)
    UNREAD   — nothing reads it and nothing declares it. This is the defect.

`tests/test_config_honesty.py` turns the UNREAD count into a failing test, so a
new key that nothing reads cannot land quietly.

WHY AN AST AND NOT A REGEX
--------------------------
The previous version grepped for `cfg.get("<path>"` and reported 138 of 233 keys
as "possibly-dormant" — it could not see `_clamp_cfg(self.cfg, "retrieval.
rerank_top_k", ...)`, a sub-dict fetched once and indexed later (`w = cfg.get(
"context_engine.keep_weights"); w.get("recency")`), or a dynamic key template
(`cfg.get(f"sweeps.budgets.{name}")`). Nobody trusted its output, which is the
same failure mode as the config it audits.

The loose fix — "treat any quoted dotted string as a read" — was measured and
rejected (A3): it flips genuinely-unread keys such as `provider` and `store` to
WIRED because those words appear as quoted literals all over the tree. So this
scanner requires a string literal to REACH a config accessor, through one of the
shapes the codebase actually uses:

  1. direct        `cfg.get("a.b")`, `self.cfg["a.b"]`, `self.core.cfg.get(...)`
  2. helper param  `_clamp_cfg(self.cfg, "a.b", ...)` — recognised because
                   `_clamp_cfg`'s own body does `cfg.get(key)` on that parameter
  3. sub-dict      `gf = cfg.get("health.ghost_fact"); gf.get("age_days")`,
                   including one hop into a callee (`self._ghost_facts(gf)`)
  4. template      `cfg.get(f"sweeps.budgets.{name}")` — the fragment resolves
                   to the literals its call sites pass, and to a `*` wildcard
                   only when they cannot be resolved
  5. table-driven  `for name, key in _SCHEDULES: cfg.get(key)` — literals in a
                   collection that is iterated into a config read

Usage:  python3 scripts/audit_config.py [--json] [--unread-only]
Exit:   0 always (the report is a report; the TEST is the gate)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.config import DECLARED_DORMANT, DEFAULTS  # noqa: E402

# Attribute/variable names that hold a Config (or a plain merged config dict).
# `self.cfg`, `self.core.cfg`, a bare `cfg` parameter, `self.config`.
CONFIG_OBJ_NAMES = frozenset({"cfg", "config", "_cfg"})

# One path segment we could not resolve to a literal (an f-string hole whose
# value the call sites do not pin down). Matches any single segment.
WILD = "*"
# Everything below this point is consumed wholesale (`for k in sub:`,
# `sub.items()`, `dict(sub)`): every descendant counts as read.
DEEP = "**"

# Files whose config reads count. Tests are deliberately excluded: a test
# reading a key does not make the engine honour it.
SOURCE_GLOBS = ("engine/*.py", "*.py", "dashboard/*.py", "scripts/*.py")
SELF_NAME = "audit_config.py"


# --------------------------------------------------------------------------
# key inventory
# --------------------------------------------------------------------------

def leaf_keys(d, prefix=""):
    """Flatten DEFAULTS to (dotted path, value). An EMPTY dict is a leaf.

    The old version recursed into `{}` and emitted nothing, so `federation.pins`
    simply vanished from the audit — a key the report could never mention.
    """
    out = []
    for k, v in (d or {}).items():
        full = "{}.{}".format(prefix, k) if prefix else str(k)
        if isinstance(v, dict) and v:
            out.extend(leaf_keys(v, full))
        else:
            out.append((full, v))
    return out


# --------------------------------------------------------------------------
# AST helpers
# --------------------------------------------------------------------------

def _is_config_obj(node):
    """`cfg` / `self.cfg` / `self.core.cfg` / `config` / `self._cfg`."""
    if isinstance(node, ast.Name):
        return node.id in CONFIG_OBJ_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in CONFIG_OBJ_NAMES
    return False


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _seg_concat(cur, text):
    """Append literal `text` to the segment being built (WILD absorbs)."""
    if cur is WILD:
        return WILD
    return cur + text


def _split_into(segs, cur, text):
    """Consume `text` (which may contain dots) into (segs, cur)."""
    pieces = text.split(".")
    cur = _seg_concat(cur, pieces[0])
    for p in pieces[1:]:
        segs.append(cur)
        cur = p
    return segs, cur


class _LiteralEnv:
    """Names bound to string literals, and names bound to collections of them.

    Populated from assignments and `for` targets in the scope being scanned,
    plus module-level constants (the table-driven case: a module tuple of key
    names iterated into a config read).
    """

    def __init__(self, parent=None):
        self.vals = {}
        self.hidden = set()
        self.parent = parent

    def shadow(self, names):
        """Declare names as local-and-unknown (function parameters).

        Without this, `cfg.get(f"context_engine.{name}")` inside a helper whose
        `name` is a PARAMETER would resolve against some unrelated module-level
        `name = "chronicle"` and invent a read of a key nobody reads.
        """
        self.hidden.update(names)

    def get(self, name):
        cur = self
        while cur is not None:
            if name in cur.vals:
                return cur.vals[name]
            if name in cur.hidden:
                return None
            cur = cur.parent
        return None

    def set(self, name, values):
        if values:
            self.vals.setdefault(name, set()).update(values)


def _collect_literals(node, env):
    """Every string literal reachable inside a collection/constant expression."""
    if node is None:
        return set()
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out = set()
        for e in node.elts:
            out |= _collect_literals(e, env)
        return out
    if isinstance(node, ast.Dict):
        out = set()
        for k in node.keys:
            out |= _collect_literals(k, env)
        for v in node.values:
            out |= _collect_literals(v, env)
        return out
    if isinstance(node, ast.Name):
        return set(env.get(node.id) or ())
    if isinstance(node, ast.Call):
        # `TBL.items()` / `sorted(TBL)` / `list(TBL)` — look through one level.
        out = set()
        if isinstance(node.func, ast.Attribute):
            out |= _collect_literals(node.func.value, env)
        for a in node.args:
            out |= _collect_literals(a, env)
        return out
    if isinstance(node, ast.Subscript):
        return _collect_literals(node.value, env)
    return set()


def _tuple_positions(node, env):
    """For `for a, b in TBL`: literals available at each tuple position.

    Returns a list of sets, or None when the collection is not a literal list
    of same-shaped tuples.
    """
    elts = None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        elts = node.elts
    elif isinstance(node, ast.Name):
        return None
    if elts is None:
        return None
    cols = []
    for e in elts:
        if not isinstance(e, (ast.Tuple, ast.List)):
            return None
        for i, sub in enumerate(e.elts):
            while len(cols) <= i:
                cols.append(set())
            s = _const_str(sub)
            if s is not None:
                cols[i].add(s)
    return cols or None


def _template_parts(node, env):
    """Break a string-building expression into ('t', text) / ('v', node) parts.

    One code path for every template shape the tree uses: f-strings,
    `"a.{}.b".format(x)`, `"a.%s.b" % x` and `"a." + x`. Returns None when the
    expression is not a template at all.
    """
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            text = _const_str(piece)
            if text is not None:
                parts.append(("t", text))
            elif isinstance(piece, ast.FormattedValue):
                parts.append(("v", piece.value))
            else:
                return None
        return parts

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _const_str(node.left), _const_str(node.right)
        if left is None:
            return None
        return [("t", left)] + ([("t", right)] if right is not None else [("v", node.right)])

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        tmpl = _const_str(node.left)
        if tmpl is None or "%s" not in tmpl:
            return None
        args = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
        return _interleave(tmpl.split("%s"), args)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "format":
        tmpl = _const_str(node.func.value)
        if tmpl is None or "{}" not in tmpl:
            return None
        return _interleave(tmpl.split("{}"), list(node.args))

    return None


def _interleave(chunks, args):
    parts = [("t", chunks[0])]
    for i, chunk in enumerate(chunks[1:]):
        parts.append(("v", args[i]) if i < len(args) else ("v", None))
        parts.append(("t", chunk))
    return parts


def _template_alts(parts, env):
    """Segment tuples a part list can evaluate to (WILD for unresolved holes)."""
    states = [([], "")]
    for kind, payload in parts:
        if kind == "t":
            states = [_split_into(list(segs), cur, payload) for segs, cur in states]
            continue
        vals = _literal_or_none(payload, env) if payload is not None else None
        new_states = []
        for segs, cur in states:
            if vals:
                for v in sorted(vals):
                    new_states.append(_split_into(list(segs), cur, str(v)))
            else:
                new_states.append((list(segs), WILD))
        states = new_states
    return [tuple(segs + [cur]) for segs, cur in states]


def _splice(template, pattern):
    """Fill a (prefix, suffix) key template with the segments a caller supplies."""
    prefix, suffix = template
    return tuple(prefix) + tuple(pattern) + tuple(suffix)


def _key_patterns(node, env):
    """Segment tuples a key expression can evaluate to.

    Returns [] when the expression is not a config path at all.
    """
    s = _const_str(node)
    if s is not None:
        return [tuple(s.split("."))]

    if isinstance(node, ast.Name):
        vals = env.get(node.id)
        if vals:
            return [tuple(v.split(".")) for v in sorted(vals) if isinstance(v, str)]
        return []

    parts = _template_parts(node, env)
    if parts is not None:
        return _template_alts(parts, env)
    return []


def _literal_or_none(node, env):
    s = _const_str(node)
    if s is not None:
        return {s}
    if isinstance(node, ast.Name):
        vals = env.get(node.id)
        return set(vals) if vals else None
    return None


# --------------------------------------------------------------------------
# the scanner
# --------------------------------------------------------------------------

class Read:
    """One recorded read of a config path pattern."""

    __slots__ = ("pattern", "kind", "where")

    def __init__(self, pattern, kind, where):
        self.pattern = pattern
        self.kind = kind          # direct | helper | subdict | template | table
        self.where = where        # "file:line"

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Read({}, {}, {})".format(".".join(self.pattern), self.kind, self.where)


class ConfigReadScanner:
    """Collects config-read patterns from a set of Python source files."""

    def __init__(self, files, defaults=None):
        self.defaults = DEFAULTS if defaults is None else defaults
        self.files = list(files)
        self.trees = {}
        self.reads = []
        self.functions = {}        # simple name -> [(relpath, FunctionDef)]
        self.module_env = {}       # relpath -> _LiteralEnv
        # (func simple name, param name) -> list of prefix segment tuples that a
        # literal argument in that position completes. () means "whole path".
        self.path_params = {}
        self._seen_prefix_jobs = set()
        # Parameters of the function currently being scanned that are config
        # path/fragment parameters (`_clamp_cfg`'s `key`, `_cfg_percent`'s
        # `name`). A read written in terms of one of them must NOT be recorded
        # as a wildcard over the whole subtree: `cfg.get(f"context_engine.
        # {name}")` inside the helper would otherwise wire `context_engine.
        # engine`, `.never_evict` and `.standalone_fallback`, none of which any
        # caller ever asks for. The CALL SITES are the evidence; the helper body
        # is just plumbing.
        self._param_keys = frozenset()
        self._rel = ""          # file currently being scanned
        # (file, function, param) fragment slots that at least one call site
        # pinned down with a literal. A slot nobody ever resolves is genuinely
        # dynamic, and _fallback_wildcards below then says so.
        self._resolved_params = set()

    # -- entry point ------------------------------------------------------
    def scan(self):
        for path in self.files:
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except (SyntaxError, OSError):
                continue
            rel = str(path.relative_to(REPO)) if REPO in path.parents else path.name
            self.trees[rel] = tree
        for rel, tree in self.trees.items():
            self._index_module(rel, tree)
        # Pass 1: which function parameters are config paths / path fragments.
        for _ in range(2):          # one extra round: helpers calling helpers
            self._find_path_params()
        # Pass 2: walk every function body (and module level) recording reads.
        for rel, tree in self.trees.items():
            self._scan_scope(rel, tree, _LiteralEnv(self.module_env[rel]), {})
        self._fallback_wildcards()
        return self

    def _fallback_wildcards(self):
        """A key template no caller ever pins down really is dynamic.

        `cfg.get(f"sweeps.budgets.{name}")` inside the helper is suppressed while
        the call sites are being read, because the call sites are the better
        evidence -- that is what stops the helper body from wiring every key
        under its prefix. But if NO call site resolves to a literal, suppressing
        it would lose the read entirely, so the wildcard comes back here.

        Whole-path parameters (`_clamp_cfg`'s `key`) are excluded: a wildcard
        with no prefix would match every top-level key in DEFAULTS at once.
        """
        for (rel, func, param), templates in sorted(self.path_params.items()):
            if (rel, func, param) in self._resolved_params:
                continue
            for tmpl in templates:
                if not (tmpl[0] or tmpl[1]):
                    continue
                self.reads.append(
                    Read(_splice(tmpl, (WILD,)), "template", "{}:{}".format(rel, func)))

    # -- indexing ---------------------------------------------------------
    def _index_module(self, rel, tree):
        env = _LiteralEnv()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append((rel, node))
            elif isinstance(node, ast.ClassDef):
                # `Topology(principals_cfg)` must resolve to Topology.__init__,
                # or the principals sub-dict stops at the constructor.
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and sub.name == "__init__":
                        self.functions.setdefault(node.name, []).append((rel, sub))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                vals = _collect_literals(node.value, env)
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        env.set(tgt.id, vals)
        self.module_env[rel] = env

    def _find_path_params(self):
        """A parameter used AS a config key is a config-path parameter.

        `_clamp_cfg(cfg, key, ...)` does `cfg.get(key, default)` → `key` is a
        whole path. `sweep_budget(cfg, name)` does `cfg.get(f"sweeps.budgets.
        {name}")` → `name` completes the prefix ("sweeps", "budgets").
        """
        for rel, tree in self.trees.items():
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                params = {a.arg for a in node.args.args + node.args.kwonlyargs}
                for sub in ast.walk(node):
                    key_node = self._key_node_of_config_read(sub)
                    if key_node is None:
                        continue
                    for param, tmpl in self._param_holes(key_node, params):
                        slot = (rel, node.name, param)
                        self.path_params.setdefault(slot, [])
                        if tmpl not in self.path_params[slot]:
                            self.path_params[slot].append(tmpl)
                # a helper that forwards its param into ANOTHER helper's path slot
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    callee = self._callee_name(sub)
                    if callee is None:
                        continue
                    for arg_node, argname, drel in self._named_args(sub, callee, rel):
                        if not isinstance(arg_node, ast.Name):
                            continue
                        if arg_node.id not in params:
                            continue
                        for tmpl in self.path_params.get((drel, callee, argname), []):
                            slot = (rel, node.name, arg_node.id)
                            self.path_params.setdefault(slot, [])
                            if tmpl not in self.path_params[slot]:
                                self.path_params[slot].append(tmpl)

    @staticmethod
    def _param_holes(key_node, params):
        """(param, (prefix, suffix)) templates this key expression depends on.

        The hole is not always last: `contradiction_policy` reads
        `"domains.{}.contradiction_policy".format(domain)`, so the parameter
        fills the MIDDLE segment and a caller's literal has to be spliced in,
        not appended.
        """
        out = []
        if isinstance(key_node, ast.Name) and key_node.id in params:
            return [(key_node.id, ((), ()))]
        parts = _template_parts(key_node, None)
        if not parts:
            return out
        holes = []          # (param, index of the segment it fills)
        segs, cur = [], ""
        for kind, payload in parts:
            if kind == "t":
                segs, cur = _split_into(segs, cur, payload)
                continue
            if isinstance(payload, ast.Name) and payload.id in params and cur == "":
                holes.append((payload.id, len(segs)))
            segs, cur = list(segs), WILD
        full = tuple(segs + [cur])
        for param, idx in holes:
            out.append((param, (full[:idx], full[idx + 1:])))
        return out

    # -- read detection ---------------------------------------------------
    @staticmethod
    def _key_node_of_config_read(node):
        """`cfgobj.get(K, ...)` / `cfgobj[K]` → the key expression node."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and _is_config_obj(node.func.value) \
                and node.args:
            return node.args[0]
        if isinstance(node, ast.Subscript) and _is_config_obj(node.value):
            sl = node.slice
            if isinstance(sl, ast.Index):        # py<3.9 shape, harmless here
                sl = sl.value                    # pragma: no cover
            return sl
        return None

    @staticmethod
    def _callee_name(call):
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    def _defs_for(self, callee, rel):
        """Definitions of `callee`, preferring the ones in the calling file.

        `engine/hostmodel.py`, `engine/retrieval.py` and a test fixture can all
        define `_clamp` with different signatures; binding a call to the wrong
        one silently shifts every argument position.
        """
        defs = self.functions.get(callee) or []
        same = [d for d in defs if d[0] == rel]
        return same or defs

    def _named_args(self, call, callee, rel):
        """Yield (arg node, parameter name, defining file) for a resolvable callee."""
        for drel, fn in self._defs_for(callee, rel):
            names = [a.arg for a in fn.args.args]
            if names and names[0] in ("self", "cls"):
                names = names[1:]
            for i, arg in enumerate(call.args):
                if i < len(names):
                    yield arg, names[i], drel
            for kw in call.keywords:
                if kw.arg:
                    yield kw.value, kw.arg, drel

    # -- scope walking ----------------------------------------------------
    def _scan_scope(self, rel, scope_node, env, prefixes):
        self._rel = rel
        """Record reads inside one scope.

        `prefixes` maps a local variable name to the set of config path prefixes
        it holds (a sub-dict pulled out of the config).
        """
        body = scope_node.body if hasattr(scope_node, "body") else []
        saved = self._param_keys
        if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [a.arg for a in scope_node.args.args + scope_node.args.kwonlyargs]
            env.shadow(p for p in params if p not in prefixes)
            self._param_keys = frozenset(
                p for p in params if (rel, scope_node.name, p) in self.path_params)
        for stmt in body:
            self._scan_stmt(rel, stmt, env, prefixes)
        self._param_keys = saved

    def _scan_stmt(self, rel, stmt, env, prefixes):
        self._rel = rel
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # ONE env and ONE prefix map for the whole body: a sub-dict bound on
            # line 3 must still be known on line 4 (that is the entire point of
            # the sub-dict rule).
            sub_env = _LiteralEnv(env)
            params = [a.arg for a in stmt.args.args + stmt.args.kwonlyargs]
            sub_env.shadow(params)
            sub_prefixes = {}
            saved = self._param_keys
            self._param_keys = frozenset(
                p for p in params if (rel, stmt.name, p) in self.path_params)
            for s in stmt.body:
                self._scan_stmt(rel, s, sub_env, sub_prefixes)
            self._param_keys = saved
            return
        if isinstance(stmt, ast.ClassDef):
            sub_env = _LiteralEnv(env)
            sub_prefixes = dict(prefixes)
            for s in stmt.body:
                self._scan_stmt(rel, s, sub_env, sub_prefixes)
            return

        # bindings introduced BY this statement, before its expressions are read
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._bind_for(stmt, env, prefixes)
            if isinstance(stmt.iter, ast.Name) and stmt.iter.id in prefixes:
                where = "{}:{}".format(rel, getattr(stmt, "lineno", 0))
                for pref in prefixes[stmt.iter.id]:
                    self.reads.append(Read(tuple(pref) + (DEEP,), "subdict", where))
        if isinstance(stmt, ast.Assign):
            self._bind_assign(rel, stmt, env, prefixes)
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if isinstance(item.optional_vars, ast.Name):
                    pats = self._sub_dict_source(item.context_expr, env, prefixes)
                    if pats:
                        prefixes.setdefault(item.optional_vars.id, set()).update(pats)

        # every expression this statement owns (nested statements handled below)
        for child in ast.iter_child_nodes(stmt):
            if not isinstance(child, ast.expr):
                continue
            for node in ast.walk(child):
                self._scan_expr(rel, node, env, prefixes)

        # nested statement lists
        for field in ("body", "orelse", "finalbody"):
            for s in getattr(stmt, field, None) or []:
                if isinstance(s, ast.stmt):
                    self._scan_stmt(rel, s, env, prefixes)
        for handler in getattr(stmt, "handlers", None) or []:
            for s in handler.body:
                self._scan_stmt(rel, s, env, prefixes)

    def _bind_for(self, stmt, env, prefixes):
        if isinstance(stmt.target, ast.Name):
            vals = _collect_literals(stmt.iter, env)
            env.set(stmt.target.id, vals)
        elif isinstance(stmt.target, ast.Tuple):
            cols = _tuple_positions(stmt.iter, env)
            if cols:
                for i, tgt in enumerate(stmt.target.elts):
                    if isinstance(tgt, ast.Name) and i < len(cols):
                        env.set(tgt.id, cols[i])
            else:
                vals = _collect_literals(stmt.iter, env)
                for tgt in stmt.target.elts:
                    if isinstance(tgt, ast.Name):
                        env.set(tgt.id, vals)

    def _bind_assign(self, rel, stmt, env, prefixes):
        vals = _collect_literals(stmt.value, env)
        for tgt in stmt.targets:
            if isinstance(tgt, ast.Name):
                env.set(tgt.id, vals)
        # sub-dict binding: `w = cfg.get("context_engine.keep_weights", {})`
        pats = self._sub_dict_source(stmt.value, env, prefixes)
        if not pats:
            return
        pats = {p for p in pats if _is_dict_path(p, self.defaults)}
        for tgt in stmt.targets:
            if isinstance(tgt, ast.Name):
                prefixes.setdefault(tgt.id, set()).update(pats)

    def _sub_dict_source(self, node, env, prefixes):  # noqa: C901
        """Patterns a value expression carries as a config SUB-DICT prefix."""
        if isinstance(node, ast.BoolOp):            # `cfg.get(x) or {}`
            out = set()
            for v in node.values:
                out |= self._sub_dict_source(v, env, prefixes)
            return out
        if isinstance(node, ast.IfExp):             # `cfg.get(x) if core else {}`
            return self._sub_dict_source(node.body, env, prefixes) | \
                self._sub_dict_source(node.orelse, env, prefixes)
        if isinstance(node, ast.Name):
            return set(prefixes.get(node.id) or ())
        key_node = self._key_node_of_config_read(node)
        if key_node is not None:
            return set(_key_patterns(key_node, env))
        # helper call in a path-param slot returning a sub-dict
        if isinstance(node, ast.Call):
            callee = self._callee_name(node)
            if callee:
                out = set()
                for arg, argname, drel in self._named_args(node, callee, self._rel):
                    for tmpl in self.path_params.get((drel, callee, argname), []):
                        for pat in _key_patterns(arg, env):
                            out.add(_splice(tmpl, pat))
                return out
        return set()

    def _scan_expr(self, rel, node, env, prefixes):
        line = getattr(node, "lineno", 0)
        where = "{}:{}".format(rel, line)

        # 0. sub-dict member access — checked FIRST, because a callee parameter
        #    that holds a sub-dict is often itself named `cfg` (engine/access.py
        #    Topology). Reading a member off it is a read of the CHILD path.
        base, member = self._prefixed_member(node, prefixes)
        if base is not None:
            for pref in prefixes[base]:
                subs = _key_patterns(member, env)
                if subs:
                    for sub in subs:
                        self.reads.append(Read(tuple(pref) + sub, "subdict", where))
                else:
                    self.reads.append(Read(tuple(pref) + (WILD,), "subdict", where))
            return

        # 1. direct config read
        key_node = self._key_node_of_config_read(node)
        if key_node is not None:
            if self._is_param_key_expr(key_node):
                return
            kind = "direct" if _const_str(key_node) is not None else "template"
            for pat in _key_patterns(key_node, env):
                self.reads.append(Read(pat, kind, where))
            return

        # 2/4. helper with a config-path parameter
        if isinstance(node, ast.Call):
            callee = self._callee_name(node)
            if callee:
                for arg, argname, drel in self._named_args(node, callee, rel):
                    for tmpl in self.path_params.get((drel, callee, argname), []):
                        pats = _key_patterns(arg, env)
                        if pats:
                            self._resolved_params.add((drel, callee, argname))
                        for pat in pats:
                            self.reads.append(Read(_splice(tmpl, pat), "helper", where))
                        if not pats and (tmpl[0] or tmpl[1]) \
                                and not self._is_param_key_expr(arg):
                            # A genuinely dynamic call site: the caller computes
                            # the fragment at runtime, so every declared key the
                            # template can name really is in play.
                            self.reads.append(Read(_splice(tmpl, (WILD,)), "template", where))
            # 3. one hop: a sub-dict handed to another function or constructor
            if callee:
                for arg, argname, drel in self._named_args(node, callee, rel):
                    for pat in self._sub_dict_source(arg, env, prefixes):
                        if _is_dict_path(pat, self.defaults):
                            self._enqueue_prefixed_callee(drel, callee, argname, pat)

        # 3b. wholesale consumption of a sub-dict → the whole subtree is read
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("items", "values", "keys") \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in prefixes:
            for pref in prefixes[node.func.value.id]:
                self.reads.append(Read(tuple(pref) + (DEEP,), "subdict", where))

    def _is_param_key_expr(self, node):
        """Does this key expression get its value from a config-path parameter?"""
        if not self._param_keys:
            return False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in self._param_keys:
                return True
        return False

    @staticmethod
    def _prefixed_member(node, prefixes):
        """(base var, member key node) when `node` reads a member off a var that
        holds a config sub-dict: `w.get("recency")`, `w["recency"]`,
        `"recency" in w`."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in prefixes and node.args:
            return node.func.value.id, node.args[0]
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id in prefixes:
            member = node.slice
            if isinstance(member, ast.Index):          # pragma: no cover (py<3.9)
                member = member.value
            return node.value.id, member
        if isinstance(node, ast.Compare) and node.ops and \
                isinstance(node.ops[0], (ast.In, ast.NotIn)) and \
                isinstance(node.comparators[0], ast.Name) and \
                node.comparators[0].id in prefixes:
            return node.comparators[0].id, node.left
        return None, None

    def _enqueue_prefixed_callee(self, drel, callee, argname, pattern):
        job = (drel, callee, argname, pattern)
        if job in self._seen_prefix_jobs:
            return
        self._seen_prefix_jobs.add(job)
        for rel, fn in self._defs_for(callee, drel):
            env = _LiteralEnv(self.module_env.get(rel) or _LiteralEnv())
            self._scan_scope(rel, fn, env, {argname: {pattern}})


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def _is_dict_path(pattern, defaults=None):
    """Does this pattern name a dict-valued node in DEFAULTS?

    Only a dict can be a sub-dict prefix. Without this check a helper that
    returns a scalar (`sweep_budget(cfg, "decay")` -> int) would seed a prefix
    and every subsequent `.get(...)` on that variable would invent a read.
    """
    defaults = DEFAULTS if defaults is None else defaults
    cur = defaults
    for seg in pattern:
        if seg in (WILD, DEEP):
            if not isinstance(cur, dict):
                return False
            nxt = [v for v in cur.values() if isinstance(v, dict)]
            if not nxt:
                return False
            cur = nxt[0]
            continue
        if not isinstance(cur, dict) or seg not in cur:
            return False
        cur = cur[seg]
    return isinstance(cur, dict)


def pattern_matches(pattern, path_segments):
    """Does a recorded read pattern cover this DEFAULTS leaf path?"""
    pi = 0
    for i, seg in enumerate(pattern):
        if seg == DEEP:
            return i <= len(path_segments)
        if pi >= len(path_segments):
            return False
        if seg != WILD and seg != path_segments[pi]:
            return False
        pi += 1
    return pi == len(path_segments)


def source_files(repo=REPO):
    seen, out = set(), []
    for glob in SOURCE_GLOBS:
        for p in sorted(repo.glob(glob)):
            if p.name == SELF_NAME or p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def audit(repo=REPO, defaults=None, extra_files=()):
    """Return {path: (status, kind, evidence)} for every DEFAULTS leaf."""
    defaults = DEFAULTS if defaults is None else defaults
    files = list(source_files(repo)) + [Path(f) for f in extra_files]
    scanner = ConfigReadScanner(files, defaults).scan()
    result = {}
    for path, _val in sorted(leaf_keys(defaults)):
        segs = tuple(path.split("."))
        hit = None
        for read in scanner.reads:
            if pattern_matches(read.pattern, segs):
                # prefer an exact/direct read as the reported evidence
                if hit is None or (hit.kind != "direct" and read.kind == "direct"):
                    hit = read
                if hit.kind == "direct":
                    break
        if hit is not None:
            result[path] = ("WIRED", hit.kind, hit.where)
        elif path in DECLARED_DORMANT:
            result[path] = ("DORMANT", "declared", DECLARED_DORMANT[path])
        else:
            result[path] = ("UNREAD", "", "")
    return result


#: Literal config reads that do NOT resolve in DEFAULTS and are not defects.
#: Every entry needs a reason, and the list is meant to stay short — the point
#: of `undeclared_literal_reads` is that a new entry is a bug until proven
#: otherwise, exactly as DECLARED_DORMANT works in the other direction.
ALLOWED_UNDECLARED_READS = {
    # engine/access.py's `cfg` is NOT a Config: `Topology.__init__` does
    # `cfg = principals_cfg or {}`, i.e. it already holds the `principals`
    # sub-dict, so `cfg.get("users")` is really `principals.users` (declared,
    # and read). The scanner keys on the NAME `cfg`, so it cannot see that.
    # Resolving these would mean teaching the scanner local rebinding; naming
    # them is cheaper and does not weaken the guard for anything else.
    "default_cross_agent_read": "engine/access.py: local `cfg` is the principals sub-dict",
    "users": "engine/access.py: local `cfg` is the principals sub-dict",
    "agents": "engine/access.py: local `cfg` is the principals sub-dict",
}


def undeclared_literal_reads(repo=REPO, defaults=None, extra_files=()):
    """The MIRROR of `audit`: config paths the code READS that DEFAULTS lacks.

    `audit` walks DEFAULTS and asks "is this key read?". That direction alone
    is one-sided, and the v5.7.0 pre-ship review found the hole: a duplicate
    `"health"` literal in DEFAULTS deleted two keys the engine reads, and the
    audit still reported "UNREAD 0" because it never looks at reads that have
    no key. Runtime survived only because both readers passed an inline default
    that happened to match; the keys were simply gone from the config surface.

    Only FULLY LITERAL, DIRECT reads are checked. A pattern carrying a WILD or
    DEEP segment is by construction not a claim about one key, and an indirect
    read (helper / sub-dict / template) is evidence about a prefix rather than
    a path. Those are the shapes that produce false positives, and a guard that
    cries wolf gets disabled.

    Returns {dotted path: sorted [file:line, ...]}, excluding
    ALLOWED_UNDECLARED_READS.
    """
    defaults = DEFAULTS if defaults is None else defaults
    files = list(source_files(repo)) + [Path(f) for f in extra_files]
    scanner = ConfigReadScanner(files, defaults).scan()
    out = {}
    for read in scanner.reads:
        if read.kind != "direct":
            continue
        if WILD in read.pattern or DEEP in read.pattern:
            continue
        cur, resolved = defaults, True
        for seg in read.pattern:
            # membership, not truthiness: a key whose declared value is None,
            # 0, "" or [] still resolves, and several are.
            if not isinstance(cur, dict) or seg not in cur:
                resolved = False
                break
            cur = cur[seg]
        if resolved:
            continue
        path = ".".join(read.pattern)
        if path in ALLOWED_UNDECLARED_READS:
            continue
        out.setdefault(path, set()).add(read.where)
    return {k: sorted(v) for k, v in sorted(out.items())}


def stale_dormant_declarations(rows=None):
    """Declared-dormant keys that are, in fact, read (or no longer exist)."""
    rows = audit() if rows is None else rows
    stale = []
    for path in sorted(DECLARED_DORMANT):
        status = rows.get(path, ("MISSING", "", ""))[0]
        if status != "DORMANT":
            stale.append((path, status))
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chronicle config honesty audit")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--unread-only", action="store_true", help="only the UNREAD keys")
    args = ap.parse_args(argv)

    rows = audit()
    undeclared = undeclared_literal_reads()
    if args.json:
        # Flat {path: [status, kind, evidence]} as before; the mirror goes under
        # a reserved key that cannot collide with a config path (paths have no
        # leading underscore, and this one is not a dotted path at all).
        out = {k: list(v) for k, v in rows.items()}
        out["_undeclared_reads"] = undeclared
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    wired = [k for k, v in rows.items() if v[0] == "WIRED"]
    dormant = [k for k, v in rows.items() if v[0] == "DORMANT"]
    unread = [k for k, v in rows.items() if v[0] == "UNREAD"]

    print("Chronicle config audit — declared vs. wired (§A12)")
    print("=" * 104)
    if not args.unread_only:
        print("{:<52} {:<9} {:<10} {}".format("Path", "Status", "Via", "Evidence"))
        print("-" * 104)
        for path in sorted(rows):
            status, kind, ev = rows[path]
            print("{:<52} {:<9} {:<10} {}".format(path, status, kind, ev[:38]))
        print("-" * 104)
    else:
        for path in sorted(unread):
            print("  {}".format(path))
        print("-" * 104)

    print("Total leaf keys:        {}".format(len(rows)))
    print("WIRED (read by code):   {}".format(len(wired)))
    print("DORMANT (declared):     {}".format(len(dormant)))
    print("UNREAD (undeclared):    {}   <- must be 0".format(len(unread)))
    # The MIRROR. "UNREAD 0" over a DEFAULTS that is missing keys the engine
    # reads is not honesty, it is a smaller denominator -- which is exactly how
    # the duplicate "health" literal hid two deleted keys behind a green audit.
    print("UNDECLARED reads:       {}   <- must be 0".format(len(undeclared)))
    for path in sorted(undeclared):
        print("  {:<50} read at {}".format(path, ", ".join(undeclared[path])))
    stale = stale_dormant_declarations(rows)
    if stale:
        print("STALE declarations:     {}  {}".format(len(stale), stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
