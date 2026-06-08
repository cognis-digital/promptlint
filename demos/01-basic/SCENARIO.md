# Demo 01 - Basic: lint, version, and gate a support-bot prompt

This demo shows PROMPTLINT treating a prompt file as code: a static linter, a
deterministic content hash for version drift, and a hermetic test gate suitable
for CI. No network, no API keys.

## Files

- `support_bot.prompt` - a prompt with front matter (`model`, `version`, `vars`)
  and a `{{var}}` template body. It intentionally contains two lint problems:
  a single-brace placeholder (`{tone}` instead of `{{tone}}`) and a `TODO`
  marker.
- `tests.json` - deterministic test cases asserting the rendered prompt
  contains the customer name, never leaks the internal `TODO`, stays under a
  character budget, and resolves all variables.

## Try it

```sh
# 1. Lint (warnings only here -> exit 0)
python -m promptlint lint demos/01-basic/support_bot.prompt

# 2. Content hash for drift detection in version control
python -m promptlint version demos/01-basic/support_bot.prompt --format json

# 3. Run the deterministic test cases
python -m promptlint test demos/01-basic/support_bot.prompt \
    --tests demos/01-basic/tests.json

# 4. The CI gate: lint + tests together (non-zero exit fails the build)
python -m promptlint check demos/01-basic/support_bot.prompt \
    --tests demos/01-basic/tests.json --format json
```

## What to expect

- `lint` flags `PL012` (single-brace `{tone}`) and `PL020` (`TODO`) as warnings.
- `version` prints a stable `sha256:` hash; edit the body and it changes.
- `test` renders the prompt with each case's `vars` and checks the assertions.
- `check` is the gate: it exits 0 only when there are no lint *errors* and all
  test cases pass.
