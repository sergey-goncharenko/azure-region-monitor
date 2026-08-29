# AW Issue Policy

`[aw]`-prefixed issues with the `agentic-workflows` label are **operational signals** produced by automated agentic workflows. They are **not backlog items by default** and must pass an actionability gate before engineering attention is warranted.

## Actionability gate

An issue is **actionable** only when it satisfies at least one of:

- `occurrences_24h >= 3` (repeated failure), **or**
- `severity` is `high` or `critical`.

Everything else is closed as **noise** by the automated triage workflow.

## Required body fields

Every AW issue must include the following structured fields (one per line, `key: value`):

| Field | Description |
|---|---|
| `fingerprint` | Stable key identifying the failure class (e.g. `agentic-pr-rework/missing-tool`) |
| `workflow` | Workflow filename or display name |
| `run_url` | Full URL to the failing GitHub Actions run |
| `first_seen` | ISO 8601 timestamp of first occurrence |
| `last_seen` | ISO 8601 timestamp of most recent occurrence |
| `occurrences_24h` | Integer count of occurrences in the past 24 h |
| `surface` | `repo-code`, `ci-infra`, `external-dependency`, or `unknown` |
| `severity` | `low`, `medium`, `high`, or `critical` |

Issues missing or supplying invalid values for these fields are labeled `aw-needs-human-repro` and left open for manual completion.

## Deduplication

When a new AW issue is opened with a `fingerprint` that matches an existing open canonical issue, the new issue is:

1. labeled `aw-duplicate` + `aw-noise`,
2. commented with a pointer to the canonical issue, and
3. closed automatically.

The canonical issue receives a bump comment with the latest `last_seen`, `occurrences_24h`, and `run_url`.

**Canonical issue title convention:**

```
[aw][<workflow>][<fingerprint-slug>] <short failure description>
```

Example: `[aw][agentic-pr-rework][missing-tool] Tool contract mismatch`

## Stale sweep

Open AW issues with `occurrences_24h < 3` and `last_seen` older than **7 days** are automatically closed as stale noise. The thresholds are tunable constants at the top of `.github/workflows/aw-triage.yml`.

## Label taxonomy

| Label | Meaning |
|---|---|
| `agentic-workflows` | Source label; all AW issues carry this |
| `aw-actionable` | Passes the actionability gate; engineers should look at this |
| `aw-noise` | Classified as transient/low-signal; closed automatically |
| `aw-duplicate` | Duplicate of a canonical tracker; closed automatically |
| `aw-escalated` | High/critical severity; requires prompt attention |
| `aw-needs-human-repro` | Missing required fields; open pending human completion |

## Operating model

- Engineers work only `aw-actionable` issues.
- `aw-needs-human-repro` is a short remediation queue for improving AW signal quality.
- Everything else (`aw-noise`, `aw-duplicate`) is closed automatically.
- Pure state transitions (queued/running/cancelled/completed) should be reported in the `agent-status` rollup issue, not as standalone `[aw]` issues.

## Tuning the automation

Edit the constants at the top of the `script` block in `.github/workflows/aw-triage.yml`:

```
RECURRENCE_THRESHOLD = 3   // occurrences_24h threshold for actionability
STALE_DAYS           = 7   // days before stale noise issues are auto-closed
```
