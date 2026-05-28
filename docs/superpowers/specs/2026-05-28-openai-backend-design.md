# OpenAI/ChatGPT as an alternative backend — design

Status: proposed 2026-05-28

## Goal

Let consumers of `motsognirr/aider-code-review` run the PR review against
OpenAI's ChatGPT models (e.g. `gpt-4o`) as an alternative to the default
DeepSeek backend. aider already speaks to OpenAI natively, so the work is
about authentication (supplying an OpenAI key) and routing (forwarding the
right key for the chosen model). DeepSeek remains the default; OpenAI is
opt-in.

## Non-goals

- Changing the default model. `deepseek/deepseek-reasoner` stays the
  default; OpenAI is selected explicitly via the `model` input.
- Supporting providers beyond DeepSeek and OpenAI in this change.
- Any change to the prompt, JSON extraction, hallucination filter, or
  comment-posting pipeline — all of these are model-agnostic and stay as-is.
- A single unified `api_key`/`provider` interface (rejected: it is a
  breaking change to the existing input surface).

## Inputs (`action.yml`)

- Add `openai_api_key` — optional, no default. Forwarded to aider as
  `OPENAI_API_KEY` when the chosen model routes to OpenAI.
- Change `deepseek_api_key` to `required: false`. A user on OpenAI should
  not be forced to supply a DeepSeek key. Presence is validated at runtime
  based on the chosen model (see below), which is stricter and clearer than
  the schema-level `required` flag.
- `model` is unchanged: default `deepseek/deepseek-reasoner`. OpenAI is
  selected by setting e.g. `model: gpt-4o` or `model: openai/gpt-4o`.

`action.yml` passes both keys through as env (`DEEPSEEK_API_KEY`,
`OPENAI_API_KEY`) to `run_review.sh`.

## Provider routing

A new `scripts/resolve_provider.py` maps a model string to its provider and
the env var that carries its key. This keeps the matching logic unit-testable
per the repo's "pure logic in Python + pytest" convention.

```
Usage: resolve_provider.py <model-string>
Stdout: the provider's API-key env var name (e.g. OPENAI_API_KEY),
        a single line.
Exit codes:
  0 — always (an unrecognized model falls back to DeepSeek, matching
      today's behavior where any non-routed model used the DeepSeek key)
```

### Interface

`resolve_provider.py <model>` prints the required key's env-var name to
stdout (single line), e.g.:

- `gpt-4o`        → `OPENAI_API_KEY`
- `o3-mini`       → `OPENAI_API_KEY`
- `openai/gpt-4o` → `OPENAI_API_KEY`
- `deepseek/deepseek-reasoner` → `DEEPSEEK_API_KEY`
- `some-other-model` → `DEEPSEEK_API_KEY` (fallback)

### Match rule (OpenAI prefixes)

A model routes to OpenAI when its name matches any of:

- `gpt-*` (e.g. `gpt-4o`, `gpt-4.1`, `gpt-4o-mini`)
- `o1*`, `o3*`, `o4*` (reasoning models, e.g. `o1`, `o3-mini`)
- `openai/*` (explicit litellm provider prefix)

Everything else routes to DeepSeek (`DEEPSEEK_API_KEY`), preserving current
behavior for `deepseek/*` and any unrecognized string.

## `run_review.sh` changes

Replace the unconditional `DEEPSEEK_API_KEY` requirement with:

1. Resolve the required key env-var name:
   `key_var=$("$ACTION_DIR/scripts/resolve_provider.py" "$MODEL")`.
2. Verify that the corresponding variable is non-empty. If empty, emit a
   `::error::` that names the missing input (e.g. "model 'gpt-4o' requires
   `openai_api_key`") and `exit 2`.
3. Invoke `aider` with that key exported. Currently the call hardcodes
   `DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" aider ...`. Generalize so the
   resolved key is exported under its env-var name. The non-selected
   provider's key is simply not passed.
4. Add `OPENAI_API_KEY` to the secret-scrub heredoc's loop alongside
   `DEEPSEEK_API_KEY`, so an OpenAI key can never leak into stdout that gets
   posted.

The `: "${DEEPSEEK_API_KEY:?...}"` guard at the top is removed (replaced by
the model-driven check); `MODEL` keeps its default.

## Documentation (`README.md`)

- Add an `openai_api_key` row to the Inputs table; note `deepseek_api_key`
  is now required only when using a DeepSeek model.
- Add a short "Using OpenAI/ChatGPT" subsection with a caller snippet:

  ```yaml
  - uses: motsognirr/aider-code-review@v1
    with:
      openai_api_key: ${{ secrets.OPENAI_API_KEY }}
      github_token: ${{ secrets.GITHUB_TOKEN }}
      model: gpt-4o
  ```

## Testing

`tests/test_resolve_provider.py` (subprocess-style, matching the existing
tests), covering:

- `gpt-4o`, `gpt-4.1`, `gpt-4o-mini` → `OPENAI_API_KEY`
- `o1`, `o3-mini`, `o4-mini` → `OPENAI_API_KEY`
- `openai/gpt-4o` → `OPENAI_API_KEY`
- `deepseek/deepseek-reasoner` → `DEEPSEEK_API_KEY`
- an unrecognized model → `DEEPSEEK_API_KEY` (fallback)
- exit code 0 in all cases

The `run_review.sh` key-presence validation is shell glue and is not unit
tested directly (consistent with the rest of the orchestrator); the routing
decision it depends on is covered by the resolver tests.

## Rollout

A normal `v1.x.y` minor release. Backward compatible: existing callers that
set only `deepseek_api_key` continue to work unchanged.
