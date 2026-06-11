# Anfaia Jobs AI 🤖💼

Sistema autónomo **multiagente** que cada día busca **ofertas de empleo** de
tecnología e IA en varios portales, selecciona las más relevantes para una
comunidad técnica hispanohablante y las publica **contextualizadas en Discord**.
No copia el anuncio: lo **resume, lo estructura y aporta criterio** (qué harías,
qué piden de verdad, condiciones y por qué puede encajarte).

Hermano del [Anfaia News AI](https://github.com/ANFAIA/Anfaia-Bot-Daily-AI) y construido con la misma
**arquitectura hexagonal (puertos y adaptadores)**: la lógica de negocio es
independiente de proveedores (LLM, fuentes, base de datos, canal de
publicación) y puede evolucionar a frameworks de orquestación como
**LangGraph, CrewAI, DeepAgents o AutoGen** sin reescribir el dominio.

---

## ✨ Características

- **5 agentes** especializados que colaboran en un pipeline:
  1. **Job Collector** — recolecta de varias APIs/feeds, normaliza a `JobOffer`
     y aplica un pre-filtro por palabras clave (`JOB_KEYWORDS`).
  2. **Job Classifier** — clasifica (AI/ML, Data, Backend, Frontend, Fullstack,
     DevOps/Cloud, Mobile, Other), estima el seniority y puntúa la relevancia
     (0-100) para la comunidad.
  3. **Duplicate Detector** — evita repetir ofertas (URL exacta + similitud
     semántica por embeddings en PostgreSQL/pgvector, que caza la misma oferta
     cross-posteada en varios portales).
  4. **Job Editor** — convierte el anuncio en una ficha clara en español: qué
     harías, qué piden, condiciones y por qué puede interesarte.
  5. **Discord Publisher** — publica cada oferta como *embed* con reintentos y
     gestión de errores.
- **Varias ofertas por ejecución**: publica las `MAX_OFFERS_PER_RUN` mejores
  ofertas únicas de cada día (no solo una).
- **Prioridad Europa + cupo España**: las ofertas aplicables desde Europa
  reciben un *boost* en el ranking (`EUROPE_BOOST`, y la misma penalización si
  están restringidas a otras regiones), y cada ejecución reserva
  `SPAIN_OFFERS_PER_RUN` huecos para ofertas basadas en España (si ese día no
  hay ninguna única, el hueco vuelve al cupo general).
- **Máximo una oferta por empresa y ejecución**: una empresa que publica varios
  roles a la vez no monopoliza el lote del día (solo entra su mejor oferta).
- **Fuentes gratuitas sin API key**:
  - APIs JSON: [Remotive](https://remotive.com), [RemoteOK](https://remoteok.com)
    y [Arbeitnow](https://www.arbeitnow.com).
  - Feeds RSS por defecto: **SEPE / Portal Único de Empleo**
    (Informática/Telecomunicaciones), **We Work Remotely** (Programming +
    DevOps), [Himalayas](https://himalayas.app) y
    [Real Work From Anywhere](https://www.realworkfromanywhere.com).
  - Añade los tuyos con `JOB_RSS_FEEDS` (p. ej. **Tecnoempleo** genera un RSS
    por búsqueda, y [EmpleoRSS](https://www.empleorss.com/) crea feeds de
    Tecnoempleo por provincia).
- **Scheduler diario** (APScheduler) configurable por hora y zona horaria.
- **LLM intercambiable**: OpenAI, Anthropic u OpenRouter.
- **API REST** completa (FastAPI) para operar y observar el sistema.
- **Observabilidad**: logging estructurado (structlog), métricas y healthcheck.
- **Tests** unitarios y de integración con dobles (sin red ni base de datos).

---

## 🏗️ Arquitectura

```
app/
├── domain/          # Entidades y objetos de valor (núcleo, sin dependencias)
├── interfaces/      # Puertos: contratos abstractos (LLM, fuentes, repos, publisher, agente)
├── application/     # Casos de uso (orquestación de alto nivel)
├── agents/          # Los 5 agentes (dependen solo de puertos)
├── workflows/       # Orquestación: pipeline secuencial diario
├── infrastructure/  # Adapters concretos: llm/, embeddings/, sources/, discord/, scheduler/, persistence/
├── database/        # SQLAlchemy 2.x + repositorio PostgreSQL/pgvector
├── api/             # FastAPI: rutas + esquemas + dependencias
└── core/            # Config, logging, métricas, contenedor de DI
```

### Flujo del workflow

```
Collect Offers → Classify → Rank (prioridad Europa + cupo España)
   → Remove Duplicates → Edit Job Post → Publish to Discord → Save History
   (se repite hasta publicar MAX_OFFERS_PER_RUN ofertas)
```

### Por qué hexagonal

- El **dominio** (`domain/`) no conoce FastAPI, SQLAlchemy ni ningún SDK.
- Los **agentes** dependen de **puertos** (`interfaces/`), no de implementaciones.
- La **infraestructura** implementa esos puertos; cambiar de proveedor LLM, de
  base vectorial o de canal de publicación no toca la lógica de negocio.
- El **contenedor** (`core/container.py`) es el único *composition root* que
  ensambla todo a partir de la configuración.

---

## 🚀 Puesta en marcha con Docker (recomendado)

Requisitos: Docker y Docker Compose.

```bash
# 1. Configura el entorno
cp .env.example .env
# Edita .env y rellena al menos:
#   - OPENAI_API_KEY (o ANTHROPIC_API_KEY / OPENROUTER_API_KEY + LLM_PROVIDER)
#   - DISCORD_TOKEN y DISCORD_CHANNEL_ID

# 2. Levanta app + PostgreSQL (con pgvector)
docker compose up --build
```

El contenedor espera a PostgreSQL, aplica las migraciones Alembic y arranca la
API en `http://localhost:8001`. Documentación interactiva en
`http://localhost:8001/docs`.

> Los puertos del host (`8001` para la API, `5433` para PostgreSQL) están
> desplazados para poder convivir con el newsbot en la misma máquina.

---

## 🧑‍💻 Desarrollo local (sin Docker)

Requisitos: Python 3.12 y un PostgreSQL con la extensión `pgvector`
(`CREATE EXTENSION vector;`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # ajusta DATABASE_URL a tu PostgreSQL local

# Aplica migraciones
alembic upgrade head

# Arranca la API
uvicorn app.main:app --reload
```

> Necesitas una API key válida para el proveedor LLM activo (`LLM_PROVIDER`): la
> app no arranca sin ella. En cambio, los **embeddings** sí caen automáticamente
> al proveedor *hash* determinista (offline) si falta `OPENAI_API_KEY`. Y en
> tiempo de ejecución, si una **llamada** al LLM falla, los agentes degradan a
> heurísticas/fallbacks para no bloquear la publicación.

---

## 🔌 API REST

| Método | Ruta            | Descripción                                              |
|--------|-----------------|----------------------------------------------------------|
| GET    | `/health`       | Estado del servicio.                                     |
| GET    | `/jobs`         | Lista el histórico (filtros `limit`, `offset`, `category`). |
| GET    | `/jobs/{id}`    | Detalle de una oferta.                                   |
| POST   | `/workflow/run` | Ejecuta el pipeline completo bajo demanda.               |
| POST   | `/discord/test` | Publica un mensaje de prueba en Discord.                 |
| GET    | `/stats`        | Métricas: analizadas, publicadas, descartadas, por categoría, última ejecución. |

Ejemplos:

```bash
curl http://localhost:8001/health
curl -X POST http://localhost:8001/workflow/run
curl -X POST http://localhost:8001/discord/test -H 'Content-Type: application/json' -d '{"message":"Hola comunidad"}'
curl http://localhost:8001/stats
```

---

## ⚙️ Configuración (`.env`)

| Variable | Descripción | Por defecto |
|----------|-------------|-------------|
| `LLM_PROVIDER` | `openai` \| `anthropic` \| `openrouter` | `openai` |
| `LLM_MODEL` | Modelo del proveedor activo | `gpt-4o-mini` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | Claves de API | — |
| `EMBEDDING_PROVIDER` | `openai` \| `hash` | `openai` |
| `EMBEDDING_DIM` | Dimensión del vector | `1536` |
| `DUPLICATE_SIMILARITY_THRESHOLD` | Umbral coseno de duplicado | `0.90` |
| `DISCORD_TOKEN` / `DISCORD_CHANNEL_ID` | Credenciales de Discord | — |
| `SCHEDULER_ENABLED` | Activa la publicación diaria automática | `true` |
| `POST_TIME` | Hora de publicación diaria (HH:MM) | `10:00` |
| `TIMEZONE` | Zona horaria | `Europe/Madrid` |
| `MIN_RELEVANCE_SCORE` | Score mínimo para publicar | `55` |
| `MAX_OFFERS_PER_RUN` | Ofertas publicadas por ejecución | `3` |
| `EUROPE_BOOST` | Boost (±) en el ranking según se pueda aplicar desde Europa o no (solo ordena; el umbral usa el score bruto) | `15` |
| `SPAIN_OFFERS_PER_RUN` | Huecos reservados por ejecución para ofertas de España (0 lo desactiva) | `1` |
| `MAX_ITEMS_PER_SOURCE` | Ofertas recogidas por fuente | `25` |
| `JOB_KEYWORDS` | Pre-filtro por palabras clave (separadas por comas; vacío lo desactiva) | `ai,machine learning,...` |
| `REMOTIVE_ENABLED` / `REMOTEOK_ENABLED` / `ARBEITNOW_ENABLED` | Activan cada fuente | `true` |
| `REMOTIVE_CATEGORY` | Categoría de Remotive a consultar | `software-dev` |
| `JOB_RSS_FEEDS` | Feeds RSS: pares `Nombre\|URL` separados por comas (vacío = catálogo por defecto: SEPE, WWR, Himalayas, RWFA; definirla lo reemplaza) | — |
| `DATABASE_URL` | DSN async de PostgreSQL | se ensambla de `POSTGRES_*` |

> ⚠️ Si cambias `EMBEDDING_DIM`, regenera/migra la columna vectorial: la
> dimensión del vector en PostgreSQL es fija por migración.

---

## 🤖 Configurar el bot de Discord

1. Crea una aplicación y un bot en el [Discord Developer Portal](https://discord.com/developers/applications).
2. Copia el **token** del bot → `DISCORD_TOKEN`.
3. Invita el bot a tu servidor con permiso de **enviar mensajes** en el canal.
4. Activa el *Developer Mode* en Discord, clic derecho sobre el canal → *Copiar ID* → `DISCORD_CHANNEL_ID`.

---

## 🧪 Tests y calidad

```bash
pip install -e ".[dev]"

ruff check .          # linting
pytest                # tests
```

---

## 🛣️ Evolución futura

El mismo contrato `JobsWorkflow` (`app/workflows/base.py`) y el puerto `Agent`
(`app/interfaces/agent.py`) permiten añadir más motores (**LangGraph**,
**CrewAI**, **DeepAgents**, **AutoGen**) reutilizando los mismos agentes y
adapters, sin tocar dominio, persistencia ni API:

1. Crear `app/workflows/<framework>_jobs_workflow.py` que implemente `JobsWorkflow`.
2. Envolver cada `Agent` existente como nodo/tarea del framework.
3. Añadir la rama correspondiente en el contenedor de DI.

Otras extensiones naturales (espejo del newsbot): resumen semanal de ofertas en
HTML, alertas por categoría en hilos/canales separados, o búsqueda dirigida por
perfiles de la comunidad.

---

## 📄 Licencia

MIT.
