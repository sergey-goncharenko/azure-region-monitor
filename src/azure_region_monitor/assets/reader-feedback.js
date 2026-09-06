(() => {
  "use strict";
  const contextNode = document.getElementById("reader-context");
  if (!contextNode) return;
  const context = JSON.parse(contextNode.textContent);
  const get = id => document.getElementById(`reader-${id}`);
  const role = get("role");
  const prior = get("prior");
  const start = get("start");
  const skip = get("skip");
  const status = get("status");
  const reading = get("reading");
  const answers = get("answers");
  const response = get("response");
  const exported = get("export");
  const budget = context.reading_budget_ms;
  let state = "ready";
  let started = null;
  let startedAt = null;
  let readingElapsed = null;
  let readingInterrupted = false;
  let answeringInterrupted = false;
  let endReason = null;
  let timeout = null;
  let clock = null;
  let attemptId = null;
  let preparedPacket = null;

  function markdownText(value) {
    return String(value ?? "Not answered").replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/([\\`*_[\]{}()#!|~])/g, "\\$1");
  }

  function draftSummary(packet) {
    const yesNo = value => value ? "yes" : "no";
    const milliseconds = value => value === null ? "not timed" : `${value} ms`;
    const answer = (question, value) =>
      `### ${question}\n> ${markdownText(value || "Not answered").replace(/\r?\n/g, "\n> ")}`;
    const proofLabels = {
      deployment: "The listed features were successfully deployed",
      observations: "Only the catalog or measurement observations stated",
      capacity: "Capacity and quota are available for my subscription",
      retirement: "Missing listings are confirmed retirements",
      unsure: "Not sure",
    };
    const choiceLabels = {yes: "Yes", no: "No", unsure: "Not sure"};
    const result = packet.answers;
    return [
      "## Optional reading check",
      "Eligibility below is not a correctness score. Founder/repeat-reader feedback is qualitative.",
      `- Date: ${markdownText(packet.date)}; protocol: ${markdownText(packet.protocol)}`,
      `- Case ID: ${markdownText(packet.case_id)}; view ID: ${markdownText(packet.view_id)}`,
      `- Attempt ID: ${markdownText(packet.attempt_id)}`,
      `- Snapshots: ${markdownText(packet.previous_timestamp ?? "none")} → ${markdownText(packet.current_timestamp)}`,
      `- Method: ${packet.method}; role: ${markdownText(packet.role)}; prior exposure: ${markdownText(packet.prior_exposure)}`,
      `- Started (UTC): ${markdownText(packet.started_at)}; viewport class: ${packet.viewport}`,
      `- Reading exposure: ${milliseconds(packet.reading_elapsed_ms)}; budget: ${packet.reading_budget_ms} ms; overrun: ${milliseconds(packet.timer_overrun_ms)}`,
      `- End reason: ${packet.end_reason}; interrupted reading/answering: ${yesNo(packet.reading_interrupted)}/${yesNo(packet.answering_interrupted)}; help/reopening: ${yesNo(packet.used_help)}`,
      `- Eligibility suggestion: ${packet.candidate_for_scoring ? "candidate for human comprehension review" : "qualitative/repeat-exposure only"}`,
      answer("What changed most?", result.main_change),
      answer("Affected region", result.affected_region),
      answer("What does the evidence establish?", proofLabels[result.evidence_meaning]),
      answer("Do zero new delistings prove earlier recovery?", choiceLabels[result.zero_delistings_means_recovery]),
      answer("Feature and distinction", result.feature_distinction),
      answer("Clarity", result.clarity ? `${result.clarity}/5` : null),
      answer("What was confusing or missing?", result.confusion),
      "Full JSON record: optionally attach the reviewed download manually. Nothing is submitted by the dashboard.",
    ].join("\n\n");
  }

  function updateStart() {
    start.disabled = skip.disabled = state !== "ready" || !role.value || !prior.value;
  }
  role.addEventListener("change", updateStart);
  prior.addEventListener("change", updateStart);
  updateStart();

  function begin(timed) {
    if (state !== "ready" || !role.value || !prior.value) return;
    attemptId = crypto.randomUUID();
    role.disabled = prior.disabled = start.disabled = skip.disabled = true;
    startedAt = new Date().toISOString();
    if (!timed) {
      state = "answering";
      endReason = "skipped";
      response.querySelectorAll("[required]").forEach(input => { input.required = false; });
      answers.hidden = false;
      status.textContent = "Qualitative feedback only; no timed reading measurement.";
      get("main").focus();
      return;
    }
    state = "reading";
    started = performance.now();
    reading.hidden = false;
    status.textContent = "Read the briefing. It will hide after 15 seconds, or when you choose to answer.";
    reading.scrollIntoView({block: "start"});
    clock = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((budget - (performance.now() - started)) / 1000));
      get("clock").textContent = `${remaining} seconds remaining`;
    }, 100);
    timeout = setTimeout(() => finish("budget"), budget);
    get("ready").focus({preventScroll: true});
  }

  function finish(reason) {
    if (state !== "reading") return;
    readingElapsed = Math.round(performance.now() - started);
    endReason = reason;
    clearTimeout(timeout);
    clearInterval(clock);
    reading.hidden = true;
    state = "answering";
    answers.hidden = false;
    status.textContent = "Reading finished. Answer from memory; no feedback has been sent.";
    get("main").focus();
  }

  start.addEventListener("click", () => begin(true));
  skip.addEventListener("click", () => begin(false));
  get("ready").addEventListener("click", () => finish("ready"));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) return;
    if (state === "reading") {
      readingInterrupted = true;
      finish("interrupted");
    } else if (state === "answering") {
      answeringInterrupted = true;
    }
  });

  response.addEventListener("input", () => {
    if (state === "prepared") state = "answering";
    preparedPacket = null;
    exported.hidden = true;
    get("draft").href = "#reader-export";
    get("draft-status").textContent = "";
  });
  response.addEventListener("submit", event => {
    event.preventDefault();
    if (!["answering", "prepared"].includes(state) || !response.reportValidity()) return;
    const helped = get("helped").checked;
    const overrun = readingElapsed === null ? null : Math.max(0, readingElapsed - budget);
    const candidate = endReason !== "skipped" && prior.value === "no" &&
      !readingInterrupted && !answeringInterrupted && !helped && overrun <= 250;
    const packet = {
      ...context,
      attempt_id: attemptId,
      started_at: startedAt,
      method: endReason === "skipped" ? "qualitative" : "timed",
      role: role.value,
      prior_exposure: prior.value,
      viewport: innerWidth < 720 ? "small" : "large",
      reading_elapsed_ms: readingElapsed,
      timer_overrun_ms: overrun,
      end_reason: endReason,
      reading_interrupted: readingInterrupted,
      answering_interrupted: answeringInterrupted,
      used_help: helped,
      candidate_for_scoring: candidate,
      answers: {
        main_change: get("main").value.trim(),
        affected_region: get("region").value.trim(),
        evidence_meaning: get("proof").value || null,
        zero_delistings_means_recovery: get("recovery").value || null,
        feature_distinction: get("feature").value.trim(),
        clarity: get("clarity").value ? Number(get("clarity").value) : null,
        confusion: get("confusion").value.trim(),
      },
    };
    const encoded = JSON.stringify(packet);
    preparedPacket = packet;
    get("packet").value = encoded;
    const timing = readingElapsed === null ? "No reading timer was used. " :
      `Recorded reading exposure: ${(readingElapsed / 1000).toFixed(2)} seconds. `;
    const reasons = [];
    if (prior.value !== "no") reasons.push("prior exposure is not confirmed as first-time");
    if (readingInterrupted || answeringInterrupted) reasons.push("the tab was interrupted");
    if (helped) reasons.push("help or reopening was reported");
    if (overrun > 250) reasons.push("timer delivery exceeded the permitted overrun");
    get("result-note").textContent = timing + (candidate ?
      "This first-exposure attempt can be reviewed for comprehension. This is not a correctness score." :
      `Keep this as qualitative/repeat-exposure feedback${reasons.length ? ": " + reasons.join("; ") : ""}, separate from first-exposure timed results.`);
    get("copy-status").textContent = "";
    get("draft").href = "#reader-export";
    get("draft-status").textContent = "";
    state = "prepared";
    exported.hidden = false;
    get("packet").focus();
  });

  get("draft").addEventListener("click", event => {
    try {
      if (!preparedPacket) throw new Error("Prepare your local result first.");
      if (!window.AzureMonitorFeedback?.issueUrl) {
        throw new Error("The GitHub draft helper is unavailable.");
      }
      get("draft").href = window.AzureMonitorFeedback.issueUrl(
        `Optional reading check: ${preparedPacket.date}`,
        draftSummary(preparedPacket),
        context.repository_url,
      );
      get("draft-status").textContent = "Opening a reviewable GitHub draft, not submitting an issue.";
    } catch (error) {
      event.preventDefault();
      get("draft").href = "#reader-export";
      get("draft-status").textContent = `${error.message} Your full local result and JSON download are still available. Nothing was truncated or submitted.`;
    }
  });

  get("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(get("packet").value);
      get("copy-status").textContent = "Copied the full local JSON record. Nothing was submitted; review it before sharing.";
    } catch (error) {
      get("packet").focus();
      get("packet").select();
      get("copy-status").textContent = `Clipboard unavailable (${error.name}). Copy the selected packet manually.`;
    }
  });
  get("download").addEventListener("click", () => {
    const blob = new Blob([get("packet").value + "\n"], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `reader-feedback-${context.date}-${attemptId}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    get("copy-status").textContent = "A local JSON download was requested. Nothing was submitted.";
  });
})();
