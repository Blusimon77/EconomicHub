"""
Configurazione logging centralizzata.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "storage"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging(level: int = logging.INFO) -> None:
    """Configura il logging con output su file e console."""
    LOG_DIR.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    # Evita duplicati se chiamato più volte
    if not root.handlers:
        root.addHandler(fh)
        root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """Ritorna un logger con il nome specificato."""
    return logging.getLogger(name)
