# Documentación Detallada - Proceso 3: Video
(Scienceluxe Videos Largos)

## 1. Visión General del Proceso
El **Proceso 3 (Video)** es el módulo central encargado de la construcción visual del contenido. 
Su objetivo principal es transformar los guiones y audios generados en los procesos anteriores en una secuencia de **Escenas Enriquecidas con IA**, listas para la producción final.

Este proceso abarca desde la organización temporal (Timeline) hasta el enriquecimiento visual automático (Visual Types & Descriptions).

---

## 2. Flujo de Trabajo Actual (Workflow)

El flujo de datos dentro del Proceso 3 sigue una estructura secuencial e iterativa:

### 2.1. Entrada de Datos
El proceso recibe como insumo principal los resultados del **Proceso 2 (Audio)**:
- **Audio Final**: Archivo `.mp3` o `.wav` concatenado.
- **Transcripción / Guión**: Estructura de texto segmentada por tiempos.
- **Insumos de IA**: Respuesta cruda de generación de escenas (Batches).

### 2.2. Etapas del Proceso (Subprocesos)

#### A. Subproceso 1: Timeline de Escenas (`timeline_view.py`)
- **Función**: Visualizar y ajustar la duración de cada escena.
- **Interacción**: El usuario puede ver la secuencia temporal de escenas.
- **Estado Actual**: Actúa como el "lienzo" donde se pintarán los datos enriquecidos.

#### B. Subproceso 2: Enriquecimiento IA (`enricher_view.py`)
Esta es la etapa crítica de inteligencia visual.
1. **Carga de Batches (Staging)**:
   - El sistema NO lee escenas finales directamente.
   - Lee **Batches de Escenas** (`SceneBatch`) generados por la IA en pasos previos.
   - Estos batches contienen JSONs con propuestas de:
     - *Visual Type* (Tipo de imagen/video sugerido).
     - *Visual Description* (Prompt para generación visual).
2. **Revisión y Filtrado**:
   - El usuario ingresa el **ID del Proyecto**.
   - El sistema recupera y combina los batches fragmentados (Intro, Parte 1, Parte 2, etc.).
   - Se presenta una lista unificada y ordenada cronológicamente.
3. **Aplicación (Commit)**:
   - Al confirmar, estas propuestas "enriquecidas" se envían al Timeline para convertirse en la estructura definitiva del video.

---

## 3. Arquitectura Técnica de Datos

El flujo de datos a nivel de base de datos (PostgreSQL) es el siguiente:

### 3.1. Origen: Tabla `scene_batches`
Es el área de "llegada" (Staging Area). Aquí la IA deposita sus respuestas sin procesar.
- **Clave de Búsqueda**: `project_external_id` (Ej: "8", "video_mars").
- **Contenido**: Columna `scenes` (JSONB) que contiene arrays de objetos escena.
- **Estado**: Los registros aquí son inmutables (logs de generación).

### 3.2. Destino Lógico (En Memoria / UI)
- La vista `EnricherView` actúa como un **Transformador (ETL)** en tiempo real.
- **Extracción**: `SELECT * FROM scene_batches WHERE project_external_id = 'X'`.
- **Transformación**:
  - Deserialización de JSONs.
  - Normalización de campos (`start`, `end`, `visual_type`).
  - Ordenamiento por `start_time`.
- **Carga (Load)**: Se inyectan en el componente visual del Timeline.

*(Nota: En una fase futura, el botón "Aplicar" debería persistir estos datos transformados en las tablas `scenes` y `scene_enrichments` para cerrar el ciclo de normalización).*

---

## 4. Componentes Clave del Código

### `proceso3/views/enricher_view.py`
Clase principal: `EnricherView`
- **Responsabilidad**: Interfaz de usuario para la gestión de batches.
- **Métodos Críticos**:
  - `_handle_load_from_db(e)`: 
    - Conecta con `SessionLocal`.
    - Ejecuta la query sobre `SceneBatch`.
    - Maneja errores de IDs inexistentes o batches vacíos.
  - `_build()`: Construye la UI con Flet (Input ID + Botones de Acción).

### `core/database.py`
Modelos involucrados:
- **`SceneBatch`**:
  - `id`: Identificador único del batch.
  - `project_external_id`: Enlace con el proyecto (String).
  - `scenes`: Payload JSON vital.
  - `status`: Estado del procesamiento del batch.

---

## 5. Guía de Uso Rápido (UX)

1. **Navegación**: Ir a Menú Lateral -> **PROCESO 3** -> **Enriquecer**.
2. **Identificación**: Escribir el ID externo del proyecto (ej: `8`) en el campo de texto.
3. **Carga**: Pulsar **"CARGAR DE BD"**.
   - *Éxito*: Aparecerá la lista de escenas y el contador total.
   - *Error*: Verificar que el ID sea correcto y que existan batches generados previamente.
4. **Finalización**: Revisar la lista y (próximamente) pulsar **"APLICAR AL TIMELINE"** para continuar la edición.
