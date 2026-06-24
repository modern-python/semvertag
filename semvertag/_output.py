import dataclasses
import json
import sys
import typing

import rich.console

from semvertag._outcome import AlreadyTagged, Created, DryRun, NoBump, NoTags, Outcome, to_run_result
from semvertag._redact import redact


_COMMIT_SHORT_LEN: typing.Final = 7


class Output(typing.Protocol):
    def progress(self, message: str) -> None: ...
    def emit(self, outcome: Outcome, *, strategy: str) -> None: ...
    def error(self, message: str) -> None: ...


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class RichOutput:
    info_console: rich.console.Console
    error_console: rich.console.Console
    quiet: bool = False

    def progress(self, message: str) -> None:
        if self.quiet:
            return
        self.info_console.print(redact(message), markup=False, highlight=False)

    def emit(self, outcome: Outcome, *, strategy: str) -> None:
        self.info_console.print(redact(_format_outcome(outcome, strategy=strategy)), markup=False, highlight=False)

    def error(self, message: str) -> None:
        self.error_console.print(redact(message), markup=False, highlight=False)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class JsonOutput:
    error_console: rich.console.Console
    quiet: bool = False

    def progress(self, message: str) -> None:
        _ = message

    def emit(self, outcome: Outcome, *, strategy: str) -> None:
        result: typing.Final = to_run_result(outcome, strategy=strategy)
        payload: typing.Final = json.dumps(dataclasses.asdict(result), separators=(",", ":"))
        sys.stdout.write(payload + "\n")
        sys.stdout.flush()

    def error(self, message: str) -> None:
        self.error_console.print(redact(message), markup=False, highlight=False)


def _format_outcome(outcome: Outcome, *, strategy: str) -> str:
    match outcome:
        case Created(tag=tag, bump=bump, commit=commit):
            short = commit[:_COMMIT_SHORT_LEN]
            return f"Created tag {tag} on commit {short} (strategy: {strategy}, bump: {bump.value})"
        case DryRun(tag=tag, bump=bump, commit=commit):
            short = commit[:_COMMIT_SHORT_LEN]
            return f"Dry run: would create tag {tag} on commit {short} (strategy: {strategy}, bump: {bump.value})"
        case NoTags():
            return "No tag created — no prior semver-conforming tag to bump from."
        case AlreadyTagged(tag=tag):
            return f"No tag created — latest commit is already tagged {tag}."
        case NoBump(reason=reason):
            return f"No tag created — {reason}"
        case _:  # pragma: no cover
            typing.assert_never(outcome)


def build_rich_output(*, quiet: bool = False) -> RichOutput:
    return RichOutput(
        info_console=rich.console.Console(),
        error_console=rich.console.Console(stderr=True),
        quiet=quiet,
    )


def build_json_output(*, quiet: bool = False) -> JsonOutput:
    return JsonOutput(
        error_console=rich.console.Console(stderr=True),
        quiet=quiet,
    )
