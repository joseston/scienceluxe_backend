# Incidencia: sincronizacion selectiva de Clip Library con rclone

Fecha: 2026-05-16  
Proyecto: `Scienceluxe`  
Componentes: `backend`, `Clip Library`, `Proceso 4`, `rclone`, `Google Drive`

## Resumen

Despues de migrar el backend a Linux y reescribir las rutas persistidas de Windows a Linux, la `Clip Library` quedo conectada a la ruta correcta:

- `/home/jose/GoogleDrive/Scienceluxe_clips`

Sin embargo, el contenido local seguia incompleto y el sistema no debia intentar sincronizar todo Google Drive, porque eso seria demasiado costoso en tiempo y almacenamiento.

La solucion aplicada fue convertir la biblioteca en una cache local selectiva:

- si un clip ya existe localmente, se usa directo
- si un clip falta localmente, se descarga bajo demanda con `rclone`
- cuando se sube un clip nuevo, se guarda localmente y se sube al remoto en segundo plano
- cuando se generan `thumbnails` o `proxies`, tambien se suben al remoto en segundo plano

## Problema original

El flujo anterior tenia dos limitaciones importantes:

### 1. Biblioteca activa pero incompleta

La BD ya conocia cientos de clips historicos, pero muchos archivos no existian todavia en disco local.

Eso producia un estado parcial:

- la UI podia listar clips o asignaciones historicas
- pero al abrirlos, previsualizarlos o reutilizarlos, el backend podia responder `file not found`

### 2. Google Drive no debia sincronizarse completo

El caso de uso real no necesitaba traer todo el Drive.

Solo hacia falta:

- acceder a clips concretos cuando una escena o la UI los pidiera
- mantener en remoto los clips nuevos que se vayan creando o subiendo

Montar o sincronizar toda la cuenta era innecesario para este escenario.

## Objetivo

Implementar una sincronizacion puntual y persistente solo para la `Clip Library`, con estas reglas:

- descargar solo el archivo faltante cuando haga falta
- no volver a descargarlo si ya esta cacheado localmente
- subir al remoto los nuevos archivos creados localmente
- mantener la logica transparente para `Proceso 4`, previews, renders y endpoints de la biblioteca

## Solucion aplicada

### 1. Configuracion por variables de entorno

Se agregaron al backend:

- `RCLONE_BIN`
- `CLIPS_LIBRARY_RCLONE_REMOTE`

Valores usados:

- `RCLONE_BIN=/usr/bin/rclone`
- `CLIPS_LIBRARY_RCLONE_REMOTE=nuevo remoto:Scienceluxe_clips`

### 2. Resolucion local-remoto por ruta relativa

Se implemento una traduccion estable:

- local: `/home/jose/GoogleDrive/Scienceluxe_clips/originals/...`
- remoto: `nuevo remoto:Scienceluxe_clips/originals/...`

La clave es que el backend ya no piensa en el remoto como un mount completo, sino como un origen/destino de archivos individuales.

### 3. Descarga bajo demanda

Se agrego el helper:

- `ensure_clip_library_file_local(path)`

Comportamiento:

- si el archivo existe localmente, retorna `True`
- si no existe, calcula la ruta remota equivalente
- ejecuta `rclone copyto remoto local`
- usa locks por ruta para que dos requests no intenten bajar el mismo archivo al mismo tiempo

### 4. Subida asincrona

Se agrego el helper:

- `_sync_clip_library_file_async(path, app, reason=...)`

Comportamiento:

- si el archivo local existe, se lanza un thread daemon
- el thread hace `rclone copyto local remoto`
- no bloquea la respuesta HTTP del usuario

### 5. Integracion en uploads de Clip Library

Cuando un clip entra por:

- `POST /api/clip-library/clips`

el backend ahora:

1. guarda localmente el original en `Scienceluxe_clips/originals/...`
2. crea el registro en BD
3. dispara subida asincrona del original al remoto
4. genera `thumbnail` y `proxy` en segundo plano
5. sube tambien esos derivados al remoto cuando se crean

### 6. Integracion en uploads desde escena

Cuando un clip entra por:

- `POST /api/proceso4/jobs/<pid>/scenes/<scene_num>/media`

el backend ahora:

1. guarda el original en la `Clip Library`
2. crea o reutiliza el `ClipLibraryItem`
3. dispara subida asincrona del original al remoto
4. genera derivados en segundo plano
5. reaprovecha esa misma ruta en el `SceneMedia`

### 7. Integracion en lectura de archivos

Se integraron fetches bajo demanda en:

- `GET /api/clip-library/clips/<id>/file`
- `GET /api/clip-library/clips/<id>/proxy`
- `GET /api/clip-library/clips/<id>/thumbnail`
- `POST /api/clip-library/clips/<id>/use-in-scene`

Eso hace que la biblioteca pueda “revivir” un clip faltante localmente justo cuando alguien lo pide.

### 8. Integracion en Proceso 4

Se agregaron helpers de puente para `SceneMedia`:

- `ensure_scene_media_local_file(clip)`
- `ensure_scene_media_proxy_local_file(clip)`

Y se integraron en:

- `routes/media.py`
- `routes/preview.py`
- `routes/render.py`
- `render_ffmpeg.py`

Efecto practico:

- si un `SceneMedia` apunta a un clip de biblioteca que falta localmente, el backend intenta traerlo antes de servirlo, previsualizarlo, generar proxies o renderizar

## Validacion realizada

### 1. Compilacion Python

Se ejecuto `py_compile` sobre:

- `config.py`
- `aplicacion/endpoints/clip_library/__init__.py`
- `aplicacion/endpoints/proceso4/helpers.py`
- `aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `aplicacion/endpoints/proceso4/routes/media.py`
- `aplicacion/endpoints/proceso4/routes/preview.py`
- `aplicacion/endpoints/proceso4/routes/render.py`

Resultado:

- sin errores de sintaxis

### 2. Validacion de configuracion del remoto

Se verifico que el backend levantara con:

- `CLIPS_LIBRARY_RCLONE_REMOTE = nuevo remoto:Scienceluxe_clips`

Tambien se comprobo que una ruta local de ejemplo se traduzca correctamente a remoto:

- local: `/home/jose/GoogleDrive/Scienceluxe_clips/originals/ab/test.mp4`
- remoto: `nuevo remoto:Scienceluxe_clips/originals/ab/test.mp4`

### 3. Validacion de conectividad rclone

Se verifico conectividad con:

```bash
timeout 8s rclone lsf "nuevo remoto:Scienceluxe_clips" --max-depth 1
timeout 8s rclone about "nuevo remoto:"
```

Resultado observado:

- el remoto responde
- la carpeta remota expone:
  - `_tmp/`
  - `originals/`
  - `proxies/`
  - `thumbnails/`

## Estado final

La `Clip Library` ahora funciona como cache selectiva persistente.

Eso significa:

- no se baja todo Google Drive
- solo se baja lo que se usa
- lo ya descargado queda reutilizable localmente
- los clips nuevos y sus derivados se empujan al remoto

En terminos practicos:

- la biblioteca deja de depender exclusivamente de una sincronizacion manual previa
- el sistema puede auto-recuperar clips faltantes cuando una escena los necesita

## Limites actuales

### 1. No se hizo smoke test de extremo a extremo con una escena real faltante

La implementacion quedo conectada y validada a nivel tecnico, pero no se ejecuto todavia una prueba completa de:

- abrir escena
- detectar clip faltante
- descargarlo
- previsualizarlo o renderizarlo exitosamente

### 2. Solo cubre la Clip Library

Esta incidencia no resuelve por si sola:

- media historica de `data/proceso4/.../media`
- media historica de `data/proceso4_corto/.../media`
- assets globales como `indice_image`

Ese contenido sigue requiriendo restauracion fisica si no esta en la biblioteca.

### 3. Fallos remotos siguen siendo posibles

Si `rclone` no puede autenticar, no hay red, o el remoto no contiene el archivo esperado:

- el backend seguira sin poder abrir ese clip

La mejora aqui es que ahora lo intenta automaticamente antes de fallar.

## Siguiente paso recomendado

Hacer un smoke test real con un clip historico faltante:

1. elegir una escena que apunte a un clip de biblioteca no presente localmente
2. abrir preview o servir el clip
3. confirmar en logs que se ejecute `rclone copyto`
4. validar que el archivo quede en `/home/jose/GoogleDrive/Scienceluxe_clips/...`
5. reintentar y confirmar que la segunda vez ya no descargue nada

## Archivos tocados

- `config.py`
- `.env`
- `aplicacion/endpoints/clip_library/__init__.py`
- `aplicacion/endpoints/proceso4/helpers.py`
- `aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `aplicacion/endpoints/proceso4/routes/media.py`
- `aplicacion/endpoints/proceso4/routes/preview.py`
- `aplicacion/endpoints/proceso4/routes/render.py`
