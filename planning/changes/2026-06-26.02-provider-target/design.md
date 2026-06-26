---
summary: Replaced the duplicated provider invariant (validator + two ioc asserts) with a discriminated ProviderTarget the validator builds and ioc matches exhaustively; the asserts are gone and the invariant lives only in the validator.
---

# Design: Encode the provider invariant in a `ProviderTarget` type

## Summary

The invariant "provider=github ⟹ `repo` set; provider=gitlab ⟹ `project_id`
set" lives in **two** coupled places: `Settings._resolve_provider` enforces it,
and `ioc._build_current_provider` re-asserts it (`assert settings.repo is not
None` / `assert settings.project_id is not None`) — partly as a defensive
backstop, partly because `ty` cannot prove the cross-field invariant and the
provider dataclasses want non-optional `repo: str` / `project_id: int`. This
change makes the validator build a discriminated `ProviderTarget`
(`GitHubTarget | GitLabTarget`) whose id field is non-optional, and has `ioc`
match it exhaustively. The business invariant then lives in **one** place
(its construction in the validator); `ioc` stops encoding it, the two asserts
and their "validator guarantees" coupling-comment disappear, and the only
residual assert is a trivial "fully-validated" init check on the new property.

## Motivation

`ioc._build_current_provider` (`ioc.py:63-74`) currently reads:

```python
if settings.provider == "github":
    assert settings.repo is not None, "provider=github invariant: validator guarantees repo is set"
    return GitHubProvider(config=settings.github, repo=settings.repo, ...)
assert settings.project_id is not None, "provider=gitlab invariant: validator guarantees project_id is set"
return GitLabProvider(config=settings.gitlab, project_id=settings.project_id, ...)
```

The asserts restate, in a second module, the rule that
`Settings._resolve_provider` already enforces — two places that must agree,
coupled only by a comment. The asserts exist because `settings.repo` is typed
`str | None` while `GitHubProvider.repo` is `str`: `ty` cannot see that the
validator guarantees non-`None`.

This was scoped **out** of the load-settings change
(`changes/2026-06-26.01-load-settings-pipeline/design.md`, non-goal: "the
`ioc` asserts stay … removing them was explicitly scoped out") because, at the
time, the only shapes considered were *relocating* or `cast`-ing the asserts —
low value against a working backstop. This design uses a shape not considered
then: a discriminated target built from locals that narrow across the
validator's **existing** guard, which *eliminates* the business invariant from
`ioc` rather than moving it. That materially better outcome is why C2 graduates
from deferred to scheduled. No `decisions/` record forbade it; it was deferred,
not decided-against.

## Non-goals

- No change to the user-facing invariant, its error messages, auto-detection,
  precedence, env aliases, or any observable behavior. Behavior-preserving.
- `Settings.provider` (the `Literal` selector) stays — it is the env/CLI-facing
  field and drives `--token` routing in `load_settings`. `provider_target` is a
  one-way **projection** of it, built once, never an independent source of truth.
- No change to the `Provider` protocol, the providers, the use-case, or output.
- Both HTTP clients stay eagerly resolved by modern-di (unchanged); the match
  only picks which client wraps which provider.

## Design

### 1. A discriminated `ProviderTarget` in `_settings.py`

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitHubTarget:
    repo: str

@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitLabTarget:
    project_id: int

ProviderTarget: typing.TypeAlias = GitHubTarget | GitLabTarget
```

It lives in `_settings.py` (next to the validator that builds it); `ioc`
already imports from `_settings`, so the coupling graph is unchanged. The
providers do **not** import it — they still take `repo` / `project_id` directly.

### 2. The validator builds it; a property exposes it

`Settings` gains a `PrivateAttr` and a property, and `_resolve_provider` builds
the target using locals that narrow across its existing guard — no `assert`, no
`cast` on the build path:

```python
_provider_target: ProviderTarget | None = pydantic.PrivateAttr(default=None)

@property
def provider_target(self) -> ProviderTarget:
    assert self._provider_target is not None, "provider_target is set by _resolve_provider"  # noqa: S101
    return self._provider_target

@pydantic.model_validator(mode="after")
def _resolve_provider(self) -> "Settings":
    if self.provider is None:
        self.provider = _detect_provider_from_env()
    if self.provider == "github":
        repo = self.repo
        if not repo:
            msg = "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
            raise ValueError(msg)
        self._provider_target = GitHubTarget(repo=repo)
    else:
        project_id = self.project_id
        if project_id is None:
            msg = "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
            raise ValueError(msg)
        self._provider_target = GitLabTarget(project_id=project_id)
    return self
```

The error messages and raise conditions are **identical** to today
(`not repo` for github, `project_id is None` for gitlab). The residual
`assert` in the property means "this `Settings` is fully validated," not the
cross-field business rule — and it is coverage-free for the same reason today's
asserts are (see Risk).

### 3. `ioc` matches the target exhaustively

```python
match settings.provider_target:
    case GitHubTarget(repo=repo):
        return GitHubProvider(config=settings.github, repo=repo, http=github_client, default_branch=settings.default_branch)
    case GitLabTarget(project_id=project_id):
        return GitLabProvider(config=settings.gitlab, project_id=project_id, http=gitlab_client, default_branch=settings.default_branch)
    case _:  # pragma: no cover
        typing.assert_never(settings.provider_target)
```

This mirrors the closed-sum match in `_outcome.to_run_result`: `ty` already
knows the union is exhaustive, and the `assert_never` arm makes a third forge a
`ty` error here until handled. The two asserts and the "validator guarantees"
docstring sentences are removed; the eager-resolution note stays.

## Testing

TDD. New pure tests in `tests/unit/test_settings.py`:

- `Settings(provider="github", repo="o/r").provider_target == GitHubTarget(repo="o/r")`
- `Settings(provider="gitlab", project_id=999).provider_target == GitLabTarget(project_id=999)`

Existing tests are unchanged and are the behavior-preservation proof: the
invariant-violation tests (`test_provider_github_requires_repo`,
`test_provider_gitlab_requires_project_id`, and the `load_settings` gitlab/no-id
case) still raise with the same messages; `test_ioc.py`'s container tests
already resolve both providers (exercising both match arms and both validator
build-branches) and assert the `default_branch` override.

Gates: `just test` (100% branch), `just lint-ci`, `just docs-build`.

## Out of scope

Documented in Non-goals. The `provider` selector string is deliberately kept.

## Risk

- **Behavior drift in the validator restructure (medium × low).** The two-`if`
  block becomes an `if/else` that also builds the target. Mitigated: identical
  messages and guard conditions, and the existing invariant tests + full suite
  must stay green.
- **Coverage of the residual property assert (low × low).** Today's two
  `assert ... is not None` lines in `ioc` coexist with 100% branch coverage and
  no pragma (coverage config excludes only `if typing.TYPE_CHECKING:`), so an
  always-true assert's failure arc is not penalized. The single new
  property-assert is structurally identical, so net assert burden drops from two
  to one and coverage is unaffected.
- **`architecture/cli.md` drift (low × low).** The IoC-wiring section describes
  the asserts by name; promote it in the same PR to describe `provider_target`
  and the exhaustive match.
