# EQTY Guestbook – review pack for the EQTY DAO

**Status: test version on Base Sepolia. Not deployed on Base mainnet.** It goes to mainnet only if the EQTY DAO reviews it and decides to proceed.

Page: <https://mdrx92.github.io/eqty-dashboard/guestbook/> · Community proposal, not an official DAO product.

## 1. What it is
A public guestbook on Base. Posting a message (max 140 characters) costs a fixed amount of EQTY, which is **burned**: total supply goes down and nobody receives it, not the builder, not the contract, not the DAO.

Why: it gives holders something small and fun to do with EQTY today, and it previews Ownables' Anchor model ("pay EQTY to put something on-chain").

## 2. How it works
1. The user connects a wallet (EIP-6963 discovery; any browser wallet).
2. The page checks balance and allowance, then asks for `approve(guestbook, fee)`: **exactly the fee**, never unlimited.
3. The page dry-runs `post(text)` with `eth_call`, then sends it. The contract stores the message, emits `Posted`, and calls `EQTY.burnFrom(user, fee)`.
4. Smart wallets supporting EIP-5792 do steps 2 and 3 in one confirmation.

There are no signature requests and no ETH transfers; nothing is ever sent to an address.

## 3. Contracts
| | Base Sepolia (testnet) | Base mainnet |
|---|---|---|
| EQTYGuestbook | [`0x01652D8Eff1605c0F446a67d7047deE59723E2b5`](https://sepolia.basescan.org/address/0x01652D8Eff1605c0F446a67d7047deE59723E2b5#code) – verified | not deployed |
| Token | TestEQTY [`0x6E937bB123bFd626a05686f16466c57f2210e7b7`](https://sepolia.basescan.org/address/0x6E937bB123bFd626a05686f16466c57f2210e7b7#code) – verified, faucet, no value | EQTY `0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29` (has `burnFrom`) |
| Fee | 100 tEQTY | to be decided by the DAO |

Source: [`src/EQTYGuestbook.sol`](src/EQTYGuestbook.sol) (~90 lines). Compiler 0.8.28, optimizer 200 runs, EVM cancun. Deployed 16-11-2026 with Remix; the on-chain bytecode size matches the CI build (2,576 / 1,834 bytes) and Basescan verification succeeded for both.

## 4. Security design
- **No owner, no admin, no upgrades.** `token` and `fee` are `immutable`. Nobody can change them, pause the contract, or withdraw anything.
- **Holds nothing.** Every function is non-payable (sending ETH reverts) and there is no `receive`. Tokens are burned straight from the poster's wallet.
- **Effects before interaction.** The message is stored, then `burnFrom` runs; if the burn fails (no allowance or balance), the whole post reverts.
- **On-chain content rules.** Empty messages, more than 560 bytes, ASCII control characters (incl. newlines) and links (`http`, `www.`, `://`, case-insensitive) are rejected.
- **Website rules.** Max 140 characters; also blocks domain names (`scam.xyz`) and invisible or bidi-override characters; message text is rendered with `textContent` only (no HTML); domains that slip through are shown as "[link removed]". No external scripts or libraries.
- **Token check.** Before posting, the page reads `token()` from the contract and refuses to continue if it isn't the expected token.
- **Moderation.** On-chain data can't be deleted. The page hides abusive messages via a public list, [`site/guestbook/hidden.json`](../site/guestbook/hidden.json), and shows the reason. Policy: hide scams, abuse, hate, personal data and spam; never criticism.

### What can go wrong
| Risk | Impact | Mitigation |
|---|---|---|
| Bug in the contract | Worst case a user loses the fee (the contract can't take more than the approval and holds no funds) | Small, no admin; 18 tests incl. fuzzing; a short review by a Solidity developer recommended before mainnet |
| Abusive content | Reputational | Link and length rules on-chain; transparent hide list on the page |
| Hosting account compromised (page replaced) | Phishing risk for visitors; the contract is unaffected | 2FA on the GitHub account; option to host under a DAO-controlled account or domain |
| Wallet phishing warning on a new site | Users hesitate | Verified contracts; false-positive report to MetaMask; announcement or link from official EQTY channels |
| Fee becomes too high or low as the price moves | UX | Fee is fixed; a new contract can be deployed with a new fee if needed |

## 5. Testing
- **Contracts:** 18 Foundry tests ([`test/EQTYGuestbook.t.sol`](test/EQTYGuestbook.t.sol)): burn and storage, exact allowance used up, no ETH accepted, empty/too long/links/control characters, unicode, zero-fee mode, immutable config, fuzzed lengths. They run on every change in the [Contracts workflow](../.github/workflows/contracts.yml).
- **Page:** 56 checks in Chrome with a simulated wallet and chain ([`tests/guestbook.browser.mjs`](../tests/guestbook.browser.mjs)): two-step and one-click (batch) flows, approve amount and spender, no value or signatures, rejection, low balance, input rules, HTML/domain/bidi on display, hide list, RPC fallback, "not live" state.
- **Live testnet:** end-to-end with MetaMask on Base Sepolia (faucet → approve 100 tEQTY → post → burned).
- **Not done:** a professional audit.

## 6. Decisions for the DAO
1. Go / no-go.
2. Timing: soft launch now as a community activity, or together with the Ownables launch.
3. Fee per message (fixed once deployed).
4. Moderation: who may add entries to the hide list.
5. Hosting: keep on the community GitHub Pages, or move to a DAO-controlled repository or domain.
6. Whether a Snapshot vote is needed. No DAO funds are required: deployment costs a few cents of gas, paid by the deployer.

## 7. Mainnet steps (only after approval)
1. Optional review of `EQTYGuestbook.sol` by a Solidity developer.
2. Deploy `EQTYGuestbook(0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29, <fee>)` from a dedicated account; never deploy `TestEQTY` on mainnet.
3. Verify on Basescan; check `token()` and `fee()`.
4. Set `NETWORKS.base.guestbook` and `DEFAULT_NET = "base"` in `site/guestbook/index.html`; run the tests.
5. Announce through official EQTY channels; link from the dashboard.
