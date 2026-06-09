"""
Uso:
    python main.py                 # scrape único
    python main.py --loop 5        # repite cada 5 minutos (útil en noche electoral)
    python main.py --db mi.db      # ruta de DB personalizada
"""

import argparse
import logging
import time

from scraper import ONPEScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def run_once(db_path: str = None):
    scraper = ONPEScraper(db_path)
    scraper.run()


def main():
    parser = argparse.ArgumentParser(description="Scraper ONPE Elecciones 2026")
    parser.add_argument("--db", default=None, help="Ruta de la base de datos SQLite")
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        metavar="MINUTOS",
        help="Si se especifica, repite el scraping cada N minutos",
    )
    args = parser.parse_args()

    if args.loop > 0:
        log.info("Modo loop: scraping cada %d minutos. Ctrl+C para detener.", args.loop)
        while True:
            try:
                run_once(args.db)
            except Exception as exc:
                log.error("Error en scraping: %s", exc)
            log.info("Próxima ejecución en %d minutos...", args.loop)
            time.sleep(args.loop * 60)
    else:
        run_once(args.db)


if __name__ == "__main__":
    main()
