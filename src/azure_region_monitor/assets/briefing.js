(() => {
  "use strict";
  const pageSize = 20;
  const number = value => Number(value).toLocaleString("en-US");
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };

  document.querySelectorAll(".reader-briefing").forEach(root => {
    if (root.dataset.initialized) return;
    root.dataset.initialized = "true";
    const data = JSON.parse(root.querySelector(".briefing-data").textContent);
    const region = root.querySelector("#briefing-region");
    const modality = root.querySelector("#briefing-modality");
    const reset = root.querySelector("[data-reset-briefing]");
    const search = root.querySelector("#briefing-search");
    const explorer = root.querySelector(".briefing-explorer");
    const status = root.querySelector("[data-evidence-status]");
    const retry = root.querySelector("[data-evidence-retry]");
    const rows = root.querySelector("[data-evidence-rows]");
    const pager = root.querySelector(".briefing-pager");
    const previous = root.querySelector("[data-evidence-prev]");
    const next = root.querySelector("[data-evidence-next]");
    let records = null;
    let featureContexts = {};
    let loading = false;
    let page = 0;
    let selectedGroup = null;
    let pages = 1;
    region.disabled = modality.disabled = reset.disabled = false;

    const regionName = value => data.regions[value] || value;
    const groupMatches = record => selectedGroup === null ||
      (record.kind === data.groups[selectedGroup].kind &&
       record.modality === data.groups[selectedGroup].modality);

    function updateCards() {
      let matching = 0;
      let visibleGroups = 0;
      data.groups.forEach((group, index) => {
        const card = root.querySelector(`[data-group="${index}"]`);
        const count = region.value ? (group.region_counts[region.value] || 0) : group.listing_count;
        const visible = count > 0 && (!modality.value || group.modality === modality.value);
        card.hidden = !visible;
        if (!visible) return;
        visibleGroups += 1;
        matching += count;
        const features = region.value ? count : group.feature_count;
        const units = data.featureUnits[group.modality] || ["feature", "features"];
        card.querySelector("[data-feature-count]").textContent = number(features);
        card.querySelector("[data-feature-unit]").textContent = units[features === 1 ? 0 : 1];
        card.querySelector("[data-listing-count]").textContent = number(count);
        card.querySelector("[data-record-unit]").textContent = count === 1 ? "record" : "records";
        card.querySelector("[data-regions]").textContent = region.value ?
          regionName(region.value) : group.regions.map(regionName).join(", ");
        card.querySelectorAll(".briefing-example, .briefing-novelty, .briefing-feature-context").forEach(example => {
          example.hidden = Boolean(region.value);
        });
      });
      root.querySelector("[data-empty]").hidden = visibleGroups > 0;
      root.querySelector("[data-selection]").textContent =
        `${region.value ? regionName(region.value) : "All regions"} \u00b7 ${modality.value || "All services"}: ` +
        `${number(matching)} matching feature-region records in ${visibleGroups} ${visibleGroups === 1 ? "group" : "groups"}. ` +
        "Scan-wide totals above do not change with these filters.";
    }

    function showRecordDetails(container, items) {
      const list = element("ul");
      items.forEach(record => {
        const item = element("li");
        item.append(element("strong", regionName(record.region) + " "));
        item.append(element("code", record.region));
        item.append(element("p",
          `${record.previous ?? "not observed"} \u2192 ${record.current ?? "not observed"}`));
        for (const [label, evidence] of [["Previous", record.evidence_before], ["Current", record.evidence_after]]) {
          if (!evidence) continue;
          item.append(element("p", `${label} snapshot: ${evidence.timestamp}; source: ${evidence.source}.`));
          if (evidence.detail) item.append(element("p", evidence.detail));
          if (evidence.error_code) item.append(element("p", `Probe error: ${evidence.error_code}`));
        }
        if (record.last_available_date) item.append(element("p", `Last tracked positive listing: ${record.last_available_date}`));
        if (record.absence_since) item.append(element("p", `Tracked absence since: ${record.absence_since}`));
        if (record.scope_reason) item.append(element("p", record.scope_reason));
        list.append(item);
      });
      container.append(list);
    }

    function renderEvidence() {
      if (records === null) return;
      const query = search.value.trim().toLowerCase();
      const filtered = records.filter(record =>
        (!region.value || record.region === region.value) &&
        (!modality.value || record.modality === modality.value) &&
        groupMatches(record) &&
        (!query || `${record.feature} ${record.label || ""} ${featureContexts[record.feature]?.title || ""} ${(featureContexts[record.feature]?.differentiators || []).join(" ")}`.toLowerCase().includes(query)));
      const grouped = new Map();
      filtered.forEach(record => {
        const key = JSON.stringify([record.kind, record.service, record.feature]);
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(record);
      });
      const groups = Array.from(grouped.values());
      pages = Math.max(1, Math.ceil(groups.length / pageSize));
      page = Math.min(page, pages - 1);
      rows.replaceChildren();
      groups.slice(page * pageSize, (page + 1) * pageSize).forEach(items => {
        const record = items[0];
        const article = element("article", undefined, "briefing-feature");
        article.append(element("span", data.kindLabels[record.kind] || record.kind, "briefing-kind"));
        article.append(element("h4", record.label || record.feature));
        article.append(element("code", record.feature));
        article.append(element("p", `${items.length} region${items.length === 1 ? "" : "s"}: ` +
          items.map(item => regionName(item.region)).join(", ")));
        const before = record.coverage_before;
        const after = record.coverage_after;
        if (before && after) {
          article.append(element("p",
            `Scan-wide listing coverage: ${before.available}/${before.total_regions} \u2192 ${after.available}/${after.total_regions} regions.`));
        }
        if (record.novelty) article.append(element("p", record.novelty, "briefing-novelty"));
        const context = featureContexts[record.feature];
        if (context) {
          article.append(element("h5", context.title));
          article.append(element("p", context.summary));
          const facts = element("ul");
          context.differentiators.forEach(fact => facts.append(element("li", fact)));
          article.append(facts);
          if (context.use_cases) article.append(element("p", context.use_cases));
          article.append(element("p", context.limitations, "briefing-context-limit"));
          const sources = element("p", "Read more: ", "briefing-context-sources");
          context.sources.forEach((source, index) => {
            const url = new URL(source.url);
            if (url.protocol === "https:" && !url.username && !url.password) {
              if (index) sources.append(document.createTextNode(" \u00b7 "));
              const link = element("a", source.label);
              link.href = url.href;
              link.target = "_blank";
              link.rel = "noopener noreferrer";
              sources.append(link);
            } else {
              sources.append(element("span", "Reference URL unavailable"));
            }
          });
          article.append(sources);
          article.append(element("p",
            `Context level: ${context.specificity}. ${context.verified_on ? `Sources checked: ${context.verified_on}.` : "Exact product capabilities have not been verified."}`,
            "briefing-context-limit"));
        } else if (record.feature_note) article.append(element("p", record.feature_note));
        if (!context && record.details_url) {
          const url = new URL(record.details_url, location.origin);
          if (url.protocol === "https:" && url.hostname === "learn.microsoft.com") {
            const link = element("a", "Microsoft Learn: product requirements");
            link.href = url.href;
            article.append(link);
          }
        }
        const details = element("details", undefined, "briefing-records");
        details.append(element("summary", "Exact observations and probe messages"));
        details.addEventListener("toggle", () => {
          if (details.open && !details.dataset.loaded) {
            showRecordDetails(details, items);
            details.dataset.loaded = "true";
          }
        });
        article.append(details);
        rows.append(article);
      });
      status.textContent = `${number(filtered.length)} records grouped into ${number(groups.length)} feature/status entries` +
        (selectedGroup === null ? "." : ` \u00b7 ${data.kindLabels[data.groups[selectedGroup].kind]}. Change filters to view all groups.`);
      pager.hidden = groups.length === 0;
      previous.disabled = page === 0;
      next.disabled = page >= pages - 1;
      root.querySelector("[data-evidence-page]").textContent = `Page ${page + 1} of ${pages}`;
    }

    async function loadEvidence() {
      if (loading || records !== null) return;
      loading = true;
      retry.hidden = true;
      status.textContent = "Loading complete daily evidence...";
      try {
        if (!data.evidenceUrl) throw new Error("No daily evidence URL was published.");
        const response = await fetch(data.evidenceUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (payload.date !== data.date || payload.briefing?.version !== 1 ||
            !Array.isArray(payload.briefing.records)) {
          throw new Error("The daily evidence does not match this briefing.");
        }
        records = payload.briefing.records;
        featureContexts = payload.briefing.feature_contexts || {};
        search.disabled = false;
        renderEvidence();
      } catch (error) {
        status.textContent = `Unable to load evidence: ${error.message} Use the download link or retry.`;
        retry.hidden = false;
      } finally {
        loading = false;
      }
    }

    [region, modality].forEach(control => control.addEventListener("change", () => {
      page = 0;
      selectedGroup = null;
      updateCards();
      renderEvidence();
    }));
    reset.addEventListener("click", () => {
      region.value = modality.value = search.value = "";
      selectedGroup = null;
      page = 0;
      updateCards();
      renderEvidence();
    });
    root.querySelectorAll("[data-explore-group]").forEach(button => {
      button.addEventListener("click", () => {
        selectedGroup = Number(button.dataset.exploreGroup);
        page = 0;
        explorer.open = true;
        loadEvidence();
        renderEvidence();
        explorer.scrollIntoView({block: "start"});
        explorer.querySelector("summary").focus();
      });
    });
    search.addEventListener("input", () => { page = 0; renderEvidence(); });
    explorer.addEventListener("toggle", () => { if (explorer.open) loadEvidence(); });
    retry.addEventListener("click", loadEvidence);
    previous.addEventListener("click", () => { if (page > 0) { page -= 1; renderEvidence(); } });
    next.addEventListener("click", () => { if (page < pages - 1) { page += 1; renderEvidence(); } });
    updateCards();
  });
})();
