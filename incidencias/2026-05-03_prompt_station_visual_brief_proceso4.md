# Incidencia: visual brief por seccion en Prompt Station de Proceso 4

Fecha: 2026-05-03  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

En `Proceso 4`, los prompts de `Text-to-Image` del `Prompt Station` podian perder el sujeto visual principal de la escena, sobre todo en casos donde habia:

- una entidad grande y central en el titulo del video
- una accion localizada en el `visual_description`
- y materiales muy dominantes en `physical_composition`

El caso que disparo esta incidencia fue una escena de Jupiter donde el prompt terminaba privilegiando amoniaco, niebla y oscuridad, en vez de mantener a `Jupiter` como contexto visual reconocible.

Se implemento una capa nueva de `visual_brief` por escena, generada al presionar `Regenerar` por seccion, y luego usada para enriquecer el meta-prompt de `Text-to-Image`.

## Sintomas

- El `Prompt Station` generaba prompts formalmente correctos, pero visualmente ambiguos.
- En escenas como:

`A falling probe sinks through a 30-mile-thick layer of ammonia ice clouds into total darkness.`

el resultado tendia a empujar la IA hacia:

- niebla de amoniaco
- cristales
- fondo negro
- close-ups sin contexto planetario

- Aunque `Jupiter` aparecia en el titulo y en `physical_composition`, podia desaparecer de la jerarquia visual final.

## Causa raiz

`Prompt Station` construia los tres prompts por escena usando solo:

- `text`
- `visual_description`
- `visual_type`
- `duration`
- `physical_composition`

Eso funcionaba para describir materiales y accion, pero no alcanzaba para fijar una jerarquia visual fuerte.

En la practica faltaba una capa intermedia que respondiera:

- que debe verse primero
- que debe seguir visible aunque la escena ocurra "dentro" o "debajo" de algo
- que errores visuales se deben prohibir de forma explicita

## Solucion aplicada

### 1. Visual brief corto por escena

Se agrego una generacion de `visual_brief` por seccion dentro de:

- `POST /api/proceso4/jobs/<pid>/prompt-station/generate`

Al dar `Regenerar`, el backend ahora:

- toma todas las escenas de la seccion (`intro`, `parte1`, etc.)
- llama una vez a Gemini para obtener briefs cortos por escena
- normaliza y guarda el brief junto al prompt generado

Cada `visual_brief` contiene:

- `primary_visible_subject`
- `visual_hierarchy`
- `palette_lighting`
- `negative_guardrails`

### 2. Fallback local si Gemini falla

Si Gemini no responde, devuelve JSON invalido, o no cubre alguna escena:

- `Prompt Station` no se rompe
- la escena recibe un `visual_brief` local de fallback
- los prompts se siguen generando como antes

### 3. Refuerzo determinista para entidades del titulo

Se detecto que, aun con Gemini, podia salir un brief insuficiente para escenas como Jupiter.

Por eso se agrego un refuerzo en backend:

- si una entidad aparece tanto en el titulo del video como en `physical_composition`
- esa entidad se trata como `anchor` visual obligatorio

Para `Jupiter`, el backend ahora puede reinyectar automaticamente:

- contexto curvo/bandeado del planeta
- prioridad visual de Jupiter por encima de niebla o cristales
- negativos como `no missing Jupiter`, `no ammonia fog only`, `no close-up without planetary context`

Esto evita depender por completo de que Gemini interprete bien cada escena.

### 4. Enriquecimiento del meta-prompt de Text-to-Image

Se actualizo `build_text_to_image_prompt(...)` para aceptar:

- `visual_brief: dict | None = None`

Y se inserta una nueva seccion:

`==== VISUAL BRIEF OBLIGATORIO ====`

Con esto, el meta-prompt final obliga a la IA de prompts a:

- respetar el sujeto visible principal
- mantener jerarquia visual
- usar una paleta y luz alineadas con la escena
- incorporar errores visuales prohibidos dentro del negativo

### 5. Ajuste de tipos en frontend

Se extendio el tipo `ScenePrompts` del frontend para aceptar `visual_brief` dentro del payload de `Prompt Station`, sin cambiar la UI actual.

## Resultado

Despues del cambio:

- `Regenerar` sigue funcionando por seccion, no por todo el video
- cada escena obtiene una capa intermedia de direccion visual
- `Text-to-Image` queda mejor protegido contra escenas que se iban solo hacia niebla, oscuridad o texturas
- entidades centrales como `Jupiter` tienen mas probabilidad de permanecer visibles y reconocibles
- el sistema sigue operando incluso si Gemini falla

En pruebas sobre la escena de Jupiter:

- el primer intento del `visual_brief` aun fue debil y privilegio amoniaco/oscuridad
- luego se endurecio el prompt interno de Gemini y se agrego el refuerzo determinista
- el brief regenerado ya paso a incluir jerarquia con `Jupiter` primero y guardrails planetarios

## Verificacion realizada

- Se valido backend con:
  - `python -m py_compile software_backend/aplicacion/endpoints/proceso4/__init__.py`
  - `python -m py_compile software_backend/aplicacion/endpoints/proceso4/prompt_templates.py`
- Se valido frontend con:
  - `npm run build`
- Se probo el template de `Text-to-Image` de forma aislada y confirmo que:
  - incluye `VISUAL BRIEF OBLIGATORIO`
  - incorpora guardrails como `no missing Jupiter`
- Se confirmo que para ver el nuevo comportamiento hay que volver a usar `Regenerar` sobre la seccion, porque los prompts ya persistidos no se recalculan solos

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/__init__.py`
- `software_backend/aplicacion/endpoints/proceso4/prompt_templates.py`
- `software_website/src/app/proceso4/types/proceso4.types.ts`

## Nota operativa

Si una escena importante sigue saliendo demasiado "material" y poco "contexto", el siguiente lugar a revisar no es el prompt final de `Text-to-Image`, sino:

- el `visual_brief` generado
- el refuerzo de anchors entre `tema_principal` y `physical_composition`

En otras palabras: el punto critico del sistema ya no es solo el template final, sino la calidad de la jerarquia visual intermedia.
