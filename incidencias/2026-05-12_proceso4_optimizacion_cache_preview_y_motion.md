# Incidencia: optimizacion de preview y cache de motion en Proceso 4

Fecha: 2026-05-12  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`

## Resumen

Despues del refactor del motion subpixel en `Proceso 4`, el sistema seguia teniendo dos cuellos de botella claros:

- los previews de escena podian renderizarse varias veces en paralelo para la misma escena
- el motion de imagen con Pillow se recalculaba desde cero aunque ya existiera un resultado identico

Eso no solo hacia mas lento el flujo, sino que en Windows podia provocar errores por archivos temporales en uso.

## Sintomas

- Algunas escenas tardaban demasiado en generar preview aunque ya se hubieran visto antes.
- El frontend podia disparar varias peticiones simultaneas a la misma ruta de preview.
- En logs aparecian varias lineas seguidas como:

```text
[P4] Rendering scene preview job=28 scene=1 clips=3 effectiveDur=12.840s
```

- Tambien aparecian errores como:

```text
PermissionError: [WinError 32] El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso
```

afectando archivos como:

- `scene_1_fadein.mp4`
- `scene_1.mp4`

## Causas raiz

### 1. Preview sin coordinacion por escena

La ruta:

- `GET /api/proceso4/jobs/<pid>/scenes/<scene_num>/preview`

podia entrar varias veces al mismo tiempo para el mismo `job` y la misma escena.

Cada request intentaba:

- borrar el `work_dir`
- regenerar el clip
- aplicar fade-in
- mover el mismo archivo temporal

En Windows eso terminaba chocando con locks del sistema de archivos.

### 2. Motion de imagen sin cache reutilizable

El renderer subpixel con Pillow generaba cada frame otra vez aunque:

- fuera la misma imagen
- con la misma duracion
- el mismo preset
- la misma intensidad
- el mismo rango de progreso

Eso era costoso especialmente en:

- renders repetidos
- previews
- escenas `indice`
- reintentos despues de refrescar UI

## Solucion aplicada

### 1. Lock por escena en preview

Se agrego coordinacion en:

- `software_backend/aplicacion/endpoints/proceso4/routes/preview.py`

Ahora existe un lock por clave:

- `(job_id, scene_num)`

Con esto:

- solo una request renderiza una escena a la vez
- las demas esperan
- al salir del lock se vuelve a revisar cache antes de renderizar

Eso evita condiciones de carrera sobre los archivos temporales del preview.

### 2. Cache de motion de imagen

Se agrego cache para el resultado del motion de imagen en:

- `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`

La firma de cache incluye:

- ruta de la imagen
- `mtime`
- tamaño del archivo
- duracion
- preset
- intensidad
- `progress_start`
- `progress_end`
- `fps`
- resolucion de salida

Si la firma coincide:

- no se vuelven a generar frames con Pillow
- se reutiliza el MP4 cacheado

### 3. Carpeta de salida garantizada

Tambien se reforzo `_render_image_motion_clip(...)` para asegurar que el directorio de salida exista antes de invocar FFmpeg.

Eso evita fallos tontos cuando un caller futuro use una ruta nueva.

## Resultado

Despues del ajuste:

- los previews repetidos de una misma escena ya no deberian competir entre si
- desaparece el choque por `WinError 32` en el caso cubierto
- el motion de imagen puede reutilizarse sin recalcular cientos de frames
- el backend conserva la misma salida visual, pero con menos trabajo redundante

## Verificacion realizada

Backend:

- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/preview.py`

Smoke test:

- se genero un clip de motion de imagen
- se repitio la misma generacion
- la segunda llamada reutilizo el cache
- quedo `1` archivo cacheado para esa firma

Prueba funcional:

- `GET /api/proceso4/jobs/28/scenes/1/preview`
- respuesta `200`

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/preview.py`

## Nota operativa

Esta optimizacion no convierte el pipeline completo a GPU.

Lo que hace es recortar trabajo repetido en los puntos donde el backend estaba perdiendo mas tiempo de forma innecesaria.
