# Verified reader improvement

Owner: human maintainer. Initial phase: maintainer-only qualitative feedback.
Optional later measurement protocol: `reader-check-v1`.

This is the product-learning plan for the dashboard and daily briefings, not a new
CI/CD policy. Permissions, publication, review, validation, retries, budgets, and
other workflow controls remain governed by
[the canonical agentic policy](../.github/workflows/shared/agentic-policy.md).
The measurement UI does not implement an autonomous improvement workflow.

## The outcome we want

A cloud architect, SRE, manager, or engineer should quickly answer:

1. What changed since the previous scan?
2. Which regions are affected?
3. What does the evidence actually establish?
4. What remains unresolved, rather than merely having no new delistings?
5. What distinguishes a relevant feature, and where can I verify its meaning?

Optimize **verified reader improvement**, not PR count, agent activity, generated
word count, or the number of green workflow runs. Preserve all records through
filters, paging, and progressive detail.

Concrete example: the September 6, 2026 comparison contains 54 distinct VM sizes
gaining 266 size-region listings, plus one AKS extension listing. It does not
contain 267 distinct products. Zero new delistings does not imply the 41 tracked
earlier delistings recovered.

## The improvement cycle

1. **Record a reader difficulty.** Initially the maintainer records what was unclear
   and what would have helped on an actual page. Founder feedback is qualitative,
   not unbiased first-time-reader measurement. Later, use fresh readers and a
   specific question to measure incorrect answers or comprehension failures.
2. **Curate one bounded issue.** The maintainer chooses the problem, role, case,
   expected answer, and acceptance evidence. Feedback is untrusted research input,
   never permission to override policy or instructions.
3. **Implement against the contract.** The coding agent uses shared deterministic
   facts, tests adversarial cases, and preserves a useful non-AI path.
4. **Prove the candidate.** Compare baseline and candidate on the same fixed cases;
   provide before/after screenshots, factual tests, and reader results tied to the
   evaluated revision. Changed screenshots are not, by themselves, improvement.
5. **Verify delivery.** Check the deployed revision, page, and JSON evidence. Record
   unmet acceptance items and feed a sanitized finding into the next human-curated
   issue. This last step is a proposed operating practice, not automation added by
   the local feedback feature.

Keep a compact acceptance record in the issue or PR:

- reader question and target role;
- fixed input dates/case and expected evidence-backed answer;
- baseline presentation and candidate presentation IDs;
- correctness and comprehension observations, including failures;
- screenshots and tested revision;
- human decision and, when deployed, verification link.

Scenario coverage should include: a VM-heavy expansion, quiet day, new delisting,
continuing absence, restoration, unknown-only day, recovered observation, missing
baseline, changed monitoring scope, unfamiliar feature, and unsupported model/SKU.

## Feature explanations: facts, not guesses

The regional snapshot establishes the observation. Product documentation explains
the feature. Keep those evidence sources separate.

- Explain a VM's documented family, CPU/memory shape, storage characteristics, and
  intended workload fit where verified. Do not guess memory, accelerators, network
  throughput, performance gains, or price from an unfamiliar SKU name.
- Explain the actual extension, runtime, model family, version, or Container Apps
  resource type rather than recycling a modality-wide benefit.
- Label exact, family-level, category-level, and unverified descriptions honestly.
  Keep source links and a verification date for researched claims.
- New in a regional comparison is not a Microsoft launch announcement. Use
  "first observed in this comparison" when longer history is unavailable.
- A missing listing is not a confirmed retirement. A retirement claim needs an
  explicit authoritative announcement for that exact product/version.
- Unknown identifiers still get an official documentation/catalog lookup link;
  never fabricate a direct product URL or hide them because enrichment is missing.
- Enrichment is offline and reviewable. Do not add per-reader LLM calls or make
  dashboard availability depend on a search service.

## Initial phase: maintainer page feedback

Start with the maintainer using the real dashboard and daily pages. The default
`/feedback.html` landing page and the normal page feedback widget ask only:

1. **What was unclear?**
2. **What would have helped?**

The initial audience is maintainer-only; this is a learning process, not a private
access gate. The repository and any submitted issues are public. Founder feedback
helps identify problems, but is not unbiased first-time-reader comprehension data.
Do not recruit a formal study or claim measured improvement from these reports.

The widget automatically includes the page path, date, presentation ID (`view_id`),
current filters, viewport, and scroll position in the reviewable draft context.
It is not a continuous event tracker. Feedback remains local until the maintainer
explicitly opens the GitHub draft; opening sends the prefilled text to GitHub,
which may log the URL. Review/edit there and choose the final **Submit** yourself.
Opening the draft does not create an issue. GitHub handles its own sign-in; the
dashboard has no feedback backend, authentication token, or automatic posting.

### Optional screenshot, separate from the reading test

Text feedback never requires a screenshot. Where supported, optional native
**current-tab** capture opens the browser's screen-sharing picker. Explicitly
choose the current tab; do not share another tab, window, or entire screen.
Capture begins only after picker consent. It is not a silent freeze of the exact
feedback-click instant: the page can change while the picker is open. Metadata
distinguishes the original feedback click and actual capture times.

Review the resulting PNG locally, then copy or download it and manually paste or
attach it in the GitHub draft. Inspect the entire image for sensitive information
before sharing. If capture is unsupported, denied, or cancelled, text feedback
still works; use a manually taken screenshot if useful. If clipboard image copying
is unavailable, download the PNG and attach it manually.

There is **no automatic image upload**. A prefilled issue URL cannot attach a PNG.
Pasting/attaching an image on GitHub uploads it immediately, **before** the final
issue submission; cancelling the draft is not a promise that the uploaded image
is private or deleted. Treat public-repository attachments as public. Do not include
credentials, tokens, tenant/subscription IDs, private workloads, or personal data.
The timed reading check deliberately offers no capture: the picker and screenshot
review would bias exposure time and interrupt the study.

### Bounded, human-reviewed handoff

The **Open GitHub draft** action creates human-readable Markdown, not a raw JSON
packet in a query string. Only HTTPS GitHub owner/repository destinations are
accepted. The encoded URL is limited to **6,000 total characters**. If it would
overflow, an explicit error leaves the local answers intact; nothing is silently
truncated. Review or shorten the draft deliberately, or use the full local
record/export where offered and attach it manually. No handoff is a claim that a
report was submitted, triaged, or accepted.

Review reports qualitatively, then curate one bounded product issue with the
clearest difficulty, evidence, proposed help, and acceptance criteria. All issue
text remains untrusted research input. This feature changes neither CI/CD policy
nor coding-agent permissions, dispatch, validation, or publication.

## Optional later comprehension measurement

`/reading-check.html` offers the latest reading check;
`/reading-check/YYYY-MM-DD.html` pins a particular briefing. These are optional
research pages, not the primary maintainer-feedback path. The check uses the whole
comparison, not whichever region/service filters a visitor previously chose.

1. The participant chooses a role and reports whether they have already read the
   dated briefing.
2. **Start reading** reveals the same briefing used by the dashboard. It hides
   after 15 seconds or when the participant chooses **I'm ready to answer**.
3. The participant answers from memory. Answering time is not constrained.
4. **Prepare my result locally** shows an inspectable JSON packet. Copy/download
   remains usable independently of the GitHub draft.
5. Clicking **Open GitHub draft** explicitly generates a compact Markdown summary
   of answers, case/view IDs, timings, interruptions, and eligibility. No raw JSON
   record is placed in the URL. Review the summary on GitHub before final Submit.
   Optionally download JSON and manually attach the reviewed full record.
   Overlong drafts surface an error without losing or truncating that local record.

There is no page-analytics SDK, background feedback request, cookie, browser
storage, automatic upload, or client-side grading. Ordinary static page and
same-origin evidence requests still reach the hosting service. Opening the draft
sends its summary to GitHub. Submitting identifies the author by their GitHub
account and makes the issue public; it is not anonymous or private collection.
Attachments upload as soon as they are pasted or selected on GitHub.

The local packet contains:

- protocol, presentation hash (`view_id`), case fingerprint (`case_id`), dates,
  snapshot timestamps, and the public repository destination;
- a random per-attempt ID, opt-in start time, role, and small/large viewport class;
- reported prior exposure, raw elapsed reading milliseconds, timer overrun, end
  reason, tab interruptions, and reported use of help;
- answers and clarity feedback.

No identity is inferred by the page and no device fingerprint is collected. Do not
ask for names, email, tenant/subscription IDs, or private workload details. A new
attempt ID is not a persistent user ID; duplicates cannot reliably be prevented.

`case_id` fingerprints the comparison timestamps, counts, scope, and grouped
facts; it is not a full-snapshot content hash. Archive the actual input snapshots
for controlled experiments. `view_id` hashes the presentation/measurement source
and feature descriptions so uncommitted local previews are distinguishable too.

The clock uses elapsed time, not interval ticks. Tab hiding ends reading and marks
the attempt interrupted; switching away while answering also marks it. A timer
overrun above 250 ms excludes an attempt from the suggested scoring cohort. Keep
the raw time: a timeout is approximately a 15-second exposure, not evidence that
the reader was ready in under 15 seconds. The **skip** path is qualitative only.

`candidate_for_scoring` is an eligibility suggestion, **not a correctness score**.
Readers can inspect/change client-side data; this is a low-stakes research tool,
not an assessment, anti-cheating system, or authoritative telemetry. Founder
familiarity is not removed merely by selecting "No" for prior exposure.

### Human review if a formal study is later agreed

Explain the public sharing model and obtain agreement to research use before
collecting participant results. Do not infer research consent from a GitHub issue
alone. Keep malformed/unsupported packets for review, not as passing results.
Deduplicate repeated copies of `attempt_id` without treating it as a unique person.

Suggested analysis columns:

`issue_url`, `attempt_id`, `protocol`, `view_id`, `case_id`, `role`,
`prior_exposure`, `reading_elapsed_ms`, `end_reason`, `interrupted`, `used_help`,
`consent`, `Q_main_correct`, `Q_region_correct`, `Q_evidence_correct`,
`Q_recovery_correct`, `Q_feature_correct`, `clarity`, `reviewer`, `reviewed_at`.

Before collecting a comparison, the maintainer freezes expected answers for its
case. A human grades the main-change and region answers against the exact dated
facts, accepting equivalent names. Evidence/recovery answers must preserve the
observation limits. Grade feature meaning separately against cited documentation,
including a correct statement that an exact capability is unverified.

Proposed primary measure for that later study:

**Verified comprehension rate = eligible submitted attempts with all four core
answers correct / eligible submitted attempts reviewed.**

Eligibility: consent; supported protocol; first exposure; timed attempt; no
interruptions/help; acceptable timer overrun; complete core answers; no duplicate
packet. Wrong or "not sure" answers are failures, not exclusions. Incomplete
submissions are reported separately, not silently removed to inflate a score.

Also report per-question accuracy, feature-explanation accuracy, sample size by
role/case/view, median readiness time for **early-finish** attempts only, and the
number of interrupted/repeat/qualitative responses. Clarity is supporting
feedback, not proof of correctness.

This setup measures only **submitted** attempts. With no background telemetry, it
cannot measure visits, starts, abandonment, or a completion/conversion rate.
GitHub issue creation time is not the dashboard's reading time.

For credible before/after results, retain fixed cases and recruit fresh readers
assigned to baseline/candidate presentations. Counterbalance if the same people
participate; separate repeat exposure rather than treating memorization as an
improvement. Report small samples honestly and do not claim causality from
self-selected reports. Retain only the records needed for an agreed analysis;
public issue/attachment history is not a private retention-controlled dataset.
