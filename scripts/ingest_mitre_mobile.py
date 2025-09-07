"""
Ingesta do MITRE ATT&CK for Mobile (STIX 2.1) focada em:
- Mitigações (course-of-action)
- Detecções (x_mitre_detection nas técnicas)
- Outras informações úteis (táticas, plataformas, relações de uso por grupos/softwares)

Saída: POST /training/train com docs ricos:
  { "id"?, "text": "<conteúdo>", "metadata": { ... } }

Uso:
  export TOKEN="seu_jwt"
  python scripts/ingest_mitre_mobile.py \
    --api http://localhost:8000 \
    --token "$TOKEN" \
    --include techniques,mitigations,relations \
    --chunk-size 800 \
    --chunk-overlap 100 \
    --limit 500
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

INDEX_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/index.json"


def http_get_json(url: str) -> dict:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def latest_mobile_url(index_json: dict) -> str:
    """
    Encontra a URL da versão mais recente do Mobile ATT&CK no index.json.
    Tipicamente a primeira versão listada é a mais recente.
    """
    for coll in index_json.get("collections", []):
        name = (coll.get("name") or "").lower()
        if "mobile" in name:
            versions = coll.get("versions", [])
            if not versions:
                raise RuntimeError("Nenhuma versão encontrada para Mobile ATT&CK.")
            return versions[0]["url"]
    raise RuntimeError("Coleção Mobile ATT&CK não encontrada no index.json.")


def strip_md(text: Optional[str]) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def ext_attack_id(obj: dict) -> Optional[str]:
    for ref in obj.get("external_references", []) or []:
        if ref.get("external_id"):
            src = (ref.get("source_name") or "").lower()
            if "mitre" in src and "attack" in src:
                return ref["external_id"]
    for ref in obj.get("external_references", []) or []:
        if ref.get("external_id"):
            return ref["external_id"]
    return None


def ref_urls(obj: dict) -> List[str]:
    urls = []
    for ref in obj.get("external_references", []) or []:
        if ref.get("url"):
            urls.append(ref["url"])
    return urls


def kill_chain_phases(obj: dict) -> List[str]:
    phases = []
    for p in obj.get("kill_chain_phases", []) or []:
        if p.get("phase_name"):
            phases.append(p["phase_name"])
    return phases


def platforms(obj: dict) -> List[str]:
    return obj.get("x_mitre_platforms") or []


def data_sources(obj: dict) -> List[str]:
    return obj.get("x_mitre_data_sources") or obj.get("x_mitre_data_source") or []


def build_maps(objects: List[dict]) -> Tuple[dict, dict, dict, dict, List[dict]]:
    """
    Retorna:
      by_id: id -> objeto
      techniques: id -> attack-pattern
      mitigations: id -> course-of-action
      actors_sw: id -> {type: 'intrusion-set'|'malware', name: ...}
      relationships: lista de relacionamentos
    """
    by_id = {}
    techniques = {}
    mitigations = {}
    actors_sw = {}
    rels = []

    for o in objects:
        oid = o.get("id")
        if oid:
            by_id[oid] = o
        t = o.get("type")
        if t == "attack-pattern":
            techniques[oid] = o
        elif t == "course-of-action":
            mitigations[oid] = o
        elif t in ("intrusion-set", "malware"):
            actors_sw[oid] = {"type": t, "name": o.get("name", "")}
        elif t == "relationship":
            rels.append(o)

    return by_id, techniques, mitigations, actors_sw, rels


def rel_index(rels: List[dict]) -> Tuple[dict, dict]:
    """
    Cria índices úteis de relacionamento:
      mitigations_for_tech[tech_id] = [mitigation_id, ...]
      used_by_tech[tech_id] = [{"id": actor_or_sw_id, "type": "...", "name": "..."}, ...]
    """
    mitigations_for_tech: Dict[str, List[str]] = {}
    used_by_tech: Dict[str, List[str]] = {}

    for r in rels:
        rtype = r.get("relationship_type")
        src = r.get("source_ref")
        tgt = r.get("target_ref")
        if not (rtype and src and tgt):
            continue

        # course-of-action --mitigates--> attack-pattern
        if (rtype == "mitigates" and src.startswith("course-of-action--")
                and tgt.startswith("attack-pattern--")):
            mitigations_for_tech.setdefault(tgt, []).append(src)

        # intrusion-set/malware --uses--> attack-pattern
        if rtype == "uses" and tgt.startswith("attack-pattern--"):
            used_by_tech.setdefault(tgt, []).append(src)

    return mitigations_for_tech, used_by_tech


def technique_doc(
    tech: dict,
    by_id: dict,
    mitigations_for_tech: dict,
    used_by_tech: dict,
    actors_sw: dict,
) -> Dict[str, Any]:
    """
    Gera um documento "técnica" com seções:
      - Description
      - Detections (x_mitre_detection)
      - Mitigations (relacionamentos para course-of-action)
      - Used by (grupos e softwares)
      - Tactics, Platforms, Data Sources
    """
    tech_id = tech["id"]
    attack_id = ext_attack_id(tech) or tech_id
    name = tech.get("name", "")
    desc = strip_md(tech.get("description"))
    detect = strip_md(tech.get("x_mitre_detection"))
    urls = ref_urls(tech)
    phases = kill_chain_phases(tech)
    plats = platforms(tech)
    dsrc = data_sources(tech)

    # Mitigações relacionadas
    mit_ids = mitigations_for_tech.get(tech_id, [])
    mitigations_list = []
    for mid in mit_ids:
        mobj = by_id.get(mid, {})
        mitigations_list.append(
            {
                "id": ext_attack_id(mobj) or mobj.get("id"),
                "name": mobj.get("name", ""),
                "url": (ref_urls(mobj) or [None])[0],
            }
        )

    # Atores/Softwares que usam a técnica
    user_ids = used_by_tech.get(tech_id, [])
    used_by_list = []
    for uid in user_ids:
        info = actors_sw.get(uid)
        if not info:
            continue
        used_by_list.append(
            {
                "id": by_id.get(uid, {}).get("id"),
                "type": info["type"],
                "name": info["name"],
            }
        )

    lines = [f"[Technique {attack_id}] {name}"]
    if phases:
        lines.append(f"Tactics: {', '.join(phases)}")
    if plats:
        lines.append(f"Platforms: {', '.join(plats)}")
    if dsrc:
        lines.append(f"Data sources: {', '.join(dsrc)}")
    lines.append("")
    if desc:
        lines.append(desc)

    if detect:
        lines.extend(["", "## Detections", detect])

    if mitigations_list:
        lines.append("")
        lines.append("## Mitigations")
        for m in mitigations_list:
            mid = m["id"] or ""
            mname = m["name"] or ""
            lines.append(f"- {mid} {mname}")

    if used_by_list:
        lines.append("")
        lines.append("## Used by")
        for u in used_by_list:
            lines.append(f"- {u['type']}: {u['name']}")

    if urls:
        lines.append("")
        lines.append("## References")
        for u in urls[:10]:
            lines.append(f"- {u}")

    text = "\n".join(lines).strip()

    metadata = {
        "source": "MITRE ATT&CK Mobile",
        "stix_type": "attack-pattern",
        "attack_id": attack_id,
        "stix_id": tech_id,
        "name": name,
        "platforms": plats,
        "tactics": phases,
        "data_sources": dsrc,
        "urls": urls,
        "url": urls[0] if urls else None,
        "has_detection": bool(detect),
        "mitigations": mitigations_list,
        "used_by": used_by_list,
    }

    return {"id": attack_id, "text": text, "metadata": metadata}


def mitigation_doc(mit: dict, techniques_by_rel: Dict[str, List[dict]]) -> Dict[str, Any]:
    """
    Gera documento de Mitigação com:
      - descrição
      - lista de técnicas que ela mitiga
    """
    mit_id = mit["id"]
    attack_id = ext_attack_id(mit) or mit_id
    name = mit.get("name", "")
    desc = strip_md(mit.get("description"))
    urls = ref_urls(mit)

    lines = [f"[Mitigation {attack_id}] {name}", ""]
    if desc:
        lines.append(desc)

    techs = techniques_by_rel.get(mit_id, [])
    if techs:
        lines.append("")
        lines.append("## Mitigates Techniques")
        for t in techs:
            tid = ext_attack_id(t) or t.get("id")
            tname = t.get("name", "")
            lines.append(f"- {tid} {tname}")

    if urls:
        lines.append("")
        lines.append("## References")
        for u in urls[:10]:
            lines.append(f"- {u}")

    text = "\n".join(lines).strip()
    metadata = {
        "source": "MITRE ATT&CK Mobile",
        "stix_type": "course-of-action",
        "attack_id": attack_id,
        "stix_id": mit_id,
        "name": name,
        "urls": urls,
        "url": urls[0] if urls else None,
        "mitigates_count": len(techs),
    }
    return {"id": attack_id, "text": text, "metadata": metadata}


def relationship_docs(objects: List[dict], by_id: dict) -> Iterable[Dict[str, Any]]:
    """
    (Opcional) Gera documentos “relações” textuais.
    Útil para consultas como: “Qual grupo usa a técnica X?”.
    """
    for obj in objects:
        if obj.get("type") != "relationship":
            continue
        rtype = obj.get("relationship_type")
        src = by_id.get(obj.get("source_ref") or "")
        tgt = by_id.get(obj.get("target_ref") or "")
        if not (rtype and src and tgt):
            continue

        src_name = src.get("name") or src.get("id")
        tgt_name = tgt.get("name") or tgt.get("id")
        text = f"[Relation] {src_name} {rtype} {tgt_name}"
        meta = {
            "source": "MITRE ATT&CK Mobile",
            "stix_type": "relationship",
            "relationship_type": rtype,
            "source_ref": src.get("id"),
            "target_ref": tgt.get("id"),
            "source_name": src_name,
            "target_name": tgt_name,
        }
        yield {"text": text, "metadata": meta}


def build_docs(bundle: dict, include: List[str], limit: Optional[int]) -> List[Dict[str, Any]]:
    objs = bundle.get("objects", []) or []
    by_id, techniques, mitigations, actors_sw, rels = build_maps(objs)
    mit_for_tech, used_by_tech = rel_index(rels)

    techs_by_mit: Dict[str, List[dict]] = {}
    for tech_id, mlist in mit_for_tech.items():
        for mid in mlist:
            techs_by_mit.setdefault(mid, []).append(by_id[tech_id])

    docs: List[Dict[str, Any]] = []

    if "techniques" in include:
        for tech in techniques.values():
            docs.append(technique_doc(tech, by_id, mit_for_tech, used_by_tech, actors_sw))

    if "mitigations" in include:
        for mid, mit in mitigations.items():
            docs.append(mitigation_doc(mit, techs_by_mit))

    if "relations" in include:
        docs.extend(relationship_docs(objs, by_id))

    seen = set()
    uniq: List[Dict[str, Any]] = []
    for d in docs:
        key = (d.get("id"), d.get("text"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    if limit:
        uniq = uniq[: int(limit)]
    return uniq


def post_training(api_base: str, token: str, docs: List[Dict[str, Any]],
                  chunk_size: int, chunk_overlap: int) -> dict:
    url = f"{api_base.rstrip('/')}/training/train"
    payload = {"docs": docs, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000",
                    help="URL base da API (ex.: http://localhost:8000)")
    ap.add_argument("--token", required=True, help="Bearer token de /auth/login")
    ap.add_argument("--include", default="techniques,mitigations,relations",
                    help="Tipos de docs: techniques,mitigations,relations (csv)")
    ap.add_argument("--limit", type=int, default=None, help="Limite de docs (teste)")
    ap.add_argument("--chunk-size", type=int, default=800)
    ap.add_argument("--chunk-overlap", type=int, default=100)
    args = ap.parse_args()

    include = [s.strip().lower() for s in args.include.split(",") if s.strip()]

    print("[1/4] Baixando index.json …")
    idx = http_get_json(INDEX_URL)

    print("[2/4] Descobrindo URL da versão mais recente do Mobile ATT&CK …")
    mobile_url = latest_mobile_url(idx)
    print("     ->", mobile_url)

    print("[3/4] Baixando bundle STIX Mobile …")
    bundle = http_get_json(mobile_url)

    print("[4/4] Preparando documentos …")
    docs = build_docs(bundle, include=include, limit=args.limit)
    print(f"     -> {len(docs)} documentos")

    print("Ingerindo via /training/train …")
    res = post_training(args.api, args.token, docs, args.chunk_size, args.chunk_overlap)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
