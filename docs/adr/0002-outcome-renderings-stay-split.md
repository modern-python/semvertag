# Outcome renderings stay split between wire and human

`to_run_result` in `_outcome.py` and `_format_outcome` in `_output.py` are two exhaustive `match`
statements over the same closed `Outcome` sum, rather than two renderings hung on the variants
themselves. Only the match skeleton is shared, and no string is, by design: the wire arm builds a
frozen machine contract of fixed status tokens and reasons that `action.yml` parses with `jq`, while
the human arm builds a sentence that is free to be reworded. Co-locating them would trade
locality-of-concern for locality-of-variant and drag presentation phrasing into a module that today
depends only on `_types`. The drift a shared home would guard against is already type-enforced:
both matches end in `assert_never`, so a sixth variant is a type error in both arms until handled.
Unification earns its keep only once a variant's two renderings must be the identical string.
