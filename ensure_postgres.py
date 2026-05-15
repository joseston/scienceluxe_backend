"""
ensure_postgres.py
------------------
Garantiza que el servidor PostgreSQL esté accesible ANTES de que
Flask intente conectarse. Se llama desde run.py al inicio.

Comportamiento:
  1. Lee DB_PORT desde el .env (por defecto 5432, el servicio del sistema).
  2. Usa pg_isready (o un socket TCP) para comprobar conectividad.
  3. Si el puerto es 5433 (instancia embebida), intenta arrancarla con pg_ctl.
  4. Si el puerto es 5432 (servicio del sistema), solo verifica que responda.
  5. Si no hay conexión tras MAX_WAIT segundos, termina con error claro.

Variables de entorno opcionales:
  PG_BIN   → directorio de binarios de PostgreSQL (default: C:\\Program Files\\PostgreSQL\\16\\bin)
  PG_PORT  → se lee del .env del backend automáticamente
"""

import os
import sys
import subprocess
import time

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))           # software_backend/
_ROOT = os.path.dirname(_HERE)                                # raíz del workspace

# Leer puerto del .env del backend
def _read_port_from_env() -> str:
    env_path = os.path.join(_HERE, ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DB_PORT="):
                    return line.split("=", 1)[1].strip()
    return "5432"

PG_BIN = os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\16\bin")
PG_PORT = os.environ.get("PG_PORT", _read_port_from_env())
PG_DATA = os.path.join(_ROOT, "data", "postgres")
PG_LOG = os.path.join(PG_DATA, "server.log")

PG_ISREADY = os.path.join(PG_BIN, "pg_isready.exe")
PG_CTL = os.path.join(PG_BIN, "pg_ctl.exe")

# Solo intentar auto-arranque para la instancia embebida (puerto 5433)
EMBEDDED_PORT = "5433"

MAX_WAIT = 15      # segundos máximo esperando a que PG arranque
RETRY_INTERVAL = 1 # segundos entre reintentos de pg_isready


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_pg_ready() -> bool:
    """Devuelve True si PostgreSQL ya acepta conexiones en el puerto configurado."""
    try:
        result = subprocess.run(
            [PG_ISREADY, "-h", "localhost", "-p", PG_PORT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except FileNotFoundError:
        # pg_isready no está en PG_BIN — intentar con socket TCP directamente
        import socket
        try:
            with socket.create_connection(("localhost", int(PG_PORT)), timeout=3):
                return True
        except OSError:
            return False
    except Exception:
        return False


def _start_pg() -> None:
    """Lanza pg_ctl start. No espera a que PG esté listo."""
    if not os.path.isfile(PG_CTL):
        print(
            f"\n[ensure_postgres] ERROR: pg_ctl no encontrado en '{PG_CTL}'.\n"
            f"  Ajusta la variable de entorno PG_BIN con la ruta correcta.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isdir(PG_DATA):
        print(
            f"\n[ensure_postgres] ERROR: directorio de datos no existe: '{PG_DATA}'.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[ensure_postgres] PostgreSQL no estaba corriendo. Iniciando en puerto {PG_PORT}...")
    subprocess.run(
        [PG_CTL, "-D", PG_DATA, "-l", PG_LOG, "-o", f" -p {PG_PORT}", "start"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def ensure_postgres_running() -> None:
    """
    Verifica que PostgreSQL esté accesible; si es la instancia embebida (5433)
    y no está corriendo, la inicia automáticamente.
    Para el servicio del sistema (5432), solo verifica conectividad.
    """
    if _is_pg_ready():
        print(f"[ensure_postgres] PostgreSQL accesible en puerto {PG_PORT}. OK.")
        return

    # Solo intentar auto-arranque si usamos la instancia embebida
    if PG_PORT == EMBEDDED_PORT:
        _start_pg()

        # Esperar a que PG esté listo
        deadline = time.time() + MAX_WAIT
        while time.time() < deadline:
            time.sleep(RETRY_INTERVAL)
            if _is_pg_ready():
                print(f"[ensure_postgres] PostgreSQL embebido listo en puerto {PG_PORT}. OK.")
                return

        print(
            f"\n[ensure_postgres] ERROR: PostgreSQL embebido no respondió en {MAX_WAIT} segundos.\n"
            f"  Revisa el log en: {PG_LOG}\n"
            f"  O inícialo manualmente: .\\workspace_aux\\scripts\\start_local_postgres.ps1\n",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Servicio del sistema — esperar un poco por si está arrancando
        deadline = time.time() + MAX_WAIT
        while time.time() < deadline:
            time.sleep(RETRY_INTERVAL)
            if _is_pg_ready():
                print(f"[ensure_postgres] PostgreSQL (servicio del sistema) listo en puerto {PG_PORT}. OK.")
                return

        print(
            f"\n[ensure_postgres] ERROR: PostgreSQL no responde en puerto {PG_PORT}.\n"
            f"  Verifica que el servicio 'postgresql-x64-16' esté corriendo:\n"
            f"    Get-Service postgresql-x64-16\n"
            f"    Start-Service postgresql-x64-16\n",
            file=sys.stderr,
        )
        sys.exit(1)
