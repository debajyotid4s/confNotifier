"use strict";

//imports
const { chromium } = require("playwright-extra");
const stealth = require("puppeteer-extra-plugin-stealth")();
const fs = require("fs");
const path = require("path");

//declarations
const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
];
chromium.use(stealth);
const BATCH = 3;
const universities = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../config/universities.json"), "utf-8"),
);
const specials = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../config/specials.json"), "utf-8"),
);
const urls = [];

//preprocessings of the stored elements
universities.forEach((element) => {
  urls.push(`https://www.${element}`);
});
specials.forEach((s) => {
  if (s.type === "path_probe") {
    s.candidates.forEach((c) => {
      if (c.includes("{year}")) {
        s.probe_years.forEach((y) =>
          urls.push(
            s.base_url.replace(/\/$/, "") + c.replaceAll("{year}", String(y)),
          ),
        );
      } else {
        urls.push(s.base_url.replace(/\/$/, "") + c);
      }
    });
  } else if (s.type === "subdomain_probe") {
    s.known_prefixes.forEach((p) => {
      s.probe_years.forEach((y) =>
        urls.push(`https://${p}${y}.${s.base_domain}`),
      );
      urls.push(`https://${p}.${s.base_domain}`);
    });
  } else if (s.url) urls.push(s.url);
  else if (s.base_url) urls.push(s.base_url);
});

// Log function
function log(level, msg, extra) {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${level}] ${msg}`;
  if (extra !== undefined) {
    console.log(line, extra);
  } else {
    console.log(line);
  }
}

// browser spawning
(async () => {
  let browser;
  try {
    log("INFO", "Browser is launching...");
    browser = await chromium.launch({
      headless: false,
      args: ["--disable-blink-features=AutomationControlled"],
    });
    log("INFO", "Browser Launched: ok");
    const UA = USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    log("INFO", UA);
    const context = await browser.newContext({
      userAgent: UA,
      viewport: { width: 1280, height: 800 },
      locale: "en-US",
    });
    log("INFO", "Browser Context created");

    for (let i = 0; i < urls.length; i += BATCH) {
      const batches = urls.slice(i, i + BATCH);
      log(
        "INFO",
        `Batch ${Math.floor(i / BATCH) + 1}/${Math.ceil(urls.length / BATCH)}: ${batches.join(", ")}`,
      );

      const pages = await Promise.all(batches.map(() => context.newPage()));
      pages.forEach((p) => {
        p.on("response", (response) => {
          const status = response.status();
          if (status >= 400) log("BAD_RESPONSE", `${status} ${response.url()}`);
        });
        p.on("pageerror", (err) => log("PAGE_ERROR", err.message));
      });

      const results = await Promise.allSettled(
        pages.map((p, idx) =>
          p
            .goto(batches[idx], {
              waitUntil: "domcontentloaded",
              timeout: 30000,
            })
            .then(async () => ({
              url: batches[idx],
              title: await p.title(),
              status: "opened",
            }))
            .catch((err) => ({
              url: batches[idx],
              status: "failed",
              reason: err.message,
            })),
        ),
      );

      results.forEach((r) => {
        const v = r.value || r.reason;
        if (v.status === "opened")
          log("INFO", `Opened ok: ${v.url}`, { title: v.title });
        else
          log("ERROR", `Failed: ${v.url}`, { reason: v.reason || v.message });
      });

      await new Promise((r) => setTimeout(r, 2000 + Math.random() * 2000));
      await Promise.all(pages.map((p) => p.close()));
      log(
        "INFO",
        `Batch ${Math.floor(i / BATCH) + 1} closed, ${Math.max(0, urls.length - (i + BATCH))} remaining`,
      );
    }

    log("INFO", "Done. Closing browser.");
    await browser.close();
  } catch (err) {
    log("ERROR", "Script failed.", { message: err.message, stack: err.stack });
    if (browser) await browser.close();
    process.exit(1);
  }
})();
