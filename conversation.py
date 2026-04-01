"""
Conversational Agent — VidrioBot
State-machine para guiar al cliente a través del flujo de cotización.
No depende de LLM para el flujo principal; usa Claude API solo para
interpretación de lenguaje natural en inputs ambiguos.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re
from datetime import datetime

from backend.quotation.engine import (
    QuotationRequest, calculate_quotation,
    BASE_PRICES, INSTALLATION_COSTS
)
from backend.scoring.intent import score_conversation, IntentScore


# ─── Estados del flujo ────────────────────────────────────────────────────────

class FlowState(str, Enum):
    GREETING          = "greeting"
    ASK_GLASS_TYPE    = "ask_glass_type"
    ASK_THICKNESS     = "ask_thickness"
    ASK_DIMENSIONS    = "ask_dimensions"
    ASK_QUANTITY      = "ask_quantity"
    ASK_INSTALL_TYPE  = "ask_install_type"
    ASK_WITH_INSTALL  = "ask_with_install"
    ASK_URGENCY       = "ask_urgency"
    ASK_CITY          = "ask_city"
    ASK_NAME          = "ask_name"
    CONFIRM           = "confirm"
    SHOW_QUOTE        = "show_quote"
    CLOSE             = "close"
    FALLBACK          = "fallback"


# ─── Estado de conversación ───────────────────────────────────────────────────

@dataclass
class ConversationState:
    conversation_id:   int
    phone:             str
    state:             FlowState = FlowState.GREETING
    messages:          list      = field(default_factory=list)
    started_at:        datetime  = field(default_factory=datetime.utcnow)

    # Datos recolectados
    name:              Optional[str]   = None
    glass_type:        Optional[str]   = None
    thickness:         Optional[str]   = None
    width_cm:          Optional[float] = None
    height_cm:         Optional[float] = None
    quantity:          int             = 1
    installation_type: Optional[str]   = None
    with_installation: bool            = False
    urgency_days:      int             = 7
    city:              Optional[str]   = None

    # Resultado
    quotation_result:  Optional[dict]  = None
    intent:            Optional[dict]  = None

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role, "content": content,
            "ts": datetime.utcnow().isoformat()
        })

    def to_quotation_request(self) -> QuotationRequest:
        return QuotationRequest(
            glass_type        = self.glass_type        or "claro",
            thickness         = self.thickness         or "6mm",
            width_cm          = self.width_cm          or 100,
            height_cm         = self.height_cm         or 100,
            quantity          = self.quantity,
            installation_type = self.installation_type or "otro",
            with_installation = self.with_installation,
            urgency_days      = self.urgency_days,
            city              = self.city              or "",
            client_name       = self.name              or "",
        )


# ─── Utilidades de parsing ────────────────────────────────────────────────────

GLASS_ALIASES = {
    "claro": ["claro", "normal", "transparente", "simple", "común"],
    "templado": ["templado", "reforzado", "seguridad"],
    "laminado": ["laminado", "pvb", "anti-robo", "antirobo"],
    "espejo": ["espejo", "mirror"],
    "mate": ["mate", "esmerilado", "opaco", "satinado"],
    "reflectante": ["reflectante", "espejado", "solar"],
    "vitral": ["vitral", "decorativo", "de color"],
}

THICKNESS_ALIASES = {
    "3mm": ["3mm", "3 mm", "3"],
    "4mm": ["4mm", "4 mm", "4"],
    "6mm": ["6mm", "6 mm", "6"],
    "8mm": ["8mm", "8 mm", "8"],
    "10mm": ["10mm", "10 mm", "10"],
    "12mm": ["12mm", "12 mm", "12"],
}

INSTALL_ALIASES = {
    "ventana": ["ventana", "ventanas"],
    "puerta": ["puerta", "puertas"],
    "mampara": ["mampara", "mamparas", "baño", "ducha", "regadera"],
    "cancel": ["cancel", "canceles", "separador", "división"],
    "fachada": ["fachada", "exterior", "edificio"],
    "mesa": ["mesa", "mesas", "cubierta"],
    "estante": ["estante", "repisa", "librero"],
    "otro": ["otro", "otros", "no sé"],
}

def _match_alias(text: str, aliases: dict) -> Optional[str]:
    t = text.lower().strip()
    for key, vals in aliases.items():
        if any(v in t for v in vals):
            return key
    return None

def _parse_dimensions(text: str) -> tuple[Optional[float], Optional[float]]:
    """Extrae dimensiones de texto como '90x120', '90 por 120', '90cm x 120cm'."""
    text = text.lower().replace("×", "x").replace("por", "x")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm)?\s*[x*]\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    # Intento 2: "ancho 90 alto 120"
    w = re.search(r"ancho[:\s]+(\d+(?:\.\d+)?)", text)
    h = re.search(r"alto[:\s]+(\d+(?:\.\d+)?)", text)
    if w and h:
        return float(w.group(1)), float(h.group(1))
    return None, None

def _parse_quantity(text: str) -> Optional[int]:
    match = re.search(r"\b(\d+)\s*(?:pieza|pza|vidrio|hoja|unidad)?s?\b", text.lower())
    if match:
        return int(match.group(1))
    words = {"una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4,
             "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "diez": 10}
    for w, n in words.items():
        if w in text.lower():
            return n
    return None

def _parse_urgency(text: str) -> int:
    t = text.lower()
    if any(w in t for w in ["hoy", "mismo día", "urgente", "ya"]):
        return 1
    if "mañana" in t:
        return 2
    if "3 días" in t or "tres días" in t:
        return 3
    if any(w in t for w in ["semana", "7 días", "siete días"]):
        return 7
    return 7  # default


# ─── Máquina de estados ───────────────────────────────────────────────────────

GLASS_MENU = (
    "¿Qué tipo de vidrio necesitas? 👇\n"
    "1️⃣ Claro (uso general)\n"
    "2️⃣ Templado (seguridad, baños, puertas)\n"
    "3️⃣ Laminado (anti-robo, auto)\n"
    "4️⃣ Espejo\n"
    "5️⃣ Mate / Esmerilado\n"
    "6️⃣ Reflectante (fachadas)\n"
    "7️⃣ Vitral / Decorativo\n\n"
    "Escribe el número o el nombre 😊"
)

GLASS_NUMBERS = {
    "1": "claro", "2": "templado", "3": "laminado",
    "4": "espejo", "5": "mate", "6": "reflectante", "7": "vitral"
}

INSTALL_MENU = (
    "¿Para qué aplicación es?\n"
    "1️⃣ Ventana\n2️⃣ Puerta\n3️⃣ Mampara / Baño\n"
    "4️⃣ Cancel\n5️⃣ Fachada\n6️⃣ Mesa / Cubierta\n"
    "7️⃣ Estante / Repisa\n8️⃣ Otro"
)

INSTALL_NUMBERS = {
    "1": "ventana", "2": "puerta", "3": "mampara",
    "4": "cancel", "5": "fachada", "6": "mesa", "7": "estante", "8": "otro"
}


def process_message(state: ConversationState, user_input: str) -> tuple[str, ConversationState]:
    """
    Procesa un mensaje del usuario y retorna (respuesta, estado_actualizado).
    """
    state.add_message("user", user_input)
    text = user_input.strip()
    response = _handle_state(state, text)
    state.add_message("assistant", response)
    return response, state


def _handle_state(state: ConversationState, text: str) -> str:
    s = state.state

    # ── GREETING ──────────────────────────────────────────────────
    if s == FlowState.GREETING:
        state.state = FlowState.ASK_NAME
        return (
            "¡Hola! 👋 Bienvenido a *Vidrios Martínez*.\n"
            "Soy tu asistente de cotización. Te ayudo a obtener "
            "el precio de tu vidrio en minutos. 🪟\n\n"
            "¿Cuál es tu nombre?"
        )

    # ── NOMBRE ────────────────────────────────────────────────────
    if s == FlowState.ASK_NAME:
        # Limpiar "soy", "me llamo", "mi nombre es"
        clean = re.sub(r"^(soy|me llamo|mi nombre es)\s+", "", text.strip(), flags=re.IGNORECASE)
        state.name  = clean.strip().split()[0].capitalize()
        state.state = FlowState.ASK_GLASS_TYPE
        return (
            f"Mucho gusto, *{state.name}*! 😊\n\n"
            + GLASS_MENU
        )

    # ── TIPO DE VIDRIO ────────────────────────────────────────────
    if s == FlowState.ASK_GLASS_TYPE:
        glass = GLASS_NUMBERS.get(text.strip()) or _match_alias(text, GLASS_ALIASES)
        if not glass:
            return "No reconocí ese tipo. " + GLASS_MENU
        state.glass_type = glass
        available = BASE_PRICES.get(glass, {})
        thicknesses = " | ".join(available.keys())
        state.state = FlowState.ASK_THICKNESS
        return (
            f"Perfecto, vidrio *{glass}* ✅\n\n"
            f"¿Qué grosor necesitas?\nDisponibles: *{thicknesses}*\n\n"
            f"Escribe solo el número (ej: *6*)"
        )

    # ── GROSOR ────────────────────────────────────────────────────
    if s == FlowState.ASK_THICKNESS:
        available = BASE_PRICES.get(state.glass_type, {})
        # normalize input "6" → "6mm"
        t_input = text.strip()
        if not t_input.endswith("mm"):
            t_input += "mm"
        if t_input not in available:
            opts = " | ".join(available.keys())
            return f"Grosor no disponible para {state.glass_type}. Opciones: *{opts}*"
        state.thickness = t_input
        state.state     = FlowState.ASK_DIMENSIONS
        return (
            f"Grosor *{t_input}* ✅\n\n"
            "📐 ¿Cuáles son las medidas?\n"
            "Escríbelas como *ancho × alto* en centímetros.\n"
            "Ejemplo: *90x120* o *90 x 120 cm*"
        )

    # ── DIMENSIONES ───────────────────────────────────────────────
    if s == FlowState.ASK_DIMENSIONS:
        w, h = _parse_dimensions(text)
        if not w or not h:
            return (
                "No pude leer las medidas 😅\n"
                "Por favor escríbelas así: *ancho x alto* en cm\n"
                "Ejemplo: *80x100*"
            )
        state.width_cm  = w
        state.height_cm = h
        state.state     = FlowState.ASK_QUANTITY
        return (
            f"Medidas *{w}×{h} cm* ✅\n\n"
            "¿Cuántas piezas necesitas?"
        )

    # ── CANTIDAD ──────────────────────────────────────────────────
    if s == FlowState.ASK_QUANTITY:
        q = _parse_quantity(text)
        if not q:
            return "¿Cuántas piezas? Escribe solo el número (ej: *2*)"
        state.quantity = q
        state.state    = FlowState.ASK_INSTALL_TYPE
        return (
            f"*{q} pieza(s)* ✅\n\n"
            + INSTALL_MENU
        )

    # ── TIPO DE INSTALACIÓN ───────────────────────────────────────
    if s == FlowState.ASK_INSTALL_TYPE:
        it = INSTALL_NUMBERS.get(text.strip()) or _match_alias(text, INSTALL_ALIASES)
        if not it:
            return "No reconocí la aplicación.\n" + INSTALL_MENU
        state.installation_type = it
        state.state = FlowState.ASK_WITH_INSTALL
        return (
            f"Aplicación: *{it}* ✅\n\n"
            "🔧 ¿Requieres *instalación incluida* o solo el vidrio?\n"
            "1️⃣ Con instalación\n"
            "2️⃣ Solo el vidrio"
        )

    # ── ¿CON INSTALACIÓN? ─────────────────────────────────────────
    if s == FlowState.ASK_WITH_INSTALL:
        t = text.lower()
        if any(w in t for w in ["1", "con", "incluida", "sí", "si", "instala"]):
            state.with_installation = True
        else:
            state.with_installation = False
        state.state = FlowState.ASK_URGENCY
        return (
            ("Con instalación ✅\n\n" if state.with_installation else "Solo vidrio ✅\n\n")
            + "⏱ ¿Para cuándo lo necesitas?\n"
              "1️⃣ Hoy (urgente +40%)\n"
              "2️⃣ Mañana (+25%)\n"
              "3️⃣ En 3 días (+15%)\n"
              "4️⃣ Esta semana (precio normal)"
        )

    # ── URGENCIA ──────────────────────────────────────────────────
    if s == FlowState.ASK_URGENCY:
        days_map = {"1": 1, "2": 2, "3": 3, "4": 7}
        days = days_map.get(text.strip()) or _parse_urgency(text)
        state.urgency_days = days
        state.state        = FlowState.ASK_CITY
        return "Perfecto ✅\n\n📍 ¿En qué ciudad o colonia es la entrega?"

    # ── CIUDAD ────────────────────────────────────────────────────
    if s == FlowState.ASK_CITY:
        state.city  = text.strip().title()
        state.state = FlowState.CONFIRM
        # Resumen antes de cotizar
        wi   = "Sí" if state.with_installation else "No"
        return (
            f"¡Listo! Antes de cotizar, confirma los datos:\n\n"
            f"🔷 Vidrio: *{state.glass_type}* {state.thickness}\n"
            f"📐 Medidas: *{state.width_cm}×{state.height_cm} cm*\n"
            f"🔢 Cantidad: *{state.quantity}*\n"
            f"🛠 Aplicación: *{state.installation_type}*\n"
            f"🔧 Instalación: *{wi}*\n"
            f"📍 Ciudad: *{state.city}*\n"
            f"⏱ Entrega: *{state.urgency_days} día(s)*\n\n"
            f"¿Los datos son correctos?\n"
            f"1️⃣ Sí, generar cotización\n"
            f"2️⃣ No, corregir"
        )

    # ── CONFIRMACIÓN ──────────────────────────────────────────────
    if s == FlowState.CONFIRM:
        t = text.lower()
        if any(w in t for w in ["2", "no", "corregir", "cambiar"]):
            state.state = FlowState.ASK_GLASS_TYPE
            return "Claro, empecemos de nuevo.\n\n" + GLASS_MENU
        # Generar cotización
        req    = state.to_quotation_request()
        result = calculate_quotation(req)
        if result.error:
            return f"❌ Error al calcular: {result.error}\nContáctanos directamente al teléfono."
        # Score de intención
        score = score_conversation(
            messages              = state.messages,
            quotation_generated   = True,
        )
        state.intent           = {
            "score": score.total,
            "label": score.label,
            "breakdown": score.breakdown,
            "explanation": score.explanation,
        }
        state.quotation_result = {
            "folio":              result.folio,
            "glass_type":         state.glass_type,
            "thickness":          state.thickness,
            "width_cm":           state.width_cm,
            "height_cm":          state.height_cm,
            "quantity":           state.quantity,
            "installation_type":  state.installation_type,
            "with_installation":  state.with_installation,
            "urgency_days":       state.urgency_days,
            "city":               state.city,
            "area_m2":            result.area_m2,
            "base_price_m2":      result.base_price_m2,
            "material_cost":      result.material_cost,
            "installation_cost":  result.installation_cost,
            "urgency_surcharge":  result.urgency_surcharge,
            "subtotal":           result.subtotal,
            "iva":                result.iva,
            "total":              result.total,
            "valid_until":        result.valid_until.isoformat(),
            "breakdown":          result.breakdown,
        }
        state.state = FlowState.SHOW_QUOTE
        return result.to_whatsapp()

    # ── MOSTRAR COTIZACIÓN ────────────────────────────────────────
    if s == FlowState.SHOW_QUOTE:
        t = text.lower()
        if any(w in t for w in ["sí", "si", "proceder", "confirmo", "quiero", "dale", "ok", "1"]):
            state.state = FlowState.CLOSE
            score_label = state.intent.get("label", "media") if state.intent else "media"
            if score_label == "alta":
                extra = "\n\n⭐ *Nuestro equipo te contactará muy pronto* para coordinar tu pedido."
            else:
                extra = "\n\n📞 Un asesor te contactará para confirmar detalles."
            return (
                f"¡Excelente, {state.name}! 🎉\n"
                f"Tu solicitud ha sido registrada con folio *{state.quotation_result['folio']}*.\n"
                f"Nos pondremos en contacto contigo a la brevedad.{extra}\n\n"
                f"¡Gracias por contactar a *Vidrios Martínez*! 🙌"
            )
        elif any(w in t for w in ["no", "2", "otra", "diferente", "cambiar"]):
            state.state = FlowState.ASK_GLASS_TYPE
            return "Por supuesto, hagamos otra cotización.\n\n" + GLASS_MENU
        else:
            return (
                "¿Deseas proceder con este pedido?\n"
                "1️⃣ Sí, quiero continuar\n"
                "2️⃣ No, quiero otra cotización"
            )

    # ── CLOSE / FALLBACK ─────────────────────────────────────────
    if s in (FlowState.CLOSE, FlowState.FALLBACK):
        return (
            "Tu solicitud ya fue registrada. 😊\n"
            "Si tienes otra pregunta, escríbenos.\n"
            "¡Hasta pronto! 👋"
        )

    return (
        "Disculpa, no entendí bien. 😅\n"
        "Escribe *hola* para iniciar una nueva cotización."
    )
