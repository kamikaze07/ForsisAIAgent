# Forsis AI Agent

Agente IA empresarial para asistir en operaciones de trafico-system y liquidaciones-system.

## Fase 0: Análisis de Infraestructura
**Fecha inicio:** 2026-10-03

### Objetivos del Proyecto
- Agente IA multimodal con capacidad de respuesta informativa, generación de reportes y ejecución de acciones
- Integración con trafico-system (ATLAS/SICRET: guías, liberación, pases descarga)
- Integración con liquidaciones-system (liquidaciones, reconciliación)
- Autenticación propia con sistema de permisos
- Widget de chat embebido en ambos sistemas
- Bot de Mattermost para acceso conversacional
- Stack: PHP/Laravel containerizado con BD propia
- Modelos IA: Omniroute API con combo "Forsis"

### Estructura del Proyecto
```
forsis-ai-agent/
├── knowledge/          # Documentación de análisis y arquitectura
├── docker/            # Configuración de contenedores
├── src/               # Código fuente del agente
├── widget/            # Widget JavaScript para chat embebido
└── mattermost-bot/    # Bot de Mattermost
```

### Fase Actual
**Fase 0:** Análisis de infraestructura existente y planificación arquitectónica

---
Generado: 2026-10-03
