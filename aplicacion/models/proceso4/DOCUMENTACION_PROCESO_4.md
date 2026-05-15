# Proceso 4 — Ensamblaje de Video

## Descripción General

Proceso 4 es la etapa final del pipeline de producción de videos documentales científicos. Se encarga de:
- Importar la línea de tiempo (timeline) generada por Proceso 3
- Asignar recursos multimedia (video/imágenes) a cada escena
- Configurar pistas de audio (música, efectos de sonido)
- Generar prompts para IA generativa (texto-a-video, imagen-a-video)
- Renderizar el video final usando FFmpeg

## Arquitectura del Sistema

### Stack Tecnológico

**Backend (Python/Flask):**
- Flask como framework web
- SQLAlchemy para ORM de base de datos
- FFmpeg/FFprobe para procesamiento de video
- PostgreSQL como base de datos

**Frontend (Next.js/TypeScript):**
- Next.js 14+ con App Router
- TypeScript para tipado estático
- Tailwind CSS para estilos
- Componentes React con estado reactivo

### Estructura de Archivos

```
proceso4/
├── models/
│   └── __init__.py          # Modelos de base de datos
├── endpoints/
│   ├── __init__.py          # Endpoints Flask (2924 líneas)
│   └── prompt_templates.py  # Plantillas de prompts IA (196 líneas)
└── DOCUMENTACION_PROCESO_4.md

software_website/src/app/proceso4/
├── page.tsx                 # Página principal
├── components/
│   ├── Proceso4Sidebar.tsx
│   ├── Proceso4ProjectBar.tsx
│   ├── TimelineOverview.tsx
│   ├── SceneEditor.tsx
│   ├── RenderSection.tsx
│   ├── PromptStationPanel.tsx
│   ├── ConfigView.tsx
│   └── ...
├── hooks/
│   └── useProceso4.ts       # Hook principal (317 líneas)
├── services/
│   └── proceso4.service.ts  # API service (331 líneas)
└── types/
    └── proceso4.types.ts    # Tipos TypeScript
```

## Modelos de Base de Datos

### Proceso4Job
**Propósito:** Job principal anclado al ID del Job de Proceso 1.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| proceso1_job_id | Integer (FK) | Referencia al job padre |
| status | String(50) | Estado del job |
| created_at | DateTime | Fecha de creación |
| updated_at | DateTime | Última actualización |

### Proceso4SubprocessState
**Propósito:** Estados de subprocesos individuales.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | Integer | PK |
| proceso1_job_id | Integer (FK) | Referencia al job |
| subprocess_key | String(50) | Clave del subproceso |
| status | String(50) | Estado (draft, pending, running, completed, failed) |
| input_payload | JSON | Datos de entrada |
| output_payload | JSON | Datos de salida |
| metadata_payload | JSON | Metadatos adicionales |

**Subprocesos soportados:**
- `import_timeline`: Importación de timeline de Proceso 3
- `render`: Renderizado del video final
- `prompt_station`: Generación de prompts IA
- `config`: Configuración global

### Proceso4SceneMedia
**Propósito:** Media (video/imagen) asignada a una escena.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | Integer | PK |
| proceso1_job_id | Integer (FK) | Referencia al job |
| scene_num | Integer | Número de escena |
| clip_index | Integer | Índice del clip (0, 1, 2...) |
| media_type | String(10) | 'video' o 'image' |
| file_path | String(500) | Ruta al archivo |
| duration | Float | Duración original (video) |
| trim_start | Float | Inicio del trim |
| trim_end | Float | Fin del trim (null = usar todo) |
| speed | Float | Velocidad de reproducción (0.25-4.0) |
| transition_type | String(30) | Tipo de transición |
| transition_duration | Float | Duración de transición |
| text_overlay | JSON | Configuración de texto superpuesto |
| proxy_path | String(500) | Ruta del proxy de baja resolución |

### Proceso4AudioTrack
**Propósito:** Pistas de audio adicionales (música, SFX).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | Integer | PK |
| proceso1_job_id | Integer (FK) | Referencia al job |
| track_type | String(20) | 'music' o 'sfx' |
| file_path | String(500) | Ruta al archivo |
| start_time | Float | Tiempo de inicio |
| volume | Float | Volumen (0.0-1.0, default 0.3) |

### Proceso4SectionTrack
**Propósito:** Música asignada por sección del video.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | Integer | PK |
| proceso1_job_id | Integer (FK) | Referencia al job |
| section | String(30) | Sección (intro, subtema_1..4, cierre) |
| pista_path | String(500) | Ruta al archivo de música |
| volume | Float | Volumen (default 0.15) |
| fade_in | Float | Fade in (default 1.0s) |
| fade_out | Float | Fade out (default 2.0s) |

### Proceso4GlobalAsset
**Propósito:** Assets reutilizables globales.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | Integer | PK |
| asset_key | String(50) | Clave única del asset |
| file_path | String(500) | Ruta al archivo |

**Assets globales típicos:**
- `indice_image`: Imagen para la escena de índice
- `indice_music`: Música para la escena de índice

### Proceso4ReverbConfig
**Propósito:** Configuración de reverb para narración.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| proceso1_job_id | Integer (FK) | PK y FK |
| enabled | Boolean | Si está habilitado |
| in_gain | Float | Ganancia de entrada (default 0.8) |
| out_gain | Float | Ganancia de salida (default 0.88) |
| delay_ms | Float | Delay en ms (default 60.0) |
| decay | Float | Decaimiento (default 0.4) |

## Endpoints de la API

### Gestión de Jobs

```
POST /api/proceso4/jobs/<pid>/init
GET  /api/proceso4/jobs/<pid>
POST /api/proceso4/jobs/<pid>/subprocesses/<key>
GET  /api/proceso4/jobs/<pid>/subprocesses
```

### Timeline

```
GET /api/proceso4/jobs/<pid>/timeline
```

### Media de Escenas

```
POST /api/proceso4/jobs/<pid>/scenes/<scene_num>/media
GET  /api/proceso4/jobs/<pid>/scenes/<scene_num>/media
PUT  /api/proceso4/jobs/<pid>/scenes/<scene_num>/media/<media_id>
DELETE /api/proceso4/jobs/<pid>/scenes/<scene_num>/media/<media_id>
```

### Pistas de Audio

```
POST /api/proceso4/jobs/<pid>/audio-tracks
GET  /api/proceso4/jobs/<pid>/audio-tracks
DELETE /api/proceso4/jobs/<pid>/audio-tracks/<track_id>
```

### Tracks por Sección

```
GET  /api/proceso4/jobs/<pid>/section-tracks
POST /api/proceso4/jobs/<pid>/section-tracks
PUT  /api/proceso4/jobs/<pid>/section-tracks/<section>
DELETE /api/proceso4/jobs/<pid>/section-tracks/<section>
```

### Configuración Global

```
GET /api/proceso4/jobs/<pid>/config
POST /api/proceso4/jobs/<pid>/config
```

### Prompt Station

```
GET  /api/proceso4/jobs/<pid>/prompt-station
POST /api/proceso4/jobs/<pid>/prompt-station/generate
```

### Renderizado

```
POST /api/proceso4/jobs/<pid>/render
GET  /api/proceso4/jobs/<pid>/render/status
GET  /api/proceso4/jobs/<pid>/render/output
```

### Índice Automático

```
POST /api/proceso4/jobs/<pid>/auto-indice
```

## Plantillas de Prompt IA

### build_text_to_video_prompt()
Genera prompts para generación de video (VEO 3, Sora, Runway Gen-3).

**Parámetros:**
- `tema_principal`: Tema del video
- `seccion_actual`: Sección actual (intro, parte1, parte2, parte3, cierre)
- `estilo_canal`: Estilo visual del canal
- `narracion_escena`: Texto de la narración
- `concepto_visual_base`: Concepto visual principal
- `tipo_visual`: Tipo de visual sugerido
- `duracion_segundos`: Duración requerida
- `physical_composition`: Composición física estricta

**Reglas de generación:**
- Duración ≤4s: Movimientos rápidos y enérgicos
- Duración ≤8s: Movimientos moderados y elegantes
- Duración >8s: Movimientos ultra-lentos e hipnóticos

### build_text_to_image_prompt()
Genera prompts para generación de imágenes (Banana Pro, Midjourney, Ideogram).

**Salida:**
- POSITIVE PROMPT: Prompt detallado en inglés
- NEGATIVE PROMPT: Elementos a excluir

### build_text_to_animation_prompt()
Genera un meta-prompt que se pega en Gemini para que Gemini escriba el prompt final o la respuesta de animacion deseada.

**Regla operativa:**
- No devuelve codigo.
- No devuelve la animacion.
- Le pide a Gemini producir la siguiente capa util del flujo.
- En esta implementacion, la salida de `Text-to-Animation` esta pensada para que Gemini genere la respuesta final de animacion a partir de un prompt cuidadosamente guiado.

### build_image_to_video_prompt()
Genera prompts para animación de imagen a video (Kling, Runway, Luma).

**Movimientos de cámara según duración:**
- ≤4s: Dolly-in rápido y preciso
- ≤8s: Orbital drift suave
- >8s: Zoom out ultra-lento

## Configuración de FFmpeg

### Detección de Binarios

El sistema busca binarios de FFmpeg en el siguiente orden:
1. Entorno Conda activo (`CONDA_PREFIX`)
2. Miniconda3 global (`~/miniconda3`)
3. Variables de entorno de usuario
4. PATH del sistema

### Codificadores de Video

Prioridad de codificadores H.264:
1. `h264_nvenc` (GPU NVIDIA)
2. `libx264` (CPU)
3. `h264_mf` (Windows Media Foundation)
4. `mpeg4` (fallback)

### Variables de Entorno

```python
FFPROBE_BIN = ruta al binario ffprobe
FFMPEG_BIN = ruta al binario ffmpeg
VIDEO_ENCODER = codificador seleccionado
USE_NVENC = booleano (GPU disponible)
```

## Flujo de Trabajo

### 1. Inicialización
```
Proceso 3 completado → Usuario abre Proceso 4 → POST /init
```

### 2. Importación de Timeline
```
GET /timeline → Carga escenas desde Proceso 3
```

### 3. Edición de Escenas
```
Subir media → Asignar a escena → Configurar trim/velocidad/transiciones
```

### 4. Configuración de Audio
```
Subir pistas de música → Asignar por sección → Ajustar volumen/fades
```

### 5. Generación de Prompts (Opcional)
```
Prompt Station → Generar prompts IA → Copiar a herramienta externa
```

**Nota sobre niveles de prompt:**
- `Text-to-Image` puede vivir como metadata o como prompt final.
- `Text-to-Animation` entrega un prompt para Gemini, no codigo directo.
- El objetivo de `Text-to-Animation` es guiar a Gemini para que produzca la siguiente respuesta util del flujo de animacion.

### 6. Renderizado
```
POST /render → FFmpeg procesa → Video final en data/proceso4/<job_id>/
```

## Vistas del Frontend

### Timeline View
- Visualización de todas las escenas
- Estado de cobertura de media
- Acceso rápido al editor

### Scene Editor
- Carga/subida de media
- Configuración de trim, velocidad, transiciones
- Preview de clips

### Render Section
- Estado del renderizado
- Progreso en tiempo real
- Descarga del video final

### Prompt Station
- Generación de prompts por sección
- Copia rápida al portapapeles
- Estado de completitud
- Soporta `Text-to-Animation` como prompt final para Gemini

### Config View
- Configuración de assets globales
- Configuración de reverb
- Edición de estilo de canal

## Tipos TypeScript Principales

```typescript
type Proceso4View = "timeline" | "editor" | "prompts" | "render" | "config";

interface Scene {
    scene_num: number;
    section: string;
    start: number;
    end: number;
    duration: number;
    effectiveDuration: number;
    text: string;
    visual_type: string;
    visual_description: string;
    media: SceneMedia[];
    coveredSeconds: number;
    remainingSeconds: number;
}

interface SceneMedia {
    id: number;
    sceneNum: number;
    clipIndex: number;
    mediaType: "video" | "image";
    filePath: string;
    duration: number | null;
    trimStart: number;
    trimEnd: number | null;
    speed: number;
    transitionType: string;
    transitionDuration: number;
}

interface PromptStationSection {
    section: string;
    sceneCount: number;
    status: "pending" | "completed";
    promptsGenerated: boolean;
    prompts: ScenePrompts[];
}
```

## Estilo de Canal Predeterminado

```python
DEFAULT_ESTILO_CANAL = (
    "Cinematográfico, hiperrealista, 8K, estilo documental de ciencias "
    "BBC/National Geographic, misterioso y grandioso, iluminación "
    "volumétrica y dramática, colores profundos (azul oscuro, dorado, "
    "negro absoluto), sin elementos gráficos ni texto en pantalla"
)
```

## Secciones del Video

```python
SECTIONS_ORDER = ["intro", "parte1", "parte2", "parte3", "cierre"]
```

## Consideraciones de Rendimiento

### Proxy de Video
- Videos subidos generan proxy de baja resolución
- Proxy usado para preview en UI
- Original usado para render final

### Duración Efectiva de Escena
- Incluye gaps inter-escena absorbidos
- Calculado automáticamente desde timeline
- Útil para sincronización de audio

### Velocidad de Reproducción
- Rango: 0.25x a 4.0x
- Afecta duración efectiva del clip
- Útil para slow-motion o time-lapse

## Depuración

### Logs
```python
logger = logging.getLogger(__name__)
# Prefijo [P4] en todos los logs
```

### Estados de Subproceso
- `draft`: Inicial
- `pending`: En cola
- `running`: En ejecución
- `completed`: Éxito
- `failed`: Error

## Dependencias Externas

- **FFmpeg:** Procesamiento de video y audio
- **FFprobe:** Extracción de metadatos de media
- **PostgreSQL:** Persistencia de datos
- **Next.js:** Frontend React
- **Tailwind CSS:** Estilos

## Mejores Prácticas

1. **Media:** Usar archivos de alta calidad para render final
2. **Audio:** Mantener volumen de música bajo (0.15) para no competir con narración
3. **Transiciones:** Usar dissolve o fade para transiciones suaves
4. **Prompts:** Personalizar estilo de canal por proyecto
5. **Reverb:** Habilitar para narración profesional
6. **Proxies:** Generados automáticamente para mejor UX
