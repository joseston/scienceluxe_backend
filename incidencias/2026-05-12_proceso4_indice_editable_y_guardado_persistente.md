# Incidencia: indice automatico editable y guardado persistente en Proceso 4

Fecha: 2026-05-12  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

En `Proceso 4` el indice automatico ya se generaba, pero los textos del bloque seguian siendo poco practicos de ajustar a mano.

El problema no era solo de UI. Tambien habia una separacion entre:

- lo que se veia en el panel de configuracion
- lo que mostraba el timeline
- lo que terminaba leyendo el render final

Eso hacia que editar un subtema o la pregunta retorica no siempre se sintiera persistente ni unificada.

## Sintomas

- Algunos subtemas del indice eran demasiado largos para verse comodos en pantalla.
- El usuario no tenia una forma clara de editar esos textos una vez generados.
- El timeline mostraba el bloque automatico, pero parecia depender de un estado distinto al render final.
- La pregunta retorica podia editarse, pero la accion de guardar no estaba claramente separada de la accion de recalcular el indice.
- Al volver a abrir otra pestaña, el estado podia verse desalineado si no se refrescaba todo el flujo.

## Causa raiz

### 1. El indice automatico no tenia una edicion persistente propia

El flujo original generaba:

- `subtemas`
- `indice_text`
- `pregunta_capciosa`

pero no ofrecía una edicion manual formal para el bloque del indice.

### 2. La UI mezclaba acciones distintas

El boton `Actualizar Indice` hacia dos cosas a la vez en la percepcion del usuario:

- recalcular el indice
- dejar la idea de que tambien guardaba cambios manuales

En realidad eran acciones distintas.

### 3. La fuente de verdad estaba repartida

El timeline toma datos de `auto_indice.output`.

El render final y el preview toman `SceneMedia.text_overlay`.

Sin una sincronizacion expresa, una edicion manual podia quedar visible en un lugar y no en el otro.

## Solucion aplicada

### 1. Edicion manual de subtemas del indice

Se agrego una tarjeta de edicion para los subtemas del indice en:

- `software_website/src/app/proceso4/components/AutoIndicePanel.tsx`

Ahora el usuario puede:

- abrir `Editar textos`
- modificar cada subtema
- guardar con `Guardar Cambios`

### 2. Guardado persistente en backend

Se agrego un endpoint para guardar los cambios del indice en:

- `software_backend/aplicacion/endpoints/proceso4/routes/indice.py`

Ese guardado actualiza:

- `auto_indice.output.subtemas`
- `auto_indice.output.indice_text`
- `Proceso4SceneMedia.text_overlay`

Con eso el cambio queda disponible para:

- timeline
- preview de escena
- render final

### 3. Conservacion de cambios manuales al recalcular

Se ajusto `auto_indice` para no pisar automaticamente una edicion manual ya guardada.

Eso permite seguir usando `Recalcular Indice` sin perder el texto refinado por el usuario.

### 4. Separacion clara de acciones

La interfaz ahora diferencia mejor:

- `Recalcular Indice`: vuelve a detectar escenas y subtemas
- `Guardar Cambios`: persiste la edicion manual del indice o de la pregunta retorica

### 5. Sincronizacion con el resto de Proceso 4

Se conecto la nueva edicion con el estado compartido del frontend para que el timeline reciba la version actualizada del indice sin quedarse mostrando datos viejos.

## Resultado

Despues del ajuste:

- los subtemas del indice ya pueden editarse de forma manual
- los textos mas largos se pueden acortar para mejorar legibilidad
- el cambio se refleja en timeline y render final
- el guardado queda claramente separado del recálculo automatico
- el indice automatico sigue siendo reutilizable, pero ya no borra la edicion humana por accidente

## Verificacion realizada

Backend:

- `python -m py_compile software_backend/aplicacion/endpoints/proceso4/routes/indice.py`

Frontend:

- `npm run build` en `software_website`

Validacion funcional:

- el panel muestra la edicion de subtemas del indice
- el cambio se puede guardar sin confundirlo con el recalcado automatico
- el timeline y el render final leen la misma version persistida

## Archivos tocados

- `software_backend/aplicacion/endpoints/proceso4/routes/indice.py`
- `software_website/src/app/proceso4/components/AutoIndicePanel.tsx`
- `software_website/src/app/proceso4/components/ConfigView.tsx`
- `software_website/src/app/proceso4/hooks/useProceso4.ts`
- `software_website/src/app/proceso4/page.tsx`
- `software_website/src/app/proceso4/services/proceso4.service.ts`

## Nota operativa

Si en una instalacion antigua el panel sigue mostrando informacion vieja, conviene refrescar la pagina completa para volver a leer el estado persistido desde backend.

Si despues se quiere permitir agregar o quitar subtemas, ya existe la base para hacerlo sin volver a rehacer el flujo principal.
