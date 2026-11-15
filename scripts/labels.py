"""Wallet labels: manual list + daily automatic detection -> site/data/labels.json.

Priority (highest first):
  1. labels.csv (manual, reviewed; 'verified' or 'estimated')
  2. on-chain contract detection (verified): Safe multisig, Coinbase Smart Wallet, other contract
  3. behaviour heuristics (estimated): very frequent trading -> "Automated trader"

Estimated labels are shown on the page with a "≈" mark: they are an educated guess based on
on-chain behaviour, not a confirmed identity.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from cdp_client import run_query

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
MAX_ADDRESSES = 150
BATCH = 25
CACHE = ROOT / "data" / "wallet_types.json"   # address -> detected label or null (no contract events)

# event signature (prefix) -> label
CONTRACT_RULES = [
    ("SafeSetup(", ("Safe multisig", "multisig")),
    ("ExecutionSuccess(", ("Safe multisig", "multisig")),
    ("AddOwner(uint256,bytes)", ("Coinbase Smart Wallet", "wallet")),
    ("Swap(", ("DEX contract", "dex")),
]


def manual_labels() -> dict[str, dict]:
    out = {}
    with open(ROOT / "labels.csv", newline="") as f:
        for r in csv.DictReader(f):
            out[r["address"].lower()] = {
                "label": r["label"], "type": r.get("type", ""),
                "confidence": r.get("confidence") or "verified",
                "note": r.get("note", ""), "source": "manual",
            }
    return out


def _load(name: str) -> dict:
    p = OUT / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def candidate_addresses() -> list[str]:
    """Addresses shown on the dashboard: top holders, leaderboard traders, whale senders/recipients."""
    seen = []

    def add(a):
        a = str(a or "").lower()
        if a.startswith("0x") and len(a) == 42 and a not in seen:
            seen.append(a)

    for r in _load("top_holders").get("rows", []):
        add(r.get("address"))
    market = _load("market")
    for board in (market.get("leaderboard") or {}).values():
        for r in board.get("rows", []):
            add(r.get("trader"))
    whales = _load("whales")
    for r in whales.get("pivot", []):
        add(r.get("sender"))
    for r in whales.get("latest", []):
        add(r.get("sender"))
        add(r.get("recipient"))
    return seen[:MAX_ADDRESSES]


def _query_types(addresses: list[str]) -> dict[str, set]:
    """Event signatures per address; splits the batch if CDP's scan limit is hit."""
    sql = (ROOT / "queries" / "11_wallet_types.sql").read_text()
    sql = sql.replace("{addresses}", ", ".join(f"'{a}'" for a in addresses))
    try:
        rows = run_query(sql)
    except RuntimeError as exc:
        if "scanned more data" in str(exc) and len(addresses) > 1:
            half = len(addresses) // 2
            a, b = _query_types(addresses[:half]), _query_types(addresses[half:])
            return {**a, **b}
        if "scanned more data" in str(exc):
            print(f"[labels] skipped {addresses[0]} (too many events to scan)", file=sys.stderr)
            return {}
        raise
    sigs = defaultdict(set)
    for r in rows:
        sigs[str(r["address"]).lower()].add(str(r["event_signature"]))
    return sigs


def detect_contracts(addresses: list[str], skip: set[str]) -> dict[str, dict]:
    """Contract type per address. Results are cached: a wallet's type does not change,
    so after the first run only new addresses are queried (usually 0-1 queries/day)."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [a for a in addresses if a not in cache and a not in skip]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        sigs = _query_types(batch)
        for addr in batch:
            s = sigs.get(addr)
            if not s:
                cache[addr] = None            # no contract events: regular wallet
                continue
            label = next((lab for prefix, lab in CONTRACT_RULES if any(x.startswith(prefix) for x in s)),
                         ("Smart contract", "contract"))
            cache[addr] = {"label": label[0], "type": label[1], "confidence": "verified",
                           "note": "Detected from the contract's on-chain events", "source": "auto"}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    print(f"[labels] checked {len(todo)} new addresses ({-(-len(todo) // BATCH)} queries)")
    return {a: v for a, v in cache.items() if v}


def detect_traders() -> dict[str, dict]:
    """Very frequent traders are most likely automated (market making / bots)."""
    market = _load("market")
    out = {}
    boards = market.get("leaderboard") or {}
    for key, min_trades in (("30d", 50), ("90d", 150)):
        for r in (boards.get(key) or {}).get("rows", []):
            if r.get("trades", 0) >= min_trades:
                out[str(r["trader"]).lower()] = {
                    "label": "Automated trader", "type": "trader", "confidence": "estimated",
                    "note": f"{r['trades']} trades in {key} – very frequent trading, likely automated",
                    "source": "auto"}
    return out


def update(now_iso: str) -> None:
    labels = {}
    manual = manual_labels()
    labels.update(detect_traders())
    try:
        labels.update(detect_contracts(candidate_addresses(), skip=set(manual)))
    except Exception as exc:  # detection is optional; manual labels still work
        print(f"[FAIL] labels (contract detection): {exc}", file=sys.stderr)
    labels.update(manual)  # manual always wins
    (OUT / "labels.json").write_text(json.dumps({"updated_at": now_iso, "labels": labels}, indent=1))
    counts = defaultdict(int)
    for v in labels.values():
        counts[v["confidence"]] += 1
    print(f"[labels] {len(labels)} labels ({dict(counts)})")
