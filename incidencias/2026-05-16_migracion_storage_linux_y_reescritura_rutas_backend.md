# Incidencia: migracion de storage a Linux y reescritura de rutas persistidas

Fecha: 2026-05-16  
Proyecto: `Scienceluxe`  
Componentes: `backend`, `PostgreSQL`, `storage`, `Proceso 0`, `Proceso 2`, `Proceso 2 corto`, `Proceso 4`, `Clip Library`

## Resumen

El backend ya estaba corriendo sobre Linux y la base de datos PostgreSQL estaba activa, pero gran parte del storage seguia referenciado con rutas absolutas del entorno Windows anterior.

Eso dejaba al sistema en un estado mixto:

- la app arrancaba
- la BD respondia
- parte de la configuracion ya apuntaba a Linux
- pero muchas rutas persistidas seguian en `C:\...`, `D:\...` y `H:\...`

El trabajo de esta incidencia fue:

1. quitar hardcodes de rutas Windows en el codigo fuente
2. alinear el `.env` del backend con rutas Linux reales
3. restaurar el backup `scienceluxe_2026.zip`
4. reescribir las rutas persistidas en la BD
5. medir con un verificador que partes quedaron resueltas y que media sigue faltando

## Sintomas

- `Proceso 2` y `Proceso 2 corto` guardaban y buscaban archivos bajo `D:/scienceluxe_2026` aun estando en Linux.
- `Proceso 4` tenia referencias persistidas a media antigua de Windows.
- la biblioteca de clips (`clip_library_items`) apuntaba a rutas `H:\Mi unidad\Scienceluxe_clips\...`
- los thumbnails de proyecto estaban configurados hacia una carpeta incorrecta
- render, preview y carga de media podian fallar aun con la BD activa porque los archivos no existian en las rutas persistidas

## Causa raiz

### 1. Hardcodes de Windows en codigo

Se detectaron hardcodes funcionales en:

- `config.py`
- `aplicacion/endpoints/proceso2/__init__.py`
- `aplicacion/endpoints/proceso2_corto/__init__.py`
- `aplicacion/endpoints/proceso4/constants.py`
- `aplicacion/endpoints/proceso0/__init__.py`
- `aplicacion/endpoints/proceso4/routes/media.py`
- `aplicacion/endpoints/clip_library/__init__.py`

Los casos mas importantes eran:

- `STORAGE_ROOT = Path("D:/scienceluxe_2026")`
- `PISTAS_DIR = Path(r'D:\scienceluxe_2026\pistas')`
- defaults a `H:\Mi unidad\Scienceluxe_clips`
- defaults a `D:\scienceluxe_2026\thumbnails`

En Linux, eso genero comportamiento inconsistente e incluso la aparicion de una carpeta accidental:

- `backend/D:`

### 2. Base de datos migrada pero con rutas historicas

La BD ya estaba poblada, pero seguia guardando rutas del sistema anterior en tablas clave:

- `proceso4_scene_media`
- `clip_library_items`
- `proceso4_section_tracks`
- `proceso4_global_assets`
- `proceso2_subprocess_states`
- `proceso4_corto_scene_media`
- `proceso2_corto_subprocess_states`

### 3. Backup parcial del storage

El archivo `~/scienceluxe_2026.zip` si contenia:

- `job_*`
- `corto_*`
- `pistas`
- `sfx`
- `thumbnails`

Pero no contenia:

- la mayor parte de `data/proceso4/.../media`
- `data/proceso4_corto/.../media`
- la biblioteca completa `Scienceluxe_clips`
- el asset global `indice_image`

## Estado encontrado antes del arreglo

Verificacion inicial sobre la BD:

- `proceso4_scene_media`: `520` registros, `0` validos con la ruta persistida original
- `clip_library_items`: `418` registros, `0` validos con la ruta persistida original
- `proceso4_section_tracks`: `36` rutas a `D:\scienceluxe_2026\pistas\...`
- `proceso2 concat finalMp3`: `7` rutas a `D:\scienceluxe_2026\job_...\output\final.mp3`
- `proceso4_corto_scene_media`: `22` rutas a `C:\...`

Patrones de rutas detectados:

- `H:\Mi unidad\Scienceluxe_clips\...`
- `D:\scienceluxe_2026\...`
- `C:\Users\JOSE\Escritorio\Scienceluxe\Aplicacion Scienceluxe Videos Largos\data\...`

## Solucion aplicada

### 1. Configuracion Linux por variables de entorno

Se normalizo el backend para que use rutas configurables y no hardcodes de Windows.

Valores finales configurados:

- `STORAGE_ROOT=/home/jose/scienceluxe_2026`
- `CLIPS_LIBRARY_DIR=/home/jose/GoogleDrive/Scienceluxe_clips`
- `THUMBNAILS_DIR=/home/jose/scienceluxe_2026/thumbnails`
- `PISTAS_DIR=/home/jose/scienceluxe_2026/pistas`

### 2. Ajuste de codigo fuente

Se actualizaron:

- `config.py`
- `aplicacion/endpoints/proceso0/__init__.py`
- `aplicacion/endpoints/proceso2/__init__.py`
- `aplicacion/endpoints/proceso2_corto/__init__.py`
- `aplicacion/endpoints/proceso4/constants.py`
- `aplicacion/endpoints/proceso4/routes/media.py`
- `aplicacion/endpoints/clip_library/__init__.py`
- `.env`

Objetivos del cambio:

- usar `env` para storage compartido
- corregir el destino de thumbnails de proyecto
- hacer que `Proceso 2` y `Proceso 2 corto` apunten a Linux real
- hacer que `Clip Library` y `Pistas` usen roots configurables

### 3. Herramientas operativas agregadas

Se agregaron dos scripts:

- `verify_storage_paths.py`
- `migrate_storage_paths.py`

Funciones:

- auditar cuantas rutas persistidas resuelven a archivos reales
- mapear rutas Windows historicas hacia Linux
- ejecutar migracion con `dry-run`
- crear backup JSON antes de aplicar cambios reales

### 4. Restauracion del backup zip

Se extrajo:

- `/home/jose/scienceluxe_2026.zip`

hacia:

- `/home/jose/scienceluxe_2026`

Contenido restaurado:

- jobs largos de audio
- jobs cortos de audio
- `pistas`
- `sfx`
- `thumbnails`

### 5. Migracion de rutas en la BD

Se aplico la reescritura de rutas persistidas con estas reglas:

- `H:\Mi unidad\Scienceluxe_clips\...` -> `/home/jose/GoogleDrive/Scienceluxe_clips/...`
- `D:\scienceluxe_2026\...` -> `/home/jose/scienceluxe_2026/...`
- `C:\Users\JOSE\Escritorio\Scienceluxe\Aplicacion Scienceluxe Videos Largos\data\...` -> `/home/jose/Proyectos/scienceluxe/data/...`

Ejecucion real:

- `python migrate_storage_paths.py --apply`

Resultado:

- `1806` cambios aplicados

Backup generado:

- `data/migration_backups/storage_paths_20260516_112825/`

Archivos de respaldo:

- `clip_library_items.json`
- `proceso2_corto_subprocess_states.json`
- `proceso2_subprocess_states.json`
- `proceso4_audio_tracks.json`
- `proceso4_corto_audio_tracks.json`
- `proceso4_corto_scene_media.json`
- `proceso4_global_assets.json`
- `proceso4_scene_media.json`
- `proceso4_section_tracks.json`

## Verificacion realizada

### 1. Validacion sintactica

Se ejecuto:

```bash
python -m py_compile config.py \
  aplicacion/endpoints/proceso0/__init__.py \
  aplicacion/endpoints/proceso2/__init__.py \
  aplicacion/endpoints/proceso2_corto/__init__.py \
  aplicacion/endpoints/proceso4/constants.py \
  aplicacion/endpoints/proceso4/routes/media.py \
  aplicacion/endpoints/clip_library/__init__.py \
  verify_storage_paths.py \
  migrate_storage_paths.py
```

Resultado:

- sin errores de compilacion

### 2. Validacion de migracion en seco

Se ejecuto:

```bash
python migrate_storage_paths.py
```

Resultado:

- `1806` cambios potenciales detectados antes de aplicar

### 3. Validacion de BD despues del apply

Se verifico que ya no queden rutas Windows persistidas.

Resultado:

- `p4_scene_media_windows = 0`
- `clip_library_windows = 0`
- `section_tracks_windows = 0`
- `global_assets_windows = 0`
- `p2_concat_windows = 0`
- `p4c_scene_media_windows = 0`
- `p2c_windows = 0`

### 4. Validacion de existencia fisica despues de extraer el zip

Se obtuvo:

- `proceso4_section_tracks.pista_path`: `36/36` resueltos
- `proceso2_subprocess_states.output.finalMp3`: `7/7` resueltos
- `proceso2_corto_subprocess_states.output audio`: `3/3` resueltos

Persisten faltantes en media visual:

- `proceso4_scene_media.file_path`: `39/520` resueltos, `481` faltantes
- `proceso4_scene_media.proxy_path`: `40/452` resueltos, `412` faltantes
- `clip_library_items.file_path`: `36/418` resueltos, `382` faltantes
- `clip_library_items.thumbnail_path`: `38/321` resueltos, `283` faltantes
- `proceso4_corto_scene_media.file_path`: `0/22` resueltos, `22` faltantes
- `proceso4_corto_scene_media.proxy_path`: `0/22` resueltos, `22` faltantes
- `proceso4_global_assets.file_path`: `0/1` resueltos, `1` faltante

## Estado final despues de esta incidencia

Lo que quedo bien:

- el backend ya usa roots Linux coherentes
- la BD ya no contiene rutas Windows
- `Proceso 2` largo ya puede encontrar sus `final.mp3`
- `Proceso 2 corto` ya puede encontrar sus audios procesados
- `Proceso 4` ya puede resolver las `pistas`
- los thumbnails de proyecto ya apuntan a la carpeta correcta restaurada desde el zip

Lo que todavia no esta completo:

- falta la mayor parte de la media visual de `Proceso 4`
- falta toda la media persistida de `Proceso 4 corto`
- falta gran parte de la `Clip Library`
- falta el asset global `indice_image`

## Riesgos y limites actuales

- los endpoints que dependan solo de audio, estados o pistas deberian comportarse mejor
- `preview` y `render` de `Proceso 4` pueden fallar o quedar incompletos cuando una escena apunte a media no restaurada
- la biblioteca de clips mostrara referencias validas en BD pero muchos archivos fisicos aun no existen
- `Proceso 4 corto` seguira roto en escenas con media faltante

## Siguiente paso recomendado

Recuperar desde el OS anterior o desde otro backup estas carpetas:

- `data/proceso4`
- `data/proceso4_corto`
- `Scienceluxe_clips` completa
- asset global `indice_image`

Despues de restaurar esas carpetas:

1. volver a ejecutar `python verify_storage_paths.py`
2. abrir el backend y hacer smoke tests por proyecto
3. probar `preview` y `render` de `Proceso 4`

## Archivos tocados

- `config.py`
- `.env`
- `aplicacion/endpoints/proceso0/__init__.py`
- `aplicacion/endpoints/proceso2/__init__.py`
- `aplicacion/endpoints/proceso2_corto/__init__.py`
- `aplicacion/endpoints/proceso4/constants.py`
- `aplicacion/endpoints/proceso4/routes/media.py`
- `aplicacion/endpoints/clip_library/__init__.py`
- `verify_storage_paths.py`
- `migrate_storage_paths.py`

## Nota sobre la biblioteca de clips

La `Clip Library` ahora quedo conceptualmente bien conectada al Linux actual, pero sigue siendo el mayor punto pendiente de recuperacion fisica.

No es un problema de rutas ya:

- el problema principal ahora es ausencia de archivos reales

Mientras no vuelva la carpeta completa `Scienceluxe_clips`, la BD describira clips existentes historicamente, pero el backend no podra servir ni reutilizar muchos de ellos.
