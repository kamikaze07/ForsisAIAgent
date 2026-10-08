# Forsis AI Agent — Esquema de Base de Datos Propia (PostgreSQL 16)

**Fecha:** 2026-10-05  
**Estado:** Especificación Técnica Completa (3NF, PKs, FKs, Índices e Integridad Referencial)  
**Motor de Persistencia:** PostgreSQL 16 Alpine  
**Base de Datos:** `forsis_agent`  

---

## 1. Principios de Diseño del Modelo de Datos

1. **Aislamiento Estricto:** La base de datos `forsis_agent` es completamente autónoma. Ningún dato operacional del ERP de Tráfico ni de SICRET se replica aquí permanentemente; solo se almacenan metadatos de contexto de sesión, referencias externas inmutables y trazas de auditoría.
2. **Normalización 3NF:** Todas las tablas cumplen la Tercera Forma Normal (3NF). Los campos compuestos o variantes dinámicas se persisten en columnas tipadas `JSONB` indexadas con GIN.
3. **Inmutabilidad de Auditoría:** Las tablas `audit_records` y `tool_executions` están diseñadas con semántica append-only para garantizar trazabilidad forense.
4. **Integridad Referencial y Cascada Controlada:** Las claves foráneas están formalmente definidas con reglas explícitas (`ON DELETE CASCADE` en elementos subordinados a sesión, y `ON DELETE RESTRICT` en auditorías y aprobaciones).
5. **Compatibilidad Vectorial:** Los embeddings para RAG se enlazan con `forsis-memory` (pgvector), manteniendo en `forsis_agent` el catálogo y metadatos de fragmentos indexados.

---

## 2. Diagrama Entidad-Relación Lógico (ERD)

```
┌────────────────────────┐         1:N         ┌────────────────────────┐
│     agent_sessions     ├────────────────────►│     agent_messages     │
└───────────┬────────────┘                     └────────────────────────┘
            │ 1:N
            │
            ▼
┌────────────────────────┐         1:1         ┌────────────────────────┐
│    tool_executions     ├────────────────────►│   approval_requests    │
└───────────┬────────────┘                     └────────────────────────┘
            │ 1:1 (opcional)
            ▼
┌────────────────────────┐
│     audit_records      │
└────────────────────────┘

┌────────────────────────┐         1:N         ┌────────────────────────┐
│     rag_documents      ├────────────────────►│      rag_chunks        │
└────────────────────────┘                     └────────────────────────┘

┌────────────────────────┐
│     agent_configs      │ (Clave-valor tipada con histórico de versiones)
└────────────────────────┘
```

---

## 3. Catálogo de Tablas y Definición Detallada

### 3.1 `agent_sessions`
Representa un hilo conversacional de usuario o una sesión de trabajo de tarea autónoma.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `UUID` | NO | Clave primaria generada por el agente |
| `channel_type` | `VARCHAR(32)` | NO | Origen del canal: `mattermost`, `web_widget`, `webhook`, `cli` |
| `channel_session_id` | `VARCHAR(128)` | NO | ID de hilo/canal en la plataforma externa (e.g. Mattermost Post Root ID) |
| `user_id` | `VARCHAR(64)` | NO | Identificador del usuario que interactúa |
| `user_role` | `VARCHAR(32)` | NO | Rol en el ERP: `operador`, `coordinador`, `director`, `sistema` |
| `state` | `VARCHAR(32)` | NO | Estado de la máquina: `active`, `waiting_approval`, `idle`, `closed`, `error` |
| `context_metadata` | `JSONB` | SÍ | Metadatos de contexto (viaje seleccionado, remolque, empresa activa) |
| `total_tokens_consumed`| `INTEGER` | NO | Contador acumulativo de tokens consumidos en la sesión |
| `created_at` | `TIMESTAMPTZ` | NO | Momento de creación |
| `updated_at` | `TIMESTAMPTZ` | NO | Última modificación |
| `closed_at` | `TIMESTAMPTZ` | SÍ | Momento de cierre formal de la sesión |

**Índices:**
- PK: `pk_agent_sessions` (`id`)
- `ix_sessions_channel`: (`channel_type`, `channel_session_id`)
- `ix_sessions_user`: (`user_id`, `state`)
- `ix_sessions_updated`: (`updated_at` DESC)

---

### 3.2 `agent_messages`
Historial cronológico de mensajes intercambiados en la sesión (roles `system`, `user`, `assistant`, `tool`).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `BIGSERIAL` | NO | Clave primaria incremental |
| `session_id` | `UUID` | NO | FK hacia `agent_sessions.id` |
| `role` | `VARCHAR(16)` | NO | `user`, `assistant`, `system`, `tool` |
| `content` | `TEXT` | SÍ | Contenido de texto en lenguaje natural o respuesta |
| `tool_calls` | `JSONB` | SÍ | LLM tool calls invocados en caso de respuesta del asistente |
| `tool_call_id` | `VARCHAR(64)` | SÍ | ID del call al que responde este mensaje (cuando role='tool') |
| `token_count` | `INTEGER` | SÍ | Tokens estimados o devueltos por el proveedor |
| `created_at` | `TIMESTAMPTZ` | NO | Timestamp inmutable de inserción |

**Índices:**
- PK: `pk_agent_messages` (`id`)
- `ix_messages_session_seq`: (`session_id`, `id` ASC)
- `ix_messages_tool_call_id`: (`tool_call_id`) WHERE `tool_call_id IS NOT NULL`

---

### 3.3 `tool_executions`
Registro estructurado de cada ejecución de herramienta operacional o analítica.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `UUID` | NO | Identificador único de la invocación |
| `session_id` | `UUID` | NO | FK hacia `agent_sessions.id` |
| `tool_name` | `VARCHAR(64)` | NO | Nombre técnico de la herramienta (e.g. `liberar_remolque_sicret`) |
| `category` | `VARCHAR(32)` | NO | Clasificación: `read_db`, `write_api`, `calculation`, `llm_rag` |
| `status` | `VARCHAR(32)` | NO | `proposed`, `approved`, `rejected`, `running`, `success`, `failed` |
| `requires_approval` | `BOOLEAN` | NO | Indicador si la herramienta altera estado operacional |
| `parameters_in` | `JSONB` | NO | Parámetros exactos con los que fue invocada la herramienta |
| `result_out` | `JSONB` | SÍ | Payload JSON devuelto tras ejecución exitosa |
| `error_message` | `TEXT` | SÍ | Detalle del error o excepción si falló |
| `execution_time_ms` | `INTEGER` | SÍ | Latencia en milisegundos de la ejecución |
| `created_at` | `TIMESTAMPTZ` | NO | Momento de solicitud/inicio |
| `completed_at` | `TIMESTAMPTZ` | SÍ | Momento de finalización |

**Índices:**
- PK: `pk_tool_executions` (`id`)
- `ix_tool_exec_session`: (`session_id`, `created_at` DESC)
- `ix_tool_exec_name_status`: (`tool_name`, `status`)
- `ix_tool_exec_pending`: (`status`) WHERE `status = 'proposed'`

---

### 3.4 `approval_requests`
Compuerta de aprobación humana requerida antes de disparar acciones de mutación en APIs del ERP.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `UUID` | NO | Clave primaria |
| `tool_execution_id` | `UUID` | NO | FK 1:1 hacia `tool_executions.id` |
| `session_id` | `UUID` | NO | FK hacia `agent_sessions.id` |
| `action_code` | `VARCHAR(64)` | NO | Código de la acción en `INDEX.yaml` (e.g. `ACT_LIBERAR_REMOLQUE`) |
| `summary` | `TEXT` | NO | Resumen en lenguaje claro de qué va a cambiar y en qué entidad |
| `requested_payload` | `JSONB` | NO | Cuerpo del request que se enviará al API si se aprueba |
| `risk_level` | `VARCHAR(16)` | NO | Nivel de riesgo operacional: `low`, `medium`, `high`, `critical` |
| `status` | `VARCHAR(16)` | NO | `pending`, `approved`, `rejected`, `expired` |
| `approver_user_id` | `VARCHAR(64)` | SÍ | Identificador del usuario que aprobó o rechazó |
| `approval_channel` | `VARCHAR(32)` | SÍ | Vía de respuesta: `mattermost_button`, `web_portal`, `cli` |
| `rejection_reason` | `TEXT` | SÍ | Justificación dada si la solicitud fue denegada |
| `expires_at` | `TIMESTAMPTZ` | NO | Límite temporal de vigencia (e.g. 15 minutos) |
| `responded_at` | `TIMESTAMPTZ` | SÍ | Momento en que el operador respondió |
| `created_at` | `TIMESTAMPTZ` | NO | Momento de generación |

**Índices:**
- PK: `pk_approval_requests` (`id`)
- UQ: `uq_approval_tool_execution`: (`tool_execution_id`)
- `ix_approvals_status_expires`: (`status`, `expires_at`)
- `ix_approvals_session`: (`session_id`)

---

### 3.5 `audit_records`
Bitácora inmutable de auditoría forense que documenta cada decisión, acceso a datos o mutación.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `BIGSERIAL` | NO | Clave primaria autoincremental |
| `event_uuid` | `UUID` | NO | UUID único inmutable del evento |
| `session_id` | `UUID` | SÍ | FK hacia `agent_sessions.id` |
| `tool_execution_id` | `UUID` | SÍ | FK hacia `tool_executions.id` |
| `event_type` | `VARCHAR(64)` | NO | Tipo: `SESSION_INIT`, `READ_QUERY`, `WRITE_API_MUTATION`, `APPROVAL_GRANTED`, `APPROVAL_DENIED`, `ANOMALY_DETECTED` |
| `actor_id` | `VARCHAR(64)` | NO | Agente (`forsis-agent-core`) o usuario humano |
| `target_entity` | `VARCHAR(64)` | SÍ | Entidad impactada: `remolque`, `despacho`, `guia`, `tarjeta_deudor` |
| `target_id` | `VARCHAR(64)` | SÍ | Identificador en el ERP (e.g. folio o ID de registro) |
| `details` | `JSONB` | NO | Detalle forense estructurado (queries ejecutados, cambios) |
| `ip_address` | `INET` | SÍ | IP de origen del cliente o llamador |
| `integrity_hash` | `VARCHAR(64)` | NO | SHA-256 HMAC del registro para garantizar inmutabilidad |
| `created_at` | `TIMESTAMPTZ` | NO | Timestamp UTC preciso con microsegundos |

**Índices:**
- PK: `pk_audit_records` (`id`)
- UQ: `uq_audit_event_uuid`: (`event_uuid`)
- `ix_audit_target`: (`target_entity`, `target_id`)
- `ix_audit_session_time`: (`session_id`, `created_at` DESC)
- `ix_audit_type_time`: (`event_type`, `created_at` DESC)
- `ix_audit_details_gin`: GIN (`details`)

---

### 3.6 `rag_documents` y `rag_chunks`
Catálogo de documentos de conocimiento normativo, manuales y políticas de Tráfico.

#### `rag_documents`
| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `UUID` | NO | Clave primaria |
| `title` | `VARCHAR(255)` | NO | Título legible del documento |
| `source_path` | `VARCHAR(512)` | NO | Ruta en disco o URL de origen |
| `doc_hash` | `VARCHAR(64)` | NO | SHA-256 del contenido para detectar modificaciones |
| `total_chunks` | `INTEGER` | NO | Número total de fragmentos generados |
| `created_at` | `TIMESTAMPTZ` | NO | Momento de indexación |
| `updated_at` | `TIMESTAMPTZ` | NO | Última reindexación |

**Índices:**
- PK: `pk_rag_documents` (`id`)
- UQ: `uq_rag_source_path`: (`source_path`)

#### `rag_chunks`
| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `UUID` | NO | Clave primaria |
| `document_id` | `UUID` | NO | FK hacia `rag_documents.id` (ON DELETE CASCADE) |
| `chunk_index` | `INTEGER` | NO | Posición secuencial dentro del documento |
| `content` | `TEXT` | NO | Fragmento de texto extraído |
| `vector_id` | `VARCHAR(128)` | SÍ | Identificador de referencia al vector en `forsis-memory` |
| `metadata` | `JSONB` | SÍ | Secciones, encabezados, palabras clave |
| `created_at` | `TIMESTAMPTZ` | NO | Momento de inserción |

**Índices:**
- PK: `pk_rag_chunks` (`id`)
- `ix_rag_chunks_doc`: (`document_id`, `chunk_index`)
- `ix_rag_chunks_meta_gin`: GIN (`metadata`)

---

### 3.7 `agent_configs`
Almacenamiento tipado de parámetros y configuración dinámica del agente con versionado y descripción.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `config_key` | `VARCHAR(64)` | NO | Clave única de configuración (e.g. `approval.timeout_minutes`) |
| `config_value` | `JSONB` | NO | Valor tipado en JSON |
| `value_type` | `VARCHAR(16)` | NO | `string`, `int`, `float`, `bool`, `json` |
| `description` | `VARCHAR(255)` | SÍ | Explicación funcional del parámetro |
| `is_secret` | `BOOLEAN` | NO | Si es `true`, no se expone en endpoints de inspección |
| `updated_by` | `VARCHAR(64)` | NO | Usuario o proceso que realizó el último ajuste |
| `updated_at` | `TIMESTAMPTZ` | NO | Fecha y hora de actualización |

**Índices:**
- PK: `pk_agent_configs` (`config_key`)

---

## 4. Script DDL de Inicialización PostgreSQL

El siguiente script DDL SQL completo se monta automáticamente en `./docker/db/init/01-init-schema.sql`:

```sql
-- ==============================================================================
-- FORSIS AI AGENT — ESQUEMA RELACIONAL (01-init-schema.sql)
-- Motor: PostgreSQL 16
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. SESIONES DE AGENTE
CREATE TABLE agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_type VARCHAR(32) NOT NULL,
    channel_session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_role VARCHAR(32) NOT NULL DEFAULT 'operador',
    state VARCHAR(32) NOT NULL DEFAULT 'active',
    context_metadata JSONB DEFAULT '{}'::jsonb,
    total_tokens_consumed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ NULL
);

CREATE INDEX ix_sessions_channel ON agent_sessions(channel_type, channel_session_id);
CREATE INDEX ix_sessions_user ON agent_sessions(user_id, state);
CREATE INDEX ix_sessions_updated ON agent_sessions(updated_at DESC);

-- 2. MENSAJES Y CONTEXTO
CREATE TABLE agent_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NULL,
    tool_calls JSONB NULL,
    tool_call_id VARCHAR(64) NULL,
    token_count INTEGER NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_messages_session_seq ON agent_messages(session_id, id ASC);
CREATE INDEX ix_messages_tool_call_id ON agent_messages(tool_call_id) WHERE tool_call_id IS NOT NULL;

-- 3. EJECUCIÓN DE HERRAMIENTAS
CREATE TABLE tool_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name VARCHAR(64) NOT NULL,
    category VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    parameters_in JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_out JSONB NULL,
    error_message TEXT NULL,
    execution_time_ms INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX ix_tool_exec_session ON tool_executions(session_id, created_at DESC);
CREATE INDEX ix_tool_exec_name_status ON tool_executions(tool_name, status);
CREATE INDEX ix_tool_exec_pending ON tool_executions(status) WHERE status = 'proposed';

-- 4. COMPUERTAS DE APROBACIÓN HUMANA
CREATE TABLE approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_execution_id UUID NOT NULL UNIQUE REFERENCES tool_executions(id) ON DELETE RESTRICT,
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    action_code VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    requested_payload JSONB NOT NULL,
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_user_id VARCHAR(64) NULL,
    approval_channel VARCHAR(32) NULL,
    rejection_reason TEXT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_approvals_status_expires ON approval_requests(status, expires_at);
CREATE INDEX ix_approvals_session ON approval_requests(session_id);

-- 5. AUDITORÍA INMUTABLE
CREATE TABLE audit_records (
    id BIGSERIAL PRIMARY KEY,
    event_uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    session_id UUID NULL REFERENCES agent_sessions(id) ON DELETE SET NULL,
    tool_execution_id UUID NULL REFERENCES tool_executions(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    target_entity VARCHAR(64) NULL,
    target_id VARCHAR(64) NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address INET NULL,
    integrity_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_audit_target ON audit_records(target_entity, target_id);
CREATE INDEX ix_audit_session_time ON audit_records(session_id, created_at DESC);
CREATE INDEX ix_audit_type_time ON audit_records(event_type, created_at DESC);
CREATE INDEX ix_audit_details_gin ON audit_records USING gin (details);

-- 6. DOCUMENTOS Y CHUNKS RAG
CREATE TABLE rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    source_path VARCHAR(512) NOT NULL UNIQUE,
    doc_hash VARCHAR(64) NOT NULL,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    vector_id VARCHAR(128) NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_rag_chunks_doc ON rag_chunks(document_id, chunk_index);
CREATE INDEX ix_rag_chunks_meta_gin ON rag_chunks USING gin (metadata);

-- 7. CONFIGURACIONES GLOBALES
CREATE TABLE agent_configs (
    config_key VARCHAR(64) PRIMARY KEY,
    config_value JSONB NOT NULL,
    value_type VARCHAR(16) NOT NULL DEFAULT 'string',
    description VARCHAR(255) NULL,
    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by VARCHAR(64) NOT NULL DEFAULT 'system',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
