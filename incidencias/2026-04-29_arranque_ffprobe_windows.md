# Incidencia: error de `ffprobe.exe` al arrancar Scienceluxe

Fecha: 2026-04-29  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`, lanzador de escritorio

## Resumen

Al iniciar la aplicacion con el acceso directo de escritorio, aparecia una ventana de Windows con el error:

`ffprobe.exe - No se encuentra el punto de entrada`

El mensaje indicaba una falla de DLL en `gdk_pixbuf-2.0-0.dll` y afectaba al arranque del backend, aunque el resto de la aplicacion podia seguir funcionando.

## Sintoma

- Al hacer doble clic en `Iniciar Scienceluxe Todo.cmd` aparecia el popup de `ffprobe.exe`.
- El backend de Flask si llegaba a levantarse, pero quedaba expuesto al error al inicializar la deteccion de binarios FFmpeg.
- El error se repetia porque el proceso estaba resolviendo un `ffprobe` defectuoso de otro paquete Conda.
- Tambien aparecia al usar `Aplicar Velocidad y Continuar` en Proceso 2 Corto, porque el calculo de duracion de audio usaba una resolucion distinta de `ffprobe`.

## Causa raiz

La aplicacion tenia varias instalaciones de FFmpeg dentro de Conda:

- `ffmpeg-7.0.2-gpl_h9cf63cc_102`
- `ffmpeg-8.0.1-gpl_hb2d76f6_912`
- el entorno `scienceluxe`

El lanzador original y la deteccion interna del backend terminaban usando o probando primero rutas asociadas a `ffmpeg-8.0.1`, que estaba roto en este equipo. Al invocar `ffprobe.exe` de ese paquete, Windows mostraba el error de entrada faltante en la DLL `gdk_pixbuf-2.0-0.dll`.

## Solucion aplicada

### 1. Lanzador de escritorio

Se ajusto `Start-Scienceluxe.ps1` para:

- detectar Conda de forma mas robusta
- preferir explicitamente el paquete `ffmpeg-7.0.2`
- exportar `FFMPEG_BIN` y `FFPROBE_BIN` antes de arrancar el backend
- evitar que el arranque dependa de la seleccion automatica de un binario defectuoso

### 2. Backend

Se actualizo `software_backend/aplicacion/endpoints/proceso4/__init__.py` para:

- aceptar rutas explicitas via variables de entorno
- ignorar rutas conocidas problematicas de `ffmpeg-8.0.1`
- dejar de probar primero el `ffprobe` roto del entorno `scienceluxe`
- priorizar un binario funcional y conocido

### 3. Procesamiento de audio

Se actualizo `software_backend/aplicacion/endpoints/proceso2/core/audio_processor.py` para:

- dejar de usar `pydub` para detectar duracion, porque internamente buscaba `ffprobe` por `PATH`
- usar `FFPROBE_BIN` o el `ffprobe` estable de `ffmpeg-7.0.2`
- usar `imageio-ffmpeg` para escribir MP3, porque el `ffmpeg-7.0.2` de Conda no trae `libmp3lame` y podia generar archivos MP3 vacios
- ignorar rutas conocidas problematicas aunque lleguen por variables de entorno

## Resultado

Despues del ajuste:

- el backend arranca sin volver a tocar el `ffprobe` roto
- el lanzador usa los binarios de `ffmpeg-7.0.2`
- Proceso 2 Corto puede aplicar velocidad sin disparar el popup de `ffprobe.exe`
- la compilacion del frontend (`npm run build`) pasa correctamente

## Verificacion realizada

- Se comprobo que `ffprobe` y `ffmpeg` resuelven a:
  - `C:\Users\JOSE\miniconda3\pkgs\ffmpeg-7.0.2-gpl_h9cf63cc_102\Library\bin\ffprobe.exe`
  - `C:\Users\JOSE\miniconda3\pkgs\ffmpeg-7.0.2-gpl_h9cf63cc_102\Library\bin\ffmpeg.exe`
- Se valido el backend con `python -m py_compile aplicacion\endpoints\proceso4\__init__.py`
- Se valido `audio_processor.py` con `python -m py_compile aplicacion\endpoints\proceso2\core\audio_processor.py`
- Se probo `speed_up_audio` sobre `D:\scienceluxe_2026\corto_3_101\input\audio.wav`, incluso simulando variables malas de `ffmpeg-8.0.1`
- Se valido el frontend con `npm run build`

## Archivos tocados

- `Start-Scienceluxe.ps1`
- `Iniciar Scienceluxe Todo.cmd`
- `software_backend/aplicacion/endpoints/proceso4/__init__.py`
- `software_backend/aplicacion/endpoints/proceso2/core/audio_processor.py`

## Nota operativa

Si se abrio una ventana antigua del backend antes del fix, esa instancia puede conservar variables de entorno viejas. En ese caso conviene cerrarla por completo y volver a lanzar desde el acceso directo ya actualizado.
