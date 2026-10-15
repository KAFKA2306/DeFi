# AGENTS.md

## Repository responsibility

This repository owns finalized Ethereum DeFi primary evidence for Aave V3 and Uniswap V3. Do not reintroduce the former stock/skewness/Tauri product surface.

## Source hierarchy

1. Ethereum mainnet finalized block/log evidence
2. Official Aave and Uniswap deployment/address repositories
3. Derived daily views regenerated from stored raw evidence

Aggregator TVL/volume, third-party indexed event APIs, guessed backfills, and silent fallbacks are not canonical inputs.

## Autonomous execution

1. Re-read current `main`, README, open Issues/PRs, raw evidence/manifests, workflows, tests and public outputs before choosing work.
2. Continue one existing canonical workline for the same outcome before creating another collector, evidence store, RPC fallback, branch or Issue.
3. Prefer new verified finalized-chain evidence, provenance/rebuild correctness, protocol identity/semantic fixes, public read-back, then simplification that removes recurring manual work.
4. Keep deterministic PR verification independent of unstable live RPC where possible. Live acquisition still requires explicit runtime evidence when live collection is the requested outcome.
5. Stop at the fixed point. Do not add protocols, metrics, wrappers or dashboards solely to increase activity or coverage counts.
6. If the external RPC condition has not changed, do not repeatedly churn a blocked live-collection workline.

Other finance repositories should reference this repository's versioned DeFi artifacts instead of maintaining duplicate Aave/Uniswap facts or collectors. Do not execute swaps, approvals, deposits, borrows, repayments, liquidations, wallet operations, trades, or account actions. An unavailable or rate-limited endpoint is a blocker, not permission to fabricate or silently change authority.

## Implementation constraints

- Python standard library only unless a dependency is strictly necessary for evidence correctness.
- Unknown contract/event/schema states fail closed.
- Preserve chain ID, block number, block hash, transaction/log provenance where available.
- Keep protocol asset amounts in native units unless a primary price source is explicitly added; never relabel token deltas as USD volume.
- Contract migrations/upgrades append history instead of mutating old evidence.
- Delete obsolete duplicate paths rather than maintain compatibility with the removed Tauri/React/Rust prototype.

## Branch lifecycle

- Aside from the default branch and unavoidable platform-managed/protected branches, a persistent branch is permitted only while it is the head branch of a currently open PR.
- Creating a work branch creates an obligation to open or reuse its canonical PR immediately; do not use branches as backlog, continuation state, backup, archive, or evidence storage.
- After a PR is merged or closed, delete its head branch after verifying PR/main state. A branch with no open PR is an orphan and must be deleted.
- Before and after work, compare repository branches with open PR heads. Do not report cleanup/fixed point while an orphan task branch remains.
- If the available tool cannot delete a branch, record that as a tooling blocker and do not claim cleanup complete. Never create another orphan branch as a workaround.

## Merge and release are separate

### PR merge conditions

A PR may merge when the deterministic repository-local contract is correct on the exact reviewed revision: raw/provenance semantics hold, focused tests pass, offline rebuild succeeds where affected, and no unresolved review or correctness blocker remains.

Live Ethereum RPC success, a fresh finalized block, production publication, or public endpoint availability is **not** a merge condition unless the PR specifically changes the live/release mechanism and that mechanism must be validated before merge.

### Product/data release conditions

Release is a separate post-merge decision. Treat DeFi evidence as released only after the merged `main` revision is read back and the release requirements in scope are actually executed: live finalized-chain collection when required, provenance audit, published/generated artifacts, public surface if any, and rollback/rebuild path where applicable.

A merged PR does not prove live collection. A live RPC blocker may block release without invalidating a correctly merged deterministic change. Report merge and release independently.

## Required checks

```bash
python -m py_compile defi.py test_defi.py
python -m unittest -v test_defi
```

These checks are merge evidence. The `DeFi evidence` workflow or equivalent live collection/provenance run is release evidence when live production acquisition is in scope. A check or runtime layer that did not run is not PASS.

## Completion report

Report verified evidence/capability Before -> After, canonical raw/hash evidence, Issue/PR/commit/check evidence, then report `merged` and `released` separately with direct evidence for each. Include branch cleanup state, duplicate/manual work removed and the remaining verified blocker.

## Outcome-first task interpretation (Altitude / Depth / Range / Speed)

- **Altitude:** Interpret a task as a verifiable user outcome, not only the named intermediate step. Infer the smallest justified acceptance criteria from the request and current repository state; do not silently expand scope or override explicit instructions.
- **Depth:** Use primary/current evidence and real domain tools and methods. Verify the actual postcondition independently of agent self-report, preferably on the exact changed revision or target runtime.
- **Range:** Combine code, data, tests, runtime/UI, and domain expertise when that materially improves the outcome, while respecting canonical owners and avoiding duplicate systems.
- **Speed:** Complete authorized read-only and reversible work through implementation, focused checks, and read-back without unnecessary approval loops. Bound retries and stop at the proven outcome.
- These principles never bypass repository-specific security, privacy, permission, publication, spending, destructive-action, or release boundaries. State verified results and any remaining `UNVERIFIED` layers.
