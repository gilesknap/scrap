// Record the demo video (#549): stage.html at 1920x1080 with Playwright's recordVideo, the
// demo sim (sim/demo/build.sh) driven by real taps and typing on the left, the transcript
// replayed in the terminal on the right.
//
//   node sim/demo/record.mjs [--out DIR] [--transcript FILE] [--page FILE] [--fast] [--pace N]
//
// --out         where the video and frames go (default _claude/demo-video); the demo sim
//               is read from OUT/site
// --transcript  {steps:[{prompt, events:[...]}]}; steps 0-2 are beats a, b, c, then d-f; events
//               with internal: true are not shown (default sim/demo/transcript/transcript.json,
//               the real capture: capture/)
// --page        the page step c writes: {title, slug, body, tags, kind?, due?, priority?}
//               (default sim/demo/transcript/written-page.json); --summary and --summary-day
//               likewise for the /sc-summarise pages
// --pace        every wait, tap and the phone's typing times this (default 1.0)
// --fast        shorter waits, for checking the script (the video is then too quick)
// Writes OUT/demo.webm and OUT/frames/NN-name.png (a screenshot at each beat).
import { mkdirSync, readFileSync, writeFileSync, renameSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./serve.mjs";

const DEMO = fileURLToPath(new URL(".", import.meta.url));
const REPO = join(DEMO, "../..");
const require = createRequire(join(REPO, "web/package.json"));
const { chromium } = require("@playwright/test");

const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const OUT = opt("--out", join(REPO, "_claude/demo-video"));
// The real capture's files (capture/build_transcript.py writes them)
const pick = (flag, name) => opt(flag, join(DEMO, "transcript", `${name}.json`));
const transcript = JSON.parse(readFileSync(pick("--transcript", "transcript"), "utf8"));
const written = JSON.parse(readFileSync(pick("--page", "written-page"), "utf8"));
const summary = JSON.parse(readFileSync(pick("--summary", "summary-page"), "utf8"));
const summaryDay = JSON.parse(readFileSync(pick("--summary-day", "summary-day-page"), "utf8"));
// ListAgents' result in short: the sessions it then messages. Results the capture left
// empty: a SendMessage is sent
for (const s of transcript.steps) {
  const evs = s.events.filter((e) => !e.internal);
  const to = evs.filter((e) => e.name === "SendMessage").map((e) => /to: '([^']+)'/.exec(e.args_summary || "")?.[1]).filter(Boolean);
  for (const e of evs) {
    if (e.type === "tool_result" && e.name === "ListAgents" && to.length) e.summary = `${to.length} other sessions: ${to.join(", ")}`;
    if (e.type === "tool_result" && !e.summary) {
      if (e.name === "ListAgents") e.summary = "(no other sessions)";
      else if (e.name === "SendMessage") e.summary = "sent";
      else e.summary = "(No content)";
    }
  }
}
const FAST = args.includes("--fast");
const PHOTO_SHA = "5bbacd0b5eac519aff0037a7d1de06d808e33a26f99567f18f0dc8e26e896f9d"; // the fence
const PHOTO = join(REPO, `sim/fixtures/blobs/${PHOTO_SHA}-2048.jpg`);

const FRAMES = join(OUT, "frames");
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });
const VIDDIR = join(OUT, ".video");
rmSync(VIDDIR, { recursive: true, force: true });

const { url, close } = await serve({ site: join(OUT, "site"), demo: DEMO });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: { dir: VIDDIR, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();
const v0 = Date.now(); // the video's start: beats.json gives each shot's time in it
const beats = {};
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const PACE = Number(opt("--pace", "1.0")); // every wait times this (taps and the phone's typing too)
const wait = (ms) => page.waitForTimeout(FAST ? Math.min(ms, 300) : ms * PACE);

await page.goto(`${url}/demo/stage.html?sim=${encodeURIComponent(`${url}/art/x1/index.html#/`)}`);
await page.evaluate(() => stage.card('<h1><b>scrap</b> — your notes,<br>shared with Claude Code</h1>'));
const frameBy = (part) => page.frames().find((f) => f.url().includes(part));
await page.waitForFunction(() => document.getElementById("sim").contentWindow?.__sim?.write);
await page.waitForFunction(() => document.getElementById("term").contentWindow?.term);
const sim = frameBy("/art/x1/");
const term = frameBy("/terminal.html");
const phone = page.frameLocator("#sim");
await sim.waitForSelector("nav a");
await page.waitForTimeout(800);

let shotN = 0;
const t0 = Date.now();
// A screenshot of the beat; after a key result, a still moment (about 2 s) to take it in
const hold = (ms) => page.waitForTimeout(FAST ? 100 : ms);
const KEY = new Set(["photo-saved", "photo-queued", "photo-read", "browser", "whiteboard-drawing", "whiteboard-reading", "topic", "term-b",
  "written-appears", "written-page", "summary-appears", "day-appears", "day-sessions"]);
const shot = async (name) => {
  console.log(`${((Date.now() - t0) / 1000).toFixed(1).padStart(6)} s  ${name}`);
  beats[name] = (Date.now() - v0) / 1000;
  await page.screenshot({ path: join(FRAMES, `${String(++shotN).padStart(2, "0")}-${name}.png`) });
  if (KEY.has(name)) await hold(3000);
};

// Where an element in the phone is on the stage (the phone is scaled), its centre
async function onStage(loc) {
  await loc.first().waitFor({ state: "visible", timeout: 8000 }).catch(async (e) => {
    await page.screenshot({ path: join(FRAMES, "error.png") });
    throw e;
  });
  await loc.first().evaluate((e) => e.scrollIntoView({ block: "center", behavior: "instant" }));
  const r = await loc.first().evaluate((e) => {
    const b = e.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
  });
  return page.evaluate(({ x, y }) => {
    const f = document.getElementById("sim");
    const b = f.getBoundingClientRect();
    const s = b.width / f.offsetWidth;
    return { x: b.left + (x + f.clientLeft) * s, y: b.top + (y + f.clientTop) * s };
  }, r);
}
// A tap: the dot moves there, pulses, and the real click lands where it is
async function tap(loc) {
  const p = await onStage(loc);
  await page.evaluate(({ x, y }) => stage.dot(x, y), p);
  await wait(600);
  await page.evaluate(() => stage.tap());
  await page.mouse.click(p.x, p.y);
  await wait(450);
  await page.evaluate(() => stage.hideDot());
}
// A tap on the stage itself (the camera overlay): the dot, its pulse, then what the tap does
async function tapStage(sel, fn, dwell = 600) {
  const b = await page.locator(sel).boundingBox();
  await page.evaluate(({ x, y }) => stage.dot(x, y), { x: b.x + b.width / 2, y: b.y + b.height / 2 });
  await wait(dwell);
  await page.evaluate(() => stage.tap());
  await page.evaluate(fn);
  await wait(350);
  await page.evaluate(() => stage.hideDot());
}
// A nav tab; a page hides the nav, so Back (the header's) first, until it shows
async function nav(name) {
  const link = phone.locator("nav a", { hasText: name });
  for (let i = 0; i < 4 && !(await link.first().isVisible()); i++) await tap(phone.locator("#back"));
  await tap(link);
  await page.waitForTimeout(FAST ? 900 : 700); // its screen (a lazy chunk) settles
}
const type = async (text) => page.keyboard.type(text, { delay: FAST ? 5 : 80 * PACE });
const dotOff = () => page.evaluate(() => stage.hideDot());
// Scroll the phone's view smoothly by dy CSS px, over about ms
async function scroll(dy, ms = 1800) {
  const steps = Math.max(1, Math.round((FAST ? 300 : ms * PACE) / 50));
  for (let i = 0; i < steps; i++) {
    await sim.evaluate((d) => {
      const all = [document.scrollingElement, ...document.querySelectorAll("main, #view, .page, section")];
      const el = all.find((e) => e && e.scrollHeight > e.clientHeight + 4 && getComputedStyle(e).overflowY !== "visible") || document.scrollingElement;
      el.scrollBy(0, d);
    }, dy / steps);
    await page.waitForTimeout(50);
  }
}
// A caption, held at least 2 s before the beat goes on
const caption = async (n, title, sub) => {
  await page.evaluate(([a, b, c]) => stage.caption(a, b, c), [n, title, sub]);
  await page.waitForTimeout(FAST ? 100 : 2000);
};
// The terminal's pace: TIMING for a step unless it gives its own; MONTAGE for step d
const TIMING = { cps: 20, think: 450, call: 500, result: 550, words: 25, slow: 40, after: 400, hold: 20, holdMax: 3500 };
const MONTAGE = { cps: 30, think: 300, call: 170, result: 190, words: 25, slow: 40, after: 70, hold: 15, holdMax: 2500, replyHold: 1600 };
const QUICK = { cps: 200, think: 100, call: 100, result: 100, words: 200, after: 50, hold: 0, holdMax: 0 };
// The directory a step ran in, for the terminal's title: its cwd, else ~/demo (a-c), ~/demo/tidy (d, e)
const home = (d) => d.replace(/^\/(?:root|home\/[^/]+)(?=\/|$)/, "~");
const cwdOf = (i) => transcript.steps[i].cwd ?? (i < 3 ? "~/demo" : "~/demo/tidy");
// Play step i: its prompt typed, then each event shown; then(e, j, events) after each one
async function play(i, timing = {}, then) {
  const s = transcript.steps[i];
  const events = s.events.filter((e) => !e.internal);
  const cwd = cwdOf(i);
  await page.evaluate((d) => stage.cwd(d), home(cwd));
  await term.evaluate(([t, root]) => {
    Object.assign(term.timing, t);
    term.root = root;
  }, [FAST ? QUICK : { ...TIMING, ...timing }, cwd.startsWith("/") ? cwd : null]);
  await term.evaluate((p) => term.type(p), s.prompt);
  await term.evaluate(() => term.event({ type: "think" }));
  for (const [j, e] of events.entries()) {
    await term.evaluate((ev) => term.event(ev), e);
    if (then) await then(e, j, events);
  }
}
// The result of a step's scrap write (the page now exists)
const isWriteResult = (evs, j) => evs[j].type === "tool_result" && j > 0 && evs[j - 1].type === "tool_call" && /__write$|^write$/.test(evs[j - 1].name);
// A page Claude wrote, stored in the sim; Capture's Latest list redraws with it on top
const inject = (w) => sim.evaluate((w) => {
  __sim.write(w);
  document.dispatchEvent(new Event("queuechange"));
}, w);

// ---- title card
await wait(2800);
await page.evaluate(() => (stage.focus("phone"), stage.card(null)));
await wait(700);

// ---- 1. capture
await caption("1", "Capture first", "A note or a photo, saved the moment you tap Save");
await wait(1200);
await shot("capture-home");
await tap(phone.getByRole("button", { name: "Note", exact: true }));
await tap(phone.locator("textarea"));
await type("Ask Imogen about the spare PSU before Friday's shutdown");
await wait(500);
await shot("capture-note");
await tap(phone.getByRole("button", { name: "Save", exact: true }));
await wait(1500);
await shot("capture-saved");
// A photo, by the app's Camera button: our own viewfinder over the phone stands in for the
// phone's camera, and its photo goes to the app's camera input
try {
  await caption("1", "Snap it", "Saved instantly: Claude reads it in the background");
  const chooser = page.waitForEvent("filechooser", { timeout: 5000 });
  await tap(phone.getByRole("button", { name: "Camera", exact: true }));
  const pick = await chooser;
  await page.evaluate((src) => stage.camera.open(src), `${url}/art/x1/blobs/${PHOTO_SHA}`);
  // Live view at least 3 s, the dot resting on the shutter, then the flash and the frozen
  // frame, then the confirm, each held long enough to see
  await hold(1800);
  await shot("camera-view");
  await hold(1500);
  await tapStage("#cam .shutter", () => stage.camera.shoot(), 900);
  await page.waitForTimeout(FAST ? 50 : 150);
  await shot("camera-flash");
  await hold(1500);
  await page.evaluate(() => stage.camera.confirm());
  await shot("camera-confirm");
  await hold(1500);
  await tapStage("#cam .use", () => stage.camera.close(), 900);
  await pick.setFiles({ name: "IMG_2063.jpg", mimeType: "image/jpeg", buffer: readFileSync(PHOTO) });
  await wait(1200);
  await tap(phone.locator("textarea"));
  await page.keyboard.press("Control+Home");
  await type("Fence post for the quote\n");
  await wait(400);
  await tap(phone.getByRole("button", { name: "Save", exact: true }));
  const savedAt = Date.now();
  await page.waitForTimeout(FAST ? 100 : 600);
  await shot("photo-saved"); // "Saved", on Capture, with the photo on top of Latest
  await tap(phone.getByText("Fence post for the quote").first());
  await wait(1200);
  await shot("photo-queued");
  // sim.js marks a photo read 6 s after it arrives, with a line about the sim; the page polls
  // every 10 s. So: wait out the 6 s, give it a real reading, and nudge the page to refresh
  await page.waitForTimeout(Math.max(0, savedAt + 6300 - Date.now()));
  await sim.evaluate(() => {
    const p = __sim.pages.find((q) => q.title === "Fence post for the quote");
    const b = p.captures[0].blobs[0];
    b.ingest = { ...b.ingest, state: "done", image_kind: "photo", text: null,
      description: "A wooden garden fence with one panel split and leaning out, between two intact posts, on a lawn under a pale blue sky." };
    dispatchEvent(new CustomEvent("scrap:added", { detail: { id: p.id } }));
  });
  await wait(1200);
  try {
    await tap(phone.locator("main").getByText("Claude's reading").first());
  } catch {}
  await wait(1500);
  await shot("photo-read");
} catch (e) {
  console.warn(`photo capture skipped: ${e.message.split("\n")[0]}`);
}

// ---- 2. Claude's additions, with step a in the terminal alongside (it finds the same board)
await caption("2", "Claude reads what you keep", "A whiteboard photo: its reading, a drawing, tags, related pages");
await page.evaluate(() => stage.focus(null));
const stepA = (async () => {
  await page.waitForTimeout(FAST ? 100 : 1500);
  await play(0);
})();
await nav("Search");
await tap(phone.locator("input[type=search]"));
await type("whiteboard");
await page.waitForTimeout(Math.max(900, FAST ? 0 : 1200 * PACE)); // the search settles
await tap(phone.locator("main").getByText("Architecture whiteboard").first());
await wait(1000);
// The owner's photo, then Claude's drawing of it, then what Claude read in it
await tap(phone.locator("main").getByText("Photo", { exact: true }).first());
await wait(1600);
await shot("whiteboard-photo");
await tap(phone.locator("main").getByText("Drawing", { exact: true }).first());
await wait(1600);
await shot("whiteboard-drawing");
await tap(phone.locator("main").getByText("Claude's reading").first());
await scroll(260, 1200);
await wait(1800);
await shot("whiteboard-reading");
await scroll(900, 2200);
await wait(1800);
await shot("whiteboard-related");
await stepA; // the terminal's answer is in before the topic page
await caption("2", "Claude reads what you keep", "Topic pages: Claude gathers what belongs together");
await page.evaluate(() => stage.focus("phone"));
await nav("Topics");
await wait(800);
await tap(phone.locator("main").getByText("scrap's design").first());
await wait(1500);
await shot("topic");
await scroll(500, 2200);
await wait(1200);

// ---- 3. browse, with step b in the terminal alongside (it asks for this week's home todos)
await caption("3", "Find it again", "On the phone, or ask Claude Code");
await page.evaluate(() => stage.focus(null));
const stepB = play(1, { hold: 25, holdMax: 4000 });
await nav("Todos");
await wait(1600);
await shot("todos");
await page.emulateMedia({ colorScheme: "dark" });
await page.evaluate(() => stage.caption("3", "Find it again", "Light or dark, as your phone is"));
await wait(2500);
await shot("todos-dark");
await page.emulateMedia({ colorScheme: "light" });
await page.evaluate(() => stage.caption("3", "Find it again", "On the phone, or ask Claude Code"));
await nav("Search");
await tap(phone.locator("input[type=search]"));
await page.keyboard.press("Control+a");
await type("fence");
await wait(1800);
await shot("search");
await stepB;
await shot("term-b");

// ---- a link in Claude Code's answer opens the page in the browser
{
  const link = await term.evaluate(() => {
    const us = [...document.querySelectorAll(".say u")];
    const u = us.find((x) => /receipt/i.test(x.textContent)) || us[0];
    if (!u) return null;
    u.id = "demo-link";
    const r = u.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: u.textContent };
  });
  // Its address: the link's in the transcript, by its text
  const said = transcript.steps[1].events.map((e) => e.text || "").join("\n");
  const href = link && [...said.matchAll(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g)].find((m) => m[1] === link.text)?.[2];
  if (href) {
    const slug = new URL(href).pathname.split("/").pop();
    await page.evaluate((src) => stage.browser.load(src), `${url}/art/x1/index.html#/p/${slug}`);
    await page.evaluate(() => stage.focus("term"));
    await caption("3", "Links open in your browser", "Click one in Claude Code's answer");
    const at = await page.evaluate(({ x, y }) => {
      const r = document.getElementById("term").getBoundingClientRect();
      return { x: r.left + x, y: r.top + y };
    }, link);
    await page.evaluate(({ x, y }) => stage.dot(x, y), at);
    await hold(500);
    await term.evaluate(() => document.getElementById("demo-link").classList.add("hover"));
    await hold(1000);
    await page.evaluate(() => stage.tap());
    await hold(350);
    await page.evaluate(() => stage.hideDot());
    await page.evaluate(([h, t]) => stage.browser.open(h, t, "Links open the page in your browser",
      document.getElementById("termwrap").getBoundingClientRect()), [href, `${link.text} · scrap`]);
    await hold(1500);
    await shot("browser");
    // Claude's reading of the photo: its fold opened, then scrolled up into view
    const web = await (await page.locator("#web").elementHandle()).contentFrame();
    const dy = await web.evaluate(() => {
      const f = [...document.querySelectorAll("summary")].find((s) => /Claude's reading/.test(s.textContent));
      if (!f) return 600;
      f.click();
      // and the text it read, in its own fold inside
      setTimeout(() => [...document.querySelectorAll("summary")].find((s) => /Text read/.test(s.textContent))?.click(), 50);
      return f.getBoundingClientRect().top - 300;
    });
    await hold(300);
    for (let i = 0; i < 40; i++) {
      await web.evaluate((d) => document.scrollingElement.scrollBy(0, d), dy / 40);
      await page.waitForTimeout(45);
    }
    await hold(1500);
    await shot("browser-reading");
    await page.evaluate(() => stage.browser.close());
    await hold(1000);
    await term.evaluate(() => document.getElementById("demo-link").classList.remove("hover"));
  } else console.warn("no link to open in step b's answer");
}

// ---- 4. Claude Code writes a page to scrap
await page.evaluate(() => stage.focus(null)); // beat 3 left the terminal in focus
await nav("Capture");
await caption("4", "Claude Code writes to it too", "Ask it to write something down…");
await play(2, {}, async (e, i, evs) => {
  if (isWriteResult(evs, i)) {
    await inject(written);
    await caption("4", "Claude Code writes to it too", "…and it's on your phone");
    await wait(1000);
    await shot("written-appears");
  }
});
await wait(600);
await tap(phone.locator("main").getByText(written.title).first());
await wait(1800);
await shot("written-page");
await scroll(400, 2200);
await wait(1500);

// ---- 5. another session: a PR, a question, then /sc-summarise and /sc-summarise day
await caption("5", "Claude Code works through a PR", "Branch, edit, test, commit: in another project");
await page.evaluate(() => stage.focus("term"));
await term.evaluate(() => term.reset());
await play(3, { ...MONTAGE, words: 50, holdMax: 1500 });
await shot("pr-done");
await caption("5", "Claude Code works through a PR", "…and asks scrap along the way");
await play(4, { ...MONTAGE, words: 50, hold: 10, holdMax: 1800 });
await page.evaluate(() => stage.focus(null));
await nav("Capture");
await caption("5", "Then it writes things up", "/sc-summarise: this topic · /sc-summarise day: today, across all your sessions and GitHub");
// Each scrap write in these steps lands on the phone: the first is /sc-summarise's, the last the day's
let writes = 0;
const lastStep = transcript.steps.length - 1;
let dayMode = false;
for (let i = 5; i <= lastStep; i++) {
  const day = /^\/sc-summarise day/.test(transcript.steps[i].prompt);
  if (day) {
    dayMode = true;
    await page.evaluate(() => stage.focus("term"));
  }
  // The day step's many calls go by as a montage; its replies from the other sessions, and
  // every answer, at reading speed
  await play(i, day ? { ...MONTAGE, words: 25, hold: 15, holdMax: 3000 } : { hold: 15, holdMax: 2500 }, async (e, j, evs) => {
    if (!isWriteResult(evs, j)) return;
    const w = dayMode ? summaryDay : summary;
    writes++;
    if (dayMode) await page.evaluate(() => stage.focus(null));
    await inject(w);
    await wait(900);
    await shot(dayMode ? "day-appears" : "summary-appears");
  });
}
await wait(1000);
await shot("summaries-latest");
await tap(phone.locator("main").getByText(summaryDay.title).first());
await wait(1500);
// Down to its Sessions section
const toSessions = await sim.evaluate(() => {
  const h = [...document.querySelectorAll("main h2, main h3")].find((x) => /sessions/i.test(x.textContent));
  return h ? h.getBoundingClientRect().top - 120 : 300;
});
await scroll(toSessions, 1800);
await wait(2500);
await shot("day-sessions");

// ---- end card
await page.evaluate(() =>
  stage.card('<h1><b>scrap</b></h1><p>github.com/gilesknap/scrap</p><p>try it: one <code>podman run</code></p>'),
);
await wait(900);
await shot("end");
await wait(3500);

const video = page.video();
await context.close();
await browser.close();
close();
renameSync(await video.path(), join(OUT, "demo.webm"));
writeFileSync(join(OUT, "beats.json"), JSON.stringify(beats, null, 1));
rmSync(VIDDIR, { recursive: true, force: true });
if (errors.length) console.warn(`page errors:\n${errors.join("\n")}`);
console.log(join(OUT, "demo.webm"));
