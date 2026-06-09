"""
Scraper segunda vuelta presidencial 2026
Genera data.json a partir de la API de ONPE.

Uso:
    python scraper_2v.py
    python scraper_2v.py --out /ruta/data.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests
except ImportError:
    import requests

BASE = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend"
DEFAULT_OUT = Path(__file__).parent.parent / "data.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": "https://resultadosegundavuelta.onpe.gob.pe/main/resumen",
}

# Nombres legibles para departamentos y exterior
DEPT_NAMES = {
    "010000": "Amazonas", "020000": "Áncash", "030000": "Apurímac",
    "040000": "Arequipa", "050000": "Ayacucho", "060000": "Cajamarca",
    "070000": "Callao", "080000": "Cusco", "090000": "Huancavelica",
    "100000": "Huánuco", "110000": "Ica", "120000": "Junín",
    "130000": "La Libertad", "140000": "Lambayeque", "150000": "Lima",
    "160000": "Loreto", "170000": "Madre de Dios", "180000": "Moquegua",
    "190000": "Pasco", "200000": "Piura", "210000": "Puno",
    "220000": "San Martín", "230000": "Tacna", "240000": "Tumbes",
    "250000": "Ucayali",
    "910000": "África", "920000": "América", "930000": "Asia",
    "940000": "Europa", "950000": "Oceanía",
}


def get_session():
    try:
        s = requests.Session(impersonate="chrome")
    except TypeError:
        s = requests.Session()
    return s


def fetch(s, path, params=None):
    r = s.get(f"{BASE}{path}", params=params or {}, headers=HEADERS, timeout=20)
    if r.status_code == 200:
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            return r.json().get("data")
    return None


def build_dept_rows(data_keiko, data_roberto, ubigeo_pad=6):
    """Merge dept rows from two candidates into a list."""
    # Index by ubigeo
    by_ubigeo_k = {str(d["ubigeoNivel01"]).zfill(ubigeo_pad): d for d in (data_keiko or [])}
    by_ubigeo_r = {str(d["ubigeoNivel01"]).zfill(ubigeo_pad): d for d in (data_roberto or [])}
    all_ubigeos = sorted(set(list(by_ubigeo_k.keys()) + list(by_ubigeo_r.keys())))

    rows = []
    for ub in all_ubigeos:
        dk = by_ubigeo_k.get(ub)
        dr = by_ubigeo_r.get(ub)
        ref = dk or dr
        if not ref:
            continue

        pct_actas = ref.get("porcentajeActasContabilizadas") or 0
        actas_cont = ref.get("actasContabilizadas") or 0

        cands = []
        if dk and dk.get("participante"):
            p = dk["participante"]
            cands.append({
                "nombre": p.get("nombreCandidato", "KEIKO SOFIA FUJIMORI HIGUCHI"),
                "codigo": 8,
                "votos": int(p.get("totalVotosValidos") or 0),
                "pct": round(float(p.get("porcentajeVotosValidos") or 0), 2),
            })
        if dr and dr.get("participante"):
            p = dr["participante"]
            cands.append({
                "nombre": p.get("nombreCandidato", "ROBERTO HELBERT SANCHEZ PALOMINO"),
                "codigo": 10,
                "votos": int(p.get("totalVotosValidos") or 0),
                "pct": round(float(p.get("porcentajeVotosValidos") or 0), 2),
            })

        cands.sort(key=lambda c: -c["votos"])

        rows.append({
            "ubigeo": ub,
            "nombre": DEPT_NAMES.get(ub, ub),
            "pct_actas": round(float(pct_actas), 1),
            "actas_contabilizadas": int(actas_cont),
            "candidatos": cands,
        })

    return rows


def scrape(out_path=None):
    out = Path(out_path) if out_path else DEFAULT_OUT
    s = get_session()

    # ── Totales nacionales ─────────────────────────────────────────────────
    tot = fetch(s, "/resumen-general/totales",
                {"idEleccion": 10, "tipoFiltro": "eleccion"}) or {}

    # ── Candidatos nacionales ──────────────────────────────────────────────
    cands_raw = fetch(s, "/resumen-general/participantes",
                      {"idEleccion": 10, "tipoFiltro": "eleccion"}) or []

    candidatos = []
    for c in cands_raw:
        candidatos.append({
            "nombre": c.get("nombreCandidato") or "",
            "partido": c.get("nombreAgrupacionPolitica") or "",
            "codigo": int(c.get("codigoAgrupacionPolitica") or 0),
            "votos": int(c.get("totalVotosValidos") or 0),
            "pct": round(float(c.get("porcentajeVotosValidos") or 0), 3),
        })
    candidatos.sort(key=lambda c: -c["votos"])

    # ── Por departamento (Perú) ────────────────────────────────────────────
    dk_peru = fetch(s, "/resumen-general/mapa-calor",
                    {"idEleccion": 10, "tipoFiltro": "ambito_geografico",
                     "idAmbitoGeografico": 1, "codigoAgrupacionPolitica": 8})
    dr_peru = fetch(s, "/resumen-general/mapa-calor",
                    {"idEleccion": 10, "tipoFiltro": "ambito_geografico",
                     "idAmbitoGeografico": 1, "codigoAgrupacionPolitica": 10})

    por_departamento = build_dept_rows(dk_peru, dr_peru)

    # ── Exterior ───────────────────────────────────────────────────────────
    dk_ext = fetch(s, "/resumen-general/mapa-calor",
                   {"idEleccion": 10, "tipoFiltro": "ambito_geografico",
                    "idAmbitoGeografico": 2, "codigoAgrupacionPolitica": 8})
    dr_ext = fetch(s, "/resumen-general/mapa-calor",
                   {"idEleccion": 10, "tipoFiltro": "ambito_geografico",
                    "idAmbitoGeografico": 2, "codigoAgrupacionPolitica": 10})

    exterior = build_dept_rows(dk_ext, dr_ext, ubigeo_pad=6)

    # ── Totales nacionales incluyendo exterior ─────────────────────────────
    tot_ext = fetch(s, "/resumen-general/totales",
                    {"idEleccion": 10, "tipoFiltro": "eleccion",
                     "idAmbitoGeografico": 2}) or {}

    meta = {
        "proceso": "Segunda Elección Presidencial 2026",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "pct_actas": round(float(tot.get("actasContabilizadas") or 0), 3),
        "actas_contabilizadas": int(tot.get("contabilizadas") or 0),
        "total_actas": int(tot.get("totalActas") or 0),
        "votos_emitidos": 0,  # no expuesto en la API
        "votos_validos": sum(c["votos"] for c in candidatos),
        "participacion": round(float(tot.get("participacionCiudadana") or 0), 3),
        "exterior_pct_actas": round(float(
            (tot_ext.get("actasContabilizadas") or
             (sum(d["pct_actas"] for d in exterior) / max(len(exterior), 1))
             if exterior else 0)
        ), 1),
    }

    output = {
        "meta": meta,
        "candidatos": candidatos,
        "por_departamento": por_departamento,
        "exterior": exterior,
    }

    # ── Guardia: no sobreescribir con datos vacíos ─────────────────────────
    if not candidatos or meta["pct_actas"] == 0:
        print("⚠️  API devolvió datos vacíos (posible bloqueo Cloudflare).")
        if out.exists():
            print("   Conservando data.json anterior sin cambios.")
            return None
        else:
            print("   No existe data.json previo — guardando igual.")

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── Historial de tendencias ────────────────────────────────────────
    hist_path = out.parent / "history.json"
    r_cand = next((c for c in candidatos if c["codigo"] == 10), {})
    k_cand = next((c for c in candidatos if c["codigo"] == 8),  {})
    new_point = {
        "t":     meta["scraped_at"],
        "actas": meta["pct_actas"],
        "r":     r_cand.get("pct", 0),
        "k":     k_cand.get("pct", 0),
    }
    history = []
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    # Evitar duplicados exactos de porcentaje
    if not history or history[-1]["r"] != new_point["r"] or history[-1]["k"] != new_point["k"]:
        history.append(new_point)
        history = history[-500:]  # conservar últimos 500 puntos
        hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        print(f"    Historial: {len(history)} puntos → history.json")

    print(f"✅  data.json generado → {out}")
    print(f"    Actas: {meta['pct_actas']}%  ({meta['actas_contabilizadas']}/{meta['total_actas']})")
    print(f"    Candidatos: {len(candidatos)}")
    print(f"    Departamentos: {len(por_departamento)}")
    print(f"    Exterior: {len(exterior)} zonas")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    scrape(args.out)
