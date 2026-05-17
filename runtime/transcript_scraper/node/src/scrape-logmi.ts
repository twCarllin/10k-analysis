/**
 * scrape-logmi.ts — Stagehand scraper for logmi Finance earnings call transcripts.
 *
 * Interface:
 *   argv: npx tsx src/scrape-logmi.ts <jpx_code> <company_name_ja> [headless]
 *   stdout: single JSON line: { url, title, date, raw_text, speakers, scraped_at }
 *   stderr: all logs and errors
 *   returncode: 0 = success, 1 = failure
 */
import { Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod";

const log = (...args: unknown[]) => console.error("[scrape-logmi]", ...args);

// ─── CLI args ────────────────────────────────────────────────────────────────
const [, , jpx_code, company_name_ja, headlessArg] = process.argv;

if (!jpx_code || !company_name_ja) {
  console.error(
    "[scrape-logmi] Usage: npx tsx src/scrape-logmi.ts <jpx_code> <company_name_ja> [headless]"
  );
  process.exit(1);
}

const HEADLESS = (headlessArg ?? "true").toLowerCase() !== "false";
const API_KEY = process.env.ANTHROPIC_API_KEY;

if (!API_KEY) {
  console.error("[scrape-logmi] ANTHROPIC_API_KEY env var not set");
  process.exit(1);
}

const MIN_RAW_TEXT = 500;

// ─── Schemas ─────────────────────────────────────────────────────────────────
const TranscriptMetaSchema = z.object({
  title: z.string().describe("Title of the earnings call article"),
  date: z.string().describe("Publication date of the article, e.g. '2025-05-09'"),
  speakers: z
    .array(
      z.object({
        name: z.string().describe("Speaker's name"),
        role: z.string().optional().describe("Speaker's role or title"),
        company: z.string().optional().describe("Speaker's company or affiliation"),
      })
    )
    .describe("All speakers mentioned or identified in the transcript"),
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

    // ── Step 1: Navigate to logmi Finance search ──────────────────────────────
    const query = encodeURIComponent(`${company_name_ja} ${jpx_code}`);
    const searchUrl = `https://finance.logmi.jp/search?q=${query}`;
    log(`Navigating to search: ${searchUrl}`);
    await page.goto(searchUrl);

    // ── Step 2: Find the most recent 決算説明会 article URL via DOM ──────────
    interface AnchorEntry {
      href: string;
      text: string;
    }

    // Extract all article links from the search results page
    const anchors: AnchorEntry[] = await page.evaluate(() => {
      return Array.from(document.querySelectorAll("a[href]"))
        .map((a) => ({
          href: (a as HTMLAnchorElement).href,
          text: (a.textContent ?? "").trim(),
        }))
        .filter(
          (a) =>
            a.href.includes("finance.logmi.jp/") &&
            a.text.length > 0
        );
    }) as AnchorEntry[];

    log(`Found ${anchors.length} candidate anchors`);

    // Check for auth/login wall
    const currentUrl: string = await page.evaluate(() => window.location.href) as string;
    const pageTitle: string = await page.evaluate(() => document.title) as string;
    if (
      pageTitle.toLowerCase().includes("login") ||
      pageTitle.toLowerCase().includes("auth") ||
      currentUrl.includes("/login") ||
      currentUrl.includes("/auth")
    ) {
      console.error("[scrape-logmi] Auth wall detected: " + pageTitle);
      process.exit(1);
    }

    // Filter for 決算説明会 articles — prefer company name or jpx_code match
    const EARNINGS_KEYWORDS = ["決算説明会", "決算発表", "業績説明", "投資家説明会"];
    let matchedUrl: string | null = null;

    for (const anchor of anchors) {
      const hasEarnings = EARNINGS_KEYWORDS.some((kw) => anchor.text.includes(kw));
      const hasCompany =
        anchor.text.includes(company_name_ja) ||
        anchor.text.includes(jpx_code);
      if (hasEarnings && hasCompany) {
        matchedUrl = anchor.href;
        log(`Matched via DOM: "${anchor.text}" → ${matchedUrl}`);
        break;
      }
    }

    if (!matchedUrl) {
      console.error(
        `[scrape-logmi] no 決算説明会 article found for ${jpx_code} ${company_name_ja}`
      );
      process.exit(1);
    } else {
      // ── Step 3: Navigate to the matched article ─────────────────────────────
      log(`Navigating to article: ${matchedUrl}`);
      await page.goto(matchedUrl);
    }

    // Check for auth wall on article page
    const articleUrl: string = await page.evaluate(() => window.location.href) as string;
    const articleHtml: string = await page.evaluate(() => document.body.innerHTML) as string;
    if (
      articleHtml.toLowerCase().includes("login") ||
      articleHtml.toLowerCase().includes("paywall") ||
      articleUrl.includes("/login")
    ) {
      console.error("[scrape-logmi] auth/paywall detected on article page");
      process.exit(1);
    }

    // ── Step 4: Extract raw_text via selector chain ───────────────────────────
    interface TextResult {
      text: string;
      matchedSelector: string | null;
    }

    const textResult: TextResult = await page.evaluate(() => {
      // Priority selectors for logmi article body
      const SELECTORS = [
        "article.article-body",
        'div[class*="article-body"]',
        "article",
        "main",
      ];

      for (const sel of SELECTORS) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const text = (el as HTMLElement).innerText ?? el.textContent ?? "";
        if (text.length >= MIN_RAW_TEXT) {
          return { text, matchedSelector: sel };
        }
      }

      // Final fallback: body.innerText
      return {
        text: document.body.innerText,
        matchedSelector: null,
      };
    }) as TextResult;

    log(
      `raw_text via selector "${textResult.matchedSelector ?? "body fallback"}", length=${textResult.text.length}`
    );

    if (textResult.text.length < MIN_RAW_TEXT) {
      console.error(
        `[scrape-logmi] raw_text too short (${textResult.text.length} chars), possible scrape failure`
      );
      process.exit(1);
    }

    // ── Step 5: Extract metadata via stagehand.extract ────────────────────────
    log("Extracting metadata (title, date, speakers)");
    const metadata = await stagehand.extract(
      `Extract the title and publication date of this earnings call article, and list all speakers/participants identified in the transcript. Include each speaker's name, role/title, and company affiliation.`,
      TranscriptMetaSchema
    );

    log(
      `Extracted title: ${metadata.title}, date: ${metadata.date}, speakers: ${metadata.speakers.length}`
    );

    // ── Step 6: Output JSON to stdout ─────────────────────────────────────────
    const output = {
      url: articleUrl,
      title: metadata.title,
      date: metadata.date,
      raw_text: textResult.text,
      speakers: metadata.speakers,
      scraped_at: new Date().toISOString(),
    };

    process.stdout.write(JSON.stringify(output) + "\n");
    log("Done — JSON written to stdout");
  } finally {
    try {
      await stagehand.close();
      log("Stagehand closed");
    } catch (e) {
      console.error("[scrape-logmi] Error closing stagehand:", e);
    }
  }
}

main().catch((e) => {
  console.error(
    "[scrape-logmi] Fatal error:",
    e instanceof Error ? e.stack : String(e)
  );
  process.exit(1);
});
