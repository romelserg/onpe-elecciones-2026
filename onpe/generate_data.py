"""
Genera data.json a partir de la base de datos SQLite.
Salida: ../data.json  (raíz del repositorio GitHub)

Uso:
    python generate_data.py
    python generate_data.py --out /ruta/personalizada/data.json
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "onpe_elecciones_2026.db"
DEFAULT_OUT = Path(__file__).parent.parent / "data.json"


def get_con(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def generate(db_path=None, out_path=None):
    db  = db_path  or DB_PATH
    out = out_path or DEFAULT_OUT

    con = get_con(str(db))

    # ── Proceso activo ──────────────────────────────────────────────
    proc = con.execute(
        "SELECT * FROM proceso_electoral ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # ── Qué elecciones existen? ─────────────────────────────────────
    elecciones = {
        r["id"]: dict(r)
        for r in con.execute("SELECT * FROM eleccion_tipo").fetchall()
    }

    # ── Buscar elección presidencial activa ─────────────────────────
    # Estrategia: buscar la elección que tenga candidatos individuales
    # (nombre_candidato no nulo) a nivel nacional, con más votos totales.
    # Esto distingue la presidencial de parlamento andino u otras.
    id_pres = None

    # 1) Buscar por nombre: "presidencial" en eleccion_tipo
    for eid, e in sorted(elecciones.items(), reverse=True):
        nombre = (e.get("nombre") or "").lower()
        if "presidencial" in nombre:
            n = con.execute(
                "SELECT COUNT(*) FROM candidatos WHERE id_eleccion=? AND id_distrito IS NULL AND nombre_candidato IS NOT NULL",
                (eid,)
            ).fetchone()[0]
            if n > 0:
                id_pres = eid
                break

    # 2) Fallback: elección con más votos válidos nacionales y candidatos con nombre
    if id_pres is None:
        row = con.execute("""
            SELECT c.id_eleccion, MAX(t.votos_validos) as vv
            FROM candidatos c
            JOIN totales t ON t.id_eleccion = c.id_eleccion AND t.id_distrito IS NULL
            WHERE c.id_distrito IS NULL AND c.nombre_candidato IS NOT NULL
            GROUP BY c.id_eleccion
            ORDER BY vv DESC LIMIT 1
        """).fetchone()
        if row:
            id_pres = row["id_eleccion"]

    # 3) Último recurso: el resumen-general con más candidatos nacionales
    if id_pres is None:
        row = con.execute("""
            SELECT id_eleccion, COUNT(*) as n FROM candidatos
            WHERE id_distrito IS NULL AND fuente='resumen-general'
            GROUP BY id_eleccion ORDER BY n DESC LIMIT 1
        """).fetchone()
        if row:
            id_pres = row["id_eleccion"]

    # ── Totales presidenciales ──────────────────────────────────────
    tot = con.execute(
        "SELECT * FROM totales WHERE id_eleccion=? AND id_distrito IS NULL",
        (id_pres,)
    ).fetchone()

    meta = {
        "proceso": proc["nombre"] if proc else "Elecciones 2026",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "id_eleccion": id_pres,
        "pct_actas": round(float(tot["pct_actas_contabilizadas"] or 0), 3) if tot else 0,
        "actas_contabilizadas": int(tot["actas_contabilizadas"] or 0) if tot else 0,
        "total_actas": int(tot["total_actas"] or 0) if tot else 0,
        "votos_emitidos": int(tot["votos_emitidos"] or 0) if tot else 0,
        "votos_validos": int(tot["votos_validos"] or 0) if tot else 0,
        "participacion": round(float(tot["participacion_ciudadana"] or 0), 3) if tot else 0,
    }

    # ── Candidatos nacionales ───────────────────────────────────────
    rows = con.execute("""
        SELECT nombre_candidato, nombre_agrupacion, codigo_agrupacion,
               MAX(votos_validos) as votos_validos,
               MAX(pct_votos_validos) as pct_votos_validos,
               MAX(pct_votos_emitidos) as pct_votos_emitidos
        FROM candidatos
        WHERE id_eleccion=? AND id_distrito IS NULL
          AND nombre_agrupacion NOT LIKE '%NULOS%'
          AND nombre_agrupacion NOT LIKE '%BLANCO%'
          AND (votos_validos IS NOT NULL AND votos_validos > 0)
        GROUP BY COALESCE(nombre_candidato, nombre_agrupacion)
        ORDER BY votos_validos DESC
    """, (id_pres,)).fetchall()

    candidatos = [
        {
            "nombre":   r["nombre_candidato"] or r["nombre_agrupacion"],
            "partido":  r["nombre_agrupacion"] or "",
            "codigo":   r["codigo_agrupacion"] or "",
            "votos":    int(r["votos_validos"] or 0),
            "pct":      round(float(r["pct_votos_validos"] or 0), 3),
            "pct_emit": round(float(r["pct_votos_emitidos"] or 0), 3),
        }
        for r in rows
    ]

    # ── Por distrito ────────────────────────────────────────────────
    distritos_db = con.execute(
        "SELECT codigo, nombre FROM distrito_electoral ORDER BY codigo"
    ).fetchall()

    por_distrito = []
    for d in distritos_db:
        cod  = d["codigo"]
        nombre_d = d["nombre"]

        tot_d = con.execute(
            "SELECT * FROM totales WHERE id_eleccion=? AND id_distrito=?",
            (id_pres, cod)
        ).fetchone()

        cands_d = con.execute("""
            SELECT nombre_candidato, nombre_agrupacion, codigo_agrupacion,
                   votos_validos, pct_votos_validos
            FROM candidatos
            WHERE id_eleccion=? AND id_distrito=?
              AND nombre_agrupacion NOT LIKE '%NULOS%'
              AND nombre_agrupacion NOT LIKE '%BLANCO%'
              AND (votos_validos IS NOT NULL AND votos_validos > 0)
            ORDER BY votos_validos DESC
            LIMIT 5
        """, (id_pres, cod)).fetchall()

        if not cands_d:
            continue

        por_distrito.append({
            "codigo": cod,
            "nombre": nombre_d,
            "pct_actas": round(float((tot_d["pct_actas_contabilizadas"] if tot_d else None) or 0), 1),
            "votos_validos": int((tot_d["votos_validos"] if tot_d else None) or 0),
            "candidatos": [
                {
                    "nombre":  r["nombre_candidato"] or r["nombre_agrupacion"],
                    "partido": r["nombre_agrupacion"] or "",
                    "votos":   int(r["votos_validos"] or 0),
                    "pct":     round(float(r["pct_votos_validos"] or 0), 2),
                }
                for r in cands_d
            ],
        })

    # ── Log de scraping ─────────────────────────────────────────────
    last_scrape = con.execute(
        "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    output = {
        "meta": meta,
        "candidatos": candidatos,
        "por_distrito": por_distrito,
        "last_scrape": {
            "started_at":  last_scrape["started_at"]  if last_scrape else None,
            "finished_at": last_scrape["finished_at"] if last_scrape else None,
            "status":      last_scrape["status"]      if last_scrape else None,
        } if last_scrape else None,
    }

    out_path_obj = Path(out)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path_obj, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅  data.json generado → {out_path_obj}")
    print(f"    Proceso:  {meta['proceso']}")
    print(f"    Actas:    {meta['pct_actas']}%  ({meta['actas_contabilizadas']}/{meta['total_actas']})")
    print(f"    Candidatos nacionales: {len(candidatos)}")
    print(f"    Distritos: {len(por_distrito)}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",  default=None, help="Ruta de la base de datos")
    parser.add_argument("--out", default=None, help="Ruta de salida para data.json")
    args = parser.parse_args()
    generate(args.db, args.out)
