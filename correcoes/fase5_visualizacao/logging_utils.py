import logging
import sys
import inspect
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / 'arquivosgerados' / 'LOGS'

FORMATO_PADRAO = '%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s'
FORMATO_DATA = '%Y-%m-%d %H:%M:%S'

def get_logger(name=None, log_file="enade_dashboard.log", level=logging.DEBUG):
    if name is None:
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'root')

    logger = logging.getLogger(name)

    # Se já tem handler configurado, não adiciona de novo (evita duplicação em reruns do Streamlit)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(FORMATO_PADRAO, datefmt=FORMATO_DATA)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_DIR / log_file, encoding='utf-8', mode='a')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger
