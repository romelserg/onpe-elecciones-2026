import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "onpe_elecciones_2026.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proceso_electoral (
    id INTEGER PRIMARY KEY,
    nombre TEXT,
    acronimo TEXT,
    fecha_proceso INTEGER,
    id_eleccion_principal INTEGER,
    tipo_proceso TEXT,
    scraped_at TEXT
);

CREATE TABLE IF NOT EXISTS eleccion_tipo (
    id INTEGER PRIMARY KEY,
    nombre TEXT,
    id_eleccion INTEGER,
    url TEXT,
    descripcion TEXT,
    es_principal INTEGER,
    padre INTEGER,
    hijos INTEGER
);

-- Los 26 distritos electorales del Perú
CREATE TABLE IF NOT EXISTS distrito_electoral (
    codigo INTEGER PRIMARY KEY,
    nombre TEXT
);

-- Totales por elección y distrito (actas, participación, votos)
CREATE TABLE IF NOT EXISTS totales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_eleccion INTEGER NOT NULL,
    id_distrito INTEGER,
    tipo_filtro TEXT NOT NULL,
    actas_contabilizadas INTEGER,
    pct_actas_contabilizadas REAL,
    total_actas INTEGER,
    actas_enviadas_jee INTEGER,
    actas_pendientes_jee INTEGER,
    participacion_ciudadana REAL,
    votos_emitidos INTEGER,
    votos_validos INTEGER,
    fecha_actualizacion INTEGER,
    scraped_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_totales_elec_dist
    ON totales(id_eleccion, id_distrito, tipo_filtro);

-- Resultados por candidato o agrupación política
-- fuente: resumen-general | presidencial-org | presidencial-geo |
--         parlamento-candidato | parlamento-org |
--         senadores-multiple-geo | diputado-geo
CREATE TABLE IF NOT EXISTS candidatos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_eleccion INTEGER NOT NULL,
    id_distrito INTEGER,
    tipo_filtro TEXT,
    fuente TEXT,
    nombre_agrupacion TEXT,
    codigo_agrupacion TEXT,
    nombre_candidato TEXT,
    dni_candidato TEXT,
    votos_validos INTEGER,
    pct_votos_validos REAL,
    pct_votos_emitidos REAL,
    posicion INTEGER,
    total_candidatos INTEGER,
    scraped_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cand_elec_dist
    ON candidatos(id_eleccion, id_distrito, fuente);

-- Datos de mapa de calor (porcentaje de actas por zona)
CREATE TABLE IF NOT EXISTS mapa_calor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_eleccion INTEGER NOT NULL,
    tipo_filtro TEXT,
    id_distrito INTEGER,
    codigo_agrupacion TEXT,
    ambito TEXT,
    ubigeo_nivel01 TEXT,
    ubigeo_nivel02 TEXT,
    ubigeo_nivel03 TEXT,
    distrito_electoral TEXT,
    pct_actas_contabilizadas REAL,
    actas_contabilizadas INTEGER,
    scraped_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mapa_elec
    ON mapa_calor(id_eleccion, tipo_filtro);

-- Registro de cada ejecución del scraper
CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    notas TEXT
);
"""


def get_connection(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path: str = None) -> sqlite3.Connection:
    con = get_connection(db_path)
    con.executescript(SCHEMA)
    con.commit()
    return con
