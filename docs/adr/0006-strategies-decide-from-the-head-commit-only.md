# Strategies decide from the head commit only

`SemvertagUseCase` fetches one commit, the head of the default branch, and hands it to
`BumpStrategy.decide`; neither strategy sees the commits between the latest tag and the head. The
Conventional Commits convention is usually applied as a scan of that range, taking the highest bump
found, and the docs promised exactly that until they were corrected. The scan was declined because
the action runs once per push and the org's pull requests land as squash merges, so a push is one
commit and the range is the head; a merge-commit workflow is served by `branch-prefix`, which reads
the merge commit that is the head. A range scan would need a new `Provider` operation on two
independently versioned REST APIs, a bound on long ranges, and would change the bump existing users
get from the same history. The accepted cost is that a failed run is not recovered by the next
push, which is judged on its own head, so a failed tagging job has to be re-run. A range scan
stays a possible opt-in if a merge-commit team using Conventional Commits asks for it.
