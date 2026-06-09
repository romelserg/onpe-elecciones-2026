"""
Scraper para los resultados electorales de ONPE - Elecciones Generales 2026
Base URL: https://resultadoelectoral.onpe.gob.pe/presentacion-backend

Elecciones:
  id=10  Presidencial              (nacional, tipoFiltro=eleccion)
  id=12  Parlamento Andino         (nacional, tipoFiltro=eleccion)
  id=13  Diputados                 (por distrito, tipoFiltro=distrito_electoral)
  id=14  Senadores múltiple        (por distrito, tipoFiltro=distrito_electoral)
  id=15  Senadores único           (nacional, tipoFiltro=eleccion)

Requiere: pip install curl-cffi
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import sqlite3

try:
    from curl_cffi import requests as cf_requests
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as cf_requests  # type: ignore
    _HAS_CURL_CFFI = False

from db import init_db

BASE_URL = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend"

HEADERS = {
    "accept": "*/*",
    "accept-language": "es-ES,es;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "referer": "https://resultadoelectoral.onpe.gob.pe/main/resumen",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

# Elecciones nacionales (un único resultado a nivel país)
NATIONAL_ELECTIONS = [
    {"id": 10, "nombre": "Presidencial"},
    {"id": 12, "nombre": "Parlamento Andino"},
    {"id": 15, "nombre": "Senadores Único Nacional"},
]

# Elecciones por distrito (26 distritos electorales)
DISTRICT_ELECTIONS = [
    {"id": 13, "nombre": "Diputados"},
    {"id": 14, "nombre": "Senadores Múltiple"},
]

log = logging.getLogger(__name__)


class ONPEClient:
    """Cliente HTTP que impersona Chrome para evadir Cloudflare."""

    def __init__(self):
        if _HAS_CURL_CFFI:
            self.session = cf_requests.Session(impersonate="chrome")
        else:
            log.warning(
                "curl_cffi no encontrado. Instala con: pip install curl-cffi\n"
                "Usando requests estándar (puede ser bloqueado por Cloudflare)."
            )
            self.session = cf_requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, path: str, params: dict = None, retries: int = 3) -> Optional[object]:
        url = f"{BASE_URL}/{path}"
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 204:
                    return None
                if r.status_code != 200:
                    log.warning("HTTP %d → %s", r.status_code, url)
                    return None
                if not r.content or not r.text.strip():
                    return None
                try:
                    payload = r.json()
                except Exception:
                    log.debug("Respuesta no-JSON para %s (ignorada)", url)
                    return None
                if isinstance(payload, dict) and payload.get("success") is False:
                    log.warning("API error %s: %s", url, payload.get("message"))
                    return None
                return payload.get("data") if isinstance(payload, dict) else payload
            except Exception as exc:
                log.error("Intento %d/%d fallido %s: %s", attempt + 1, retries, url, exc)
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        return None


class ONPEScraper:
    def __init__(self, db_path: str = None):
        self.client = ONPEClient()
        self.con = init_db(db_path)
        self._proceso_id = None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------ #
    # Helpers de persistencia                                              #
    # ------------------------------------------------------------------ #

    def _clear_and_insert_candidatos(
        self, rows: list, id_eleccion: int, id_distrito: Optional[int],
        tipo_filtro: str, fuente: str
    ):
        """Reemplaza los candidatos de una combinación (elección, distrito, fuente)."""
        self.con.execute(
            "DELETE FROM candidatos "
            "WHERE id_eleccion=? AND COALESCE(id_distrito,-1)=COALESCE(?,-1) "
            "AND tipo_filtro=? AND fuente=?",
            (id_eleccion, id_distrito, tipo_filtro, fuente),
        )
        now = self._now()
        self.con.executemany(
            """INSERT INTO candidatos
               (id_eleccion, id_distrito, tipo_filtro, fuente,
                nombre_agrupacion, codigo_agrupacion,
                nombre_candidato, dni_candidato,
                votos_validos, pct_votos_validos, pct_votos_emitidos,
                posicion, total_candidatos, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    id_eleccion, id_distrito, tipo_filtro, fuente,
                    r.get("nombreAgrupacionPolitica"),
                    str(r.get("codigoAgrupacionPolitica", "") or ""),
                    r.get("nombreCandidato"),
                    r.get("dniCandidato"),
                    r.get("totalVotosValidos"),
                    r.get("porcentajeVotosValidos"),
                    r.get("porcentajeVotosEmitidos"),
                    r.get("posicion"),
                    r.get("totalCandidatos"),
                    now,
                )
                for r in rows
            ],
        )
        self.con.commit()

    def _upsert_totales(
        self, data: dict, id_eleccion: int, id_distrito: Optional[int], tipo_filtro: str
    ):
        self.con.execute(
            "DELETE FROM totales "
            "WHERE id_eleccion=? AND COALESCE(id_distrito,-1)=COALESCE(?,-1) AND tipo_filtro=?",
            (id_eleccion, id_distrito, tipo_filtro),
        )
        self.con.execute(
            """INSERT INTO totales
               (id_eleccion, id_distrito, tipo_filtro,
                actas_contabilizadas, pct_actas_contabilizadas, total_actas,
                actas_enviadas_jee, actas_pendientes_jee,
                participacion_ciudadana, votos_emitidos, votos_validos,
                fecha_actualizacion, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                id_eleccion, id_distrito, tipo_filtro,
                data.get("contabilizadas"),
                data.get("actasContabilizadas"),
                data.get("totalActas"),
                data.get("enviadasJee"),
                data.get("pendientesJee"),
                data.get("participacionCiudadana"),
                data.get("totalVotosEmitidos"),
                data.get("totalVotosValidos"),
                data.get("fechaActualizacion"),
                self._now(),
            ),
        )
        self.con.commit()

    def _insert_mapa_calor(
        self, rows: list, id_eleccion: int, tipo_filtro: str,
        id_distrito: Optional[int] = None, codigo_agrupacion: str = None
    ):
        now = self._now()
        self.con.executemany(
            """INSERT INTO mapa_calor
               (id_eleccion, tipo_filtro, id_distrito, codigo_agrupacion,
                ambito, ubigeo_nivel01, ubigeo_nivel02, ubigeo_nivel03,
                distrito_electoral, pct_actas_contabilizadas, actas_contabilizadas, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    id_eleccion, tipo_filtro, id_distrito,
                    str(codigo_agrupacion or ""),
                    r.get("ambitoGeografico"),
                    r.get("ubigeoNivel01"), r.get("ubigeoNivel02"), r.get("ubigeoNivel03"),
                    r.get("distritoElectoral"),
                    r.get("porcentajeActasContabilizadas"),
                    r.get("actasContabilizadas"),
                    now,
                )
                for r in rows
            ],
        )
        self.con.commit()

    # ------------------------------------------------------------------ #
    # Metadatos                                                            #
    # ------------------------------------------------------------------ #

    def scrape_metadata(self) -> list:
        log.info("Scraping metadatos...")

        proc = self.client.get("proceso/proceso-electoral-activo")
        if not proc:
            log.error("No se pudo obtener el proceso electoral activo.")
            return []

        self._proceso_id = proc["id"]
        self.con.execute(
            "INSERT OR REPLACE INTO proceso_electoral "
            "(id, nombre, acronimo, fecha_proceso, id_eleccion_principal, tipo_proceso, scraped_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                proc["id"], proc["nombre"], proc["acronimo"],
                proc["fechaProceso"], proc["idEleccionPrincipal"],
                proc["tipoProcesoElectoral"], self._now(),
            ),
        )

        elecciones = self.client.get(f"proceso/{self._proceso_id}/elecciones")
        if elecciones:
            self.con.executemany(
                "INSERT OR REPLACE INTO eleccion_tipo "
                "(id, nombre, id_eleccion, url, descripcion, es_principal, padre, hijos) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        e["id"], e["nombre"], e["idEleccion"], e.get("url", ""),
                        e.get("descripcion", ""), int(e.get("esPrincipal", False)),
                        e["padre"], int(e.get("hijos", False)),
                    )
                    for e in elecciones
                ],
            )

        distritos = self.client.get("distrito-electoral/distritos")
        if distritos:
            self.con.executemany(
                "INSERT OR REPLACE INTO distrito_electoral (codigo, nombre) VALUES (?,?)",
                [(d["codigo"], d["nombre"]) for d in distritos],
            )

        self.con.commit()
        log.info("  %d distritos electorales guardados.", len(distritos or []))
        return distritos or []

    def _get_distritos(self) -> list:
        rows = self.con.execute(
            "SELECT codigo, nombre FROM distrito_electoral ORDER BY codigo"
        ).fetchall()
        return [{"codigo": r["codigo"], "nombre": r["nombre"]} for r in rows]

    # ------------------------------------------------------------------ #
    # Elecciones nacionales                                                #
    # ------------------------------------------------------------------ #

    def scrape_presidencial(self, distritos: list):
        id_elec = 10
        log.info("Presidencial — totales y candidatos nacionales...")

        data = self.client.get(
            "resumen-general/totales", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if data:
            self._upsert_totales(data, id_elec, None, "eleccion")

        rows = self.client.get(
            "resumen-general/participantes", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if rows:
            self._clear_and_insert_candidatos(rows, id_elec, None, "eleccion", "resumen-general")

        # Resultados por partido (nacional)
        rows = self.client.get(
            "eleccion-presidencial/participantes-organizacion-politica",
            {"idEleccion": id_elec, "tipoFiltro": "eleccion"},
        )
        if rows:
            self._clear_and_insert_candidatos(rows, id_elec, None, "eleccion", "presidencial-org")

        # Mapa de calor nacional
        rows = self.client.get(
            "resumen-general/mapa-calor", {"idEleccion": id_elec, "tipoFiltro": "total"}
        )
        if rows:
            self._insert_mapa_calor(rows, id_elec, "total")

        # Resultados presidenciales por distrito electoral
        log.info("Presidencial — desglose por los %d distritos...", len(distritos))
        for d in distritos:
            codigo, nombre = d["codigo"], d["nombre"]
            rows = self.client.get(
                "eleccion-presidencial/participantes-ubicacion-geografica",
                {"idEleccion": id_elec, "tipoFiltro": "eleccion", "idDistritoElectoral": codigo},
            )
            if rows:
                self._clear_and_insert_candidatos(
                    rows, id_elec, codigo, "eleccion", "presidencial-geo"
                )
            log.info("  ✓ Presidencial / %s", nombre)

    def scrape_senadores_unico(self):
        id_elec = 15
        log.info("Senadores Único Nacional...")

        data = self.client.get(
            "resumen-general/totales", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if data:
            self._upsert_totales(data, id_elec, None, "eleccion")

        rows = self.client.get(
            "resumen-general/participantes", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if rows:
            self._clear_and_insert_candidatos(rows, id_elec, None, "eleccion", "resumen-general")

        rows = self.client.get(
            "resumen-general/mapa-calor", {"idEleccion": id_elec, "tipoFiltro": "total"}
        )
        if rows:
            self._insert_mapa_calor(rows, id_elec, "total")

    def scrape_parlamento_andino(self):
        id_elec = 12
        log.info("Parlamento Andino...")

        data = self.client.get(
            "resumen-general/totales", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if data:
            self._upsert_totales(data, id_elec, None, "eleccion")

        rows = self.client.get(
            "resumen-general/participantes", {"idEleccion": id_elec, "tipoFiltro": "eleccion"}
        )
        if rows:
            self._clear_and_insert_candidatos(rows, id_elec, None, "eleccion", "resumen-general")

        # Candidatos individuales
        rows = self.client.get(
            "parlamento-andino/participantes-por-candidato",
            {"idEleccion": id_elec, "tipoFiltro": "eleccion"},
        )
        if rows:
            self._clear_and_insert_candidatos(
                rows, id_elec, None, "eleccion", "parlamento-candidato"
            )

        # Por organización política
        rows = self.client.get(
            "parlamento-andino/participantes-organizacion-politica",
            {"idEleccion": id_elec, "tipoFiltro": "eleccion"},
        )
        if rows:
            self._clear_and_insert_candidatos(rows, id_elec, None, "eleccion", "parlamento-org")

        rows = self.client.get(
            "resumen-general/mapa-calor", {"idEleccion": id_elec, "tipoFiltro": "total"}
        )
        if rows:
            self._insert_mapa_calor(rows, id_elec, "total")

    # ------------------------------------------------------------------ #
    # Elecciones por distrito                                              #
    # ------------------------------------------------------------------ #

    def scrape_senadores_multiple(self, distritos: list):
        id_elec = 14
        log.info("Senadores Múltiple — %d distritos...", len(distritos))

        rows = self.client.get(
            "resumen-general/mapa-calor", {"idEleccion": id_elec, "tipoFiltro": "total"}
        )
        if rows:
            self._insert_mapa_calor(rows, id_elec, "total")

        for d in distritos:
            codigo, nombre = d["codigo"], d["nombre"]
            params_base = {
                "idAmbitoGeografico": 1,
                "idEleccion": id_elec,
                "tipoFiltro": "distrito_electoral",
                "idDistritoElectoral": codigo,
            }

            data = self.client.get("resumen-general/totales", params_base)
            if data:
                self._upsert_totales(data, id_elec, codigo, "distrito_electoral")

            rows = self.client.get("resumen-general/participantes", params_base)
            if rows:
                self._clear_and_insert_candidatos(
                    rows, id_elec, codigo, "distrito_electoral", "resumen-general"
                )

            # Desglose geográfico dentro del distrito (por partido)
            rows = self.client.get(
                "senadores-distrital-multiple/participantes-ubicacion-geografica",
                {
                    "idDistritoElectoral": codigo,
                    "idEleccion": id_elec,
                    "tipoFiltro": "distrito_electoral",
                },
            )
            if rows:
                self._clear_and_insert_candidatos(
                    rows, id_elec, codigo, "distrito_electoral", "senadores-multiple-geo"
                )

            log.info("  ✓ Senadores múltiple / %s", nombre)

    def scrape_diputados(self, distritos: list):
        id_elec = 13
        log.info("Diputados — %d distritos...", len(distritos))

        rows = self.client.get(
            "resumen-general/mapa-calor", {"idEleccion": id_elec, "tipoFiltro": "total"}
        )
        if rows:
            self._insert_mapa_calor(rows, id_elec, "total")

        for d in distritos:
            codigo, nombre = d["codigo"], d["nombre"]
            params_base = {
                "idAmbitoGeografico": 1,
                "idEleccion": id_elec,
                "tipoFiltro": "distrito_electoral",
                "idDistritoElectoral": codigo,
            }

            data = self.client.get("resumen-general/totales", params_base)
            if data:
                self._upsert_totales(data, id_elec, codigo, "distrito_electoral")

            rows = self.client.get("resumen-general/participantes", params_base)
            if rows:
                self._clear_and_insert_candidatos(
                    rows, id_elec, codigo, "distrito_electoral", "resumen-general"
                )

            # Resultados por partido dentro del distrito
            rows = self.client.get(
                "eleccion-diputado/participantes-ubicacion-geografica",
                {
                    "idEleccion": id_elec,
                    "tipoFiltro": "distrito_electoral",
                    "idDistritoElectoral": codigo,
                },
            )
            if rows:
                self._clear_and_insert_candidatos(
                    rows, id_elec, codigo, "distrito_electoral", "diputado-geo"
                )

            log.info("  ✓ Diputados / %s", nombre)

    # ------------------------------------------------------------------ #
    # Punto de entrada                                                     #
    # ------------------------------------------------------------------ #

    def run(self):
        started = self._now()
        log_id = self.con.execute(
            "INSERT INTO scrape_log (started_at, status) VALUES (?, 'running')",
            (started,),
        ).lastrowid
        self.con.commit()

        try:
            distritos = self.scrape_metadata()
            if not distritos:
                distritos = self._get_distritos()

            self.scrape_presidencial(distritos)
            self.scrape_senadores_unico()
            self.scrape_parlamento_andino()
            self.scrape_senadores_multiple(distritos)
            self.scrape_diputados(distritos)

            self.con.execute(
                "UPDATE scrape_log SET finished_at=?, status='ok' WHERE id=?",
                (self._now(), log_id),
            )
        except Exception as exc:
            self.con.execute(
                "UPDATE scrape_log SET finished_at=?, status='error', notas=? WHERE id=?",
                (self._now(), str(exc), log_id),
            )
            raise
        finally:
            self.con.commit()
            self.con.close()

        log.info("Scraping completado.")
