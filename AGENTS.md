# Agent guidelines: writing, comments, and commits

Future readers, mostly agents and sometimes humans, have the repository and its git history. They do
not have your conversation. Write for them.

## Plain English

These rules apply to everything you write into the repository: code comments, commit messages, pull
request descriptions, docs, and ADRs.

Each word must add information. If you can delete a word or phrase and the meaning stays the same,
delete it.

- Use short sentences. Put one idea in each sentence.
- Use common words that a high school student knows. Technical terms are the exception: when an
  exact technical term exists (`mutex`, `idempotent`, `race condition`), use it. A precise term is
  better than a simple but vague one.
- Use active voice. Name who or what does the action: "The scheduler retries the job," not "The job
  is retried."
- Be specific. Give names, numbers, error text, and file paths instead of general descriptions.
- Do not use filler words or phrases. Common ones: comprehensive, robust, seamless, leverage,
  enhance, streamline, utilize, facilitate, delve, crucial, key (as an adjective), various,
  significantly (without a number), properly, correctly, gracefully, "it's worth noting", "note
  that", "in order to", "this change", "going forward".
- Do not praise the code or the change. Words like "clean", "elegant", and "improved" say nothing a
  reader can check.
- Do not add an introduction that says what you are about to say. Do not add a summary that repeats
  what you said.
- Do not hedge unless you are unsure. If you are unsure, state what you do not know: "Not tested on
  Windows," not "should work on most platforms."
- No emoji, no exclamation marks, no patterns like "not just X, but Y."

### Examples

Bad: This change significantly improves performance.
Good: Cut p95 request latency from 340 ms to 90 ms on the checkout benchmark.

Bad: Enhance error handling to gracefully handle edge cases.
Good: Return 400 instead of 500 when `quantity` is negative or missing.

Bad: Utilize a more robust approach to ensure data consistency.
Good: Write both rows in one transaction, so a crash cannot leave an order without its line items.

Bad: It's worth noting that this function is not thread-safe.
Good: Not thread-safe. Callers must hold `registry_lock`.

Bad: In order to facilitate testing, we leverage dependency injection.
Good: Take the clock as a parameter so tests can set the time.

Bad: Refactored the parser for improved readability and maintainability.
Good: Split `parse()` into `tokenize()` and `build_tree()`. No behavior change.

Bad: This comprehensive update addresses various issues with the sync logic.
Good: Name each issue. If the issues are unrelated, put them in separate commits.

## Code comments

- Comments describe the code as it is now. Do not describe history, changes, earlier versions, or
  what you tried during development. If a comment only makes sense to someone who saw an earlier
  version or this conversation, put that content in the commit message.
- Test: a reader who has only seen the current file must be able to understand the comment and check
  that it is true.
- Comment only what a competent reader would otherwise get wrong: invariants, non-obvious
  constraints, and external facts. Cite external facts by issue ID, URL, or spec section. Do not
  describe what the code does line by line.
- If removing a non-obvious line would break something, write a test that fails without that line.
  Reference the test in the comment.
- Delete or fix comments that your change makes false.

### Examples

Bad:  # Use a copy here since in-place mutation caused the flaky export test
Good: # Callers keep references to `rows`. Do not mutate.
      # See test_export_does_not_mutate_input.

Bad:  # Changed to a set instead of a list for faster lookups
Good: # Set for O(1) membership checks. This runs once per input row.

Bad:  # Workaround for the timezone issue we found earlier
Good: # The vendor API returns naive timestamps in US/Eastern.
      # Convert to UTC here. See docs/vendor-api.md.

## Reuse and structure

- Before you write a new function, search the codebase for one that does the same job. Reuse or
  extend it.
- Do not copy a block of code to change it slightly. Extract the shared part.
- If the change is hard to make in the current structure, restructure first. Put the
  restructuring in its own commit with no behavior change, then make the change in the next
  commit.

## Tests

- Write the test before the code. Run it and confirm it fails for the reason you expect. Then
  write the code and confirm the test passes.
- Test real behavior. Mock only external systems (network, clock, third-party services), never
  the code under test.

## Commit messages

- Subject: `area: imperative summary`, 72 characters or fewer. Never use "fix", "update", "wip",
  "more fixes", "address review", or similar.
- The body explains what the diff cannot show:
  - the problem, with evidence (exact error text, steps to reproduce, numbers);
  - why you chose this approach, and which alternatives you rejected and why;
  - what you tested and how, and what you did not test.
- Do not list the files you changed or restate the diff.
- Match length to how surprising the change is, not to the size of the diff. A mechanical rename
  gets one line. A subtle one-line fix may need several paragraphs.
- Write the message last. Read `git diff --staged` and write what a reader with no access to this
  conversation needs.

### Example: a subtle fix

```
cache: key entries on normalized path

On case-insensitive file systems (the macOS default), "Foo.py" and
"foo.py" name the same file but created two cache entries. Invalidation
cleared only one of them, so `lint --watch` kept reporting errors that
were already fixed until the process restarted.

Normalize paths with os.path.normcase(os.path.realpath(p)) on both
insert and lookup. Normalizing only on lookup does not work: entries
inserted under the raw path could never be found for invalidation.

Tested: added test_cache_case_insensitive_paths. It fails without this
change on macOS and is skipped on case-sensitive file systems. Full test
suite passes on macOS and Linux. Not tested on Windows.

Closes: #1432
```

### Example: a mechanical change

```
parser: rename Tok to Token
```

No body. The diff says everything.

### Example: what not to write

```
Fix cache invalidation issue

This commit fixes an issue where the cache was not being properly
invalidated.

- Updated cache.py to normalize paths
- Added new test

This ensures robust and consistent cache behavior across platforms.
```

Problems: the subject does not say what changed. "An issue" and "properly" do not say what was
wrong. The bullet list restates the diff. The last sentence is filler. The message does not say how
to reproduce the bug, why this approach, or what was tested.

## Trailers

Put trailers in the final paragraph, with no blank lines between them. Use only these keys. Do not
invent others.

- `Fixes: <12-char sha> ("<subject>")`: the commit on main that introduced the bug this commit
  fixes.
- `Closes: #N` or `Refs: #N`: the related issue.
- `Co-authored-by: Name <email>`

If a value needs a sentence, it goes in the body, not in a trailer.

## Branch history

- All changes reach main through a reviewed branch. Commits on that branch become permanent history,
  so shape them before review.
- While working, commit as often as you like. Use `git commit --fixup=<sha>` to change an earlier
  commit on the branch.
- Before you request review, run `git rebase -i --autosquash main`. Shape the branch into atomic
  commits: one logical change each, each one builds and passes tests, each one has a full message.
- After you shape the branch, review each commit with `git show <sha>`:
  - Check that the message matches the final diff of that commit. Squashed fixups change the diff,
    so the message may describe code that is gone or leave out code that was added.
  - Check the message and every comment in the diff against the Plain English, Code comments, and
    Commit messages sections. Text written during the work often refers to the conversation or to
    earlier versions. Remove those references.
  - To fix a message, use `reword` in `git rebase -i main`. To fix a comment, use `edit`, amend the
    commit, and confirm tests still pass.
- Apply review feedback as fixups to the commit it belongs to, then autosquash and force-push the
  branch. Do not add "address review" commits.

## Pull requests

- Keep each pull request small enough to review in one sitting. Split large work into several
  pull requests.
- The description states the goal, links the issue, and gives evidence that the change works:
  the commands you ran and their output, or screenshots for UI changes. Explanation is not
  evidence.

## Read history before you change code

- Before you remove or rewrite code that looks unnecessary, odd, or wrong, run
  `git log -L <start>,<end>:<file>` or `git blame` and read the commits that added it. Assume the
  code exists for a reason until the history shows otherwise.
- Before a structural change, check docs/decisions/ for related ADRs.

## Working in this repository

The "Developing Rocky" section of `README.md` describes the layout and the development workflow.
These rules are the ones an agent must not miss.

- Run `scripts/check.sh` before every commit. It runs ruff, mypy, shellcheck, and the unit tests. It
  needs only `uv`, and it is safe anywhere, including inside `rocky run`.
- Run tools through `uv run --locked`, not from a global install. `uv.lock` pins their versions and
  hashes. Add a dev tool with `uv add --group dev <name>`.
- You are in a Rocky container when `/.rockyenv` exists.
- `scripts/integration.sh` needs docker on the host. A `rocky run` container has no docker, so the
  script refuses to run there. If you change code they cover, say in the commit message
  that you did not run them.
- Never run `tests/integration/run.sh` yourself. It deletes `/home/rocky` and rewrites
  `/etc/passwd`. Inside `rocky run`, `/home/rocky` is the user's profile home, with every agent's
  credentials. The script refuses to run on a host or inside `rocky run`. Do not test those checks
  by running it.
- Let names carry the meaning, so the code reads like prose. Name a function for what it returns
  or does, in its module's words: `image.tag(settings)`, not `image.image_tag(settings)`. Give each
  idea one name, and name numbers (`DNS_LABEL_MAX`). Keep comments to the constraints a reader
  would get wrong.
- mypy runs in strict mode. Annotate every function. Do not use `Any`, `cast`, or `# type: ignore`
  to silence an error. Fix the types.
- Rocky's runtime dependencies are in `pyproject.toml`, each pinned to an exact version, because
  `uv tool install` ignores `uv.lock`. Adding one needs a human's approval.
- An edit to `src/rocky/context/` changes the image's digest, and so its tag. Every user then has
  to run `rocky build`. Say so in the commit message.
- Write the project's name as Rocky in prose. Keep `rocky` lowercase where it is a literal: the
  command, the `rocky` user and `/home/rocky`, `~/.rocky`, the `rocky:<digest>` image tag, and the
  Python package.
- The repository is `wesc/rocky-sandbox` and the distribution is `rocky-sandbox`, because `rocky`
  is taken on PyPI. The command is still `rocky`.

## Where other knowledge goes

- A decision that limits future work across more than one change: propose an ADR in docs/decisions/
  with the sections Context, Decision, and Consequences. ADRs are rare and need human approval. To
  change a decision, write a new ADR that supersedes the old one. Do not edit accepted ADRs.
- Facts about the build, tools, or environment that future agents need: propose an addition to this
  file.
- Dead ends and exploration from this conversation: do not record them in the repository.
