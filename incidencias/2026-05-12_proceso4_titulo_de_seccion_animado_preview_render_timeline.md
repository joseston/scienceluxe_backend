# Incidencia: titulo de seccion animado en preview, render y timeline de Proceso 4

Fecha: 2026-05-12  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

Se implemento un overlay animado con el nombre del bloque/seccion al inicio de cada seccion de contenido en `Proceso 4`.

La idea fue mantener una solucion hibrida:

- en `render final` y `preview de escena`, el texto se dibuja de verdad en backend
- en el `Timeline visual`, el texto se simula con una capa liviana en DOM/CSS

Con eso se evita volver a depender de un `preview compuesto` pesado para algo que puede resolverse de forma ligera en la UI.

## Sintomas / necesidad

La necesidad aparecio porque el flujo ya tenia:

- previews compuestos para escenas con transiciones
- overlays especiales para `indice` y `pregunta capciosa`
- una UI de timeline que intenta permanecer rapida y liviana

Pero no existia una capa consistente para mostrar, durante los primeros 3 o 4 segundos de una seccion, el nombre humano del subtema.

## Causa raiz

### 1. La seccion tecnica no era el titulo humano

El timeline ya conocia claves como `intro`, `parte1`, `parte2`, `parte3`, `parte4` y `cierre`, pero no tenia una fuente directa y reusable para el nombre visible de cada bloque.

### 2. El flujo tenia overlays especiales, pero no un overlay generico de apertura de seccion

El backend ya resolvia casos particulares como:

- `indice`
- `pregunta capciosa`

Sin embargo, el titulo de seccion necesitaba un tratamiento distinto:

- no solo en la primera escena
- sino durante una ventana de tiempo que puede cruzar escenas

### 3. El timeline no debia volver a depender de previews compuestos pesados

Por las incidencias previas, el monitor visual se mantuvo liviano. Entonces la nueva capa tenia que respetar esa decision y no reintroducir bloqueo visual.

## Solucion aplicada

### 1. Helper backend para resolver metadatos de titulo por seccion

Se agrego en `software_backend/aplicacion/endpoints/proceso4/helpers.py` un helper que:

- lee los subtemas reales desde la fuente ya existente de Proceso 1/2
- mapea secciones tipo `parte1` / `subtema_1` al titulo humano correspondiente
- calcula una ventana de overlay de `3.5s`
- reparte el overlay a traves de escenas consecutivas cuando la seccion cruza mas de un clip

El helper nuevo es `_build_section_title_metadata(...)`.

### 2. Overlay animado en backend para render final y preview

Se agrego en `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py` el helper:

- `_apply_section_title_overlay(...)`

Ese overlay:

- usa la tipografia del proyecto
- centra el titulo
- aplica fade-in y fade-out
- respeta cuanto tiempo del overlay ya transcurrio antes de la escena actual

Luego se conecto ese helper en:

- `software_backend/aplicacion/endpoints/proceso4/routes/render.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/preview.py`

Eso hace que el titulo aparezca tanto en el export final como en el preview de escena.

### 3. Cache/versionado de preview actualizado

Se actualizo la version interna del preview de escena para que el frontend no reutilice blobs viejos cuando cambia el renderer.

### 4. Exposicion de metadatos al frontend

Se extendio `GET /api/proceso4/jobs/<pid>/timeline` para devolver por escena:

- `sectionTitle`
- `sectionTitleOverlayDuration`
- `sectionTitleElapsedBefore`
- `sectionTitleSceneStart`

Con eso la UI puede simular el mismo comportamiento sin recomputar reglas distintas.

### 5. Simulacion liviana en Timeline

Se agrego en `software_website/src/app/proceso4/components/TimelineOverview.tsx` una capa DOM/CSS que:

- muestra el titulo de la seccion durante la misma ventana temporal
- respeta fade-in/fade-out
- no depende de preview compuesto

Tambien se actualizo la firma de cache local del preview en:

- `software_website/src/app/proceso4/components/TimelineOverview.tsx`
- `software_website/src/app/proceso4/components/SceneEditor.tsx`

para que los blobs viejos no sobrevivan a los cambios de overlay.

## Alcance intencional

Se dejo fuera de este titulo animado a:

- `intro`
- `cierre`
- `indice`
- `pregunta capciosa`

La razon es simple: esas partes ya tienen una logica visual propia y no conviene superponer otro tratamiento encima.

## Resultado

Despues de este cambio:

- el render final muestra el titulo de la seccion al comienzo del bloque
- el preview de escena muestra el mismo comportamiento
- el timeline visual conserva una version liviana y coherente con backend
- el overlay puede cruzar escenas cuando la seccion dura mas que una sola escena

## Verificacion realizada

Backend:

- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/helpers.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/render.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/preview.py`
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/timeline.py`

Frontend:

- `npm run build` en `software_website`

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/helpers.py`
- `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/render.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/preview.py`
- `software_backend/aplicacion/endpoints/proceso4/routes/timeline.py`
- `software_website/src/app/proceso4/components/TimelineOverview.tsx`
- `software_website/src/app/proceso4/components/SceneEditor.tsx`
- `software_website/src/app/proceso4/types/proceso4.types.ts`

## Actualizacion posterior: rediseño visual del overlay

Fecha de actualizacion: 2026-05-12 (mismo dia, iteracion posterior)

### Problema detectado

El titulo de seccion se mostraba centrado horizontalmente, con una caja de fondo grande (`max-w-[78%]`) y una fuente muy grande (`fontsize=64` en render, `clamp(16px, 4vw, 34px)` en timeline). Esto tapaba gran parte del contenido visual y se veia desproporcionado.

Ademas, el texto se rompia en lineas cortas en el backend (`max_chars_per_line = 24`), creando bloques verticales invasivos.

Finalmente, tras la primera correccion, se detecto que el render y el timeline seguian viendose distintos (tamaño de fuente, posicion, wrap).

### Cambios aplicados

#### 1. Posicion: centrado → esquina superior izquierda

- **Timeline:** de `absolute inset-x-0 top-[12%] flex justify-center` a `absolute top-3 left-3`
- **Backend (FFmpeg):** de `x=(w-text_w)/2 : y=max(96,h*0.12)` a `x=36 : y=28`

#### 2. Estilo: caja de fondo → solo text-shadow

Se elimino la caja de fondo (gradiente oscuro, `backdrop-filter`, padding, border-radius) para un look mas cinematografico tipo Netflix/YouTube.

- **Timeline:** se quito el `<div>` contenedor con fondo; ahora es solo un `<p>` con `text-shadow` doble (`0 2px 6px rgba(0,0,0,0.85), 0 1px 2px rgba(0,0,0,0.9)`).
- **Backend:** se quito `box=1:boxcolor=...:boxborderw=...`; se mantuvo solo `shadowcolor=black@0.85:shadowx=2:shadowy=2`.

#### 3. Tamaño de fuente reducido y homogeneizado

- **Timeline:** `clamp(10px, 1.2vw, 16px)` (antes `clamp(16px, 4vw, 34px)`)
- **Backend:** `fontsize=20` → luego ajustado a `fontsize=20` con `line_spacing=4` para que no crezca desproporcionado sobre 1920x1080.
  - Nota: tras pruebas visuales se fijo en `fontsize=20` para aproximar la escala del preview DOM.

#### 4. Word-wrap: menos agresivo

- **Backend:** `max_chars_per_line` cambio de `24` → `38` → `48` para evitar cortes ridiculos en titulos largos (ej. "Everything You've Seen of Jupiter Is a Lie" se partia en "...Is a" / "Lie").
- **Timeline:** `max-w-[40%]` para limitar el ancho natural del texto.

#### 5. Fuente y peso

- **Timeline:** se mantuvo `var(--font-montserrat)` pero se bajo de `fontWeight: 900` a `700`.
- **Backend:** se mantuvo `Montserrat-Black.ttf` (FFmpeg no permite cambiar peso sin cambiar archivo de fuente).

#### 6. Alineacion

- De `text-center` a `text-left` en ambos lados.

### Diferencias resueltas entre render y timeline

| Aspecto | Timeline (DOM/CSS) | Render (FFmpeg) |
|---|---|---|
| Posicion | `top-3 left-3` (~12px) | `x=36:y=28` (~36x28px en 1080p) |
| Fuente | Montserrat 700, clamp(10px,1.2vw,16px) | Montserrat Black, fontsize=20 |
| Sombra | text-shadow doble CSS | shadowcolor black@0.85 x=2 y=2 |
| Fondo | Ninguno | Ninguno |
| Wrap | max-w-[40%] + alineacion natural | max_chars_per_line=48 |
| Alineacion | Izquierda | Izquierda (por x fijo) |

### Archivos tocados en esta actualizacion

- `software_website/src/app/proceso4/components/TimelineOverview.tsx` — rediseño del overlay DOM/CSS
- `software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py` — ajustes de `_apply_section_title_overlay(...)`

### Verificacion realizada

- `npm run build` en `software_website` → exitoso
- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/render_ffmpeg.py` → exitoso

## Nota operativa

Si el frontend sigue mostrando un blob viejo del preview, conviene refrescar la pagina.

Si el backend seguia levantado desde antes del cambio, conviene reiniciarlo para asegurar que cargue el renderer nuevo.
