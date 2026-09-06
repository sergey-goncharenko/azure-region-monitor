"""Static, token-free feedback UI; GitHub handles authentication and publishing."""

from __future__ import annotations

import json
from typing import Any

from azure_region_monitor.feedback_context import REPOSITORY_URL, SITE_URL


def render_feedback_widget(context: dict[str, Any]) -> str:
    payload = json.dumps(
        {**context, "repository_url": REPOSITORY_URL, "site_url": SITE_URL},
        ensure_ascii=True, separators=(",", ":"),
    ).replace("<", "\\u003c")
    return f"""
    <aside class="github-feedback-launcher" aria-label="Give website feedback" id="github-feedback-launcher">
      <button type="button" id="github-feedback-capture" disabled title="Choose this browser tab when prompted">Feedback + screenshot</button>
      <button type="button" id="github-feedback-text" disabled>Feedback only</button>
    </aside>
    <dialog id="github-feedback-dialog" class="github-feedback-dialog" aria-labelledby="github-feedback-heading">
      <div class="github-feedback-heading"><h2 id="github-feedback-heading">Help make this page clearer</h2>
        <button type="button" id="github-feedback-close" aria-label="Close feedback">Close</button></div>
      <p>Two short answers; GitHub will open a draft for your review. No Forms, token, or automatic submission.</p>
      <p class="github-feedback-public"><strong>This repository is public.</strong> Review the text and image for private details.
        Opening the draft sends text/context to GitHub in its URL. Pasting or attaching an image uploads it to GitHub immediately.</p>
      <p id="github-feedback-status" role="status"></p>
      <section id="github-feedback-image" hidden aria-label="Review screenshot">
        <img id="github-feedback-preview" alt="Preview of the captured website tab">
        <p id="github-feedback-image-info"></p>
        <div class="feedback-actions">
          <button type="button" id="github-feedback-copy">Copy screenshot</button>
          <button type="button" id="github-feedback-download">Download PNG</button>
          <button type="button" id="github-feedback-remove">Remove screenshot</button>
        </div>
        <p><strong>Attach it yourself:</strong> copy the screenshot, open the GitHub draft, then paste into its body (or drag in the downloaded PNG).
          A prefilled issue link cannot attach images.</p>
      </section>
      <form id="github-feedback-form">
        <label for="github-feedback-unclear">What was unclear or wrong?
          <textarea id="github-feedback-unclear" rows="3" maxlength="600" required></textarea></label>
        <label for="github-feedback-improve">What would have helped? (Optional)
          <textarea id="github-feedback-improve" rows="3" maxlength="400"></textarea></label>
        <details class="github-feedback-context"><summary>Page context included in the draft</summary>
          <pre id="github-feedback-context"></pre></details>
        <p id="github-feedback-error" role="alert"></p>
        <button type="submit">Open GitHub draft</button>
      </form>
      <p><a id="github-feedback-draft" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" hidden>Open the prepared draft</a></p>
      <p>Nothing is posted by this website. Sign in to GitHub if needed, review, attach your screenshot, and choose Submit.
        Closing this panel clears the local draft and screenshot.</p>
    </dialog>
    <noscript><p><a href="{REPOSITORY_URL}/issues/new">Give feedback on GitHub</a>; attach a screenshot manually.</p></noscript>
    <script id="github-feedback-context-data" type="application/json">{payload}</script>
    <script src="/assets/github-feedback.js" defer></script>
    """


def render_feedback_landing(style: str) -> str:
    return f"""<!doctype html><html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Website feedback</title>{style}</head><body>
      <main class="content-page"><header><h1>Website feedback</h1><a href="/">Back to dashboard</a></header>
        <section class="panel feedback-intro">
          <h2>Feedback goes to GitHub</h2>
          <p>Go to the page you want to report and use the floating <strong>Feedback + screenshot</strong>
            or <strong>Feedback only</strong> button. The page stays in place, so its filters, expanded sections,
            and scroll position can be included.</p>
          <p>For screenshots, choose this browser tab when asked. Capture occurs after you grant permission,
            before the feedback panel opens; it is not a silent snapshot frozen at click time.
            Other tabs, windows, and screens are rejected. Unsupported browsers can use a manual screenshot.</p>
          <p>You review the image locally and paste or attach it in the prefilled GitHub issue.
            Feedback and attachments in this repository are public. No data is automatically uploaded.</p>
          <p><a href="/">Open dashboard</a> &middot; <a href="/blog/">Daily briefings</a></p>
        </section>
        <section class="panel feedback-intro"><h2>Optional reader study</h2>
          <p>Maintainer feedback is qualitative, not unbiased first-time-reader evidence.
            The timed reading check is available separately for deliberate reader testing.</p>
          <a href="/reading-check.html">Open the optional reading check</a>
        </section>
      </main></body></html>"""
