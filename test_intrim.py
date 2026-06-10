# -*- coding: utf-8 -*-
"""Intrimningstest: kör samma indata som fullflödestestet 2026-06-10 och bedömer svaret.

Körs mot lokal server (port 8001). Skriver hela svaret till intrim_result.json
och en kompakt bedömning till stdout så loopen kan utvärderas snabbt.
"""
import json
import sys

import httpx

BASE = "http://localhost:8001"

PROFILE = {
    "name": "Prompt Team",
    "purpose": "Webbapp där ett team av AI-agenter granskar idéer/kod och syntetiserar byggbara specar.",
    "stack": ["Python", "FastAPI", "vanilla JS"],
    "byggsatt": {
        "primary_language": "Python",
        "target_builder": "claude_code",
        "test_level": "kritiska",
    },
}

VAGUE_INPUT = "itterera över systemet."


def run_review(input_text: str, label: str) -> dict:
    payload = {
        "mode": "ny_funktion",
        "input_text": input_text,
        "context": "",
        "project_id": "intrim-test",
        "depth": "djup",
        "profile": PROFILE,
        "run_id": f"intrim-{label}",
    }
    r = httpx.post(f"{BASE}/api/review", json=payload, timeout=400.0)
    r.raise_for_status()
    return r.json()


def judge_vague(data: dict) -> list:
    """Returnerar lista med brister — tom lista = perfekt."""
    problems = []
    krav = data.get("krav_result", {})
    smith = data.get("smith", {})
    results = data.get("results", [])

    if krav.get("underlag") != "FÖR_VAGT":
        problems.append(f"Kravanalytikern dömde underlaget som {krav.get('underlag')!r}, inte FÖR_VAGT")
    if data.get("gated") != "FÖR_VAGT":
        problems.append("Gaten triggade inte — specialistrundan kördes")
    if results:
        problems.append(f"{len(results)} specialister kördes trots vagt underlag")
    if krav.get("krav"):
        problems.append(f"Kravanalytikern hittade på {len(krav['krav'])} krav ur tomma intet: {krav['krav'][:2]}")
    if smith.get("type") != "questions":
        problems.append(f"Promptsmeden returnerade typ {smith.get('type')!r}, inte questions")
    qs = smith.get("questions") or []
    if not (2 <= len(qs) <= 4):
        problems.append(f"{len(qs)} frågor (förväntat 2-4)")
    for q in qs:
        if not (q.get("options") or []):
            problems.append(f"Fråga utan svarsalternativ: {q.get('text','')[:60]}")
    cost = data.get("cost_summary", {})
    if (cost.get("total_usd") or 0) > 0.02:
        problems.append(f"Kostnad ${cost.get('total_usd')} — gaten ska vara billig (<$0.02)")
    return problems


def judge_concrete(data: dict) -> list:
    problems = []
    krav = data.get("krav_result", {})
    smith = data.get("smith", {})
    results = data.get("results", [])

    if krav.get("underlag") == "FÖR_VAGT":
        problems.append("FALSKT GATE-UTSLAG: konkret idé dömdes som FÖR_VAGT")
    if not results:
        problems.append("Inga specialistresultat")
    for r in results:
        if r.get("skipped"):
            continue
        if not (r.get("motivering") or "").strip():
            problems.append(f"{r['name']} ({r['status']}) saknar motivering")
        if r.get("status") == "FEL":
            problems.append(f"{r['name']} FEL: {(r.get('findings') or ['?'])[0][:80]}")
    if smith.get("type") not in ("prompt", "questions"):
        problems.append(f"Promptsmeden returnerade typ {smith.get('type')!r}")
    return problems


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "vague"
    if which == "vague":
        data = run_review(VAGUE_INPUT, "vague")
        problems = judge_vague(data)
        out = "intrim_result.json"
    else:
        concrete = (
            "Lägg till en knapp 'Kopiera spec' bredvid exportknappen som kopierar den "
            "genererade specifikationen till urklipp och visar en toast som bekräftelse."
        )
        data = run_review(concrete, "concrete")
        problems = judge_concrete(data)
        out = "intrim_result_concrete.json"

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    krav = data.get("krav_result", {})
    smith = data.get("smith", {})
    cost = data.get("cost_summary", {})
    print(f"underlag={krav.get('underlag')} gated={data.get('gated')} "
          f"agents={len(data.get('results', []))} smith_type={smith.get('type')} "
          f"cost=${cost.get('total_usd')}")
    if smith.get("type") == "questions":
        print(f"intro: {smith.get('intro','')[:200]}")
        for q in smith.get("questions") or []:
            print(f"  Q: {q.get('text','')}")
            for o in q.get("options") or []:
                print(f"     - {o}")
    if which != "vague":
        for r in data.get("results", []):
            print(f"  {r['status']:<10} {r['name']:<28} motivering: {(r.get('motivering') or '—')[:90]}")
    print()
    if problems:
        print("BRISTER:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print("PERFEKT — alla kriterier uppfyllda.")


if __name__ == "__main__":
    main()
