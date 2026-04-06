#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
DIST = ROOT / "dist"
DOWNLOADS = WORK / "downloads"
CONFIG_DIR = ROOT / "config"
ROUTING_CONFIG = CONFIG_DIR / "happ-routing-source.json"
CATEGORY_CONFIG = CONFIG_DIR / "categories.json"
GOLDEN_HAPP = ROOT / "tests" / "golden" / "happ-routing.json"

DIST_PLAIN = DIST / "plain"
DIST_PLAIN_GEOSITE = DIST_PLAIN / "geosite"
DIST_PLAIN_GEOIP = DIST_PLAIN / "geoip"

V2FLY_DLC_REPO = "https://github.com/v2fly/domain-list-community.git"
V2FLY_GEOIP_REPO = "https://github.com/v2fly/geoip.git"
GITHUB_API_RELEASE = "https://api.github.com/repos/{repo}/releases/latest"

UPSTREAMS = {
    "v2fly_geosite": {
        "repo": "v2fly/domain-list-community",
        "asset": "dlc.dat",
        "clone_url": V2FLY_DLC_REPO,
    },
    "v2fly_geoip": {
        "repo": "v2fly/geoip",
        "asset": "geoip.dat",
        "clone_url": V2FLY_GEOIP_REPO,
    },
    "zkeen_geosite": {
        "repo": "jameszeroX/zkeen-domains",
        "asset": "zkeen.dat",
    },
    "zkeen_geoip": {
        "repo": "jameszeroX/zkeen-ip",
        "asset": "zkeenip.dat",
    },
}


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def capture(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "zkeen-v2fly-merge",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def fetch_bytes(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "zkeen-v2fly-merge"})
    with urllib.request.urlopen(request) as response, dest.open("wb") as fh:
        shutil.copyfileobj(response, fh)


def shallow_clone(url: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    run("git", "clone", "--depth=1", url, str(dest))


def parse_datdump_all_yaml(path: Path) -> dict[str, list[str]]:
    lists: dict[str, list[str]] = {}
    current: str | None = None
    in_rules = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("- name:"):
            current = stripped.split(":", 1)[1].strip().lower()
            lists[current] = []
            in_rules = False
            continue
        if stripped == "rules:":
            in_rules = True
            continue
        if in_rules and stripped.startswith("- "):
            if current is None:
                raise RuntimeError("encountered a rule before any list name")
            value = stripped[2:].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            lists[current].append(value)
    return lists


def read_nonempty_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_text_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def normalize_rules(rules: list[str]) -> list[str]:
    return sorted(set(rules))


def preview_names(names: set[str], limit: int = 12) -> list[str]:
    ordered = sorted(names)
    if len(ordered) <= limit:
        return ordered
    return ordered[:limit] + ["..."]


def resolve_release_metadata() -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    for name, spec in UPSTREAMS.items():
        release = fetch_json(GITHUB_API_RELEASE.format(repo=spec["repo"]))
        assets = {asset["name"]: asset for asset in release["assets"]}
        asset = assets[spec["asset"]]
        metadata[name] = {
            "repo": spec["repo"],
            "tag": release["tag_name"],
            "published_at": release.get("published_at"),
            "release_url": release["html_url"],
            "asset_name": spec["asset"],
            "asset_url": asset["browser_download_url"],
        }
    return metadata


def make_upstream_state(upstream_meta: dict[str, dict]) -> dict[str, str]:
    return {name: meta["tag"] for name, meta in sorted(upstream_meta.items())}


def fetch_upstreams(upstream_meta: dict[str, dict]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, meta in upstream_meta.items():
        dest = DOWNLOADS / meta["asset_name"]
        fetch_bytes(meta["asset_url"], dest)
        paths[name] = dest
    return paths


def clone_build_tools() -> dict[str, Path]:
    dlc_dir = WORK / "domain-list-community"
    geoip_dir = WORK / "geoip"
    shallow_clone(V2FLY_DLC_REPO, dlc_dir)
    shallow_clone(V2FLY_GEOIP_REPO, geoip_dir)
    return {"dlc": dlc_dir, "geoip": geoip_dir}


def build_geosite_sources(
    dlc_dir: Path,
    upstream_paths: dict[str, Path],
    category_config: dict,
) -> tuple[Path, dict[str, list[str]], dict]:
    geosite_data = WORK / "geosite-data"
    zkeen_dump = WORK / "zkeen-geosite-dump"
    clean_dir(zkeen_dump)
    if geosite_data.exists():
        shutil.rmtree(geosite_data)
    shutil.copytree(dlc_dir / "data", geosite_data)

    run(
        "go",
        "run",
        "./cmd/datdump",
        "--inputdata",
        str(upstream_paths["zkeen_geosite"]),
        "--outputdir",
        str(zkeen_dump),
        "--exportlists",
        "_all_",
        cwd=dlc_dir,
    )
    dumped = parse_datdump_all_yaml(zkeen_dump / "zkeen.dat_plain.yml")

    imports = category_config["geosite"]["zkeen_imports"]
    missing = [name for name in imports if name not in dumped or not dumped[name]]
    if missing:
        raise RuntimeError(f"missing required zkeen geosite imports: {', '.join(missing)}")

    for name, rules in dumped.items():
        write_text_lines(geosite_data / f"zkeen-{name}", normalize_rules(rules))

    curated_resolved: dict[str, dict] = {}
    curated = category_config["geosite"]["curated"]
    for name, spec in curated.items():
        sources = spec["sources"]
        for source in sources:
            if not (geosite_data / source).exists():
                raise RuntimeError(f"geosite source {source!r} required by {name!r} does not exist")
        lines = [f"include:{source}" for source in sources]
        write_text_lines(geosite_data / name, lines)
        curated_resolved[name] = {
            "type": "geosite",
            "description": spec["description"],
            "sources": sources,
        }

    return geosite_data, dumped, curated_resolved


def build_geosite_dat(dlc_dir: Path, geosite_data: Path) -> None:
    run(
        "go",
        "run",
        "./",
        "--datapath",
        str(geosite_data),
        "--outputname",
        "geosite.dat",
        "--outputdir",
        str(DIST),
        cwd=dlc_dir,
    )


def export_geosite_plain(dlc_dir: Path, names: list[str]) -> None:
    clean_dir(DIST_PLAIN_GEOSITE)
    if not names:
        return
    run(
        "go",
        "run",
        "./cmd/datdump",
        "--inputdata",
        str(DIST / "geosite.dat"),
        "--outputdir",
        str(DIST_PLAIN_GEOSITE),
        "--exportlists",
        ",".join(names),
        cwd=dlc_dir,
    )


def build_geoip_sources(
    geoip_dir: Path,
    upstream_paths: dict[str, Path],
    category_config: dict,
) -> tuple[Path, dict[str, list[str]], dict]:
    v2fly_text_dir = WORK / "v2fly-geoip-text"
    zkeen_text_dir = WORK / "zkeen-geoip-text"
    merged_geoip_text_dir = WORK / "merged-geoip-text"
    v2fly_text_config = WORK / "v2fly-geoip-text-config.json"
    zkeen_text_config = WORK / "zkeen-geoip-text-config.json"

    clean_dir(v2fly_text_dir)
    clean_dir(zkeen_text_dir)
    clean_dir(merged_geoip_text_dir)

    v2fly_text_config.write_text(
        json.dumps(
            {
                "input": [
                    {
                        "type": "v2rayGeoIPDat",
                        "action": "add",
                        "args": {"uri": str(upstream_paths["v2fly_geoip"])},
                    }
                ],
                "output": [
                    {
                        "type": "text",
                        "action": "output",
                        "args": {"outputDir": str(v2fly_text_dir)},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    zkeen_text_config.write_text(
        json.dumps(
            {
                "input": [
                    {
                        "type": "v2rayGeoIPDat",
                        "action": "add",
                        "args": {"uri": str(upstream_paths["zkeen_geoip"])},
                    }
                ],
                "output": [
                    {
                        "type": "text",
                        "action": "output",
                        "args": {"outputDir": str(zkeen_text_dir)},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run("go", "run", ".", "-c", str(v2fly_text_config), cwd=geoip_dir)
    run("go", "run", ".", "-c", str(zkeen_text_config), cwd=geoip_dir)

    raw_geoip_lists: dict[str, list[str]] = {}

    for src in sorted(v2fly_text_dir.iterdir()):
        if not src.is_file():
            continue
        lines = normalize_rules(read_nonempty_lines(src))
        raw_geoip_lists[src.stem] = lines
        write_text_lines(merged_geoip_text_dir / src.name, lines)

    imports = category_config["geoip"]["zkeen_imports"]
    for name in imports:
        src = zkeen_text_dir / f"{name}.txt"
        if not src.exists():
            raise RuntimeError(f"missing required zkeen geoip import: {name}")
        lines = normalize_rules(read_nonempty_lines(src))
        prefixed_name = f"zkeen-{name}"
        raw_geoip_lists[prefixed_name] = lines
        write_text_lines(merged_geoip_text_dir / f"{prefixed_name}.txt", lines)

    available_geoip_sources = {
        path.stem
        for path in merged_geoip_text_dir.iterdir()
        if path.is_file()
    }

    curated_resolved: dict[str, dict] = {}
    for name, spec in category_config["geoip"]["curated"].items():
        combined: list[str] = []
        for source in spec["sources"]:
            source_path = merged_geoip_text_dir / f"{source}.txt"
            if not source_path.exists():
                raise RuntimeError(
                    f"geoip source {source!r} required by curated category {name!r} does not exist; "
                    f"available sources include {preview_names(available_geoip_sources)}"
                )
            combined.extend(read_nonempty_lines(source_path))
        write_text_lines(merged_geoip_text_dir / f"{name}.txt", normalize_rules(combined))
        curated_resolved[name] = {
            "type": "geoip",
            "description": spec["description"],
            "sources": spec["sources"],
        }

    return merged_geoip_text_dir, raw_geoip_lists, curated_resolved


def build_geoip_dat(geoip_dir: Path, merged_geoip_text_dir: Path) -> None:
    merged_config = WORK / "merged-geoip-config.json"
    merged_config.write_text(
        json.dumps(
            {
                "input": [
                    {
                        "type": "text",
                        "action": "add",
                        "args": {"inputDir": str(merged_geoip_text_dir)},
                    }
                ],
                "output": [
                    {
                        "type": "v2rayGeoIPDat",
                        "action": "output",
                        "args": {
                            "outputDir": str(DIST),
                            "outputName": "geoip.dat",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run("go", "run", ".", "-c", str(merged_config), cwd=geoip_dir)


def export_geoip_plain(merged_geoip_text_dir: Path, names: list[str]) -> None:
    clean_dir(DIST_PLAIN_GEOIP)
    for name in names:
        src = merged_geoip_text_dir / f"{name}.txt"
        if src.exists():
            shutil.copyfile(src, DIST_PLAIN_GEOIP / src.name)


def parse_routing_reference(value: str) -> tuple[str | None, str | None]:
    if ":" not in value:
        return None, None
    prefix, remainder = value.split(":", 1)
    return prefix, remainder


def generate_happ(repo: str) -> dict:
    source = json.loads(ROUTING_CONFIG.read_text(encoding="utf-8"))
    geosite_url = f"https://github.com/{repo}/releases/latest/download/geosite.dat"
    geoip_url = f"https://github.com/{repo}/releases/latest/download/geoip.dat"
    profile = {
        "Name": source["name"],
        "GlobalProxy": source["globalProxy"],
        "RemoteDNSType": source["remoteDnsType"],
        "RemoteDNSDomain": source["remoteDnsDomain"],
        "RemoteDNSIP": source["remoteDnsIp"],
        "DomesticDNSType": source["domesticDnsType"],
        "DomesticDNSDomain": source["domesticDnsDomain"],
        "DomesticDNSIP": source["domesticDnsIp"],
        "Geoipurl": geoip_url,
        "Geositeurl": geosite_url,
        "DnsHosts": source["dnsHosts"],
        "DirectSites": source["directSites"],
        "DirectIp": source["directIp"],
        "ProxySites": source["proxySites"],
        "ProxyIp": source["proxyIp"],
        "BlockSites": source["blockSites"],
        "BlockIp": source["blockIp"],
        "DomainStrategy": source["domainStrategy"],
        "FakeDNS": source["fakeDns"],
        "UseChunkFiles": source["useChunkFiles"],
    }
    json_text = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    (DIST / "happ-routing.json").write_text(json_text, encoding="utf-8")
    payload = base64.b64encode(json_text.encode("utf-8")).decode("ascii")
    (DIST / "happ-routing.onadd.txt").write_text(
        f"happ://routing/onadd/{payload}\n", encoding="utf-8"
    )
    (DIST / "happ-routing.add.txt").write_text(
        f"happ://routing/add/{payload}\n", encoding="utf-8"
    )
    return profile


def normalize_happ_for_golden(profile: dict) -> dict:
    cloned = json.loads(json.dumps(profile))
    cloned["Geoipurl"] = "__GEOIP_URL__"
    cloned["Geositeurl"] = "__GEOSITE_URL__"
    return cloned


def assert_happ_matches_golden(profile: dict) -> None:
    expected = json.loads(GOLDEN_HAPP.read_text(encoding="utf-8"))
    actual = normalize_happ_for_golden(profile)
    if actual != expected:
        raise RuntimeError("generated Happ profile does not match tests/golden/happ-routing.json")


def validate_routing_refs(profile: dict, geosite_names: set[str], geoip_names: set[str]) -> None:
    for key in ("DirectSites", "ProxySites", "BlockSites"):
        for entry in profile[key]:
            kind, value = parse_routing_reference(entry)
            if kind == "geosite" and value not in geosite_names:
                raise RuntimeError(f"{key} references missing geosite category {value!r}")
    for key in ("ProxyIp", "BlockIp"):
        for entry in profile[key]:
            kind, value = parse_routing_reference(entry)
            if kind == "geoip" and value not in geoip_names:
                raise RuntimeError(f"{key} references missing geoip category {value!r}")


def write_categories_manifest(
    category_config: dict,
    raw_geosite: dict[str, list[str]],
    raw_geoip: dict[str, list[str]],
    curated_geosite: dict[str, dict],
    curated_geoip: dict[str, dict],
) -> dict:
    payload = {
        "raw": {
            "geosite": {
                "zkeen_imported": [
                    {
                        "name": f"zkeen-{name}",
                        "rule_count": len(raw_geosite[f"zkeen-{name}"]),
                    }
                    for name in sorted(category_config["geosite"]["zkeen_imports"])
                ],
            },
            "geoip": {
                "zkeen_imported": [
                    {
                        "name": f"zkeen-{name}",
                        "cidr_count": len(raw_geoip[f"zkeen-{name}"]),
                    }
                    for name in sorted(category_config["geoip"]["zkeen_imports"])
                ],
            },
        },
        "curated": {
            "geosite": [],
            "geoip": [],
        },
    }
    for name, spec in sorted(curated_geosite.items()):
        payload["curated"]["geosite"].append(
            {
                "name": name,
                "description": spec["description"],
                "sources": spec["sources"],
            }
        )
    for name, spec in sorted(curated_geoip.items()):
        payload["curated"]["geoip"].append(
            {
                "name": name,
                "description": spec["description"],
                "sources": spec["sources"],
            }
        )
    (DIST / "categories.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def write_checksums() -> dict[str, str]:
    checksums: dict[str, str] = {}
    lines: list[str] = []
    for path in sorted(DIST.rglob("*")):
        if not path.is_file() or path.name == "sha256sums.txt":
            continue
        rel = path.relative_to(DIST).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums[rel] = digest
        lines.append(f"{digest}  {rel}")
    (DIST / "sha256sums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    checksums["sha256sums.txt"] = hashlib.sha256((DIST / "sha256sums.txt").read_bytes()).hexdigest()
    return checksums


def write_build_info(
    upstream_meta: dict[str, dict],
    categories_manifest: dict,
    checksums: dict[str, str],
) -> None:
    build_info = {
        "upstream_state": make_upstream_state(upstream_meta),
        "upstreams": upstream_meta,
        "artifacts": [{"path": path, "sha256": digest} for path, digest in sorted(checksums.items())],
        "categories": {
            "curated_geosite": [item["name"] for item in categories_manifest["curated"]["geosite"]],
            "curated_geoip": [item["name"] for item in categories_manifest["curated"]["geoip"]],
        },
    }
    (DIST / "build-info.json").write_text(
        json.dumps(build_info, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_output_contract() -> None:
    required = [
        DIST / "geosite.dat",
        DIST / "geoip.dat",
        DIST / "happ-routing.json",
        DIST / "happ-routing.onadd.txt",
        DIST / "happ-routing.add.txt",
        DIST / "categories.json",
        DIST / "build-info.json",
        DIST / "sha256sums.txt",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"missing required output artifacts: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    parser.add_argument(
        "--print-upstream-state",
        action="store_true",
        help="Print resolved upstream release tags as JSON and exit",
    )
    args = parser.parse_args()

    upstream_meta = resolve_release_metadata()
    if args.print_upstream_state:
        print(json.dumps(make_upstream_state(upstream_meta), indent=2, sort_keys=True))
        return 0

    clean_dir(WORK)
    clean_dir(DIST)
    mkdir(DIST_PLAIN)

    category_config = json.loads(CATEGORY_CONFIG.read_text(encoding="utf-8"))
    upstream_paths = fetch_upstreams(upstream_meta)
    tools = clone_build_tools()

    geosite_data, zkeen_geosite_dump, curated_geosite = build_geosite_sources(
        tools["dlc"], upstream_paths, category_config
    )
    build_geosite_dat(tools["dlc"], geosite_data)

    geoip_text_dir, raw_geoip, curated_geoip = build_geoip_sources(
        tools["geoip"], upstream_paths, category_config
    )
    build_geoip_dat(tools["geoip"], geoip_text_dir)

    geosite_names = {
        path.name
        for path in geosite_data.iterdir()
        if path.is_file()
    }
    geoip_names = {
        path.stem
        for path in geoip_text_dir.iterdir()
        if path.is_file()
    }
    profile = generate_happ(args.repo)
    validate_routing_refs(profile, geosite_names, geoip_names)
    assert_happ_matches_golden(profile)

    geosite_plain_exports = sorted(
        [f"zkeen-{name}" for name in category_config["geosite"]["zkeen_imports"]]
        + list(category_config["geosite"]["curated"].keys())
    )
    geoip_plain_exports = sorted(
        [f"zkeen-{name}" for name in category_config["geoip"]["zkeen_imports"]]
        + list(category_config["geoip"]["curated"].keys())
    )
    export_geosite_plain(tools["dlc"], geosite_plain_exports)
    export_geoip_plain(geoip_text_dir, geoip_plain_exports)

    raw_geosite = {
        f"zkeen-{name}": rules
        for name, rules in zkeen_geosite_dump.items()
        if f"zkeen-{name}" in geosite_plain_exports or name in category_config["geosite"]["zkeen_imports"]
    }
    categories_manifest = write_categories_manifest(
        category_config, raw_geosite, raw_geoip, curated_geosite, curated_geoip
    )
    checksums = write_checksums()
    write_build_info(upstream_meta, categories_manifest, checksums)
    validate_output_contract()

    summary = {
        "dist": str(DIST),
        "files": sorted(
            path.relative_to(DIST).as_posix()
            for path in DIST.rglob("*")
            if path.is_file()
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
