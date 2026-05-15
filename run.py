
import os
from ensure_postgres import ensure_postgres_running
from aplicacion import create_app

# Solo se ejecuta en el proceso padre del reloader de Werkzeug,
# para evitar un doble intento de arranque con debug=True.
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    ensure_postgres_running()

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True)
