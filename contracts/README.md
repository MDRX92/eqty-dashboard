# EQTY Guestbook – contracts

`src/EQTYGuestbook.sol` – burn a fixed amount of EQTY to post a short message (≤ 560 bytes; the website limits it to 140 characters). No owner, no admin functions, not upgradeable, never holds tokens or ETH. Rejects links (`http`, `www.`, `://`) and control characters.

`src/TestEQTY.sol` – worthless test token with a public `faucet()` (1,000 tEQTY per call). **Base Sepolia only.**

Tests run automatically on GitHub (workflow *Contracts*, Foundry). Locally:

```
cd contracts
git clone --depth 1 --branch v1.9.7 https://github.com/foundry-rs/forge-std lib/forge-std
forge test -vv
```

## Deploying with Remix (no install needed)

1. Open <https://remix.ethereum.org>, create the files and paste the source from `src/`.
2. *Solidity compiler*: version **0.8.28**, *Advanced*: EVM **cancun**, optimizer **on, 200 runs** (same as `foundry.toml`). Compile.
3. *Deploy & run*: environment *Injected Provider* (your wallet), on the right network.
4. **Testnet (Base Sepolia, chain 84532)**
   - Deploy `TestEQTY` → copy its address.
   - Deploy `EQTYGuestbook` with `token_` = TestEQTY address, `fee_` = `100000000000000000000` (100 tokens, 18 decimals).
5. **Mainnet (Base, chain 8453)** – only after testing and agreeing on it with the DAO
   - Deploy only `EQTYGuestbook` with `token_` = `0xc71f37d9bf4c5d1e7fe4bccb97e6f30b11b37d29` and the agreed fee.
   - Never deploy `TestEQTY` on mainnet.
6. Verify the source on Basescan (Remix *Contract verification* plugin or Sourcify), so anyone can read it.
7. Put the addresses in `site/guestbook/index.html` (`NETWORKS.sepolia` / `NETWORKS.base`) and switch `DEFAULT_NET` to `"base"` for the mainnet launch.

The fee and token can never be changed after deployment. To change them, deploy a new guestbook.

## Moderation

Messages can't be deleted on-chain. `site/guestbook/hidden.json` lists message ids the website hides, with a reason (scam, abuse, hate, personal data, spam). Never hide criticism.
