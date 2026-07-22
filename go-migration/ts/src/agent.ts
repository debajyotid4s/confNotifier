import { chromium } from 'playwright';
import * as readline from 'node:readline';
import type { BrowserRequest, BrowserResponse } from './protocol';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  });
  const page = await context.newPage();

  const rl = readline.createInterface({ input: process.stdin });

  for await (const line of rl) {
    if (!line.trim()) continue;

    let req: BrowserRequest;
    try {
      req = JSON.parse(line);
    } catch {
      continue;
    }

    if (req.method === 'shutdown') break;

    const resp: BrowserResponse = { id: req.id };

    try {
      await page.goto(req.params!.url, {
        timeout: req.params?.timeout ?? 30000,
        waitUntil: 'domcontentloaded',
      });

      if (req.method === 'fetch_page_html') {
        resp.result = await page.content();
      } else {
        resp.result = await page.evaluate(() => document.body.innerText);
      }
    } catch (err: any) {
      resp.error = err?.message ?? String(err);
    }

    process.stdout.write(JSON.stringify(resp) + '\n');
  }

  await browser.close();
}

main().catch((err) => {
  console.error('browser agent fatal:', err);
  process.exit(1);
});
