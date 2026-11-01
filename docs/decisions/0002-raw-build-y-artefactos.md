# ADR-0002: separar datos brutos y build, y versionar artefactos derivados

## Contexto

Los datos brutos de SkillCorner pesan unos 350 MB para los 10 partidos (el tracking de cada partido son 32-43 MB en gz) y se alojan en GitHub LFS de un tercero, cuya cuota de ancho de banda no controlamos. Las bases de la competición excluyen "los datos" del repositorio, y el dataset es MIT.

Medido en el partido 114243: construir el tracking completo tarda 2,48 s de pared y unos 422 MB de RSS pico; el parquet resultante ocupa 19,0 MB y tiene 847 253 filas (77 023 frames no vacíos x 11 filas). El 47,6 % de los 146 870 frames están vacíos (tiempo muerto, cortes de realización) y no generan filas. El escritor acumula lotes de 50 000 frames en columnas, los concatena con `pl.concat` y escribe una sola vez con `write_parquet` (pyarrow no está instalado, así que no hay `ParquetWriter`); un sink por lotes queda como mejora posible. Los eventos se vuelcan a 20 tablas parquet por partido, en snake_case y con ids de jugador canónicos.

## Decisión

Se separan los datos brutos (`VENTAJA_DATA_DIR`, layout de SkillCorner, nunca se versionan) del build (`VENTAJA_BUILD_DIR`, parquet tidy). `ventaja data build` es idempotente y es la vía para recalcular desde cero. Cualquier capa lee parquet, nunca JSON.

Las capas posteriores versionarán en el repo los **artefactos derivados** (modelo entrenado, tablas de decisión por tiro, fichas de jugador; unos pocos MB) para que el jurado use la herramienta sin descargar los 350 MB.

Alternativas descartadas: (a) leer el JSON/JSONL directamente cada vez (30 s o más por partido y sin SQL); (b) versionar los datos brutos (prohibido por las bases y demasiado grande); (c) un fichero DuckDB en lugar de parquet (menos portable y Polars no lo lee directamente).

## Consecuencias

El build es rápido y reproducible, y el repo se mantiene pequeño. La CI ejecuta el pipeline real sobre un partido, con caché del raw, y de forma semanal sobre los 10.

Nota de shell: en zsh, `VAR=... time cmd` no se parsea; usar `env VAR=... time cmd` o ejecutar bajo bash.
