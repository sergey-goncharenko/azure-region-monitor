"""Optional, browser-local comprehension checks with a reviewable GitHub draft."""

from __future__ import annotations

import html
import json
from typing import Any

from azure_region_monitor.briefing_view import has_briefing, render_briefing
from azure_region_monitor.feedback_context import measurement_context as measurement_context
from azure_region_monitor.feedback_context import presentation_id as presentation_id


def render_reading_check_page(day: dict[str, Any] | None, style: str, view_id: str) -> str:
    title = "Optional briefing reading check"
    if day is None or not has_briefing(day):
        body = '<p>A complete daily briefing is not available for a reading check yet. Please try again after the next snapshot comparison.</p>'
    else:
        context = measurement_context(day, view_id)
        encoded = json.dumps(context, ensure_ascii=True).replace("<", "\\u003c")
        body = f"""
        <section class="panel feedback-intro">
          <h2>A voluntary 15-second reading check</h2>
          <p>This optional research check is not the main feedback path.
             For maintainer observations, use <a href="/feedback.html">page feedback</a> instead.
             Founder or repeat-reader observations are qualitative, not unbiased first-time-reader results.</p>
          <p>Read the briefing, then answer from memory: what changed most, where, and what does the evidence prove?
             This measures comprehension, not whether you liked the design.</p>
          <p><strong>Privacy:</strong> answers and timing stay in this page's memory.
             No analytics, cookies, background submissions, or browser storage.
             Ordinary page/evidence requests still reach the static host.
             Opening a GitHub draft sends its summary to GitHub, but does not submit an issue.
             You review it and choose the final Submit on GitHub.</p>
          <p><strong>Public feedback:</strong> submitted issues and attachments in this repository are public.
             Do not share secrets or private information. The dashboard needs no backend or authentication token.</p>
          <p>Use one attempt. Switching away from this tab marks it interrupted; it does not silently pause the clock.
             You may stop or skip at any time. Do not enter names, email addresses, subscription IDs, or private workload details.</p>
          <p>No screenshot capture is offered in this timed check. Use normal page feedback for optional screenshots.</p>
          <div class="feedback-profile">
            <label for="reader-role">Your perspective<select id="reader-role" required>
              <option value="">Choose a perspective</option>
              <option value="architect">Cloud architect</option><option value="sre">SRE / operations</option>
              <option value="manager">Manager</option><option value="engineer">Engineer / technical reader</option>
              <option value="other">Another perspective / prefer not to say</option>
            </select></label>
            <label for="reader-prior">Have you already read this dated briefing?<select id="reader-prior" required>
              <option value="">Choose an answer</option><option value="no">No</option>
              <option value="yes">Yes</option><option value="unsure">Not sure</option>
            </select></label>
          </div>
          <p>Case: {html.escape(day['date'])}. The timer limits reading, not answering.
             This is a self-selected check, not a controlled experiment.</p>
          <button type="button" id="reader-start" disabled>Start reading</button>
          <button type="button" id="reader-skip" disabled>Skip timer; leave qualitative feedback</button>
          <p role="status" id="reader-status">Choose your perspective and prior familiarity to begin.</p>
          <noscript><p>JavaScript is needed for the local check. You can still read the dashboard.</p></noscript>
        </section>
        <section id="reader-reading" hidden aria-label="Timed reading">
          <div class="feedback-timer"><strong id="reader-clock" aria-live="off">15 seconds</strong>
            <button type="button" id="reader-ready">I'm ready to answer</button></div>
          {render_briefing(day, include_feedback=False)}
        </section>
        <section class="panel feedback-answers" id="reader-answers" hidden>
          <h2>Answer without reopening the briefing</h2>
          <form id="reader-response">
            <label for="reader-main">1. What changed most since the previous scan?
              <textarea id="reader-main" rows="3" maxlength="500" required></textarea></label>
            <label for="reader-region">2. Name one region affected by a new change or evidence gap. If there were none, say so.
              <input id="reader-region" maxlength="200" required></label>
            <label for="reader-proof">3. What does this briefing establish?
              <select id="reader-proof" required><option value="">Choose an answer</option>
                <option value="deployment">The listed features were successfully deployed</option>
                <option value="observations">Only the catalog or measurement observations stated</option>
                <option value="capacity">Capacity and quota are available for my subscription</option>
                <option value="retirement">Missing listings are confirmed retirements</option>
                <option value="unsure">Not sure</option></select></label>
            <label for="reader-recovery">4. Does zero NEW delistings prove that previously missing listings recovered?
              <select id="reader-recovery" required><option value="">Choose an answer</option>
                <option value="yes">Yes</option><option value="no">No</option><option value="unsure">Not sure</option>
              </select></label>
            <label for="reader-feature">5. Name one feature and explain what distinguishes it. (Optional)
              <textarea id="reader-feature" rows="3" maxlength="400"></textarea></label>
            <label for="reader-clarity">6. How easy was the briefing to understand?
              <select id="reader-clarity" required><option value="">Choose a rating</option>
                <option value="1">1 - Very difficult</option><option value="2">2 - Difficult</option>
                <option value="3">3 - Mixed</option><option value="4">4 - Easy</option><option value="5">5 - Very easy</option>
              </select></label>
            <label for="reader-confusion">7. What was confusing, missing, or hard to find? (Optional)
              <textarea id="reader-confusion" rows="3" maxlength="500"></textarea></label>
            <label class="feedback-helped"><input id="reader-helped" type="checkbox">
              I used another tab, reopened the briefing, or received help while answering.</label>
            <button type="submit">Prepare my result locally</button>
          </form>
        </section>
        <section class="panel feedback-export" id="reader-export" hidden>
          <h2>Review before sharing</h2>
          <p id="reader-result-note"></p>
          <p>This is <strong>not submitted</strong>. Open a GitHub draft to review a human-readable summary
             of your answers, case/view IDs, timing, and eligibility. No raw JSON packet goes in the URL.
             Only your final Submit on GitHub creates the public issue.</p>
          <p>The full local record includes your answers, timing, role, case ID, and presentation version,
             with no expected answers or automatic grade. You may download JSON and manually attach it
             to the draft. Review it first: attachments upload immediately when pasted or attached on GitHub,
             even before you submit the issue.</p>
          <label for="reader-packet">Your full local record (JSON)<textarea id="reader-packet" rows="9" readonly></textarea></label>
          <div class="feedback-actions"><button type="button" id="reader-copy">Copy packet</button>
            <button type="button" id="reader-download">Download JSON</button></div>
          <p role="status" id="reader-copy-status"></p>
          <a id="reader-draft" href="#reader-export" target="_blank" rel="noopener noreferrer"
             referrerpolicy="no-referrer">Open GitHub draft</a>
          <p id="reader-draft-status" role="alert"></p>
          <p>GitHub may log the draft URL and requires its own sign-in to submit. The dashboard never asks for a token.
             If the summary exceeds the draft URL limit, the full local result and JSON download remain available;
             nothing is truncated or automatically sent.</p>
        </section>
        <script id="reader-context" type="application/json">{encoded}</script>
        <script src="/assets/github-feedback.js" defer></script>
        <script src="/assets/reader-feedback.js" defer></script>"""
    return f"""<!doctype html><html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <meta name="robots" content="noindex"><meta name="referrer" content="no-referrer">
      <title>{title}</title>{style}</head><body><main class="content-page reader-study">
      <header><h1>{title}</h1><a href="/">Back to dashboard</a>
        · <a href="/feedback.html">Maintainer page feedback</a></header>{body}
      </main></body></html>"""
