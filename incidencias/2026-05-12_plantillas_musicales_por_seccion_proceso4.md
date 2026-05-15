# Incidencia: plantillas musicales por seccion en Proceso 4

Fecha: 2026-05-12  
Proyecto: `Scienceluxe`  
Componentes: `software_backend`, `software_website`

## Resumen

En `Proceso 4` se necesitaba reutilizar la misma secuencia musical en varios videos futuros, manteniendo:

- la pista asignada por seccion
- el volumen por seccion
- los fades por seccion
- el `startOffset` de cada pista

La idea no era guardar esto como una edicion aislada de un solo video, sino como una plantilla global reutilizable por seccion.

## Problema que resuelve

Antes de esta mejora, la configuracion musical quedaba asociada al `job` actual del video.

Eso servia para un proyecto puntual, pero no para repetir una misma estructura musical en videos futuros sin volver a configurar todo manualmente.

Lo que se queria era poder:

- guardar una configuracion actual como plantilla
- aplicarla despues a otro video
- mantener la misma estructura por seccion

## Solucion aplicada

Se agrego un flujo de plantillas musicales reutilizables por seccion.

Cada plantilla guarda, por cada seccion:

- `pistaFilename`
- `volume`
- `fadeIn`
- `fadeOut`
- `startOffset`

En la UI de `Pistas musicales por seccion` se agrego una franja para:

- escribir el nombre de una nueva plantilla
- guardar la configuracion actual
- elegir una plantilla existente
- aplicarla al video actual

## Contrato tecnico

### Listar plantillas

```http
GET /api/proceso4/music-templates
```

Devuelve una lista de plantillas globales.

### Guardar plantilla

```http
POST /api/proceso4/music-templates
```

Entrada:

```json
{
  "name": "SciLuxe Base Espacial V1",
  "items": [
    {
      "section": "intro",
      "pistaFilename": "tokyorifft interstellar 374344",
      "volume": 0.18,
      "fadeIn": 1.0,
      "fadeOut": 2.0,
      "startOffset": 7.9
    }
  ]
}
```

### Aplicar plantilla a un video

```http
POST /api/proceso4/jobs/<pid>/music-templates/<template_id>/apply
```

Esta operacion borra las `section-tracks` actuales del job y recrea la configuracion usando la plantilla guardada.

## Problema encontrado durante la implementacion

Cuando se intento abrir la UI, el frontend mostraba:

- `Failed to fetch`

La llamada que fallaba era:

```http
GET /api/proceso4/music-templates
```

### Causa raiz

El backend ya tenia el codigo del endpoint, pero la tabla correspondiente no existia todavia en PostgreSQL:

- `proceso4_music_templates`
- `proceso4_music_template_items`

Por eso SQLAlchemy lanzaba:

- `sqlalchemy.exc.ProgrammingError`
- `psycopg2.errors.UndefinedTable`

## Correccion aplicada

Se agregaron dos migraciones:

### Start offset de pistas por seccion

```text
4f6b0f8a9c1d_add_start_offset_to_proceso4_section_tracks.py
```

### Plantillas musicales

```text
7a2d1c4e5f9b_add_music_templates_for_proceso4.py
```

Ademas, en la base local habia una desalineacion previa:

- la columna `start_offset` ya existia en `proceso4_section_tracks`
- pero Alembic seguia apuntando a una revision anterior

Se resolvio alineando la version de Alembic y aplicando despues la migracion de plantillas.

## Estado final

Despues de aplicar las migraciones:

- `GET /api/proceso4/music-templates` respondio `200`
- la tabla de plantillas quedo creada
- el panel de `Proceso 4` pudo cargar y listar plantillas sin error

## Archivos tocados

- `software_backend/aplicacion/models/proceso4/__init__.py`
- `software_backend/aplicacion/models/__init__.py`
- `software_backend/aplicacion/endpoints/proceso4/__init__.py`
- `software_backend/migrations/versions/4f6b0f8a9c1d_add_start_offset_to_proceso4_section_tracks.py`
- `software_backend/migrations/versions/7a2d1c4e5f9b_add_music_templates_for_proceso4.py`
- `software_website/src/app/proceso4/components/SectionTracksPanel.tsx`
- `software_website/src/app/proceso4/services/proceso4.service.ts`
- `software_website/src/app/proceso4/types/proceso4.types.ts`

## Verificacion realizada

Backend:

```powershell
conda run -n scienceluxe flask --app run.py db upgrade
```

Frontend:

```powershell
npm run build
```

Ambos pasaron correctamente despues de aplicar las migraciones.

## Nota operativa

Esta solucion esta pensada para reutilizar musica por seccion, no por escena.

Ese enfoque es el mas practico para videos futuros porque:

- la estructura por seccion cambia menos que la lista exacta de escenas
- el usuario puede conservar una base musical consistente
- se pueden seguir haciendo ajustes finos por video sin perder la plantilla general

