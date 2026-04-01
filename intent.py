"""
Intent Scoring — VidrioBot
Sistema de scoring basado en reglas heurísticas claras.
Cada señal tiene un peso definido. Total: 0–100 pts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re

# ─── Señales de alta intención ────────────────────────────────────────────────
HIGH_INTENT_KEYWORDS = [
    "comprar", "compro", "quiero pedir", "necesito urgente", "cuándo pueden",
    "cuándo instalan", "tienen disponible", "lo quiero", "lo necesito",
    "pedido", "apartarlo", "lo aparto", "confirmo", "procedo",
    "manden", "manda", "dale", "sí quiero", "sí procede",
    "esta semana", "hoy", "mañana", "lo antes posible", "urgent",
    "ya lo decidí", "vamos con eso",
]

MEDIUM_INTENT_KEYWORDS = [
    "cotización", "precio", "cuánto cuesta", "cuánto sale",
    "qué incluye", "tienen", "manejan", "hacen",
    "para ver", "para saber", "me interesa", "puede ser",
    "qué opciones", "qué tipos", "plazos",
]

LOW_INTENT_KEYWORDS = [
    "no sé", "todavía no", "por ahora no", "es para más adelante",
    "sólo me fijo", "sólo curiosidad", "no es urgente",
    "por si acaso", "nada más estoy viendo",
]

NEGATIVE_SIGNALS = [
    "no gracias", "ya no", "me canceló", "cancelar",
    "ya lo conseguí", "ya lo compré en otro lado",
]


@dataclass
class IntentScore:
    total: float                   # 0–100
    label: str                     # alta / media / baja
    breakdown: dict = field(default_factory=dict)
    explanation: str = ""

    @property
    def should_notify_boss(self) -> bool:
        return self.label == "alta"


def score_conversation(
    messages: list[dict],
    quotation_generated: bool = False,
    response_time_avg_seconds: Optional[float] = None,
) -> IntentScore:
    """
    Analiza la conversación completa y retorna un IntentScore.

    Factores y pesos:
    ─────────────────────────────────────────────────────────────────
    Factor                            Pts máx  Descripción
    ─────────────────────────────────────────────────────────────────
    1. Palabras de alta intención       +30    hits en mensajes cliente
    2. Cotización generada              +20    llegó al final del flujo
    3. Tiempo de respuesta rápido       +15    < 60 seg promedio
    4. Confirmaciones positivas         +15    "sí", "ok", "perfecto"
    5. Completitud de datos             +10    dio todas las medidas
    6. Señales de urgencia              +10    plazos cortos
    ─ Palabras de baja intención        −15
    ─ Señales negativas                 −30
    ─────────────────────────────────────────────────────────────────
    Total: 0–100
    """
    client_msgs = [m["content"].lower() for m in messages if m.get("role") == "user"]
    full_text   = " ".join(client_msgs)

    breakdown: dict = {}

    # 1. Alta intención en texto
    hi_hits = sum(1 for kw in HIGH_INTENT_KEYWORDS if kw in full_text)
    pts_hi  = min(hi_hits * 10, 30)
    breakdown["high_intent_keywords"] = {"hits": hi_hits, "pts": pts_hi}

    # 2. Cotización generada
    pts_quote = 20 if quotation_generated else 0
    breakdown["quotation_generated"] = {"pts": pts_quote}

    # 3. Tiempo de respuesta
    pts_speed = 0
    if response_time_avg_seconds is not None:
        if response_time_avg_seconds < 30:
            pts_speed = 15
        elif response_time_avg_seconds < 60:
            pts_speed = 10
        elif response_time_avg_seconds < 120:
            pts_speed = 5
    breakdown["response_speed"] = {
        "avg_seconds": response_time_avg_seconds,
        "pts": pts_speed
    }

    # 4. Confirmaciones positivas
    confirm_patterns = [r"\bsí\b", r"\bsi\b", r"\bok\b", r"\bperfecto\b",
                        r"\bde acuerdo\b", r"\bva\b", r"\bclaro\b",
                        r"\bexcelente\b", r"\bdale\b"]
    confirm_hits = sum(1 for p in confirm_patterns if re.search(p, full_text))
    pts_confirm  = min(confirm_hits * 5, 15)
    breakdown["confirmations"] = {"hits": confirm_hits, "pts": pts_confirm}

    # 5. Datos completos (medidas, tipo, etc.)
    data_signals = [
        r"\d+\s*(cm|metros?|mts?|m)\b",          # medidas
        r"\bgrosor\b|\bmm\b|\b\d+mm\b",           # grosor
        r"\bventana|puerta|mampara|cancel\b",      # tipo instalación
    ]
    data_hits = sum(1 for p in data_signals if re.search(p, full_text))
    pts_data  = min(data_hits * 4, 10)
    breakdown["data_completeness"] = {"signals": data_hits, "pts": pts_data}

    # 6. Urgencia
    urgency_patterns = [
        r"\bhoy\b", r"\bmañana\b", r"\burgente\b",
        r"\bcuanto antes\b", r"\besta semana\b", r"\blo antes posible\b"
    ]
    urgency_hits = sum(1 for p in urgency_patterns if re.search(p, full_text))
    pts_urgency  = min(urgency_hits * 5, 10)
    breakdown["urgency_signals"] = {"hits": urgency_hits, "pts": pts_urgency}

    # Penalizaciones
    li_hits  = sum(1 for kw in LOW_INTENT_KEYWORDS if kw in full_text)
    pts_li   = min(li_hits * 5, 15)
    breakdown["low_intent_keywords"] = {"hits": li_hits, "pts": -pts_li}

    neg_hits = sum(1 for kw in NEGATIVE_SIGNALS if kw in full_text)
    pts_neg  = min(neg_hits * 15, 30)
    breakdown["negative_signals"] = {"hits": neg_hits, "pts": -pts_neg}

    # Total
    raw = (pts_hi + pts_quote + pts_speed + pts_confirm +
           pts_data + pts_urgency - pts_li - pts_neg)
    total = max(0.0, min(100.0, float(raw)))

    # Clasificación
    if total >= 60:
        label = "alta"
        explanation = (
            "Cliente con alta probabilidad de cierre. "
            f"Score {total:.0f}/100. Notificar al jefe."
        )
    elif total >= 30:
        label = "media"
        explanation = (
            f"Cliente en fase de consideración. Score {total:.0f}/100. "
            "Seguimiento recomendado."
        )
    else:
        label = "baja"
        explanation = (
            f"Baja señal de compra. Score {total:.0f}/100. "
            "No notificar al jefe en este momento."
        )

    return IntentScore(
        total=total,
        label=label,
        breakdown=breakdown,
        explanation=explanation,
    )
