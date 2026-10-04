"use strict";

const https = require("node:https");
const fs = require("node:fs");
const path = require("node:path");

const MAX_RESPONSE_BYTES = 64 * 1024 * 1024;
const MIME = {
  ".json": "application/json; charset=utf-8",
  ".gz": "application/gzip",
  ".html": "text/html; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

function archiveUrl(base, requestedPath) {
  const url = new URL(base);
  if (url.protocol !== "https:" || url.port || url.username || url.password ||
      url.search || url.hash || !/^[a-z0-9]{3,24}\.blob\.core\.windows\.net$/.test(url.hostname) ||
      !/^\/[a-z0-9][a-z0-9-]+\/publications\/[0-9]+-[0-9]+$/.test(url.pathname)) {
    throw new Error("Invalid pinned archive configuration.");
  }
  if (typeof requestedPath !== "string" ||
      !/^(?:api\/(?!archive\/)|blog\/|feedback\/|reading-check\/|assets\/|archive\/)/.test(requestedPath) ||
      !/^[a-zA-Z0-9_./-]+$/.test(requestedPath) ||
      requestedPath.split("/").some((part) => !part || part === "." || part === "..")) {
    return null;
  }
  return new URL(url.href.replace(/\/$/, "") + "/" + requestedPath);
}

function download(url, method) {
  return new Promise((resolve, reject) => {
    const request = https.request(url, {
      method,
      headers: { "Accept-Encoding": "identity" },
      timeout: 30000,
    }, (response) => {
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > MAX_RESPONSE_BYTES) {
          response.destroy(new Error("Archive object exceeds the reader response limit."));
          return;
        }
        chunks.push(chunk);
      });
      response.on("error", reject);
      response.on("end", () => resolve({
        status: response.statusCode,
        headers: response.headers,
        body: Buffer.concat(chunks),
      }));
    });
    request.on("timeout", () => request.destroy(new Error("Archive request timed out.")));
    request.on("error", reject);
    request.end();
  });
}

async function respond(req, config, get = download) {
  const headers = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  };
  if (req.method === "OPTIONS") return { status: 204, headers };
  if (!["GET", "HEAD"].includes(req.method)) return { status: 405, headers };
  const requestUrl = new URL(req.url, "https://archive.invalid");
  const history = requestUrl.pathname.startsWith("/api/history/");
  const archivedPage = requestUrl.pathname.startsWith("/api/archive/");
  const relativePath = (history ? "api/history/" : archivedPage ? "" : "api/") +
    (req.params?.path || "");
  let target;
  try {
    if (typeof config.generation !== "string" || !/^[0-9a-f]{64}$/.test(config.generation)) {
      throw new Error("Invalid archive generation.");
    }
    target = archiveUrl(config.archive_base_url, relativePath);
  } catch {
    return { status: 503, headers, body: "Archive configuration is unavailable." };
  }
  if (!target) return { status: 400, headers, body: "Invalid archive evidence path." };
  try {
    let upstream = await get(target, req.method);
    let compressedAlias = false;
    if (upstream.status === 404 &&
        /^api\/history\/snapshots\/\d{4}-\d{2}-\d{2}\.json$/.test(relativePath)) {
      upstream = await get(new URL(target.href + ".gz"), req.method);
      compressedAlias = upstream.status === 200;
    }
    if (upstream.status === 404) {
      return { status: 404, headers, body: "The requested archive evidence is missing." };
    }
    if (upstream.status !== 200) {
      return { status: 502, headers, body: "Archive evidence could not be retrieved." };
    }
    return {
      status: 200,
      headers: {
        ...headers,
        "Cache-Control": "public, max-age=300, must-revalidate",
        "X-Archive-Generation": config.generation,
        "Content-Type": MIME[path.extname(relativePath)] || "application/octet-stream",
        ...(compressedAlias ? { "Content-Encoding": "gzip" } : upstream.headers["content-encoding"] ?
          { "Content-Encoding": upstream.headers["content-encoding"] } : {}),
      },
      body: req.method === "HEAD" ? undefined : upstream.body,
      isRaw: true,
    };
  } catch {
    return { status: 502, headers, body: "Archive evidence is temporarily unavailable." };
  }
}

module.exports = async function (context, req) {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(__dirname, "archive-config.json"), "utf8"));
    context.res = await respond(req, config);
    if (context.res.status >= 500) context.log.error(context.res.body);
  } catch (error) {
    context.log.error("Archive reader configuration failed: " + error.message);
    context.res = {
      status: 503,
      headers: { "Cache-Control": "no-store", "Content-Type": "text/plain" },
      body: "Archive configuration is unavailable.",
    };
  }
};
module.exports.respond = respond;
module.exports.archiveUrl = archiveUrl;
