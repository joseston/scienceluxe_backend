# Incidencia: resumen de seccion y guia visual manual por escena en Prompt Station

Fecha: 2026-05-10  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

En `Proceso 4`, `Prompt Station` ya generaba prompts utiles, pero seguia habiendo un riesgo operativo:

- la IA podia producir una imagen visualmente atractiva pero conceptualmente equivocada
- una escena podia verse "epica" y aun asi no representar bien lo que la narracion queria explicar
- si el usuario no estaba revisando cada escena con mucha atencion, esos errores podian pasar desapercibidos

Para reducir ese riesgo se agregaron dos ayudas manuales dentro de `Prompt Station`:

- `Resumen de seccion`
- `Guia visual` por escena

Las dos funciones usan Gemini, pero no se ejecutan automaticamente. Solo corren cuando el usuario pulsa el boton.

## Problema que resuelve

Habia dos huecos distintos:

### 1. Faltaba contexto narrativo de alto nivel

Una seccion como `parte4` puede tener 10 o mas escenas. Aunque cada escena tenga su `text`, a veces cuesta ver rapido:

- que esta contando la seccion en conjunto
- hacia donde progresa
- que idea cientifica principal une todas las escenas

Por eso se agrego un resumen de toda la seccion.

### 2. Faltaba una explicacion manual de control visual por escena

Aunque el `visual_brief` y los prompts mejoraron, seguia faltando una capa humana de verificacion rapida que dijera:

- que debe verse realmente en esta escena
- como se conecta con la seccion entera
- que elementos no pueden faltar
- que errores visuales serian una senal de que la IA se desvio

Por eso se agrego una `Guia visual` manual por escena.

## Solucion aplicada

### Resumen de seccion

Se agrego un boton `Resumen de seccion` en el encabezado de cada bloque de `Prompt Station`.

Comportamiento:

- toma todos los `scene.text` de la seccion en orden de `scene_num`
- llama a Gemini para resumir la seccion completa en espanol
- muestra el resultado inline, arriba de las escenas
- guarda el resultado en cache para no repetir costo de API si la seccion no cambio

El objetivo es que el usuario entienda rapidamente que esta diciendo esa parte del documental antes de revisar prompts o imagenes.

### Guia visual manual por escena

Se agrego un boton `Guia visual` dentro de cada escena expandida.

Comportamiento:

- no corre sola
- se ejecuta solo cuando el usuario pulsa el boton
- toma el texto de la escena, el `visual_description`, la `physical_composition`, el texto completo de la seccion y el resumen de seccion
- genera una guia en espanol con cuatro bloques:
  - `Que debe verse`
  - `Relacion con la seccion`
  - `Elementos obligatorios`
  - `Evitar`

El objetivo no es escribir otro prompt cinematografico largo, sino una explicacion clara para detectar rapido cuando una generacion visual no tiene sentido.

## Contrato tecnico

### Endpoint de resumen de seccion

```http
POST /api/proceso4/jobs/<pid>/prompt-station/sections/<section>/summary
```

Entrada:

```json
{
  "force": false
}
```

Salida:

```json
{
  "section": "parte4",
  "sceneCount": 13,
  "summary": "Resumen en espanol de toda la seccion...",
  "cached": true
}
```

Persistencia:

- subprocess state `section_summaries`

Regla de cache:

- se reutiliza si el hash del texto completo de la seccion no cambio

### Endpoint de guia visual por escena

```http
POST /api/proceso4/jobs/<pid>/prompt-station/sections/<section>/scenes/<scene_num>/visual-guide
```

Entrada:

```json
{
  "force": false
}
```

Salida:

```json
{
  "section": "parte4",
  "sceneNum": 54,
  "guide": "Que debe verse...\nRelacion con la seccion...\nElementos obligatorios...\nEvitar...",
  "sectionSummary": "Resumen en espanol de la seccion...",
  "sectionSummaryCached": true,
  "cached": false
}
```

Persistencia:

- subprocess state `scene_visual_guides`

Regla de cache:

- se reutiliza si no cambiaron la escena, el texto completo de la seccion ni el resumen usado como contexto

## Comportamiento importante

- Si la seccion todavia no tiene resumen, la `Guia visual` lo resuelve primero en backend para usarlo como contexto.
- Nada se genera automaticamente al abrir `Prompt Station`.
- El usuario decide manualmente cuando gastar API.
- Si quiere forzar una nueva salida, puede usar `Regenerar resumen` o `Regenerar guia`.

## Bug encontrado durante la implementacion

Durante el cambio aparecio un error que rompia `Prompt Station`:

```python
AttributeError: 'str' object has no attribute 'append'
```

Causa raiz:

- dentro de `get_prompt_station(...)` ya existia una lista llamada `section_summary`
- al agregar el resumen textual de la seccion se reutilizo accidentalmente ese mismo nombre para un string
- despues el codigo intento hacer `.append(...)` sobre ese string

Correccion:

- la lista final se renombro a `section_summary_rows`
- el resumen textual se renombro a `cached_section_summary`

Resultado:

- `GET /api/proceso4/jobs/<pid>/prompt-station` volvio a responder `200`
- `Prompt Station` recupero su render normal

## Ajuste adicional: preview dinamico del indice automatico

Despues aparecio otra incidencia en `Proceso 4`, esta vez en el preview del `Indice Automatico`.

### Sintoma

- el preview del indice mostraba la imagen de fondo
- pero no mostraba las letras de los subtemas
- en un primer arreglo temporal, el texto volvio a aparecer, pero se perdio el efecto dinamico
- eso rompia justo la parte cinematica importante: que cada subtema aparezca mientras va siendo nombrado

### Causa raiz

El renderer del preview estaba construyendo varios `drawtext` de FFmpeg con texto inline.

Eso era fragil por tres motivos:

- comas como en `70,000`
- apostrofes como en `You've`
- algunos caracteres tipograficos como guiones largos

Cuando FFmpeg interpretaba mal uno de esos textos, el filtro fallaba o caia en fallback silencioso y el preview terminaba sin letras.

### Error de enfoque en el primer arreglo

Se hizo un arreglo defensivo que cambiaba el overlay a un bloque estatico con todos los subtemas visibles desde el inicio.

Eso resolvia la ausencia de letras, pero eliminaba el comportamiento narrativo correcto del indice.

En otras palabras:

- resolvia estabilidad
- pero degradaba la experiencia visual

### Correccion final aplicada

Se rehizo el renderer para conservar ambas cosas:

- estabilidad tecnica
- aparicion progresiva de subtemas

La solucion final fue:

- mantener el flujo dinamico por subtema
- dejar de inyectar el texto completo inline en `drawtext`
- crear un `textfile` temporal por cada subtema
- usar ese `textfile` en cada `drawtext`
- conservar la logica de aparicion escalonada y fade por tiempo
- invalidar el cache de preview con una nueva version de renderer

Adicionalmente, se normalizaron algunos caracteres visuales para evitar glitches de fuente en preview:

- `—` y `–` se convierten a `-`
- comillas tipograficas se normalizan

### Resultado esperado

El indice vuelve a comportarse como antes en lo narrativo, pero ya no se rompe con textos reales:

- al inicio aparece solo el primer subtema
- despues aparece el segundo
- luego el tercero
- y asi sucesivamente

### Nota operativa importante

Aunque el codigo quede bien en disco, si el backend no se reinicia puede seguir devolviendo el renderer anterior.

Por eso, despues de este cambio, hace falta reiniciar Flask para que el preview nuevo del indice se vea realmente en la UI.

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/__init__.py`
- `software_website/src/app/proceso4/services/proceso4.service.ts`
- `software_website/src/app/proceso4/hooks/useProceso4.ts`
- `software_website/src/app/proceso4/components/PromptStationPanel.tsx`
- `software_website/src/app/proceso4/types/proceso4.types.ts`

## Verificacion realizada

Backend:

```powershell
conda activate scieluxe
python -m py_compile software_backend\aplicacion\endpoints\proceso4\__init__.py
```

Se comprobo tambien que:

```http
GET /api/proceso4/jobs/28/prompt-station
```

respondiera `200`.

Frontend:

```powershell
npm run build
```

El build de `software_website` termino correctamente.

## Nota operativa

Estas dos funciones no reemplazan el prompt ni el `visual_brief`.

Su rol es complementar el flujo con una capa de lectura rapida:

- el `Resumen de seccion` ayuda a entender el bloque narrativo completo
- la `Guia visual` ayuda a juzgar si una generacion visual realmente representa esa escena dentro de ese bloque

Si una imagen sale bonita pero no comunica la idea correcta, el lugar mas util para mirar ahora es:

- el resumen de la seccion
- la guia visual de la escena
- y luego recien el prompt final completo
