#!/usr/bin/env python3
"""Refresh data.json for the ShortGRH Roadmap dependency graph & progress tracker."""

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data.json"
ROADMAP_URL = "https://github.com/TauCetiProject/TauCetiRoadmap.git"

ARG_ROADMAPS = {
    "OneSidedPrimeSumBoundsAndAdmissibleData",
    "DivisibilityOfThetaDerivatives",
    "ThetaLiftChainsAndTheSeesawIdentity",
    "CompositeThetaLiftsAndShortForms",
    "SecondMomentsOfPoincareSeries",
    "RemainingAndMainTermsOfSecondMoments",
    "PairsOfFramesAtOnePlace",
    "DeterminantsOfThetaLiftChains",
    "NormsOfThetaLiftsAndExchangeIdentities",
    "CongruencesOfTwistedThetaLifts",
    "SelmerBoundsForAnticyclotomicTwists",
}

# Static [ShortProof] LOC per sub-roadmap (from lsernau/grh-lean@72fead10)
SHORTPROOF_LOC = {
    "AbelianSchemesWithThetaStructuresAndTheirCohomology": 31410,
    "AdelicUnitaryGroupsAndAlgebraicModularForms": 29099,
    "AuxiliaryAlgebraAndAnalysisForThetaLifts": 3792,
    "CohomologyOfFunctorsOnTestRings": 22770,
    "CompositeThetaLiftsAndShortForms": 21821,
    "CongruencesOfTwistedThetaLifts": 21775,
    "CrystallineRepresentationsAndKisinModules": 17003,
    "DeterminantsOfThetaLiftChains": 32045,
    "DivisibilityOfThetaDerivatives": 18809,
    "GaloisRepresentationsOfUnitaryEigenforms": 21463,
    "HolomorphicDiscreteSeriesOfUnitaryGroups": 26420,
    "IdelicReciprocityCountsAndCyclotomicClassGroups": 29803,
    "IntegralRepresentationsOfGeneralLinearGroups": 17918,
    "NormsOfThetaLiftsAndExchangeIdentities": 19715,
    "OneSidedPrimeSumBoundsAndAdmissibleData": 13463,
    "PadicComparisonForFunctorCohomology": 12639,
    "PairsOfFramesAtOnePlace": 23622,
    "RemainingAndMainTermsOfSecondMoments": 21379,
    "SecondMomentsOfPoincareSeries": 26967,
    "SelmerBoundsForAnticyclotomicTwists": 25001,
    "SiegelWeilAndRallisFormulasOnUnitaryGroups": 17102,
    "ThetaFunctionsAndUnitsOfCMLattices": 10511,
    "ThetaLiftChainsAndTheSeesawIdentity": 19818,
    "WeilRepresentationsOnBanachSpacesOfData": 34704,
    "ZeroFreeRegionsAndPrimesInShortWindows": 3872,
}


def fetch_shortgrh_prs() -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "shortgrh-roadmap-tracker",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    prs = []
    for state in ("is:merged", "is:open"):
        for page in range(1, 11):
            url = (
                "https://api.github.com/search/issues"
                f"?q=repo:TauCetiProject/TauCeti+is:pr+{state}+ShortGRH"
                f"&per_page=100&page={page}"
            )
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = payload.get("items", [])
            if not items:
                break
            for it in items:
                prs.append(
                    {
                        "number": it["number"],
                        "state": "merged" if state == "is:merged" else "open",
                        "title": it["title"],
                        "url": it["html_url"],
                        "updated": it["updated_at"],
                        "body": it.get("body") or "",
                    }
                )
            if len(items) < 100:
                break
    return prs


def main() -> int:
    prs = fetch_shortgrh_prs()
    print(f"Fetched {len(prs)} ShortGRH PRs")

    with tempfile.TemporaryDirectory(prefix="shortgrh-rm-") as tmpdir:
        rm_dir = Path(tmpdir) / "TauCetiRoadmap"
        subprocess.run(
            ["git", "clone", "--depth=1", ROADMAP_URL, str(rm_dir)],
            check=True,
        )
        sg_root = rm_dir / "TauCetiRoadmap" / "ShortGRH"
        sub_dirs = sorted(p for p in sg_root.iterdir() if p.is_dir())
        all_names = {p.name for p in sub_dirs}

        nodes: dict[str, dict] = {}
        cross_edges: set[tuple[str, str]] = set()

        for d in sub_dirs:
            name = d.name
            lines = (d / "README.md").read_text(encoding="utf-8").splitlines()
            title = re.sub(r"^#\s*(?:Roadmap:\s*)?", "", lines[0]).strip() if lines else name

            sections = []
            roadmap_files: set[str] = set()
            deps_on: set[str] = set()
            cur_layer = "General"
            cur_sec = None
            cur_buf: list[str] = []

            def flush():
                nonlocal cur_sec
                if cur_sec is None:
                    return
                body = "\n".join(cur_buf)
                m = re.search(r"\*Needs:\*\s*(.+?)(?:\n\n|\Z)", body, re.S)
                needs_text = m.group(1) if m else ""
                local_deps: set[str] = set()
                ext_deps: set[str] = set()

                for em in re.finditer(r"\b([A-Z][A-Za-z0-9]+)\s+\u00A7", needs_text):
                    tgt = em.group(1)
                    if tgt in all_names and tgt != name:
                        deps_on.add(tgt)
                        ext_deps.add(tgt)
                        cross_edges.add((tgt, name))

                stripped = re.sub(
                    r"\b[A-Z][A-Za-z0-9]+\s+\u00A7\u00A7?[\d\.\u2013\-,\s]+", "", needs_text
                )
                for lm in re.finditer(r"\b(\d+\.\d+)\b", stripped):
                    sid = lm.group(1)
                    if sid != cur_sec["id"]:
                        local_deps.add(sid)

                sec_files: set[str] = set()
                for fm in re.finditer(r"`((?:New|Lib)/[A-Za-z0-9_/]+(?:\.lean)?)`", body):
                    p = fm.group(1)
                    if not p.endswith(".lean"):
                        p += ".lean"
                    sec_files.add(p)
                    roadmap_files.add(p)

                cur_sec["localDeps"] = sorted(local_deps)
                cur_sec["extDeps"] = sorted(ext_deps)
                cur_sec["files"] = sorted(sec_files)
                sections.append(cur_sec)
                cur_sec = None

            for line in lines:
                ml = re.match(r"^##\s+(Layer\s+\d+.*|Supplement.*|Appendix.*)$", line)
                if ml:
                    flush()
                    cur_layer = ml.group(1).strip()
                    continue
                if re.match(r"^##\s+(Downstream|What the library|Results taken|References)", line):
                    flush()
                    break
                ms = re.match(r"^###\s+(\d+\.\d+)\s+(.+)$", line)
                if ms:
                    flush()
                    cur_buf = []
                    cur_sec = {
                        "id": ms.group(1),
                        "title": ms.group(2).strip(),
                        "layer": cur_layer,
                        "localDeps": [],
                        "extDeps": [],
                        "files": [],
                        "mergedPrs": [],
                        "openPrs": [],
                    }
                    continue
                if cur_sec is not None:
                    cur_buf.append(line)
            flush()

            nodes[name] = {
                "id": name,
                "title": title,
                "kind": "arg" if name in ARG_ROADMAPS else "bg",
                "loc": SHORTPROOF_LOC.get(name, 0),
                "refFileCount": len(roadmap_files),
                "deps": sorted(deps_on),
                "sections": sections,
                "unmatchedOpenPrs": [],
                "unmatchedMergedPrs": [],
            }

        mapped_count = 0
        unmapped_prs = []
        for pr in prs:
            body = pr["body"]
            pr_sum = {
                "number": pr["number"],
                "title": pr["title"],
                "url": pr["url"],
                "state": pr["state"],
                "updated": pr["updated"],
            }
            first_para = re.split(r"\r?\n\r?\n", body, maxsplit=1)[0]
            primary: set[tuple[str, str]] = set()
            for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s*\u00A7\u00A7?\s*(\d+\.\d+)", first_para):
                if m.group(1) in all_names:
                    primary.add((m.group(1), m.group(2)))
            if not primary:
                for m in re.finditer(r"ShortGRH/([A-Z][A-Za-z0-9]+)/README\.md", first_para):
                    if m.group(1) in all_names:
                        sm = re.search(r"\u00A7\u00A7?\s*(\d+\.\d+)", first_para)
                        primary.add((m.group(1), sm.group(1) if sm else ""))
            targets = primary
            if not targets:
                targets = set()
                for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s*\u00A7\u00A7?\s*(\d+\.\d+)", body):
                    if m.group(1) in all_names:
                        targets.add((m.group(1), m.group(2)))
                for m in re.finditer(
                    r"ShortGRH/([A-Z][A-Za-z0-9]+)[^\r\n]{0,80}?\u00A7\u00A7?\s*(\d+\.\d+)", body
                ):
                    if m.group(1) in all_names:
                        targets.add((m.group(1), m.group(2)))

            matched = False
            for rm_name, sec_id in targets:
                node = nodes[rm_name]
                sec = next((s for s in node["sections"] if s["id"] == sec_id), None) if sec_id else None
                if sec is not None:
                    (sec["mergedPrs"] if pr["state"] == "merged" else sec["openPrs"]).append(pr_sum)
                else:
                    (
                        node["unmatchedMergedPrs"]
                        if pr["state"] == "merged"
                        else node["unmatchedOpenPrs"]
                    ).append(pr_sum)
                matched = True

            if matched:
                mapped_count += 1
            else:
                unmapped_prs.append(pr_sum)

        node_list = []
        tot_secs = tot_merged = tot_open = 0
        for name in sorted(nodes):
            n = nodes[name]
            m_cnt = sum(1 for s in n["sections"] if s["mergedPrs"])
            o_cnt = sum(1 for s in n["sections"] if not s["mergedPrs"] and s["openPrs"])
            open_pr_cnt = sum(len(s["openPrs"]) for s in n["sections"]) + len(n["unmatchedOpenPrs"])
            merged_pr_cnt = sum(len(s["mergedPrs"]) for s in n["sections"]) + len(n["unmatchedMergedPrs"])
            tot_secs += len(n["sections"])
            tot_merged += m_cnt
            tot_open += o_cnt
            node_list.append(
                {
                    **n,
                    "totalSections": len(n["sections"]),
                    "mergedSections": m_cnt,
                    "openSections": o_cnt,
                    "openPrCount": open_pr_cnt,
                    "mergedPrCount": merged_pr_cnt,
                }
            )

        payload = {
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "totalPrsFetched": len(prs),
            "mappedPrs": mapped_count,
            "mergedPrs": sum(1 for p in prs if p["state"] == "merged"),
            "openPrs": sum(1 for p in prs if p["state"] == "open"),
            "totalSections": tot_secs,
            "mergedSections": tot_merged,
            "openSections": tot_open,
            "totalLoc": 461424,
            "estPrsPerLoc": 421,
            "nodes": node_list,
            "edges": [{"from": u, "to": v} for u, v in sorted(cross_edges)],
            "unmappedPrs": unmapped_prs,
        }
        DATA_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(
            f"Wrote {DATA_PATH}: {tot_secs} sections "
            f"({tot_merged} merged, {tot_open} open, {tot_secs - tot_merged - tot_open} empty)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
