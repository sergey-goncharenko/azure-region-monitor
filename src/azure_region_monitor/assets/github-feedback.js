(() => {
  "use strict";
  const MAX_ISSUE_URL = 6000;
  const MAX_PNG_BYTES = 10 * 1024 * 1024;
  const MAX_PIXELS = 3840 * 2160;

  function issueUrl(title, body, repositoryUrl) {
    if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repositoryUrl)) {
      throw new Error("The feedback repository URL is invalid.");
    }
    if (typeof title !== "string" || typeof body !== "string" || !title.trim() || !body.trim()) {
      throw new Error("A feedback title and body are required.");
    }
    const url = new URL(`${repositoryUrl}/issues/new`);
    url.searchParams.set("title", title);
    url.searchParams.set("body", body);
    if (url.href.length > MAX_ISSUE_URL) {
      throw new Error("The GitHub draft URL is too long. Shorten the feedback; nothing was truncated or submitted.");
    }
    return url.href;
  }
  window.AzureMonitorFeedback = Object.freeze({issueUrl});

  const dataNode = document.getElementById("github-feedback-context-data");
  if (!dataNode) return;
  const config = JSON.parse(dataNode.textContent);
  const get = name => document.getElementById(`github-feedback-${name}`);
  const dialog = get("dialog");
  const launcher = get("launcher");
  const status = get("status");
  const draft = get("draft");
  let image = null;
  let imageUrl = null;
  let imageName = null;
  let state = null;
  let busy = false;
  let returnFocus = null;
  get("capture").disabled = get("text").disabled = false;
  document.body.classList.add("has-feedback-widget");

  const shorten = (value, limit) => {
    const text = String(value);
    return text.length > limit ? text.slice(0, limit) + "... [shortened]" : text;
  };

  function pageState() {
    const filters = {};
    for (const id of ["briefing-region", "briefing-modality", "briefing-search", "search", "region", "modality", "group", "status", "page-size"]) {
      const input = document.getElementById(id);
      if (input && input.value) filters[id] = shorten(input.value, 60);
    }
    const sections = Array.from(document.querySelectorAll("main details[open] > summary"));
    return {
      page: config.site_url + config.page_path,
      local_or_preview: location.origin !== config.site_url,
      snapshot_date: config.date,
      snapshot_timestamp: config.current_timestamp,
      previous_timestamp: config.previous_timestamp,
      presentation: config.view_id,
      filters,
      viewport: {width: innerWidth, height: innerHeight, scale: devicePixelRatio},
      scroll: {x: Math.round(scrollX), y: Math.round(scrollY)},
      expanded_sections: sections.slice(0, 3).map(node => shorten(node.textContent.trim(), 50)),
      additional_expanded_sections: Math.max(0, sections.length - 3),
      observed_at: new Date().toISOString(),
    };
  }

  function clearImage() {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    image = imageUrl = imageName = null;
    get("preview").removeAttribute("src");
    get("image").hidden = true;
    if (state) delete state.screenshot;
  }

  function updateContext() {
    get("context").textContent = JSON.stringify(state, null, 2);
  }

  function showDialog(message) {
    status.textContent = message;
    get("error").textContent = "";
    draft.hidden = true;
    draft.removeAttribute("href");
    updateContext();
    dialog.showModal();
    get(image ? "close" : "unclear").focus();
  }

  function openText(event) {
    if (busy || dialog.open) return;
    returnFocus = event?.currentTarget || get("text");
    state = pageState();
    clearImage();
    showDialog("No screenshot captured. You can attach a manual screenshot in GitHub.");
  }

  function verifyTrack(track, handle) {
    if (track.getSettings().displaySurface !== "browser" ||
        typeof track.getCaptureHandle !== "function") {
      throw new Error("Only a verified browser-tab capture is accepted. Windows and full screens are not captured.");
    }
    const captured = track.getCaptureHandle();
    if (!captured || captured.origin !== location.origin || captured.handle !== handle) {
      throw new Error("That is not this website tab. No image was saved. Choose this tab, or use a manual screenshot.");
    }
  }

  async function readyFrame(video) {
    let timeout;
    let poll;
    let finished = false;
    const ready = new Promise((resolve, reject) => {
      timeout = setTimeout(() => reject(new Error("The captured tab did not provide a video frame.")), 8000);
      // Off-DOM video is decoded but not composited, so frame callbacks may never run.
      const check = () => {
        if (finished) return;
        if (video.readyState >= 2 && video.videoWidth && video.videoHeight) resolve();
        else poll = setTimeout(check, 50);
      };
      video.play().then(check, reject);
    });
    try {
      await ready;
      if (!video.videoWidth || !video.videoHeight) throw new Error("The captured frame is empty.");
    } finally {
      finished = true;
      clearTimeout(timeout);
      clearTimeout(poll);
    }
  }

  async function capture(event) {
    if (busy || dialog.open) return;
    busy = true;
    returnFocus = event.currentTarget;
    const requested = new Date().toISOString();
    let stream;
    let video;
    let message;
    clearImage();
    launcher.hidden = true;
    try {
      const media = navigator.mediaDevices;
      if (!media?.getDisplayMedia || !media.setCaptureHandleConfig || !crypto.randomUUID) {
        throw new Error("Verified current-tab capture is unavailable in this browser. Use desktop Chrome/Edge, or attach a manual screenshot.");
      }
      const handle = crypto.randomUUID();
      media.setCaptureHandleConfig({handle, exposeOrigin: true, permittedOrigins: [location.origin]});
      stream = await media.getDisplayMedia({
        video: {displaySurface: "browser"}, audio: false,
        preferCurrentTab: true, selfBrowserSurface: "include",
        monitorTypeSurfaces: "exclude", surfaceSwitching: "exclude", systemAudio: "exclude",
      });
      const [track] = stream.getVideoTracks();
      if (!track) throw new Error("No video track was provided.");
      verifyTrack(track, handle);
      let changed = false;
      track.addEventListener("capturehandlechange", () => { changed = true; });
      video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await readyFrame(video);
      verifyTrack(track, handle);
      if (changed || track.readyState !== "live") throw new Error("The captured tab changed or sharing stopped. No image was saved.");
      const scale = Math.min(1, Math.sqrt(MAX_PIXELS / (video.videoWidth * video.videoHeight)));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.floor(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.floor(video.videoHeight * scale));
      const drawing = canvas.getContext("2d");
      if (!drawing) throw new Error("This browser could not create a screenshot canvas.");
      drawing.drawImage(video, 0, 0, canvas.width, canvas.height);
      state = pageState();
      const png = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      if (!png) throw new Error("This browser could not encode the screenshot.");
      if (png.size > MAX_PNG_BYTES) throw new Error("The PNG exceeds GitHub's 10 MB image limit. Use a smaller viewport or a manual screenshot.");
      image = png;
      imageName = `reader-feedback-${config.date || "page"}-${Date.now()}.png`;
      imageUrl = URL.createObjectURL(image);
      state.screenshot = {
        method: "verified-current-tab", requested_at: requested,
        captured_at: state.observed_at, width: canvas.width, height: canvas.height,
        source_width: video.videoWidth, source_height: video.videoHeight,
        bytes: png.size, filename: imageName,
      };
      get("preview").src = imageUrl;
      get("image-info").textContent = `${canvas.width} x ${canvas.height} PNG. Captured after browser permission, before this panel opened. Sharing has stopped.`;
      get("image").hidden = false;
      message = "Screenshot kept locally. Review it, then copy or download it for manual attachment in GitHub.";
    } catch (error) {
      clearImage();
      state = pageState();
      message = error.name === "NotAllowedError" ?
        "Capture was cancelled or not permitted. Continue without a screenshot, or attach one manually in GitHub." :
        `Screenshot unavailable: ${error.message}`;
    } finally {
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (video) { video.pause(); video.srcObject = null; }
      launcher.hidden = false;
      busy = false;
    }
    state.feedback_clicked_at = requested;
    showDialog(message);
  }

  function close() {
    dialog.close();
    clearImage();
    state = null;
    get("form").reset();
    draft.hidden = true;
    draft.removeAttribute("href");
    returnFocus?.focus({preventScroll: true});
  }
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  get("close").addEventListener("click", close);
  get("capture").addEventListener("click", capture);
  get("text").addEventListener("click", openText);
  document.querySelectorAll('a[href="/feedback.html"], a[href="feedback.html"]').forEach(link => {
    link.addEventListener("click", event => { event.preventDefault(); openText(event); });
  });
  get("remove").addEventListener("click", () => {
    clearImage();
    updateContext();
    draft.hidden = true;
    draft.removeAttribute("href");
    status.textContent = "Screenshot removed. You can submit text-only feedback.";
  });
  get("copy").addEventListener("click", async () => {
    if (!image) return;
    try {
      await navigator.clipboard.write([new ClipboardItem({"image/png": image})]);
      status.textContent = "Screenshot copied. Paste it into the GitHub issue body; pasting uploads it to GitHub.";
    } catch (error) {
      status.textContent = `Clipboard image copy is unavailable (${error.name}). Download the PNG and attach it manually instead.`;
    }
  });
  get("download").addEventListener("click", () => {
    if (!imageUrl) return;
    const link = document.createElement("a");
    link.href = imageUrl;
    link.download = imageName;
    link.click();
    status.textContent = "PNG download requested. Attach it in GitHub; nothing was uploaded by this website.";
  });
  get("form").addEventListener("input", () => {
    draft.hidden = true;
    draft.removeAttribute("href");
    get("error").textContent = "";
  });
  get("form").addEventListener("submit", event => {
    event.preventDefault();
    if (!state || !get("form").reportValidity()) return;
    const screen = state.screenshot;
    const body = [
      "## What was unclear or wrong?", get("unclear").value.trim(),
      "", "## What would have helped?", get("improve").value.trim() || "Not specified.",
      "", "## Page context",
      `- Page: ${state.page}${state.local_or_preview ? " (local/preview presentation; not necessarily deployed)" : ""}`,
      `- Snapshot: ${state.snapshot_date || "not available"}; current ${state.snapshot_timestamp || "not available"}; previous ${state.previous_timestamp || "not available"}`,
      `- Presentation: ${state.presentation}`,
      `- Viewport: ${state.viewport.width} x ${state.viewport.height}; scale ${state.viewport.scale}; scroll ${state.scroll.x}, ${state.scroll.y}`,
      `- Filters: ${JSON.stringify(state.filters)}`,
      `- Expanded: ${JSON.stringify(state.expanded_sections)}; ${state.additional_expanded_sections} additional open sections`,
      `- Observed: ${state.observed_at}`,
      "", "## Screenshot",
      screen ?
        `Captured after permission: ${screen.captured_at}; requested ${screen.requested_at}; ${screen.width} x ${screen.height} PNG.\nPaste or attach ${screen.filename} here before submitting. The website did not upload it.` :
        "No screenshot captured by the website. Attach a manual screenshot if useful.",
      "", "Maintainer/reader feedback; not an unbiased first-time-reader measurement or an automatic coding instruction.",
    ].join("\n");
    try {
      draft.href = issueUrl(`[reader-feedback] ${config.date || "Website"} ${config.page_path}`, body, config.repository_url);
      draft.hidden = false;
      get("error").textContent = "";
      draft.click();
      status.textContent = "A GitHub draft was requested. If it did not open, use the prepared-draft link. Review and submit on GitHub; nothing was posted automatically.";
    } catch (error) {
      draft.hidden = true;
      draft.removeAttribute("href");
      get("error").textContent = error.message;
    }
  });
})();
