(() => {
  "use strict";
  const status = document.getElementById("archive-status");
  const nextButton = document.getElementById("archive-next");
  const previousButton = document.getElementById("archive-previous");
  const retryButton = document.getElementById("archive-retry");
  const list = document.getElementById("archive-days");
  const datedPath = /^\/(blog|feedback|reading-check)\/(\d{4}-\d{2}-\d{2})\.html$/;
  const catalogPath = /^archive\/catalog\/[1-9]\d*\.json$/;
  let next = "archive/catalog/1.json";
  let previous = null;
  let current = next;
  let config;

  const isDatedPath = path => {
    const match = datedPath.exec(path);
    if (!match) return false;
    const date = new Date(match[2] + "T00:00:00Z");
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === match[2];
  };
  const fail = error => {
    status.textContent = "Archive unavailable: " + error.message +
      ". No historical observation has been substituted. Please retry later.";
    status.setAttribute("role", "alert");
    retryButton.hidden = false;
    nextButton.disabled = false;
    previousButton.disabled = false;
  };
  async function response(path) {
    const result = await fetch("/api/archive/" + path, {cache: "no-cache"});
    if (!result.ok) throw new Error("request failed (HTTP " + result.status + ")");
    const generation = result.headers.get("X-Archive-Generation");
    if (generation !== config.generation) throw new Error("archive generation does not match this publication");
    return result;
  }
  async function loadConfig() {
    const result = await fetch("/archive-config.json", {cache: "no-cache"});
    if (!result.ok) throw new Error("publication configuration is missing");
    config = await result.json();
    if (config.schema_version !== 1 || !/^[0-9a-f]{64}$/.test(config.generation)) {
      throw new Error("invalid publication configuration");
    }
  }
  async function loadPage(path) {
    const result = await response(path.slice(1));
    if (!(result.headers.get("Content-Type") || "").startsWith("text/html")) {
      throw new Error("expected an archived HTML document");
    }
    const markup = await result.text();
    if (!/<!doctype html/i.test(markup)) throw new Error("invalid archived HTML document");
    const parsed = new DOMParser().parseFromString(markup, "text/html");
    if (!parsed.title || !parsed.body.textContent.trim()) throw new Error("empty archived document");
    if (parsed.querySelector("base, iframe, object, embed")) throw new Error("unsupported archived document");
    const scripts = [...parsed.querySelectorAll("script")];
    for (const script of scripts) {
      if (script.src && !/^\/assets\/(briefing|github-feedback|reader-feedback)\.js$/.test(script.getAttribute("src"))) {
        throw new Error("unsupported archived script");
      }
    }
    document.documentElement.replaceWith(document.importNode(parsed.documentElement, true));
    for (const script of document.querySelectorAll("script[src]")) {
      const active = document.createElement("script");
      active.src = script.getAttribute("src");
      active.async = false;
      script.replaceWith(active);
    }
  }
  async function loadCatalog(path = current) {
    nextButton.disabled = true;
    previousButton.disabled = true;
    retryButton.hidden = true;
    const result = await response(path);
    const page = await result.json();
    if (page.schema_version !== 1 || !Array.isArray(page.entries) ||
        !Number.isInteger(page.page) || page.page < 1 ||
        (page.next !== null && !catalogPath.test(page.next))) {
      throw new Error("invalid archive catalog");
    }
    const rows = [];
    for (const entry of page.entries) {
      if (!entry.links || !isDatedPath("/blog/" + entry.date + ".html")) {
        throw new Error("invalid archive catalog date");
      }
      const row = document.createElement("li");
      row.textContent = entry.date + " ";
      for (const [label, href] of Object.entries(entry.links)) {
        if (!isDatedPath(href) && !/^\/api\/history\/(snapshots|changes)\/\d{4}-\d{2}-\d{2}\.json(?:\.gz)?$/.test(href)) {
          throw new Error("invalid archive catalog link");
        }
        const link = document.createElement("a");
        link.href = href;
        link.textContent = label;
        row.append(link, " ");
      }
      rows.push(row);
    }
    list.replaceChildren(...rows);
    status.textContent = "Archive page " + page.page + ". " + page.total_days + " recorded dates; no dates discarded.";
    next = page.next;
    current = path;
    previous = page.page > 1 ? "archive/catalog/" + (page.page - 1) + ".json" : null;
    nextButton.hidden = !next;
    previousButton.hidden = !previous;
    nextButton.disabled = false;
    previousButton.disabled = false;
  }
  async function start() {
    try {
      await loadConfig();
      if (location.pathname === "/archive.html") await loadCatalog();
      else await loadPage(location.pathname);
    } catch (error) {
      fail(error);
    }
  }
  if (location.pathname !== "/archive.html" && !isDatedPath(location.pathname)) {
    status.textContent = "Page not found. Only recorded dated blog, feedback, and reading-check pages are eligible for archive lookup.";
    status.setAttribute("role", "alert");
    return;
  }
  nextButton.addEventListener("click", () => loadCatalog(next).catch(fail));
  previousButton.addEventListener("click", () => loadCatalog(previous).catch(fail));
  retryButton.addEventListener("click", start);
  start();
})();
