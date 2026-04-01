"""
VidrioBot — FastAPI Backend
Endpoints principales para WhatsApp webhook, cotizaciones, dashboard y reportes.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import json

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.models import (
    Client, Conversation, Quotation, BossNotification, DailyReport,
    BuyIntent, ConversationStatus, init_db, get_engine
)
from backend.agent.conversation import (
    ConversationState, FlowState, process_message
)
from backend.quotation.engine import QuotationRequest, calculate_quotation
from backend.scoring.intent import score_conversation

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="VidrioBot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine     = get_engine("sqlite:///./vidriobot.db")
SessionLocal = init_db(engine)

# In-memory conversation states (en prod: Redis)
_conv_states: dict[str, ConversationState] = {}
_conv_id_counter = 1


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class WhatsAppMessage(BaseModel):
    phone:   str
    message: str

class QuotationRequest_(BaseModel):
    glass_type:        str
    thickness:         str
    width_cm:          float
    height_cm:         float
    quantity:          int   = 1
    installation_type: str   = "otro"
    with_installation: bool  = False
    urgency_days:      int   = 7
    city:              str   = ""
    client_name:       str   = ""

class BossNotifyRequest(BaseModel):
    conversation_id: int


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_or_create_client(phone: str, db: Session) -> Client:
    client = db.query(Client).filter(Client.phone == phone).first()
    if not client:
        client = Client(phone=phone)
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def _save_quotation(conv: ConversationState, conv_db: Conversation, db: Session) -> Optional[Quotation]:
    q = conv.quotation_result
    if not q:
        return None
    quotation = Quotation(
        client_id         = conv_db.client_id,
        conversation_id   = conv_db.id,
        folio             = q["folio"],
        glass_type        = q["glass_type"],
        thickness         = q["thickness"],
        width_cm          = q["width_cm"],
        height_cm         = q["height_cm"],
        quantity          = q["quantity"],
        installation_type = q["installation_type"],
        with_installation = q["with_installation"],
        urgency_days      = q["urgency_days"],
        city              = q["city"],
        base_price        = q["base_price_m2"],
        area_m2           = q["area_m2"],
        material_cost     = q["material_cost"],
        installation_cost = q["installation_cost"],
        urgency_surcharge = q["urgency_surcharge"],
        subtotal          = q["subtotal"],
        iva               = q["iva"],
        total             = q["total"],
        pricing_detail    = q["breakdown"],
        valid_until       = datetime.fromisoformat(q["valid_until"]),
    )
    db.add(quotation)
    db.commit()
    db.refresh(quotation)
    return quotation


async def _notify_boss(conv_id: int, quotation_id: Optional[int], payload: dict, db: Session):
    """
    Envía notificación al jefe (WhatsApp / email).
    En producción: integrar con Twilio o WABA API aquí.
    """
    notif = BossNotification(
        conversation_id = conv_id,
        quotation_id    = quotation_id,
        channel         = "whatsapp",
        payload         = payload,
        success         = True,
    )
    db.add(notif)
    # Marcar conversación como notificada
    conv_db = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv_db:
        conv_db.notified_boss = True
    db.commit()
    # TODO: llamada real a Twilio / Meta API
    print(f"[BOSS NOTIFY] {json.dumps(payload, indent=2, ensure_ascii=False)}")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    msg: WhatsAppMessage,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Endpoint principal del bot. Simula recepción de WhatsApp Business API.
    En producción: Meta WABA envía POST a este endpoint.
    """
    global _conv_id_counter
    phone = msg.phone

    # Obtener o crear estado de conversación
    if phone not in _conv_states:
        client = _get_or_create_client(phone, db)
        conv_db = Conversation(client_id=client.id, messages=[])
        db.add(conv_db)
        db.commit()
        db.refresh(conv_db)
        _conv_id_counter = conv_db.id
        _conv_states[phone] = ConversationState(
            conversation_id=conv_db.id,
            phone=phone,
        )

    state = _conv_states[phone]

    # Procesar mensaje
    response, state = process_message(state, msg.message)
    _conv_states[phone] = state

    # Persistir conversación actualizada
    conv_db = db.query(Conversation).filter(Conversation.id == state.conversation_id).first()
    if conv_db:
        conv_db.messages   = state.messages
        conv_db.updated_at = datetime.utcnow()

        # Si ya hay cotización, actualizar intención
        if state.quotation_result and state.intent:
            score = state.intent
            conv_db.intent_score  = score["score"]
            conv_db.buy_intent    = BuyIntent(score["label"])
            conv_db.intent_detail = score["breakdown"]
            conv_db.status        = ConversationStatus.QUOTED

            # Guardar cotización si no existe
            existing = db.query(Quotation).filter(
                Quotation.conversation_id == conv_db.id
            ).first()
            if not existing:
                quotation = _save_quotation(state, conv_db, db)

                # Notificar al jefe solo si intención ALTA
                if score["label"] == "alta" and not conv_db.notified_boss:
                    payload = {
                        "alert": "🔥 Cliente con ALTA intención de compra",
                        "cliente": state.name or phone,
                        "telefono": phone,
                        "cotizacion": state.quotation_result,
                        "intent_score": score["score"],
                        "intent_detail": score["breakdown"],
                    }
                    background_tasks.add_task(
                        _notify_boss, conv_db.id,
                        quotation.id if quotation else None,
                        payload, db
                    )

        db.commit()

    return {"reply": response, "state": state.state.value}


@app.post("/quotation/calculate")
def calculate_quote(req: QuotationRequest_):
    """Cotización directa sin conversación (uso interno / API)."""
    r = QuotationRequest(**req.dict())
    result = calculate_quotation(r)
    if result.error:
        raise HTTPException(status_code=400, detail=result.error)
    return {
        "folio":    result.folio,
        "total":    result.total,
        "subtotal": result.subtotal,
        "iva":      result.iva,
        "breakdown":result.breakdown,
        "whatsapp": result.to_whatsapp(),
    }


@app.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """Datos para el dashboard principal."""
    total_convs   = db.query(Conversation).count()
    total_quotes  = db.query(Quotation).count()
    high_intent   = db.query(Conversation).filter(Conversation.buy_intent == BuyIntent.HIGH).count()
    medium_intent = db.query(Conversation).filter(Conversation.buy_intent == BuyIntent.MEDIUM).count()
    low_intent    = db.query(Conversation).filter(Conversation.buy_intent == BuyIntent.LOW).count()

    revenue_q = db.query(Quotation).all()
    potential_revenue = sum(q.total for q in revenue_q)

    # Top productos
    from collections import Counter
    product_counter = Counter(q.glass_type for q in revenue_q)
    top_products = [
        {"type": k, "count": v}
        for k, v in product_counter.most_common(5)
    ]

    conversion_rate = round(high_intent / total_convs * 100, 1) if total_convs else 0

    # Últimas cotizaciones
    recent_quotes = (
        db.query(Quotation)
        .order_by(Quotation.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "total_conversations": total_convs,
        "total_quotations":    total_quotes,
        "high_intent":         high_intent,
        "medium_intent":       medium_intent,
        "low_intent":          low_intent,
        "potential_revenue":   round(potential_revenue, 2),
        "conversion_rate":     conversion_rate,
        "top_products":        top_products,
        "recent_quotations": [
            {
                "folio":      q.folio,
                "glass_type": q.glass_type,
                "total":      q.total,
                "city":       q.city,
                "created_at": q.created_at.isoformat(),
            }
            for q in recent_quotes
        ],
    }


@app.get("/dashboard/trends")
def dashboard_trends(days: int = 7, db: Session = Depends(get_db)):
    """Tendencia diaria de cotizaciones e ingresos."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    quotes = (
        db.query(Quotation)
        .filter(Quotation.created_at >= cutoff)
        .order_by(Quotation.created_at)
        .all()
    )
    from collections import defaultdict
    daily: dict = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    for q in quotes:
        day = q.created_at.strftime("%Y-%m-%d")
        daily[day]["count"]   += 1
        daily[day]["revenue"] += q.total

    return [
        {"date": d, **v}
        for d, v in sorted(daily.items())
    ]


@app.post("/boss/notify/{conversation_id}")
async def manual_boss_notify(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Envío manual de notificación al jefe."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    client = db.query(Client).filter(Client.id == conv.client_id).first()
    quotation = db.query(Quotation).filter(Quotation.conversation_id == conversation_id).first()
    payload = {
        "alert":       "📤 Notificación manual al jefe",
        "cliente":     client.name if client else "Desconocido",
        "telefono":    client.phone if client else "",
        "intent":      conv.buy_intent,
        "score":       conv.intent_score,
        "total_quote": quotation.total if quotation else 0,
    }
    background_tasks.add_task(_notify_boss, conversation_id, quotation.id if quotation else None, payload, db)
    return {"status": "queued", "conversation_id": conversation_id}


@app.get("/health")
def health():
    return {"status": "ok", "service": "VidrioBot"}
