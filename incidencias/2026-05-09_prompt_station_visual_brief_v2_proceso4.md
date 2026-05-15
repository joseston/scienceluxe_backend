# Incidencia: visual brief v2 para escenas explicativas en Prompt Station

Fecha: 2026-05-09  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

Se ajusto la capa `visual_brief` de `Prompt Station` porque el primer diseno resolvia mejor escenas de sujeto principal, pero seguia fallando en escenas explicativas o comparativas.

El problema aparecio con escenas tipo `Graphic`, por ejemplo:

- comparar rayos de Jupiter contra rayos de la Tierra
- mostrar que una descarga joviana podria alimentar una ciudad pequena
- explicar una relacion de escala, causa/efecto o proceso sin texto en pantalla

En esos casos, la imagen podia ser visualmente espectacular, pero no cumplir la funcion de la escena. Por ejemplo: salia Jupiter con rayos gigantes y arena fundida, pero faltaba una referencia clara de ciudad o red electrica, asi que no se entendia la idea `could power a small city`.

## Causa raiz

El `visual_brief` original tenia estos campos:

- `primary_visible_subject`
- `visual_hierarchy`
- `palette_lighting`
- `negative_guardrails`

Eso era suficiente para escenas donde la pregunta principal era:

`Que sujeto debe verse claramente?`

Pero era insuficiente para escenas donde la pregunta real es:

`Que relacion visual debe entenderse?`

En escenas comparativas o explicativas, el sujeto principal no siempre es un objeto. A veces el sujeto principal es:

- una comparacion
- una escala
- una causa y su efecto
- un antes/despues
- un proceso
- una referencia visual que no aparece literalmente en `physical_composition`

## Solucion aplicada

Se amplio `visual_brief` a una version v2 con campos adicionales:

- `visual_purpose`
- `required_visual_elements`
- `layout_constraints`

El objetivo no es sobreajustar la direccion artistica. El objetivo es dar una brujula visual minima:

- que debe comunicar la imagen
- que elementos concretos no pueden faltar
- que restricciones flexibles protegen la lectura de la escena

## Nuevo contrato de visual_brief

Ahora una escena puede guardar un brief con esta forma:

```json
{
  "visual_purpose": "no-text cause/effect comparison between Earth lightning melting sand into glass and a Jovian discharge powering a small city-scale grid",
  "primary_visible_subject": "fused Earth sand/glass beside a readable small city power-grid silhouette energized by a Jovian discharge",
  "visual_hierarchy": "the two-part cause/effect comparison reads first, fused sand/glass second, glowing city grid powered by Jovian-scale discharge third",
  "required_visual_elements": "fused sand/glass, Jupiter storm clouds, ionized Jovian discharge, readable small city power-grid silhouette or city lights",
  "layout_constraints": "keep both effects readable; include the city/power-grid reference as a visible scale cue; do not let Jupiter become the only dominant subject",
  "palette_lighting": "warm orange fused glass, electric white-blue Jovian discharge, dark storm clouds and city lights",
  "negative_guardrails": "no missing city-scale reference, no Jupiter-only hero shot, no missing sand/glass, no abstract plasma only, no text, no meters, no labels"
}
```

## Cambios en backend

Archivo:

- `software_backend/aplicacion/endpoints/proceso4/__init__.py`

Cambios principales:

- Se agrego deteccion de escenas relacionales con `_is_relationship_visual_scene(...)`.
- Se consideran relacionales escenas con terminos como:
  - `Graphic`
  - `comparison`
  - `scale`
  - `before/after`
  - `cause-effect`
  - `process`
  - `times stronger`
  - `than Earth`
- Se amplio el prompt interno que se envia a Gemini para que devuelva:
  - `visual_purpose`
  - `required_visual_elements`
  - `layout_constraints`
- Se ajusto el fallback local para producir esos campos aunque Gemini falle.
- Se ajusto el refuerzo de anchors para no convertir escenas comparativas en un hero shot de un solo sujeto.

Regla importante agregada:

Si una escena dice algo como `power a small city`, Gemini debe incluir una referencia visual concreta, por ejemplo:

- `small city power-grid silhouette`
- `city lights`
- `urban energy reference`

Aunque esa referencia no este literalmente en `physical_composition`, porque es necesaria para entender la narracion.

## Cambios en templates

Archivo:

- `software_backend/aplicacion/endpoints/proceso4/prompt_templates.py`

Cambios principales:

- El bloque `==== VISUAL BRIEF OBLIGATORIO ====` ahora incluye:
  - `Proposito visual`
  - `Elementos visuales obligatorios`
  - `Restricciones de composicion`
- La regla critica ahora dice que la imagen sera incorrecta si:
  - no cumple el proposito visual
  - falta un elemento visual obligatorio
  - o el sujeto visible principal no se reconoce
- El prompt final directo de imagen tambien usa:
  - `Visual purpose`
  - `Required visual elements`
  - `Composition constraints`
- El negativo final agrega `no missing required visual elements` cuando corresponde.

## Cambios en frontend

Archivo:

- `software_website/src/app/proceso4/types/proceso4.types.ts`

Se extendio el tipo `visual_brief` con:

- `visual_purpose?: string`
- `required_visual_elements?: string`
- `layout_constraints?: string`

No se cambio la UI visual. Solo se actualizo el contrato de datos para que el frontend acepte los nuevos campos.

## Por que no es sobreajuste

Este cambio no fija coordenadas exactas ni obliga una composicion unica.

No le dice a la IA:

`pon Jupiter 70% a la izquierda y la ciudad 30% a la derecha`

Le dice:

`la referencia de ciudad/red electrica debe existir y ser legible`

Eso mantiene libertad visual, pero evita que el generador haga una imagen bonita que no comunica la idea cientifica.

La separacion queda asi:

- `visual_purpose`: mision de la imagen
- `required_visual_elements`: elementos concretos necesarios para entender la narracion
- `layout_constraints`: restricciones flexibles para proteger la lectura
- `negative_guardrails`: errores que destruirian la escena

## Resultado esperado

Para escenas comparativas o tipo `Graphic`, el sistema debe evitar:

- `Jupiter-only hero shot`
- referencia de Tierra escondida en una esquina
- comparaciones que no se leen como comparaciones
- plasma abstracto sin sujeto explicativo
- falta de ciudad/red electrica cuando la narracion habla de alimentar una ciudad
- prompts que se ven epicos pero no explican la frase del locutor

## Verificacion realizada

Se valido backend con:

```powershell
conda activate scieluxe
python -m py_compile software_backend\aplicacion\endpoints\proceso4\__init__.py software_backend\aplicacion\endpoints\proceso4\prompt_templates.py
```

Se valido el builder de prompts de forma aislada y se confirmo que:

- el meta-prompt incluye `Elementos visuales obligatorios`
- el prompt final incluye `Required visual elements`
- el negativo incluye `no missing required visual elements`

Se valido frontend con:

```powershell
npm run build
```

El build de `software_website` termino correctamente.

## Nota operativa

Los prompts ya guardados no se actualizan solos.

Para ver este comportamiento hay que volver a presionar `Regenerar` en la seccion correspondiente de `Prompt Station`.

Si una escena vuelve a salir visualmente bonita pero conceptualmente incompleta, revisar primero:

- `visual_purpose`
- `required_visual_elements`
- `layout_constraints`
- `negative_guardrails`

Antes de tocar el prompt final completo.
