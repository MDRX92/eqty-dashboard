// Browser test for site/guestbook/index.html with a simulated wallet (EIP-6963) and a simulated Base Sepolia RPC.
// The chain model below mirrors the contract rules; the contract itself is tested with Foundry (contracts/test).
//
// Run:  npm i playwright   (or use a global install)   then   node tests/guestbook.browser.mjs
// Uses the Chrome at $CHROME_PATH, or Playwright's own Chromium if not set.
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const SITE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../site");
const LAUNCH = { args: ["--no-sandbox"], ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) };
const REAL_GB = "0x01652d8eff1605c0f446a67d7047dee59723e2b5", REAL_TOK = "0x6e937bb123bfd626a05686f16466c57f2210e7b7";
const GB = "0x" + "9".repeat(40), TOK = "0x" + "7".repeat(40);
const FEE = 100n * 10n ** 18n;
const ALICE = "0x00000000000000000000000000000000000a11ce";

// ---------- chain model ----------
function makeChain() {
  return { bal: {}, allow: {}, msgs: [], receipts: {}, n: 0, txs: [] };
}
const w = (h, i) => h.slice(10 + i * 64, 10 + (i + 1) * 64);
const u = (x) => BigInt(x).toString(16).padStart(64, "0");
const a = (x) => x.toLowerCase().replace(/^0x/, "").padStart(64, "0");
const ad = (word) => "0x" + word.slice(24);
const k = (o, s) => o.toLowerCase() + ":" + s.toLowerCase();
class Revert extends Error { constructor(data) { super("execution reverted"); this.data = data; } }
function decStr(data) {
  const len = Number(BigInt("0x" + w(data, 1)));
  const hex = data.slice(10 + 128, 10 + 128 + len * 2);
  return Buffer.from(hex, "hex").toString("utf8");
}
function encStr(s) {
  const b = Buffer.from(s, "utf8"); const hex = b.toString("hex");
  return u(32 * 3) + u(b.length) + hex.padEnd(Math.ceil(hex.length / 64) * 64 || 0, "0");
}
function exec(C, tx, write) {
  const sel = tx.data.slice(2, 10), from = (tx.from || "").toLowerCase(), to = tx.to.toLowerCase();
  if (to === GB) {
    if (sel === "ddca3f43") return "0x" + u(FEE);
    if (sel === "fc0c546a") return "0x" + a(TOK);
    if (sel === "06661abd") return "0x" + u(C.msgs.length);
    if (sel === "4df9cb73") {
      const m = C.msgs[Number(BigInt("0x" + w(tx.data, 0)))]; if (!m) throw new Revert("0x4e487b71");
      return "0x" + a(m.author) + u(m.ts) + encStr(m.text);
    }
    if (sel === "8ee93cf3") {
      const t = decStr(tx.data), b = Buffer.from(t, "utf8");
      if (!b.length) throw new Revert("0xbb1b6580");
      if (b.length > 560) throw new Revert("0x8fd168ea");
      if (/:\/\/|http|www\./i.test(t)) throw new Revert("0x7e2bced0");
      if ([...b].some(c => c < 0x20 || c === 0x7f)) throw new Revert("0x312a9f56");
      const al = C.allow[k(from, GB)] || 0n;
      if (al < FEE) throw new Revert("0xfb8f41b2");
      if ((C.bal[from] || 0n) < FEE) throw new Revert("0xe450d38c");
      if (write) { C.allow[k(from, GB)] = al - FEE; C.bal[from] -= FEE; C.msgs.push({ author: from, ts: Math.floor(Date.now() / 1000), text: t }); }
      return "0x" + u(C.msgs.length - 1);
    }
  }
  if (to === TOK) {
    if (sel === "70a08231") return "0x" + u(C.bal[ad(w(tx.data, 0))] || 0n);
    if (sel === "dd62ed3e") return "0x" + u(C.allow[k(ad(w(tx.data, 0)), ad(w(tx.data, 1)))] || 0n);
    if (sel === "095ea7b3") { if (write) C.allow[k(from, ad(w(tx.data, 0)))] = BigInt("0x" + w(tx.data, 1)); return "0x" + u(1); }
    if (sel === "de5f72fd") { if (write) C.bal[from] = (C.bal[from] || 0n) + 1000n * 10n ** 18n; return "0x"; }
  }
  throw new Revert("0x");
}
function rpcHandle(C, method, params) {
  if (method === "eth_call") return exec(C, params[0], false);
  if (method === "eth_chainId") return "0x14a34";
  if (method === "eth_getTransactionReceipt") return C.receipts[params[0]] || null;
  throw new Error("unsupported " + method);
}

// ---------- test harness ----------
const results = [];
const check = (name, cond, extra = "") => { results.push([cond ? "✔" : "✘", name, extra]); };

async function scenario(name, opts, fn) {
  const C = makeChain();
  (opts.seed || []).forEach(m => C.msgs.push(m));
  if (opts.balance) C.bal[ALICE] = opts.balance;
  const browser = await chromium.launch(LAUNCH);
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("dialog", d => { errors.push("dialog: " + d.message()); d.dismiss(); });

  await page.route("https://example.test/**", async route => {
    const url = new URL(route.request().url());
    let p = url.pathname.replace(/^\//, "") || "guestbook/index.html";
    if (p.endsWith("/")) p += "index.html";
    let body = fs.readFileSync(`${SITE}/${p}`);
    if (p === "guestbook/index.html") {
      body = body.toString().replaceAll(REAL_GB, GB).replaceAll(REAL_TOK, TOK);
    }
    if (p === "guestbook/hidden.json" && opts.hidden) body = JSON.stringify({ sepolia: opts.hidden });
    await route.fulfill({ body, contentType: p.endsWith(".json") ? "application/json" : "text/html" });
  });
  await page.route("https://sepolia.base.org/**", async route => {
    const req = JSON.parse(route.request().postData());
    const one = r => { try { return { jsonrpc: "2.0", id: r.id, result: rpcHandle(C, r.method, r.params) }; }
                       catch (e) { return { jsonrpc: "2.0", id: r.id, error: { code: 3, message: e.message, data: e.data } }; } };
    const out = Array.isArray(req) ? (opts.noBatch ? { error: "no batch" } : req.map(one)) : one(req);
    await route.fulfill({ body: JSON.stringify(out), contentType: "application/json" });
  });

  await page.exposeFunction("__wallet", (method, params) => {
    C.txs.push({ method, params });
    if (opts.reject && method === opts.reject) return { error: { code: 4001, message: "User rejected the request." } };
    try {
      switch (method) {
        case "eth_requestAccounts": case "eth_accounts": return { result: [ALICE] };
        case "eth_chainId": return { result: "0x14a34" };
        case "wallet_switchEthereumChain": return { result: null };
        case "eth_call": return { result: exec(C, params[0], false) };
        case "eth_getTransactionReceipt": return { result: C.receipts[params[0]] || null };
        case "eth_sendTransaction": {
          const tx = params[0]; let status = "0x1";
          try { exec(C, tx, true); } catch (e) { status = "0x0"; }
          const h = "0x" + (++C.n).toString(16).padStart(64, "0"); C.receipts[h] = { status, transactionHash: h }; return { result: h };
        }
        case "wallet_getCapabilities":
          if (!opts.atomic) return { error: { code: -32601, message: "Method not found" } };
          return { result: { "0x14a34": { atomic: { status: "supported" } } } };
        case "wallet_sendCalls": {
          const calls = params[0].calls; const snap = JSON.stringify(C, (kk, v) => typeof v === "bigint" ? v.toString() + "n" : v);
          try { calls.forEach(c => exec(C, { ...c, from: ALICE }, true)); } catch (e) { return { error: { code: -32000, message: "batch reverted", data: e.data } }; }
          return { result: { id: "batch1" } };
        }
        case "wallet_getCallsStatus": return { result: { status: 200, receipts: [{ status: "0x1" }] } };
      }
      return { error: { code: -32601, message: "unsupported " + method } };
    } catch (e) { return { error: { code: 3, message: e.message, data: e.data } }; }
  });
  await page.addInitScript(() => {
    const provider = {
      async request({ method, params }) {
        const r = await window.__wallet(method, params || []);
        if (r.error) throw Object.assign(new Error(r.error.message), r.error);
        return r.result;
      },
      on() {},
    };
    window.addEventListener("eip6963:requestProvider", () => {
      window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail: Object.freeze({
        info: { uuid: "test-wallet", name: "Test Wallet", icon: "data:image/svg+xml;base64,PHN2Zy8+", rdns: "test" }, provider }) }));
    });
  });
  await page.goto("https://example.test/guestbook/");
  await page.waitForTimeout(700);
  try { await fn(page, C); } catch (e) { check(name + ": exception", false, e.message); }
  check(name + ": no page errors", errors.length === 0, errors.join(" | "));
  await browser.close();
}
const txt = (page, sel) => page.locator(sel).innerText();
async function waitStatus(page) {
  await page.waitForFunction(() => { const s = document.getElementById("status"); return s.style.display !== "none" && (s.classList.contains("ok") || s.classList.contains("err")); }, null, { timeout: 15000 });
  return txt(page, "#status");
}

// 1. empty guestbook, full two-step flow incl. faucet
await scenario("two-step post", {}, async (page, C) => {
  check("empty state", (await txt(page, "#list")).includes("No messages yet"));
  check("fee shown", (await txt(page, "#s-fee")) === "100");
  await page.click("text=Test Wallet");
  await page.waitForTimeout(300);
  check("account shown", (await txt(page, "#acct")).startsWith("0x0000"));
  await page.click("#faucet");
  check("faucet ok", (await waitStatus(page)).includes("1,000 test tokens"));
  check("balance updated", (await txt(page, "#bal")) === "1,000");
  await page.fill("#text", "Hallo EQTY! Café ☕");
  check("counter", (await txt(page, "#counter")).startsWith("18 / 140"));
  await page.click("#post");
  const st = await waitStatus(page);
  check("posted ok", st.includes("Posted!"), st);
  const approve = C.txs.find(t => t.method === "eth_sendTransaction" && t.params[0].data.startsWith("0x095ea7b3"));
  check("approve is exactly the fee", approve && BigInt("0x" + approve.params[0].data.slice(-64)) === FEE);
  check("approve spender is guestbook", approve && approve.params[0].data.slice(10, 74).endsWith(GB.slice(2)));
  check("no value sent", C.txs.filter(t => t.method === "eth_sendTransaction").every(t => !t.params[0].value || t.params[0].value === "0x0"));
  check("no signature requests", !C.txs.some(t => /sign/i.test(t.method)));
  check("message stored utf8", C.msgs[0]?.text === "Hallo EQTY! Café ☕");
  check("message listed", (await txt(page, "#list")).includes("Hallo EQTY! Café ☕"));
  check("burned stat", (await txt(page, "#s-burned")) === "100");
  check("balance after", (await txt(page, "#bal")) === "900");
  // second post: needs a new approve again (allowance used up)
  await page.fill("#text", "Tweede bericht");
  await page.click("#post");
  check("second post ok", (await waitStatus(page)).includes("Posted!"));
  check("2 approvals total", C.txs.filter(t => t.method === "eth_sendTransaction" && t.params[0].data.startsWith("0x095ea7b3")).length === 2);
  check("newest first", (await page.locator(".msg .text").first().innerText()) === "Tweede bericht");
});

// 2. input validation
await scenario("input rules", { balance: 1000n * 10n ** 18n }, async (page) => {
  const cases = [
    ["kijk op scam.xyz", false], ["https://x", false], ["www.test", false], ["mail me@evil.io", false],
    ["a".repeat(141), false], ["a".repeat(140), true], ["e.g. dit is prima, i.e. ok", true], ["prijs 0.5 dollar", true],
    ["zero​width", false], ["rtl ‮ trick", false], ["   ", false], ["🚀".repeat(140), true], ["Ownables.me rocks", false],
  ];
  for (const [t, ok] of cases) {
    await page.fill("#text", t);
    const disabled = await page.locator("#post").isDisabled();
    check(`input ${JSON.stringify(t.slice(0, 24))} -> ${ok ? "allowed" : "blocked"}`, disabled === !ok, await txt(page, "#counter"));
  }
});

// 3. display safety + hidden list + no-batch RPC fallback
await scenario("display safety", {
  noBatch: true,
  hidden: { "2": "scam" },
  seed: [
    { author: ALICE, ts: 1700000000, text: '<img src=x onerror=alert(1)> <b>bold</b>' },
    { author: ALICE, ts: 1700000000, text: "visit scam.xyz now ‮evil" },
    { author: ALICE, ts: 1700000000, text: "free airdrop claim" },
  ],
}, async (page) => {
  const items = await page.locator(".msg .text").allInnerTexts();
  check("3 messages via sequential fallback", items.length === 3, JSON.stringify(items));
  check("hidden message replaced", items[0] === "Message hidden by moderators (scam).");
  check("domain removed on display", items[1] === "visit [link removed] now evil", items[1]);
  check("html shown as text", items[2].includes("<img src=x"), items[2]);
  check("no injected img element", (await page.locator(".msg img").count()) === 0);
  check("count stat", (await txt(page, "#s-count")) === "3");
});

// 4. smart wallet batch (one confirmation)
await scenario("atomic batch", { atomic: true, balance: 500n * 10n ** 18n }, async (page, C) => {
  await page.click("text=Test Wallet");
  await page.waitForTimeout(300);
  await page.fill("#text", "Via smart wallet");
  await page.click("#post");
  check("batch post ok", (await waitStatus(page)).includes("Posted!"));
  check("used wallet_sendCalls", C.txs.some(t => t.method === "wallet_sendCalls"));
  check("no separate eth_sendTransaction", !C.txs.some(t => t.method === "eth_sendTransaction"));
  check("message stored", C.msgs[0]?.text === "Via smart wallet");
});

// 5. user rejects approval
await scenario("user rejects", { reject: "eth_sendTransaction", balance: 500n * 10n ** 18n }, async (page, C) => {
  await page.click("text=Test Wallet");
  await page.waitForTimeout(300);
  await page.fill("#text", "Afgewezen");
  await page.click("#post");
  check("cancel message", (await waitStatus(page)) === "You cancelled in your wallet. Nothing was sent.");
  check("nothing stored", C.msgs.length === 0);
  check("button usable again", !(await page.locator("#post").isDisabled()));
});

// 6. too little balance
await scenario("low balance", { balance: 5n * 10n ** 18n }, async (page, C) => {
  await page.click("text=Test Wallet");
  await page.waitForTimeout(300);
  await page.fill("#text", "Te weinig");
  await page.click("#post");
  const s = await waitStatus(page);
  check("low balance message", s.includes("You need 100 tEQTY") && s.includes("have 5"), s);
  check("no tx sent", !C.txs.some(t => t.method === "eth_sendTransaction"));
});

// 7. not deployed (real config, no addresses)
{
  const browser = await chromium.launch(LAUNCH);
  const page = await browser.newPage(); const errs = []; page.on("pageerror", e => errs.push(e.message));
  const notLive = fs.readFileSync(`${SITE}/guestbook/index.html`, "utf8").replaceAll(REAL_GB, "").replaceAll(REAL_TOK, "");
  await page.route("https://example.test/**", r => r.fulfill({ body: notLive, contentType: "text/html" }));
  await page.goto("https://example.test/guestbook/"); await page.waitForTimeout(600);
  check("not-live message", (await page.locator("#list").innerText()).includes("not live"));
  check("post disabled when not live", await page.locator("#post").isDisabled());
  check("testnet banner", (await page.locator("#testnet").innerText()).includes("not live on Base mainnet"));
  check("not-live: no page errors", errs.length === 0, errs.join("|"));
  await browser.close();
}

for (const r of results) console.log(r[0], r[1], r[0] === "✘" ? "  " + r[2] : "");
const failed = results.filter(r => r[0] === "✘").length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
