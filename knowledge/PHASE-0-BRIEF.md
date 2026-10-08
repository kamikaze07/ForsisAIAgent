# Fase 0: Brief de Análisis

## Fecha
2026-10-03

## Agentes Asignados
- Agente 1: Análisis de trafico-system
- Agente 2: Análisis de liquidaciones-system
- Agente 3: Análisis de infraestructura Docker y servidor
- Agente 4: Análisis de integración Mattermost

## Objetivos de Análisis

### Agente 1: trafico-system
- Estructura de base de datos relevante
- APIs/endpoints disponibles
- Acciones ejecutables (guías, liberación SICRET, pases descarga)
- Sistema de autenticación/permisos actual
- Stack tecnológico y dependencias

### Agente 2: liquidaciones-system
- Estructura de base de datos relevante
- APIs/endpoints disponibles
- Acciones ejecutables (liquidaciones, reconciliación)
- Sistema de autenticación/permisos actual
- Stack tecnológico y dependencias

### Agente 3: Infraestructura Docker/Servidor
- Configuración actual de contenedores
- Redes Docker existentes
- Volúmenes y almacenamiento
- Recursos disponibles (CPU, RAM, disco)
- Puertos en uso
- Estrategia de despliegue para nuevo contenedor

### Agente 4: Mattermost
- API de Mattermost disponible
- Autenticación y permisos de bots
- Webhooks y capacidades de integración
- Usuarios/canales relevantes para el agente

## Entregables Esperados
Cada agente debe generar en `/home/servidor/forsis-ai-agent/knowledge/`:
- `{sistema}-analysis.md`: Análisis completo del sistema asignado
- `{sistema}-api-inventory.md`: Inventario de APIs/endpoints
- `{sistema}-actions.md`: Lista de acciones ejecutables
- Diagramas de arquitectura si son relevantes

---
