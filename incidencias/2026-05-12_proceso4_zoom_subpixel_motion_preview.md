# Incidencia: movimiento de imagen con micro-jitter y preview bloqueado en Proceso 4

Fecha: 2026-05-12  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

En `Proceso 4` aparecieron dos problemas relacionados:

- el zoom in, zoom out y los desplazamientos de imagen se veian con temblores o `micro-jitter`
- el monitor de previsualizacion del timeline quedaba esperando un `preview compuesto` y el render del preview podia devolver `500`

La causa no estaba en un solo lugar. Habia una combinacion de:

- motion de imagen demasiado dependiente de `zoompan` de FFmpeg
- pipeline distinto entre escenas simples, `indice` y `pregunta capciosa`
- preview del timeline demasiado pesado para dispararse automaticamente en cada cambio
- cache de preview que podia quedarse vieja en frontend

## Sintomas

- Las imagenes con efectos `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, etc. se movian con saltos visibles.
- En bordes de alto contraste, el movimiento parecia vibrar en vez de ser fluido.
- El monitor de timeline mostraba `Renderizando preview compuesto...` y no avanzaba de forma practica.
- El backend llego a responder `500 INTERNAL SERVER ERROR` al pedir el preview de escena en algunos estados del refactor.
- En consola del frontend aparecia:

```text
Error interno al renderizar el preview de la escena.
Could not load composite scene preview
```

## Causa raiz

### 1. Movimiento de imagen basado en FFmpeg `zoompan`

El pipeline original generaba el movimiento de still images con `zoompan` y recortes en 1080p.

Eso dejaba el movimiento expuesto a redondeo de coordenadas y saltos de un pixel, que se notan mucho en zooms lentos.

### 2. Inconsistencia entre rutas de render

No todas las escenas usaban el mismo motor de motion.

Habia rutas que seguian aplicando `zoompan` directo y otras que iban por helpers distintos, asi que el problema no desaparecia en toda la app.

### 3. El timeline intentaba resolver preview compuesto automaticamente

El monitor visual terminaba esperando un render compuesto pesado, incluso cuando la vista podia resolverse mejor con una vista liviana inmediata.

Eso empeoraba la sensacion de bloqueo en UI.

## Solucion aplicada

### 1. Nuevo motor de motion para imagenes en backend

Se refactorizo `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py` para que el motion de imagen no dependiera del `zoompan` clasico de FFmpeg.

Se agrego un renderer de subpixel con Pillow que:

- genera frames RGB directamente
- usa crop flotante con `Image.transform(..., EXTENT, ...)`
- aplica easing con `smoothstep`
- entrega los frames a FFmpeg solo para codificacion final

Con eso se reduce la causa real del temblor, que era el salto por pixel entero.

### 2. Unificacion del motion en escenas especiales

Tambien se ajustaron las escenas que usaban overlays especiales para que no se saltaran el motor nuevo:

- `indice`
- `pregunta capciosa`

En esas rutas:

- el fondo animado se genera con el mismo motor subpixel
- despues se aplica solo el texto con `drawtext`
- se evita volver a meter otro `zoompan` encima del clip ya construido

### 3. Correccion de imports rotos por el refactor

Durante el cambio aparecieron varios `NameError` por imports faltantes.

Se corrigieron los casos detectados, incluyendo:

- `send_file` en `routes/media.py`
- `_effective_clip_duration` en `render_ffmpeg.py`

### 4. Versionado de preview para invalidar cache vieja

Se actualizo la version interna del renderer de preview para que el frontend y backend no reutilicen blobs viejos.

Eso fuerza a generar previews nuevos cuando cambia el pipeline.

### 5. Timeline mas liviano

Se cambio el `Timeline visual` para que no dependa automaticamente del preview compuesto pesado en cada escena.

Ahora:

- la vista puede responder rapido
- las imagenes usan un motion CSS liviano en el timeline
- el preview compuesto queda para cuando realmente se pide, no como bloqueo permanente de la UI

## Estado tecnico actual

El backend ya genera el preview de escena correctamente en la ruta de preview.

Se valido tambien una respuesta directa del endpoint:

- `GET /api/proceso4/jobs/28/scenes/1/preview`
- respuesta `200`

Eso indica que el pipeline de preview ya vuelve a renderizar.

## Verificacion realizada

Backend:

- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/preview.py`
- smoke test del motion subpixel con Pillow
- smoke test del preview de `indice`

Frontend:

- `npm run build` en `software_website`

Validacion funcional:

- se probo el preview de escena directamente y respondio `200`
- se confirmo que el timeline ya no debe quedarse esperando siempre el preview compuesto

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/preview.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/media.py`
- `software_website/src/app/proceso4/components/TimelineOverview.tsx`

## Nota operativa

Si el frontend sigue mostrando una version vieja del preview, conviene refrescar la pagina para limpiar blobs en memoria.

Si el backend estaba levantado antes del cambio, tambien conviene reiniciar la instancia para asegurar que cargue el renderer nuevo.
