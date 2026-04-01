"""
VidrioBot — Simulación End-to-End Completa
Ejecuta una conversación real, genera cotización, calcula intención y muestra todo.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent.conversation import ConversationState, FlowState, process_message
from backend.scoring.intent import score_conversation
from backend.quotation.engine import QuotationRequest, calculate_quotation
from backend.db.models import get_engine, init_db, Client, Conversation, Quotation
from datetime import datetime
import json

DIVIDER = "─" * 60

def print_exchange(user_msg: str, bot_reply: str):
    print(f"\n👤 CLIENTE: {user_msg}")
    print(f"\n🤖 BOT:\n{bot_reply}")
    print(DIVIDER)


def simulate_conversation():
    print("\n" + "═" * 60)
    print("  VIDIOBOT — SIMULACIÓN END-TO-END")
    print("═" * 60)

    # Inicializar estado
    state = ConversationState(
        conversation_id=1,
        phone="+52-871-555-0123",
    )

    # ── CONVERSACIÓN SIMULADA ─────────────────────────────────────
    # Flujo completo de un cliente con alta intención de compra

    exchanges = [
        # El cliente inicia (simula primer mensaje)
        "Hola, necesito cotización",
        # Bot pregunta nombre → cliente responde
        "Soy Roberto García",
        # Bot muestra menú de vidrios → cliente pide templado
        "2",  # Templado
        # Bot pide grosor → cliente responde
        "6",  # 6mm
        # Bot pide medidas
        "90x200",  # 90cm × 200cm
        # Bot pide cantidad
        "3",  # 3 piezas
        # Bot pide tipo de instalación
        "2",  # Puerta
        # Bot pregunta si quiere instalación
        "1",  # Con instalación
        # Bot pregunta urgencia
        "2",  # Mañana (+25%)
        # Bot pregunta ciudad
        "Torreón, Coahuila",
        # Bot muestra resumen → cliente confirma
        "1",  # Sí, generar cotización
        # Bot muestra cotización → cliente confirma compra
        "Sí quiero proceder, cuándo me lo instalan?",
    ]

    for user_msg in exchanges:
        response, state = process_message(state, user_msg)
        print_exchange(user_msg, response)

        # Si ya tenemos cotización, paramos el flujo normal y mostramos análisis
        if state.quotation_result and state.state.value == "show_quote":
            # Continuar con la confirmación
            continue

    # ── MOSTRAR COTIZACIÓN COMPLETA ───────────────────────────────
    if state.quotation_result:
        print("\n" + "═" * 60)
        print("  COTIZACIÓN GENERADA (vista interna / JSON)")
        print("═" * 60)
        print(json.dumps(state.quotation_result, indent=2, ensure_ascii=False))

    # ── ANÁLISIS DE INTENCIÓN ─────────────────────────────────────
    print("\n" + "═" * 60)
    print("  SCORING DE INTENCIÓN DE COMPRA")
    print("═" * 60)

    score = score_conversation(
        messages            = state.messages,
        quotation_generated = bool(state.quotation_result),
        response_time_avg_seconds = 18.0,  # Respondió rápido
    )

    print(f"  Score total  : {score.total:.1f} / 100")
    print(f"  Clasificación: {score.label.upper()}")
    print(f"  Notificar jefe: {'✅ SÍ' if score.should_notify_boss else '❌ NO'}")
    print(f"\n  Breakdown:")
    for k, v in score.breakdown.items():
        pts = v.get("pts", 0)
        sign = "+" if pts >= 0 else ""
        print(f"    {k:<35} {sign}{pts} pts")
    print(f"\n  {score.explanation}")

    # ── REGISTRO EN BASE DE DATOS ─────────────────────────────────
    print("\n" + "═" * 60)
    print("  REGISTRO EN BASE DE DATOS")
    print("═" * 60)

    engine = get_engine("sqlite:///./vidriobot_demo.db")
    SessionLocal = init_db(engine)
    db = SessionLocal()

    # Cliente
    client = Client(phone=state.phone, name=state.name, city=state.city)
    db.add(client)
    db.commit()
    db.refresh(client)
    print(f"  ✅ Cliente guardado  — ID: {client.id}, Nombre: {client.name}")

    # Conversación
    from backend.db.models import BuyIntent, ConversationStatus
    conv = Conversation(
        client_id    = client.id,
        status       = ConversationStatus.QUOTED,
        messages     = state.messages,
        intent_score = score.total,
        buy_intent   = BuyIntent(score.label),
        intent_detail= score.breakdown,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    print(f"  ✅ Conversación guardada — ID: {conv.id}, Mensajes: {len(state.messages)}")

    # Cotización
    if state.quotation_result:
        q = state.quotation_result
        quotation = Quotation(
            client_id         = client.id,
            conversation_id   = conv.id,
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
        )
        db.add(quotation)
        db.commit()
        db.refresh(quotation)
        print(f"  ✅ Cotización guardada  — Folio: {quotation.folio}, Total: ${quotation.total:,.2f} MXN")

    db.close()

    # ── NOTIFICACIÓN AL JEFE ──────────────────────────────────────
    if score.should_notify_boss:
        print("\n" + "═" * 60)
        print("  📱 NOTIFICACIÓN ENVIADA AL JEFE (simulada)")
        print("═" * 60)
        boss_msg = {
            "🔥 ALERTA": "Cliente con ALTA intención de compra",
            "Cliente":   state.name,
            "Teléfono":  state.phone,
            "Ciudad":    state.city,
            "Folio":     state.quotation_result["folio"] if state.quotation_result else "N/A",
            "Total":     f"${state.quotation_result['total']:,.2f} MXN" if state.quotation_result else "N/A",
            "Score":     f"{score.total:.0f}/100",
            "Acción":    "Contactar dentro de 2 horas para confirmar pedido",
        }
        print(json.dumps(boss_msg, indent=2, ensure_ascii=False))

    print("\n" + "═" * 60)
    print("  FIN DE SIMULACIÓN")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    simulate_conversation()
