# Follow-up review — deferred from 2026-05-22 remediation

Items deliberately left unresolved when the three-phase remediation landed. Each requires a behavior decision rather than a mechanical fix. Severity follows the original review's P0–P3 scale.

The source review and plan documents:
- Original tech spec: `~/Downloads/civic-transparency-tool-tech-spec.md` (caller-side)
- Remediation plan: `~/.claude/plans/compressed-skipping-beaver.md`
- Review run artifacts: `.context/compound-engineering/ce-code-review/20260522-133105-330d730e/` (per-reviewer JSON)

---

## P1 — Design decisions

### 1. Retry × non-idempotent POST → duplicate Beehiiv drafts / duplicate Resend emails

**Where:** `automation/beehiiv.py:84`, `automation/notifier.py:127`.

**Problem:** `retry_if_exception_type(requests.RequestException)` catches `Timeout` and `ChunkedEncodingError`, both of which can fire *after* the server has accepted the request. tenacity retries → second draft created / second email sent.

**Options:**
- **A.** Narrow the retry predicate to `requests.ConnectionError` only (refuse to retry once the request has been transmitted). Cheapest fix, accepts dropped retries on post-send timeouts.
- **B.** Attach `Idempotency-Key: <video_id>` header. Resend supports it natively. Beehiiv API docs need checking — if not supported, fall back to A for Beehiiv only.
- **C.** Combine: idempotency keys where available + narrowed predicate as a backstop.

**Dormant today** because Beehiiv is enterprise-gated (403s every time); the Resend duplicate-email path is live. Practical impact today: editor occasionally gets two copies of the same draft.

Cross-reviewer flagged by: correctness, security, adversarial, reliability.

---

### 2. Split-brain in `monitor.process_video` ordering

**Where:** `automation/monitor.py:122-140`.

**Problem:** Order is publish → email → `mark_processed`. If publish succeeds but email fails (or `NOTIFY_EMAIL` is unset), the video is never marked processed → next cron re-runs the full pipeline (LLM cost) → potentially duplicate Beehiiv draft.

**Options:**
- **A.** Call `state.mark_processed(...)` immediately after the orchestrator returns rendered output, before publish/email. The dedupe guard already prevents double-entry; the trade-off is a successful pipeline that *didn't* email the editor still gets marked processed, so the editor would never be notified about that meeting.
- **B.** Keep current order, but document `NOTIFY_EMAIL` as a hard requirement and exit 1 if unset.
- **C.** Use a two-stage state: `processed_pipeline` (set after dashboard write) and `delivered` (set after email). Allow re-attempting email without re-running the pipeline. More work.

Cross-reviewer flagged by: correctness, adversarial, reliability, kieran-python.

---

### 3. Per-video crashes never trigger CI `if: failure()`

**Where:** `automation/monitor.py:78-91, 196-202`.

**Problem:** `process_video` catches all exceptions, prints to stderr via `traceback.print_exc()`, and returns `None`. `main()` ignores the return and exits 0. The new `if: failure()` step in `monitor.yml` only fires on non-zero exit, so LLM / transcript / schema-validation crashes silently fail with no operator email.

**Options:**
- **A.** Track failures: `failed = 0; for v in vids: if process_video(...) is None: failed += 1` and `return 1 if failed else 0`. Simple, makes per-video failures observable as CI failures.
- **B.** Keep current best-effort semantics, but call `notifier.send_plain(...)` directly inside `process_video`'s except handler. Loses the workflow `failure()` signal but emails the operator regardless.
- **C.** Both: fail the workflow AND email inline. Belt-and-suspenders.

Cross-reviewer flagged by: correctness, adversarial, cli-readiness.

---

## P2 — Behavior decisions

### 4. Schema gate's `extra="allow"` + defaults absorb the dominant LLM drift class

**Where:** `pipeline/llm_schema.py`.

**Problem:** Required fields fail loudly (good). Optional fields all default to `""` or `[]`. If the LLM renames `options` → `option_list`, validation passes with an empty `options` list and the newsletter renders empty. Thin-content drift (single-paragraph briefings, empty workshop topics) also passes.

**Options:**
- **A.** Tighten inner schemas to `extra="forbid"` on Quote, AgendaItem, etc. — catches renamed keys, but rejects any LLM exuberance with novel fields.
- **B.** Detect thin responses post-validation: warn if WorkshopAnalysis has zero topics, if a briefing has zero paragraphs, if a hearing has zero commentary across all four channels. Don't fail; surface a structured warning so prompt drift is visible.
- **C.** Both: forbid extras on stable inner shapes (Quote), allow extras on top-level analysis types where the LLM has more room to vary.

Cross-reviewer flagged by: correctness, adversarial.

---

### 5. HTTP 5xx is not retried by the current retry decorator

**Where:** `automation/beehiiv.py`, `automation/notifier.py`.

**Problem:** `retry_if_exception_type(requests.RequestException)` doesn't catch a 503 response — `requests.post` returns a `Response` and the manual `if status_code >= 400` raises `BeehiivError` / `NotifierError` (not subclasses of `RequestException`). A transient 503 fails on first attempt.

**Caveat:** Beehiiv's 403 (enterprise gate) is permanent and shouldn't be retried.

**Options:**
- **A.** Add `resp.raise_for_status()` inside `_post()`, and add a predicate filter `retry=retry_if_exception(lambda e: not (isinstance(e, requests.HTTPError) and e.response.status_code < 500))`. Retries 5xx, skips 4xx.
- **B.** Manual: inside the existing `if status_code >= 400` block, re-raise as `requests.HTTPError` if 5xx, leave `BeehiivError`/`NotifierError` for 4xx. Less elegant but explicit.

Flagged by: reliability.

---

### 6. `ValidationError` wrapped into `ValueError` discards `.errors()` from the raised type

**Where:** `pipeline/analyze_meeting.py:699-703`.

**Problem:** `analyze_meeting` catches `pydantic.ValidationError` and raises `ValueError(...) from e`. Human-readable message survives; structured `.errors()` list is only reachable via `e.__cause__`. Any handler catching `ValueError` loses the structured info.

**Options:**
- **A.** Raise the `ValidationError` directly. Callers must know about Pydantic, which leaks the implementation through the public API.
- **B.** Define `LLMSchemaError` that preserves `.errors()` as an attribute: `raise LLMSchemaError(str(e), errors=e.errors()) from e`. Clean, agent-friendly.
- **C.** Leave as-is. The current pipeline aborts fatally on this path anyway — structured detail is only useful when adding an auto-repair loop.

Flagged by: maintainability, agent-native.

---

### 7. `dashboard/src/types/meeting.ts` is unused — pure documentation that will rot

**Where:** `dashboard/src/types/meeting.ts`.

**Problem:** No `tsconfig.json` in the dashboard. No `.tsx` file imports the interface. ESLint config excludes `.ts`. The file is decorative. It also has typing bugs:
- `Alert.severity: 'info' | 'warning' | 'critical' | string` — trailing `| string` collapses the union to `string`.
- `DashboardData.meeting_type` has the same widening pattern.
- `Quote.quote` field name disagrees with the producer's `Quote.text` after schema normalization.

**Options:**
- **A.** Delete the file. Reintroduce when the first `.tsx` consumer is written.
- **B.** Add `tsconfig.json` + `tsc --noEmit` lint step. Fix the union widening. Convert `App.jsx` to `App.tsx` so the interface is actually load-bearing.
- **C.** Keep as documentation but add a header comment stating "not type-checked; may drift."

Flagged by: api-contract, maintainability, kieran-typescript.

---

### 8. Workshop / Study schemas require list fields; Business defaults all to empty

**Where:** `pipeline/llm_schema.py` — `WorkshopSchema.workshop_topics` and `StudySchema.briefings` are required; `BusinessSchema` makes everything optional.

**Open question:** Was this asymmetry intentional? A workshop with no topics is almost certainly a misclassified business meeting. If so, current strict behavior is desirable — but the symmetry is worth confirming. If not intentional, default all to `[]` and add the thin-response detector from item #4.

Flagged by: correctness.

---

## P3 — Operational

### 9. No `concurrency:` block in `.github/workflows/monitor.yml`

**Problem:** Two simultaneous workflow runs (cron + workflow_dispatch) can race on `git push` of `state/processed.json` and dashboard JSON. Atomic writes protect against intra-process corruption but not against `git push --force-with-lease` between concurrent jobs. Non-fast-forward push failures look like CI noise.

**Fix:** Add to `.github/workflows/monitor.yml`:
```yaml
concurrency:
  group: monitor
  cancel-in-progress: false
```

Flagged by: adversarial.

---

### 10. `requirements.lock` header references Python 3.9, CI uses 3.11

**Verified false alarm** for the install path — the wheel hash set in the lockfile includes `cp311` (confirmed via `pip download --python-version 3.11` + hash comparison; the `pydantic-core` cp311 wheel hash is present). CI install works.

**Cosmetic cleanup:** regenerate the lockfile under Python 3.11 so the header is honest. One command: `pip-compile --generate-hashes -o requirements.lock requirements.txt` from a 3.11 venv.

---

### 11. Schema-version mismatch warns but renders

**Where:** `dashboard/src/App.jsx`.

**Problem:** When `payload.schema_version !== EXPECTED_SCHEMA_VERSION`, the dashboard logs a console warning and renders anyway. If a future producer drops a field App.jsx needs, the dashboard silently breaks with a TypeError in a child component.

**Options:**
- **A.** Render a "schema mismatch — redeploy the dashboard" banner instead of normal UI when versions disagree.
- **B.** Per-section error boundaries that hide individual sections gracefully on render error.
- **C.** Accept current behavior; archive files predate schema_version and would always trigger A. Treat absence of the field as version 0 in any future migration tooling.

Flagged by: adversarial, kieran-typescript.

---

## Residual risks (advisory — no decision required)

- **`AliasChoices('text', 'quote')` first-match-wins:** if the LLM emits both `text` AND `quote` keys in the same Quote object, `quote` is silently dropped with no warning. Hard to trigger in practice.
- **`config/loader.py` Pydantic validation discarded by `model_dump`:** validation is real, the typed model is throwaway. Future consumers can migrate to consuming the model directly; not urgent.
- **CLAUDE.md sync rule should be extended:** "If you change `ANALYSIS_PROMPT_*`, update the dataclass and the matching Jinja template" — should now also include `pipeline/llm_schema.py`. Documentation update only.

---

## Testing gaps (no test suite exists)

The remediation introduced multiple pure functions that would benefit from tests if a suite is established:

- `pipeline/llm_schema.validate_and_normalize` — happy path, alias canonicalization (`quote`/`text`, `context`/`context_excerpt`), invalid meeting type, missing required field
- `automation/state.mark_processed` — dedupe guard, atomic write, JSONDecodeError tolerance
- `config/loader.load_city_config` — `CityConfigNotFoundError`, `CityConfigError` (missing required field), `available_cities()`
- `automation/monitor.parse_meeting_date_from_title` — all three branches
- `pipeline/generate_draft.draft_filename` — fixed-date vs `None`-date paths
- `automation/beehiiv.create_draft` — non-JSON response → `BeehiivError`

Each is testable with `pytest` + fixture dicts and no external dependencies. Estimated effort: 1–2 hours total.
