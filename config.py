
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3-flash-preview')

DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'scienceluxe_1')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', '12345')
DB_PORT = os.environ.get('DB_PORT', '5432')

# Supabase (y en general Postgres administrado) suele requerir SSL.
_default_sslmode = 'require' if 'supabase.com' in (DB_HOST or '') else 'prefer'
DB_SSLMODE = os.environ.get('DB_SSLMODE', _default_sslmode)

# Opcional: usar un schema dedicado ("otra BD" a efectos prácticos) para aislar tablas y migraciones.
DB_SCHEMA = os.environ.get('DB_SCHEMA', '').strip() or 'public'


def _append_sslmode(url: str, sslmode: str) -> str:
    if not sslmode:
        return url
    if 'sslmode=' in url:
        return url
    sep = '&' if '?' in url else '?'
    return f"{url}{sep}sslmode={sslmode}"

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    f"postgresql+psycopg2://{DB_USER}:{quote_plus(DB_PASS)}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)
DATABASE_URL = _append_sslmode(DATABASE_URL, DB_SSLMODE)

# Clip Library — central storage for reusable video/image clips (Google Drive Desktop mount)
CLIPS_LIBRARY_DIR = os.environ.get('CLIPS_LIBRARY_DIR', r'H:\Mi unidad\Scienceluxe_clips')

# Project Thumbnails — local D drive storage for uploaded YouTube thumbnail images
THUMBNAILS_DIR = os.environ.get('THUMBNAILS_DIR', r'D:\scienceluxe_2026\thumbnails')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    CLIPS_LIBRARY_DIR = CLIPS_LIBRARY_DIR
    THUMBNAILS_DIR = THUMBNAILS_DIR
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    DB_SCHEMA = DB_SCHEMA
    # Forzar search_path para que las tablas vivan en un schema separado.
    # (Evita colisiones con otras apps/tablas en 'public' en Supabase.)
    if DB_SCHEMA and DB_SCHEMA != 'public':
        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {
                'options': f"-csearch_path={DB_SCHEMA}",
            }
        }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GEMINI_API_KEY = GEMINI_API_KEY
    GEMINI_MODEL = GEMINI_MODEL
