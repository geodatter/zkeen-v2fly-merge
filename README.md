# zkeen-v2fly-merge

Builds merged `geosite.dat` and `geoip.dat` artifacts from upstream `v2fly` and `zkeen` releases, then generates Happ routing artifacts that point at the merged release assets.

## What it produces

- `geosite.dat`
- `geoip.dat`
- `happ-routing.json`
- `happ-routing.onadd.txt`
- `happ-routing.add.txt`
- `categories.json`
- `build-info.json`
- `sha256sums.txt`

## Public model

- Raw upstream lists are preserved in the merged dat files.
- Imported `zkeen` geosite lists are exposed as `zkeen-*`.
- Imported `zkeen` geoip lists are exposed as `zkeen-*`.
- Repo-owned curated categories are exposed as `merged-*`.

Downstream consumers can use either raw names or canonical `merged-*` names. The generated Happ profile uses the curated layer.

## Merge model

- All upstream `v2fly` geosite lists are kept as-is.
- All upstream `v2fly` geoip lists are kept as-is.
- All upstream `zkeen.dat` lists are imported under the `zkeen-` prefix.
- All upstream `zkeenip.dat` lists are imported under the `zkeen-` prefix.
- Repo-owned fallback geoip sources under [`config/geoip/`](./config/geoip/) are merged before curated categories and can backfill missing upstream `zkeen` lists.
- Curated `merged-*` categories are assembled from repo-tracked manifests in [`config/categories.json`](./config/categories.json).

## Generated Happ routing

The generator reads [`config/happ-routing-source.json`](./config/happ-routing-source.json) and writes a Happ profile whose `Geoipurl` and `Geositeurl` point to this repository's latest release assets. The routing source config is intentionally small and should prefer `merged-*` categories over raw upstream lists.

The default routing source mirrors the current Xray policy shape:

- direct fallback
- explicit local/bypass IPs
- direct curated bypass category
- proxied curated site category
- proxied curated ip category

## Artifacts and metadata

Each release includes:

- merged binary artifacts: `geosite.dat`, `geoip.dat`
- Happ artifacts: `happ-routing.json`, `happ-routing.onadd.txt`, `happ-routing.add.txt`
- manifests: `categories.json`, `build-info.json`, `sha256sums.txt`
- optional plaintext debug exports under `dist/plain/` for curated and imported `zkeen-*` categories only

## Local build

Requirements:

- `python3`
- `git`
- `go`

Run:

```bash
python3 scripts/build.py --repo your-user/zkeen-v2fly-merge
```

Artifacts will be written to `dist/`.

### Validation

The build validates:

- upstream release artifacts can be fetched and decoded
- required imported `zkeen-*` categories exist
- all curated `merged-*` categories resolve to non-empty inputs
- the generated Happ profile references only categories present in the merged dat files
- the generated Happ JSON matches the golden shape in [`tests/golden/happ-routing.json`](./tests/golden/happ-routing.json)

## GitHub Actions

The workflow in [`.github/workflows/release.yml`](./.github/workflows/release.yml) builds on push, manual dispatch, and a daily schedule, then publishes the generated artifacts as a GitHub release.
