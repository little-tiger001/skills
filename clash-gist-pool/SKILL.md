---
name: clash-gist-pool
description: Maintain and test a gist-based free Clash/Mihomo proxy pool. Use when syncing public gist all.yaml subscriptions, deduping/filtering free nodes, delay-testing them with the local Mihomo/Clash Verge core and this machine's network, or generating a proxies-only provider plus report.
---

# clash-gist-pool

Sync proxies-only `all.yaml` files from the curated public Gists in `sources.json`, dedupe/filter them, validate with the local Mihomo core, delay-test through this machine's network, and write a provider file plus a report. Never edit the active Clash config.

## Preconditions

- Node >= 20 (tested on v24).
- A Mihomo/Clash Verge core. On this PC it is `C:\Program Files\Clash Verge\verge-mihomo.exe`; override with `--core` or `MIHOMO_BIN`.
- Optional GitHub token: `GITHUB_TOKEN`, or the existing `~/.agents/skills/github-account/.env`. Public gists work unauthenticated but rate-limit quickly.
- For clean delay tests, **turn off TUN**. Keep system proxy on if GitHub is only reachable through it; the test core uses raw sockets and is not affected by the system proxy. `sync` can run with TUN on; `test` uses the cached merge and needs TUN off.
- **Scope:** validated on this Windows PC (Clash Verge, local campus network). A Linux server test failed for all nodes because its network path differs; do not use those results. No cron/Task Scheduler entry is created.
- Free nodes are untrusted. Do not use this pool for banking, primary email, GitHub, or other sensitive accounts.

## Quick start (this Windows PC)

```powershell
cd "C:\Users\zhang\科大云盘\self-improve\折腾\代理配置"
$skill = "$env:USERPROFILE\.agents\skills\clash-gist-pool\scripts\clash-gist-pool.mjs"
node $skill status
# turn TUN off before the test stage
node $skill pipeline --out .\gist-pool --exclude-insecure --ca-tls
# inspect gist-pool\report.md and usable.yaml, then:
node $skill publish --out .\gist-pool
```

This machine is the reference environment. Do not port a failed server result back; the local CA-TLS subscription is the validated one. No scheduled task or cron is configured.

Output defaults to `./gist-pool/`:

- `cache/<tag>/all.yaml` — last fetched source.
- `merged.yaml` — all accepted proxies, proxies-only.
- `usable.yaml` — proxies whose delay passed, sorted by delay.
- `results.json` / `usable-meta.json` — test data, no credentials beyond names/endpoints.
- `report.md` — source counts, cadence, fastest nodes, failures, warnings.
- `discovered.json` / `discovered.md` — candidates from `discover`, with node/insecure/CA-TLS counts.
- `test/` — generated test config and core log.
- `.gitignore` — ignores everything in the output dir; do not commit node credentials.

## Commands

```text
sync                 fetch sources, dedupe/filter, write merged.yaml + report
test                 load merged.yaml (sync if missing), delay-test, write usable.yaml
build                rebuild usable.yaml/report from the last results.json (no retest)
run                  sync then test in one process
discover             search Gist for new candidates, audit them, write discovered.md
pipeline             discover (optional) -> sync -> filter -> test -> publish (optional)
publish              upload usable.yaml as nodes.yaml to a secret Gist
status               show cached source state
```

Common options: `--out DIR`, `--source TAG`, `--force`, `--limit N`, `--type http,vless`, `--exclude-insecure`, `--ca-tls`, `--timeout MS`, `--concurrency N`, `--attempts N`, `--url URL`, `--max-delay MS`, `--core PATH`, `--allow-tun`, `--mixed-port`, `--api-port`.

Discovery/pipeline options: `--add`, `--discover`, `--publish`, `--query "all.yaml+proxies,..."`, `--max-pages N`, `--max-candidates N`, `--max-age-days N`, `--min-nodes N`, `--min-ca-tls N`, `--no-test`, `--gist ID` (or `GIST_ID` env). `pipeline` uses the same filter flags as `sync`/`build`; use `--exclude-insecure --ca-tls` for the current 11-node subscription. `--add` only appends discovered sources with `enabled: false`; review `discovered.md` before enabling.

`publish --create` creates a new **secret** Gist with `nodes.yaml` (the current `usable.yaml`) and writes `gist-pool/publish.json` with its id/raw URL. Later `publish` calls PATCH the same Gist using that state. The nodes file is proxies-only; use its raw URL in a `proxy-providers` entry, or point your subscription config at it. The Gist is unlisted, not access-controlled: anyone with the raw URL can read it.

`publish` refuses to upload when `usable.yaml` has no proxies, when it still contains `skip-cert-verify: true` nodes, or (for a CA-TLS subscription) when it contains non-CA-TLS/Reality/plain nodes. Run `build --exclude-insecure --ca-tls` first; the override flags for the latter two are `--allow-insecure` and `--allow-non-ca-tls`. This prevents a failed test run from replacing a working subscription with an empty or weakened one.

Minimal provider wiring for a subscription config:

```yaml
proxy-providers:
  pool:
    type: http
    url: <publish.json raw_nodes>
    interval: 3600
    path: ./providers/gist-pool.yaml
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 600
```

Point a proxy group at it with `use: [pool]`. Updating `nodes.yaml` via `publish` updates the subscription without changing the config file.

## Local Windows workflow (this machine)

Run manually from `C:\Users\zhang\科大云盘\self-improve\折腾\代理配置`. No scheduled task or cron is configured.

```powershell
$skill = "$env:USERPROFILE\.agents\skills\clash-gist-pool\scripts\clash-gist-pool.mjs"
node $skill status
node $skill discover --out .\gist-pool --add     # optional: candidates added disabled
# review gist-pool\discovered.md, enable promising sources in sources.json
node $skill pipeline --out .\gist-pool --exclude-insecure --ca-tls
# inspect gist-pool\report.md and gist-pool\usable.yaml
node $skill publish --out .\gist-pool
```

`pipeline` syncs, applies the CA-TLS filter, tests the selected nodes, and writes `usable.yaml`; `--publish` can be appended to do the Gist update in one step. The Gist `clash.yaml` (provider, bootstrap, rules) is not rewritten; only `nodes.yaml` is updated.

Do not enable TUN while testing. The old Linux wrapper/cron workflow was removed; server results are not comparable.

- `--exclude-insecure` drops `skip-cert-verify: true` nodes. Use it with `sync` to rebuild the pool, or with `build` to filter the existing results without re-testing (e.g. `build --exclude-insecure`). Many sources lose 30–98% of their nodes; in the 2026-10-18 pool this cut 319 usable nodes to 39.
- `--ca-tls` keeps only CA-verified TLS nodes: explicit `tls: true` excluding Reality, plus TLS-inherent protocols (`trojan`, `hysteria`, `hysteria2`, `tuic`, `anytls`). It excludes plain HTTP/SOCKS5, non-TLS VMess, Mieru, and Reality. With the current results this cuts the strict 39 to 11. Use `build --exclude-insecure --ca-tls` to rebuild from results; keep a CA-TLS fallback node in the subscription so the provider can bootstrap.
- `--limit` applies to the test/build selection, not to sync.
- `--allow-tun` runs a knowingly contaminated smoke test. Real filtering should be done with TUN off.
- Tests use the selected proxies through the local core API `/proxies/<name>/delay`; they do not rely on the active Clash profile.

## Current baseline (2026-10-18)

- Sync result: 8 sources, 1659 raw proxy entries → 1327 accepted after cross-source dedupe; 332 duplicates; 650 `skip-cert-verify: true`.
- All 1327 merged proxies pass `verge-mihomo -t` with Mihomo v1.19.32.
- Clean TUN-off test: 1327 tested, 581 reachable, 319 at ≤1500 ms; 280 of the 319 usable nodes are `skip-cert-verify: true`.
- Strict rebuild (`build --exclude-insecure`): 39 usable nodes with no `skip-cert-verify: true`.
- CA-TLS rebuild (`build --exclude-insecure --ca-tls`): 11 nodes — explicit `tls: true` excluding Reality (10) plus one Hysteria2 TLS node. Reality, plain HTTP/SOCKS5, non-TLS VMess, and Mieru are excluded.
- Published a secret Gist (its ID is stored only in local `publish.json`, not in this repository): `nodes.yaml` (11 CA-TLS proxies) + `clash.yaml` (subscription with provider). The original AnyTLS/VMess nodes were removed; `PROXY` uses one CA-TLS bootstrap node, then `AUTO`/`DIRECT`, plus the provider nodes. The 39- and 319-node versions remain in Gist history.
- `publish` now refuses insecure nodes and, when `publish.json.ca_tls` is true, refuses non-CA-TLS/Reality/plain nodes unless the corresponding override flag is passed.
- The old 10-node TUN smoke test was discarded; all current numbers are from the TUN-off run.
- 2026-10-18 server test: all 11 CA-TLS nodes were unreachable because the server's network path differs. Those results are discarded; this skill is now scoped to the Windows PC. No scheduler/cron was created.

## Finding new sources (first step)

GitHub Gist has no official search API. Use the web search page, then audit each hit with the Gist API; do not add a source just because a README claims it is active.

Automated first pass:

```bash
node ".../clash-gist-pool.mjs" discover --out "$HOME/gist-pool"
# or add passing candidates disabled:
node ".../clash-gist-pool.mjs" discover --out "$HOME/gist-pool" --add
```

It uses `sources.json.discovery.queries`, scrapes the Gist search HTML, audits `all.yaml`, and writes `discovered.md`. `--add` appends candidates with `enabled: false`; review and enable manually before a pipeline run. A scheduled agent can run this weekly, inspect the report, then run `pipeline`.

Manual audit steps:

1. Search the Gist web UI: `https://gist.github.com/search?q=all.yaml+proxies`, then try `all.yaml+hysteria2`, `all.yaml+vmess`, `base64.txt+mihomo.yaml`, and `subs-check`. Paginate with `&p=2`, `&p=3`.
2. Extract candidate links matching `gist.github.com/<owner>/<20+ hex id>`. The HTML page lists them directly; no login is needed for public gists.
3. For each id, call `GET https://api.github.com/gists/<id>` and require:
   - `files["all.yaml"]` exists and is non-empty;
   - `updated_at` is within the last 7 days;
   - recent `history[].committed_at` shows the cadence (dedupe bursts by minute);
   - content is proxies-only (`proxies:` with no `proxy-groups`/`rules`), or deliberately handle a full config;
   - the proxy type mix is supported by the local core.
4. Fetch `raw_url` (or API content if not truncated), extract the top-level `proxies` list, and count entries plus `skip-cert-verify: true`.
5. Add the source to `sources.json` with a short `tag`, `priority`, `expectedNodes`, `cadence`, and `lastAudit`. Then run `sync --force --source TAG` and `test --source TAG --limit 20` with TUN off before enabling it in a full run.
6. Re-audit periodically. `shuaidaoya` is a useful cautionary example: its README advertised active updates, but the gist was months stale when checked.

The Gist search HTML is noisy; many hits are one-off config templates or dead pools. Prefer gists that keep `all.yaml`/`base64.txt`/`mihomo.yaml` together and update on a regular `updated_at` cadence.

## Curated sources (2026-10-18 audit)

| Tag | Gist | Recent cadence | Notes |
|---|---|---|---|
| rockdale | [rockdale1899-alt](https://gist.github.com/rockdale1899-alt/822c95e7a9648a0283e7841270c75f3b/raw/all.yaml) | ~2h12m | ~900–1000 nodes, largest active pool |
| tdison | [Tdison](https://gist.github.com/Tdison/6b745663fd038e3c63e0880ecc652bcf/raw/all.yaml) | ~36m | ~51 nodes, fastest refresher |
| december | [December000](https://gist.github.com/December000/fd23d2530ffc29264297a5e687a79ecd/raw/all.yaml) | ~1h | ~40 nodes, stable hourly |
| scaleflower | [scaleflower](https://gist.github.com/scaleflower/20a2175ba0525a3660c40b837caeb97b/raw/all.yaml) | daily, with 4–10 day gaps | ~244 nodes, mostly HTTP, almost all insecure |
| lzj05 | [lzj05](https://gist.github.com/lzj05/c7a3615e1fd9ccdd4a9a5caf853d6d54/raw/all.yaml) | irregular, hours–days | ~337 nodes, mostly HTTP |
| haidejiang | [HAIDEJIANG](https://gist.github.com/HAIDEJIANG/b68d405379a0ffd9b686c6c497b484c1/raw/all.yaml) | irregular, ~1–6h | ~32 nodes; already in this user's profiles |
| mathdeep | [Mathdeep258](https://gist.github.com/Mathdeep258/007cc1adcae763f9388259f71fea0b40/raw/all.yaml) | irregular, multiple/day | ~15 nodes; already in this user's profiles |
| fdzz | [fdzzxzxx](https://gist.github.com/fdzzxzxx/c6a98bad66f358daf6d9b0128c4aed74/raw/all.yaml) | 1–2/day with bursts | ~24 nodes; already in this user's profiles |

All audited `all.yaml` files are proxies-only (no rules/groups). Re-audit before adding a source: confirm `all.yaml` exists, last update is recent, content is proxies-only, and `updated_at` is advancing. If a source fails three runs or is stale for >7 days, set `enabled: false` and record why in `sources.json`.

## Filtering and test semantics

The build stage:

1. Extracts the top-level `proxies:` list without a YAML dependency; inline `- {…}` entries are counted but skipped.
2. Filters missing name/type/server/port, unsupported types, and optionally insecure nodes.
3. Prefixes names with `<tag>/`, sanitizes `/` and `\\`, and resolves duplicate names.
4. Dedupes by type + server + port + auth/network/SNI fields, in source priority order.

The test stage:

1. Detects a Windows `Mihomo`/`Meta Tunnel` adapter and refuses unless `--allow-tun`.
2. Finds free local ports, writes a temporary test config with all selected proxies and a `TEST` select group.
3. Validates with `core -t`, starts the core, and polls `/version`.
4. Calls `/proxies/<encoded-name>/delay` with concurrency/attempts/timeout, then writes results.
5. Builds `usable.yaml` from successful delays <= `--max-delay` (default 1500 ms) and sorts by delay.

The default health URL is `https://www.gstatic.com/generate_204`. Change it with `--url` if a source's nodes systematically fail on it. Delay is a reachability/latency signal, not a speed or streaming test.

## Maintenance loop

- After each run, read `report.md`: per-source raw/accepted/duplicate/insecure counts and failures.
- Update `sources.json` with new cadence/notes and disable dead sources; do not silently drop a source.
- If a source becomes active again, re-enable it and re-audit.
- Add new sources only after checking `all.yaml`, recent `updated_at`, and proxies-only structure.
- Keep the output directory out of git; it contains public node credentials. The script writes a local `.gitignore`.
- When the skill's parser or filters change, run `sync` and `test --limit 10` to verify before a full run.
- If `core -t` rejects the merged config, inspect `test/validate.log`; isolate the bad proxy/source and update the filter or disable it. The next iteration should add a targeted prune if this becomes common.

## Remote-provider bootstrap pitfall

A subscription config that uses `proxy-providers` with a GitHub raw URL plus DNS `#PROXY` can deadlock at startup: the provider is needed to resolve/fetch itself, but DNS wants a proxy. Keep at least one explicit known-good proxy in the `PROXY` group, and list it before any empty provider-backed group. In the current CA-TLS subscription, the first item is a CA-TLS bootstrap node from the same pool (`bootstrap/haidejiang-...`), then `AUTO`, `DIRECT`, then the 11 provider nodes; the original AnyTLS/VMess nodes are gone. The provider `nodes.yaml` loads through the bootstrap and is cached at `./providers/gist-pool.yaml`. Without this fallback, the provider fetch failed with `dns resolve failed`/`EOF`.

## Limitations

- Gist web search has no official API; `discover` scrapes HTML and can break or rate-limit. New sources are added disabled and need review.
- Recent revision history is not a guarantee of future cadence; use `state.json`/report.
- Raw Gist CDN can lag. Sync compares `updated_at` and adds a cache-buster when a Gist changed.
- Some nodes use `skip-cert-verify: true`; filtering them is a security/quantity tradeoff. In the tested pool 319 were usable and 280 of those were insecure; the strict 39 then reduced to 11 CA-TLS. Flipping `skip-cert-verify` to `false` requires re-testing; many will fail the TLS handshake.
- TUN-on tests are contaminated and marked as such; do not use those delays for final selection. The automatic TUN check targets this Windows PC; keep it Windows-scoped unless the Linux path is revalidated. No scheduler is configured.
- `pipeline` tests only the filtered set (11 CA-TLS in the current configuration), not the entire merged 1327. That is intentional for the subscription, but it does not measure the full pool.
- The published `clash.yaml` is not regenerated by `pipeline`; it keeps the CA-TLS bootstrap proxy from setup time. If that bootstrap dies and the provider cache is empty, update the bootstrap block in the Gist or use a local provider file. `pipeline` only updates `nodes.yaml`.
