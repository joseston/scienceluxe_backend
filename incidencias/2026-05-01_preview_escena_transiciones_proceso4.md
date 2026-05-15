# Incidencia: preview de escena con transiciones en Proceso 4

Fecha: 2026-05-01  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`, `clip_library`

## Resumen

En `Proceso 4`, el boton `Preview Escena con Transiciones` no estaba mostrando la escena compuesta correctamente.

Se detectaron tres fallas relacionadas:

- el frontend llamaba a `/api/proceso4/jobs/:pid/scenes/:scene_num/preview`, pero esa ruta no existia y devolvia `404`
- al exponer el preview de escena, la composicion con `xfade` podia fallar en FFmpeg con `Invalid argument`
- las sugerencias de clips de biblioteca podian romperse con `500` cuando la base de datos no tenia las columnas `embedding` y `search_text`

## Sintomas

- El preview de escena mostraba solo un clip individual en vez de la escena completa.
- Los logs mostraban `GET /api/proceso4/jobs/28/scenes/1/preview 404`.
- Luego del primer fix, el preview podia salir con tramos negros porque `xfade` producia un clip demasiado corto y el sistema lo rellenaba hasta la duracion objetivo.
- En algunos intentos los logs mostraban:

`[P4] S1 xfade multi FFmpeg failed ... Invalid argument`

- Las sugerencias de biblioteca fallaban con:

`psycopg2.errors.UndefinedColumn: no existe la columna «embedding»`

y despues tambien con falta de `search_text`.

## Causas raiz

### 1. Ruta de preview inexistente

El frontend ya tenia el boton y el `fetch`, pero el backend no tenia implementado el endpoint `GET /jobs/<pid>/scenes/<scene_num>/preview`.

Por eso el visor caia al modo normal del editor, que por diseno muestra `activePreview`, es decir, un solo clip.

### 2. Falla en la cadena `xfade`

Al generar el preview multi-clip, FFmpeg rechazaba la cadena `xfade` porque las entradas intermedias no llegaban con frame rate constante.

El error observado fue:

`The inputs needs to be a constant frame rate; current rate of 1/0 is invalid`

Cuando eso pasaba, FFmpeg no escribia salida y el backend hacia fallback a concatenacion simple.

### 3. Esquema incompleto de Clip Library

En este entorno PostgreSQL existia la extension `vector`, pero la tabla `clip_library_items` no tenia las columnas:

- `embedding`
- `search_text`

El codigo asumia que esas columnas existian si `pgvector` estaba disponible, y por eso intentaba consultas que terminaban en `500`.

## Solucion aplicada

### 1. Preview real de escena en backend

Se agrego en `software_backend/aplicacion/endpoints/proceso4/__init__.py` la ruta:

- `GET /api/proceso4/jobs/<pid>/scenes/<scene_num>/preview`

Esta ruta:

- carga la escena desde el timeline importado
- calcula `effectiveDuration`
- reutiliza los mismos helpers del render final
- construye un MP4 temporal de la escena completa
- devuelve el archivo al frontend

### 2. Composicion multi-clip con mejor manejo de `xfade`

Se ajusto la logica de `_build_multi_clip` y `_build_multi_clip_xfade` para:

- usar `xfade` solo cuando realmente hay una transicion no `cut`
- normalizar transiciones antiguas con duracion `0.0` a `0.5s` cuando el tipo es `dissolve` u otra transicion valida
- validar que la salida de `xfade` no quede absurdamente corta antes de aceptarla
- corregir la cadena de filtros para normalizar timestamps y `fps=30` tanto en las entradas como en los resultados intermedios antes del siguiente `xfade`

Con esto, el preview de la escena 1 de `job=28` paso de fallar a renderizar correctamente con `xfade`.

### 3. Fallback robusto en Clip Library

Se actualizo `software_backend/aplicacion/endpoints/clip_library/__init__.py` para:

- verificar si existe la columna `embedding` antes de usar busqueda semantica
- verificar si existe la columna `search_text` antes de usar full-text search
- hacer fallback a busqueda simple por `ILIKE` sobre descripcion y nombre de archivo si faltan esas columnas
- evitar `500` tambien cuando falla la importacion del servicio de embeddings

### 4. Ajuste de frontend para el boton de preview

Se mantuvo el mismo boton del editor de escena en `software_website/src/app/proceso4/components/SceneEditor.tsx`, pero ahora:

- usa el endpoint real del backend
- evita cache HTTP viejo al pedir el preview
- puede reutilizar el preview ya generado mientras la escena no haya cambiado

### 5. Monitor de Timeline visual con preview compuesto

Se detecto despues que el `Monitor de Previsualizacion` del `Timeline visual` seguia usando proxies individuales:

- `/api/proceso4/jobs/:pid/media-file/:media_id/proxy`

Ese monitor calculaba el clip activo en frontend y saltaba entre clips, por lo que no podia mostrar `xfade` ni overlaps reales aunque las transiciones estuvieran guardadas.

Se actualizo `software_website/src/app/proceso4/components/TimelineOverview.tsx` para:

- detectar si la escena activa tiene transiciones no `cut`
- pedir el preview compuesto de esa escena cuando corresponde
- reproducir el MP4 compuesto sincronizado con el tiempo de la narracion
- mantener proxies individuales para escenas sin transiciones
- cachear en memoria el blob del preview compuesto por firma de escena
- evitar duplicar overlays de fade/indice/pregunta cuando se usa un MP4 ya compuesto

Tambien se agrego cache persistente en backend para `GET /scenes/<scene_num>/preview`, usando una firma basada en timeline, clips, trims, velocidad, transiciones, overlays y `mtime` de los archivos. Si nada cambio, el backend sirve el MP4 existente en vez de renderizar otra vez.

## Resultado

Despues del ajuste:

- el preview de escena ya no depende de un endpoint inexistente
- la escena completa puede renderizarse con transiciones desde el mismo boton del editor
- `xfade` deja de fallar en el caso validado de `job=28`, `scene=1`
- las sugerencias de clips dejan de romper la UI aun cuando falten `embedding` y `search_text`
- el monitor del timeline visual usa el preview compuesto para escenas con transiciones y conserva proxies individuales para escenas simples
- llamadas repetidas al endpoint de preview pueden responder con `Scene preview cache hit`

## Verificacion realizada

- Se valido el backend con:
  - `python -m py_compile software_backend/aplicacion/endpoints/proceso4/__init__.py`
  - `python -m py_compile software_backend/aplicacion/endpoints/clip_library/__init__.py`
- Se valido el frontend con `npm run build`
- Se probo `GET /api/proceso4/jobs/28/scenes/1/preview` y respondio `200`
- Se probo dos veces el mismo endpoint y el backend respondio con `Scene preview cache hit`
- Se confirmo por `ffprobe` que el preview generado quedo alrededor de `12.866667s`
- Se probo `POST /api/clip-library/suggest-for-scene` y respondio `200` con fallback `searchType: ilike`

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/__init__.py`
- `software_backend/aplicacion/endpoints/clip_library/__init__.py`
- `software_website/src/app/proceso4/services/proceso4.service.ts`
- `software_website/src/app/proceso4/components/SceneEditor.tsx`

## Nota operativa

Para ver el comportamiento corregido en la aplicacion, conviene reiniciar la instancia activa del backend si seguia corriendo desde antes del fix.
