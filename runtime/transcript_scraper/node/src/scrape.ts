/**
 * scrape.ts — production Node scraper for Yahoo Finance earnings call transcripts.
 *
 * Interface:
 *   argv: npx tsx src/scrape.ts <ticker> <quarter> <year> <headless>
 *   stdout: single JSON line: { url, raw_text, date, participants, scraped_at }
 *   stderr: all logs and errors
 *   returncode: 0 = success, 1 = failure
 */
import { Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod";

const log = (...args: unknown[]) => console.error("[scrape]", ...args);

// ─── CLI args ───────────────────────────────────────────────────────────────
const [, , ticker, quarter, year, headlessArg] = process.argv;

if (!ticker || !quarter || !year) {
  console.error("[scrape] Usage: npx tsx src/scrape.ts <ticker> <quarter> <year> [headless]");
  process.exit(1);
}

const HEADLESS = (headlessArg ?? "true").toLowerCase() !== "false";
const API_KEY = process.env.ANTHROPIC_API_KEY;

if (!API_KEY) {
  console.error("[scrape] ANTHROPIC_API_KEY env var not set");
  process.exit(1);
}

// ─── Schemas ─────────────────────────────────────────────────────────────────
const MetadataSchema = z.object({
  date: z.string().describe("Date of the earnings call, e.g. 'January 29, 2025'"),
  participants: z.array(
    z.object({
      name: z.string().describe("Full name of the participant"),
      role: z.string().optional().describe("Job title, e.g. 'Chief Executive Officer'"),
      affiliation: z.string().optional().describe("Company or firm name"),
    }),
  ).describe("All speakers and participants listed in the transcript"),
});

// ─── Main ────────────────────────────────────────────────────────────────────
async function main(): Promise<void> {
  const stagehand = new Stagehand({
    env: "LOCAL",
    localBrowserLaunchOptions: { headless: HEADLESS },
    model: {
      modelName: "anthropic/claude-sonnet-4-5",
      apiKey: API_KEY!,
    },
    verbose: 0,
    disablePino: true,
  });

  try {
    await stagehand.init();
    log("Stagehand initialized");

    const page = stagehand.context.pages()[0];

    // ── Step 1: Navigate to earnings-calls listing ──────────────────────────
    const listingUrl = `https://finance.yahoo.com/quote/${ticker}/earnings-calls/`;
    log(`Navigating to ${listingUrl}`);
    await page.goto(listingUrl);

    // ── Step 2: Handle cookie consent (best-effort, failure is not an error) ─
    try {
      await stagehand.act(
        "click any cookie consent or accept-all button if present, otherwise do nothing",
        { timeout: 10000 },
      );
    } catch {
      // cookie consent absent — no-op
    }

    // ── Step 3: Extract transcript list via page.evaluate (DOM anchors) ──────
    log("Extracting transcript links from DOM anchors");

    interface AnchorEntry {
      href: string;
      text: string;
    }

    const anchors: AnchorEntry[] = await page.evaluate(() => {
      return Array.from(
        document.querySelectorAll('a[href*="earnings_call-"]'),
      ).map((a) => ({
        href: (a as HTMLAnchorElement).href,
        text: (a.textContent ?? "").trim(),
      }));
    }) as AnchorEntry[];

    log(`Found ${anchors.length} transcript anchors`);

    if (anchors.length === 0) {
      // Possibly an auth wall — check title
      const title: string = await page.evaluate(() => document.title) as string;
      if (title.toLowerCase().includes("sign in") || title.toLowerCase().includes("login")) {
        console.error("[scrape] Auth wall detected: " + title);
        process.exit(1);
      }
      console.error("[scrape] No transcript anchors found on listing page");
      process.exit(1);
    }

    // ── Step 4: Find matching (quarter, year) entry ───────────────────────────
    // Titles look like: "Q1 FY2026 Earnings Call" or "Q1 2026 Earnings Call"
    const normalizedQuarter = quarter.toUpperCase().replace(/\s+/g, "");
    const normalizedYear = year.trim();

    // Regex: Q<n> followed by optional FY then 4-digit year
    const titlePattern = new RegExp(
      `${normalizedQuarter}[\\s\\-]*(?:FY)?${normalizedYear}`,
      "i",
    );

    let matchedUrl: string | null = null;
    for (const anchor of anchors) {
      if (titlePattern.test(anchor.text)) {
        matchedUrl = anchor.href;
        log(`Matched: "${anchor.text}" → ${matchedUrl}`);
        break;
      }
    }

    if (!matchedUrl) {
      console.error(
        `[scrape] Transcript not found for ${ticker} ${quarter} ${year}. ` +
        `Available titles (first 5): ${anchors.slice(0, 5).map((a) => a.text).join(" | ")}`,
      );
      process.exit(1);
    }

    // ── Step 5: Navigate to transcript page ───────────────────────────────────
    log(`Navigating to transcript page: ${matchedUrl}`);
    await page.goto(matchedUrl);

    // ── Step 6: Extract raw text via selector chain ────────────────────────────
    // Priority: transcript-specific container > main > body fallback
    // Avoids Yahoo navigation chrome ("Skip to navigation", "My Portfolio", etc.)
    interface EvaluateResult {
      text: string;
      usedFallback: boolean;
      matchedSelector: string | null;
      attemptedSelectors: { selector: string; length: number | null; skippedReason: string | null }[];
    }

    const result: EvaluateResult = await page.evaluate(() => {
      const SELECTORS = [
        '[class*="transcript"]',
        "main",
      ];
      const TEXT_MIN = 1000;
      const TEXT_MAX = 200000;
      const attemptedSelectors: { selector: string; length: number | null; skippedReason: string | null }[] = [];

      for (const sel of SELECTORS) {
        // For substring-match selectors, ensure exactly one element matches to avoid
        // hitting unrelated nav/tab elements that also contain the keyword.
        const allMatches = document.querySelectorAll(sel);
        if (allMatches.length === 0) {
          attemptedSelectors.push({ selector: sel, length: null, skippedReason: "no elements found" });
          continue;
        }
        if (sel.includes("*=") && allMatches.length !== 1) {
          attemptedSelectors.push({ selector: sel, length: null, skippedReason: `${allMatches.length} elements matched (expected 1)` });
          continue;
        }
        const el = allMatches[0];
        const text = (el as HTMLElement).innerText ?? el.textContent ?? "";
        if (text.length < TEXT_MIN) {
          attemptedSelectors.push({ selector: sel, length: text.length, skippedReason: `text too short (< ${TEXT_MIN})` });
          continue;
        }
        if (text.length > TEXT_MAX) {
          attemptedSelectors.push({ selector: sel, length: text.length, skippedReason: `text too long (> ${TEXT_MAX}), likely matched unrelated container` });
          continue;
        }
        attemptedSelectors.push({ selector: sel, length: text.length, skippedReason: null });
        return { text, usedFallback: false, matchedSelector: sel, attemptedSelectors };
      }
      // fallback: full body (may include nav chrome)
      const bodyText = document.body.innerText;
      attemptedSelectors.push({ selector: "body", length: bodyText.length, skippedReason: null });
      return { text: bodyText, usedFallback: true, matchedSelector: null, attemptedSelectors };
    }) as EvaluateResult;

    // Log selector probe results in Node context (stderr) so we can track selector health
    for (const attempt of result.attemptedSelectors) {
      if (attempt.skippedReason) {
        log(`selector "${attempt.selector}" skipped: ${attempt.skippedReason}`);
      }
    }
    if (result.usedFallback) {
      log("WARNING: no targeted selector matched, fell back to body.innerText");
    } else {
      log(`raw_text via selector "${result.matchedSelector}", length=${result.text.length}`);
    }

    const raw_text = result.text;
    log(`raw_text length: ${raw_text.length}`);

    if (raw_text.length < 1000) {
      console.error(
        `[scrape] raw_text too short (${raw_text.length} chars), possible bot block or paywall`,
      );
      process.exit(1);
    }

    // ── Step 7: Extract metadata via stagehand.extract ────────────────────────
    log("Extracting metadata (date + participants)");
    const metadata = await stagehand.extract(
      "Extract the date of this earnings call and the list of all participants " +
      "(speakers, executives, analysts). Include their full name, role/title, and company affiliation.",
      MetadataSchema,
    );

    log(`Extracted date: ${metadata.date}, participants: ${metadata.participants.length}`);

    // ── Step 8: Output JSON to stdout ─────────────────────────────────────────
    const output = {
      url: matchedUrl,
      raw_text,
      date: metadata.date,
      participants: metadata.participants,
      scraped_at: new Date().toISOString(),
    };

    process.stdout.write(JSON.stringify(output) + "\n");
    log("Done — JSON written to stdout");

  } finally {
    try {
      await stagehand.close();
      log("Stagehand closed");
    } catch (e) {
      console.error("[scrape] Error closing stagehand:", e);
    }
  }
}

main().catch((e) => {
  console.error("[scrape] Fatal error:", e instanceof Error ? e.stack : String(e));
  process.exit(1);
});
