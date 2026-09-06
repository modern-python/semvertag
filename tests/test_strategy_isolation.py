import ast
import pathlib
import typing


_PACKAGE_ROOT: typing.Final = pathlib.Path(__file__).parent.parent / "semvertag"
_STRATEGIES_ROOT: typing.Final = _PACKAGE_ROOT / "strategies"

_NETWORK_MODULES: typing.Final = frozenset(
    {"httpware", "httpx", "httpx2", "requests", "aiohttp", "socket", "urllib.request", "http.client"}
)
_TAG_HISTORY_MODULES: typing.Final = frozenset({"semvertag.providers", "semvertag.ioc", "semvertag._use_case"})


def _module_file(module: str) -> pathlib.Path | None:
    parts = module.split(".")
    if parts[0] != _PACKAGE_ROOT.name:
        return None
    base = _PACKAGE_ROOT.joinpath(*parts[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imported_modules(path: pathlib.Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _modules_reachable_from_strategies() -> set[str]:
    reachable: set[str] = set()
    visited: set[pathlib.Path] = set()
    queue = sorted(_STRATEGIES_ROOT.glob("*.py"))
    while queue:
        path = queue.pop()
        if path in visited:
            continue
        visited.add(path)
        for module in _imported_modules(path):
            reachable.add(module)
            target = _module_file(module)
            if target is not None and target not in visited:
                queue.append(target)
    return reachable


def _matching(modules: set[str], roots: frozenset[str]) -> list[str]:
    return sorted(m for m in modules if any(m == root or m.startswith(f"{root}.") for root in roots))


def test_a_strategy_reaches_neither_the_network_nor_the_tag_history() -> None:
    """INVARIANT: a strategy's answer is a function of the one commit it is handed, and nothing else.

    What breaks it is giving a strategy a second input. The moment a strategy can reach a provider,
    the container, or the use-case, "how far should the version move" stops being a pure decision
    over one commit and becomes a second place that fetches, ranks, and interprets tags — the job
    the use-case owns alone. Two rankings then have to agree forever, and the forge-neutral contract
    grows whatever each strategy wants to ask of it. A strategy's signature and return type would
    not change, so every behavioural strategy test would keep passing; the import closure is the
    only place the widening is visible.
    """
    reachable = _modules_reachable_from_strategies()

    network = _matching(reachable, _NETWORK_MODULES)
    assert network == [], f"strategies reach the network through: {network}"

    tag_history = _matching(reachable, _TAG_HISTORY_MODULES)
    assert tag_history == [], f"strategies reach tag history or orchestration through: {tag_history}"
