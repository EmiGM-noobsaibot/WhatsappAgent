# 1. Descripción del sistema
VidrioBot es un agente conversacional de WhatsApp para negocios de vidriería. El cliente escribe por WhatsApp, el bot lo guía en ~12 intercambios para recopilar especificaciones, genera una cotización con precios reales, clasifica la intención de compra y notifica al jefe solo cuando el cliente es de alta probabilidad de cierre.

# 2. Arquitectura
**WhatsApp (Meta API)**
       │  `POST /webhook/whatsapp`
       ▼
  **FastAPI Backend**
  ┌─────────────────────────────────────────┐
  │  Agent Layer      (state machine)       │
  │  Quotation Engine (pricing rules)       │
  │  Intent Scorer    (rule-based scoring)  │
  │  DB Layer         (SQLAlchemy ORM)      │
  └──────────────┬──────────────────────────┘
                 │
         **SQLite (dev) / PostgreSQL (prod)**
                 │
         **Dashboard HTML/React**

**Flujo de datos end-to-end:**

- Cliente envía mensaje → Meta WABA hace POST al webhook
- FastAPI recupera/crea ConversationState en memoria (Redis en prod)
- La máquina de estados procesa el input y retorna respuesta
- Al completar los datos, el QuotationEngine calcula precio
- El IntentScorer evalúa la conversación completa (0–100 pts)
- Todo se persiste en DB (Cliente → Conversación → Cotización)
- Si score ≥ 60 → BossNotification se envía async por WhatsApp


# 3. Stack tecnológico
| Capa | Tecnología | Justificación |
|---|---|---|
| Backend API | FastAPI | Async nativo, tipado, rápido |
| ORM / DB | SQLAlchemy + SQLite/PostgreSQL | Sin cambios de código al escalar |
| Canal | Meta WhatsApp Business API | Oficial y escalable |
| Estado conversacional | Dict en memoria → Redis | Simple en dev, escalable en prod |
| Dashboard | HTML + Chart.js | Sin build tooling, embebible |
| Hosting | Railway / Render / VPS | ~$10 USD/mes para este volumen |

# 4. Lógica del agente
La máquina de estados tiene 13 estados bien definidos:
`GREETING` → `ASK_NAME` → `ASK_GLASS_TYPE` → `ASK_THICKNESS` → `ASK_DIMENSIONS` → `ASK_QUANTITY` → `ASK_INSTALL_TYPE` → `ASK_WITH_INSTALL` → `ASK_URGENCY` → `ASK_CITY` → `CONFIRM` → `SHOW_QUOTE` → `CLOSE`

No se necesita LLM para el flujo principal. El LLM (Claude API) se integraría opcionalmente para interpretar inputs ambiguos o manejar preguntas fuera del flujo estándar.

# 5. Sistema de cotización
**Fórmula:**
```
área_total = max(ancho × alto, 0.25m²) × cantidad
material   = precio_m² × área_total
instalación= costo_instalación_tipo × cantidad  (si aplica)
urgencia   = material × recargo_urgencia (0–40%)
subtotal   = material + instalación + urgencia
total      = subtotal × 1.16  (IVA)
```
Precios base varían por tipo (claro $180/m² hasta vitral $1,200/m²) y grosor. Los recargos de urgencia son +15% (3 días), +25% (2 días) y +40% (mismo día).

# 6. Detección de intención
Sistema de 6 factores con pesos que suma 0–100 puntos:

| Factor | Pts máx | Ejemplo señal |
|---|---|---|
| Palabras de alta intención | 30 | "quiero pedirlo", "urgente" |
| Cotización completada | 20 | Llegó al estado SHOW_QUOTE |
| Velocidad de respuesta | 15 | < 30 seg promedio |
| Confirmaciones positivas | 15 | "sí", "dale", "perfecto" |
| Datos completos | 10 | Dio medidas en cm + tipo |
| Urgencia explícita | 10 | "para mañana", "hoy" |
| Señales negativas | −30 | "ya lo compré en otro lado" |

**Resultado:** `≥60` = alta (notifica jefe), `30–59` = media, `<30` = baja.

# 7. Base de datos
5 tablas relacionadas: `clients` → `conversations` → `quotations`, más `boss_notifications` y `daily_reports`. El esquema completo está en `backend/db/models.py`. Cada cotización guarda el breakdown completo de precio en JSON para auditoría.

# 8. Código
El proyecto está completamente implementado en `/home/claude/vidriobot/`:
```
vidriobot/
├── backend/
│   ├── agent/conversation.py    ← máquina de estados
│   ├── quotation/engine.py      ← precios y cotizaciones
│   ├── scoring/intent.py        ← clasificación de cliente
│   ├── db/models.py             ← esquema SQLAlchemy
│   └── api/main.py              ← FastAPI endpoints
├── simulate.py                  ← demo end-to-end
└── requirements.txt
```
La simulación ejecutada arriba mostró una conversación real con Roberto García: 3 puertas de vidrio templado 6mm con instalación urgente en Torreón → Cotización $7,238.40 MXN generada exitosamente.

# 9. Dashboard
El dashboard interactivo arriba muestra métricas en tiempo real con datos simulados realistas. Es completamente responsive y tiene:

- 5 tarjetas de métricas clave
- Gráfica de tendencia con barras + línea (cotizaciones + ingresos)
- Distribución de productos (doughnut chart)
- Cotizaciones por ciudad (barras horizontales)
- Intención de compra con barra visual
- Tabla de cotizaciones recientes con botón "Notificar jefe"
- Selector de período (7d / 30d / 90d)


# 10. Extras: mejoras futuras y escalabilidad
**Corto plazo:**

- Reemplazar el parsing de nombre con `re.search` más robusto (ya corregido en el código)
- Integrar Claude API para manejar preguntas fuera del flujo ("¿tienen vidrio curvo?")
- Redis para estado conversacional en múltiples workers

**Mediano plazo:**

- Modelo ML de intención con datos históricos reales (XGBoost sobre features de conversación)
- Envío real de PDF con cotización vía WhatsApp
- Panel de administración para editar precios base sin tocar código

**Largo plazo:**

- Multi-tenant (varias vidrierías en el mismo sistema)
- CRM integrado con seguimiento post-cotización
- Predicción de demanda con series de tiempo

El sistema completo es desplegable en un VPS de $10 USD/mes o Railway con un solo comando `uvicorn backend.api.main:app`. Se ejecutaron 2 comandos, archivo leído. Sistema completo entregado. Aquí está el resumen de lo que tienes:
~1,550 líneas de Python funcional en 6 archivos, ejecutable desde hoy:

- `simulate.py` — corre la demo completa: conversación → cotización → scoring → DB. Ejecútalo con `python simulate.py` desde la carpeta del proyecto
- `agent/conversation.py` — máquina de 13 estados, parsing de medidas, menús por número, flujo completo sin LLM
- `quotation/engine.py` — precios reales por m², recargos de urgencia, IVA, formato WhatsApp y texto plano
- `scoring/intent.py` — 6 factores con pesos claros, explicación legible por el jefe
- `db/models.py` — esquema relacional completo con SQLAlchemy
- `api/main.py` — webhook de WhatsApp, endpoint de cotización directa, datos del dashboard

Para levantar el servidor: `pip install -r requirements.txt && uvicorn backend.api.main:app --reload`. El webhook espera en `POST /webhook/whatsapp` con `{"phone": "+52...", "message": "Hola"}`.