# Documentación de Procesos (1 al 5)

Esta documentación describe la arquitectura y el flujo de trabajo de los 5 procesos principales del sistema backend para la generación semiautomatizada de videos largos documentales.

---

## Proceso 1: Generación de Guion y Extracción (Script Generation)
Este proceso es la base del sistema, el "cerebro" inicial. Está encargado de la extracción de información fáctica desde fuentes originales (URLs de YouTube, artículos), la conformación estructural del video y la redacción del guion final de narración iterativo asistido por Gemini AI. 

El código fuente de este proceso reside en `aplicacion/endpoints/proceso1/` y está dividido en una arquitectura de "core" (logica de extracción y persistencia) y "prompts" (plantillas de instrucciones LLM).

### Componentes Core (`core/`)
*   **Gestor de URLs (`url_parser.py`):** Analiza y clasifica las URLs de entrada para determinar si corresponden a videos de YouTube (extrayendo su ID) o a artículos web.
*   **Extractores de Información (`youtube_extractor.py`, `article_extractor.py`, `content_aggregator.py`):** 
    *   Extraen los subtítulos o contenido de texto de las respectivas fuentes mediante `youtube_transcript_api` y `trafilatura`.
    *   Agregan toda la data cruda extraída en un solo documento unificado de contexto.
*   **Generador de Estructura (`estructura_generator.py`):** Forma el Subproceso 2. Toma un análisis estratégico proporcionado por el usuario y se conecta con Gemini para devolver un modelo mental del video en formato JSON (`tema_principal`, `keywords`, arreglo de `subtemas` con contexto) y pre-calcula los prompts de investigación profunda.
*   **Capa de Persistencia (`persistence.py`):** Interfaz robusta y centralizada para guardar y cargar los "artefactos" JSON/Texto entre cada paso interactivo del Proceso 1 en la base de datos relacional (`p1_artifacts`), asegurando que ningún fallo haga perder el progreso de múltiples horas de la generación del guion (Ej. `save_extraction_results`, `save_p4_subtema`).

### Flujo de Subprocesos y Motores de Prompts (`prompts/`)
El guion se construye de manera fragmentada e iterativa para asegurar máxima retención y mantener a la IA (Gemini) enfocada, simulando técnicas virales de storytelling estilo Vsauce o Lemmino:

1.  **Subproceso 1 (Análisis Estratégico - `strategic_analysis.py`):** Compara el "Main Viral Target" con "Supplementary Data", generando un prompt que busca aislar el gancho viral original y repotenciarlo con nuevos datos científicos (The Clarity Filter, The Viral Topic, Key Facts).
2.  **Investigación y "Data Cruda" (`deep_research.py`, `info_interna.py`):** Formatean las solicitudes para nutrir a la IA redactora solo con evidencia validada (distancias, papers, imágenes de agencias como NASA) limitando las "alucinaciones" (Fact-Check).
3.  **Subproceso 3 (Introducción y Ensamblaje - `introduccion.py`):** Generación crítica de los primeros 45 segundos del video. Obliga a la IA a escribir usando fórmulas de YouTube comprobadas:
    *   *Gancho (0-15s):* Deíctico + Sujeto → Anclaje Viral → Superlativo de urgencia.
    *   *La Escalada (15-25s):* Pivot → Profundidad (2-3 consecuencias) → Peso emocional → Pregunta puente.
    *   *Índice "Quick Summary" (25-40s):* Resumen en viñetas rápidas (Menu) de los 4 subtemas.
    *   *La Puerta (40-45s):* Transición en seco hacia la parte 1. Produce 4 alternativas distintas para que el usuario elija.
4.  **Subproceso 4 (Cuerpo Subtema - `cuerpo_subtema.py`):** Se llama iterativamente (usualmente 4 veces). Produce un segmento del cuerpo. El prompt incluye la sección `script_acumulado` para forzar a la IA a leer lo anterior y aplicar la "Regla Anti-Redundancia", así como preparar una "Subtopic Closing Transition" al tema siguiente. Se le exige métricas nativas de US (millas, Fahrenheit) y fragmentación del texto (pausas con elipsis, negritas).
5.  **Subproceso 5 (Cierre de Video - `cierre_video.py`):** Elabora la conclusión filosófica o llamada a la acción resolviendo el misterio central.
6.  **Subproceso 6 (Edición Maestra - `edicion_maestra.py`):** El "Master YouTube Script Editor". Toma el texto crudo resultante de haber unido todas las partes de los Subprocesos 3 al 5 y le realiza un pase final puliendo los "Brick Paragraphs" (rompiendo párrafos gigantes), controlando el desgaste de vocabulario (Echo Control), acortando el índice y forzando respiros (`...`) y el capítulo audio-visual con "Ataques Fuertes" para facilitar la locución.

---

## Proceso 2: Pipeline de Audio y Subtítulos (Audio Pipeline)
Encargado del procesamiento, transcripción y manipulación de los recursos de audio a partir del guion generado en el Proceso 1.

### Flujo de Trabajo
*   **Carga y Reemplazo (`upload_audio_parts`, `replace_audio_part`):** Permite subir archivos de audio (Ej: Voz en off generada por TTS de 11Labs) parte por parte o en bloque.
*   **Ajuste de Velocidad (`run_speed`):** Modifica la velocidad del audio si es requerido para ajustar tiempos de retención.
*   **Concatenación (`run_concat`):** Une las distintas partes de las locuciones de voz en un único archivo de audio final (`final.mp3`).
*   **Generación de Subtítulos SR (`run_srt`, `whisper_status`):** Utiliza Whisper para transcribir el audio concatenado y generar subtítulos precisos con sus marcas de tiempo.
*   **Segmentación en Escenas (`run_scenes`):** Acomoda los subtítulos e información de tiempos en una estructura inicial de escenas.

---

## Proceso 3: Enriquecimiento Visual y Línea de Tiempo (Prompt Enrichment)
Tiene la responsabilidad de sincronizar la narración con elementos visuales, usando LLM (como Gemini) de apoyo para dotar de intención y descripciones a los segmentos.

### Funciones Principales
*   **Extracción a Nivel Oración (`run_segment`, `_flatten_segment_words`):** Alinear tiempos y agrupar el texto de subtítulos detectados en oraciones lógicas.
*   **Enriquecimiento con Gemini (`run_enrich_section`):** Toma las oraciones (sección por sección) y le solicita a una IA agrupar subtítulos en escenas coherentes y proponer direcciones visuales (prompts) para el editor / generación de video.
*   **Línea de Tiempo (`run_timeline`):** Genera el archivo base de línea de tiempo con todos los marcadores estructurados.
*   **Marcadores (`export_markers_csv`):** Exporta un archivo útil con la estructura de escenas, duración y propuesta visual para guiar el flujo de edición.

---

## Proceso 4: Ensamblado y Renderizado de Video (Video Assembly)
Punto central de la edición multitrack interactiva y renderizado de video programado. Este módulo (`aplicacion/endpoints/proceso4/`) une la narración, línea de tiempo (importada del Proceso 3), pistas musicales (Pistas P4) y elementos de metraje individuales de cada escena para generar el entregable final. 

### Componentes y Motores Principales
*   **Motor FFmpeg Adaptativo (`_detect_video_encoder`, `_find_working_binary`):** Comprueba automáticamente el sistema host en busca de soporte para aceleración por hardware (NVENC para GPUs NVIDIA) y codificadores CPU potentes (`libx264`). Esto asegura que el renderizado final consuma el menor tiempo posible dependiendo de las capacidades del entorno servidor/VPS.
*   **Gestión de Proxies en Background (`_generate_proxy_async`):** Para evitar congelar el frontend o consumir banda ancha en exceso al previsualizar la línea de tiempo, cada metraje largo/pesado (4K/1080p) genera una copia provisional "proxy" en resolución 480p utilizando un sub-hilo (background thread).
*   **Cálculos de "Tiempos Efectivos" (`_get_scene_effective_duration`):** Lógica avanzada de timing. Este proceso calcula el "gap" (los pequeños márgenes o silencios entre la locución de voz y escena), absorbiéndolos para que los clips de video se extiendan lo suficiente y no dejen la pantalla en negro (compensando adicionalmente alteraciones de velocidad en los clips).
*   **Índice Automático y Assets Globales (`auto_indice`, `_get_indice_data`):** Extrae automáticamente de los "subtemas" estructurados cuáles son los puntos ancla del video. A partir de una plantilla global (Imagen base + Música dedicada del Índice), el sistema "sella" los tiempos del menú principal de 4 pasos al inicio del video.

### Estaciones de Generación (Prompt Templates)
Separado del código core de la API, el archivo `prompt_templates.py` contiene fábricas paramétricas que toman la `narracion_escena` e instrucciones de canal, construyendo comandos hiper-pesonalizados para plataformas generativas externas que cubrirán visualmente los Huecos de Escena:
*   **Text-To-Video:** Generación de prompts en inglés listos para Sora, VEO 3, o Runway Gen-3.
*   **Image-To-Video:** Plantillas dedicadas con instrucciones físicas (`physical_composition`) y paneos de cámara requeridos por sistemas de animación de fotos estáticas como Kling, Runway o Luma Dream Machine. 
*   **Text-To-Image:** Generación de estilo directo y ultra detallado para Banana Pro, Midjourney o Ideogram.

### Flujo de Trabajo
1.  **Carga de Timeline:** Importación automática de los JSON producidos por la IA en el Proceso 3 (escenas en formato diccionario o *data objects*).
2.  **Carga de Medios Individuales (`upload_scene_media`):** Subida de clips, verificación dinámica por `ffprobe` e incrustación al track correspondiente.
3.  **Gestión de Pistas de Audio Adicional (`upload_audio_track`):** Creación de un editor básico manejando música de fondo (background music) sobre el video.
4.  **Render Final:** Ensambla por sub-clips a través de pipelines de la librería ffmpeg, ajustándolos con su resolución objetivo y estampando en pantalla, de ser necesario, elementos fijos.

---

## Proceso 5: Metadatos para Publicación (YouTube Metadata)
Etapa final que utiliza IA para elaborar un atractivo paquete de empaquetado para plataformas como YouTube basándose en la información unificada.

### Utilidades Generadas
*   **Propuestas de Títulos (`generate_metadata`):** Genera iterativamente ganchos para el título del video optimizados para CTR elevado (ej. llamadas a Opus o Gemini).
*   **Descripciones y Línea de Tiempo (`_build_timeline_entries`):** Construye la descripción enriquecida con metadatos y crea los capítulos de YouTube en formato `MINUTO:SEGUNDO - TITULO DEL CAPÍTULO` usando la data del Proceso 4.
*   **Palabras Clave (Keywords):** Detecta temas clave SEO y términos de búsqueda según el final del script.
*   **Prompt para Miniatura (Thumbnail):** Diseña instrucciones gráficas para pasar a herramientas de generación de imágenes generativas (Kling/Midjourney) que representen visualmente el gancho en forma de miniatura intrigante.
