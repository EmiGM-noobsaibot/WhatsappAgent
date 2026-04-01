"""
Quotation Engine — VidrioBot
Lógica de precios clara, basada en reglas de negocio reales para vidriería.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import random
import string

# ─── Precios base por m² (MXN) por tipo y grosor ─────────────────────────────
# Fuente: precios representativos del mercado 2024 en ciudades medianas MX

BASE_PRICES: dict[str, dict[str, float]] = {
    "claro": {
        "3mm": 180, "4mm": 220, "6mm": 310, "8mm": 420,
        "10mm": 560, "12mm": 720,
    },
    "templado": {
        "6mm": 680, "8mm": 850, "10mm": 1050, "12mm": 1280,
    },
    "laminado": {
        "6mm": 750, "8mm": 920, "10mm": 1100, "12mm": 1380,
    },
    "espejo": {
        "3mm": 280, "4mm": 340, "6mm": 480, "8mm": 640,
    },
    "mate": {
        "4mm": 380, "6mm": 520, "8mm": 690,
    },
    "reflectante": {
        "6mm": 820, "8mm": 980, "10mm": 1200,
    },
    "vitral": {
        "4mm": 950, "6mm": 1200,
    },
}

# Mínimo cobrable (m²) — piezas pequeñas se cobran como 0.25 m²
MIN_AREA_M2 = 0.25

# Costo de instalación base por tipo (MXN por pieza)
INSTALLATION_COSTS: dict[str, float] = {
    "ventana":  350,
    "puerta":   550,
    "mampara":  750,
    "cancel":   900,
    "fachada": 1200,
    "mesa":     300,
    "estante":  200,
    "otro":     400,
}

# Recargos por urgencia
URGENCY_SURCHARGES: dict[int, float] = {
    1: 0.40,   # mismo día    → +40%
    2: 0.25,   # 2 días       → +25%
    3: 0.15,   # 3 días       → +15%
    7: 0.0,    # 1 semana     → normal
}

IVA_RATE = 0.16


@dataclass
class QuotationRequest:
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
    notes:             str   = ""


@dataclass
class QuotationResult:
    folio:             str
    request:           QuotationRequest
    area_m2:           float
    base_price_m2:     float
    material_cost:     float
    installation_cost: float
    urgency_surcharge: float
    subtotal:          float
    iva:               float
    total:             float
    breakdown:         dict  = field(default_factory=dict)
    valid_until:       datetime = field(default_factory=lambda: datetime.now() + timedelta(days=7))
    error:             Optional[str] = None

    def to_readable(self) -> str:
        r = self.request
        lines = [
            f"╔══════════════════════════════════════╗",
            f"║        COTIZACIÓN {self.folio}        ║",
            f"╚══════════════════════════════════════╝",
            f"",
            f"Cliente  : {r.client_name or 'Sin nombre'}",
            f"Fecha    : {datetime.now().strftime('%d/%m/%Y')}",
            f"Vigencia : {self.valid_until.strftime('%d/%m/%Y')}",
            f"",
            f"── ESPECIFICACIONES ──────────────────",
            f"  Tipo de vidrio : {r.glass_type.capitalize()}",
            f"  Grosor         : {r.thickness}",
            f"  Medidas        : {r.width_cm} cm × {r.height_cm} cm",
            f"  Cantidad       : {r.quantity} pza(s)",
            f"  Aplicación     : {r.installation_type.capitalize()}",
            f"  Instalación    : {'Sí' if r.with_installation else 'No'}",
            f"  Entrega        : {r.urgency_days} día(s)",
            f"",
            f"── DESGLOSE DE PRECIO ────────────────",
            f"  Área total     : {self.area_m2:.3f} m²",
            f"  Precio/m²      : ${self.base_price_m2:,.2f}",
            f"  Material       : ${self.material_cost:,.2f}",
        ]
        if self.installation_cost > 0:
            lines.append(f"  Instalación    : ${self.installation_cost:,.2f}")
        if self.urgency_surcharge > 0:
            lines.append(f"  Recargo urgencia: ${self.urgency_surcharge:,.2f}")
        lines += [
            f"  ─────────────────────────────────",
            f"  Subtotal       : ${self.subtotal:,.2f}",
            f"  IVA (16%)      : ${self.iva:,.2f}",
            f"  ═════════════════════════════════",
            f"  TOTAL          : ${self.total:,.2f} MXN",
            f"",
            f"* Precios en pesos mexicanos (MXN)",
            f"* Cotización válida hasta {self.valid_until.strftime('%d/%m/%Y')}",
        ]
        if r.notes:
            lines.append(f"* Nota: {r.notes}")
        return "\n".join(lines)

    def to_whatsapp(self) -> str:
        """Formato con emojis para WhatsApp."""
        r = self.request
        msg = (
            f"*📋 Cotización {self.folio}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔷 *Vidrio:* {r.glass_type.capitalize()} {r.thickness}\n"
            f"📐 *Medidas:* {r.width_cm}×{r.height_cm} cm\n"
            f"🔢 *Cantidad:* {r.quantity} pieza(s)\n"
            f"🛠 *Aplicación:* {r.installation_type.capitalize()}\n"
            f"{'🔧 *Instalación incluida*' if r.with_installation else '⚙️ Solo material'}\n"
            f"🚚 *Entrega:* {r.urgency_days} día(s)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Material: ${self.material_cost:,.2f}\n"
        )
        if self.installation_cost > 0:
            msg += f"🔧 Instalación: ${self.installation_cost:,.2f}\n"
        if self.urgency_surcharge > 0:
            msg += f"⚡ Urgencia: +${self.urgency_surcharge:,.2f}\n"
        msg += (
            f"📊 Subtotal: ${self.subtotal:,.2f}\n"
            f"🧾 IVA: ${self.iva:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *TOTAL: ${self.total:,.2f} MXN*\n"
            f"📅 Vigencia: {self.valid_until.strftime('%d/%m/%Y')}\n\n"
            f"_¿Deseas proceder con el pedido?_"
        )
        return msg


def _generate_folio() -> str:
    year  = datetime.now().year
    chars = ''.join(random.choices(string.digits, k=4))
    return f"COT-{year}-{chars}"


def _get_urgency_surcharge_rate(days: int) -> float:
    for threshold in sorted(URGENCY_SURCHARGES.keys()):
        if days <= threshold:
            return URGENCY_SURCHARGES[threshold]
    return 0.0


def calculate_quotation(req: QuotationRequest) -> QuotationResult:
    """
    Calcula cotización completa para una solicitud de vidrio.
    Retorna QuotationResult con error != None si la combinación no es válida.
    """
    # Validar tipo + grosor
    available = BASE_PRICES.get(req.glass_type, {})
    if not available:
        return QuotationResult(
            folio=_generate_folio(), request=req,
            area_m2=0, base_price_m2=0, material_cost=0,
            installation_cost=0, urgency_surcharge=0,
            subtotal=0, iva=0, total=0,
            error=f"Tipo de vidrio '{req.glass_type}' no disponible."
        )

    price_m2 = available.get(req.thickness)
    if price_m2 is None:
        available_thicknesses = ", ".join(available.keys())
        return QuotationResult(
            folio=_generate_folio(), request=req,
            area_m2=0, base_price_m2=0, material_cost=0,
            installation_cost=0, urgency_surcharge=0,
            subtotal=0, iva=0, total=0,
            error=(
                f"Grosor {req.thickness} no disponible para vidrio {req.glass_type}. "
                f"Opciones: {available_thicknesses}"
            )
        )

    # Área (mínimo cobrable)
    area_raw = (req.width_cm / 100) * (req.height_cm / 100)
    area_unit = max(area_raw, MIN_AREA_M2)
    area_total = area_unit * req.quantity

    material_cost = price_m2 * area_total

    # Instalación
    install_unit  = INSTALLATION_COSTS.get(req.installation_type, 400)
    install_cost  = (install_unit * req.quantity) if req.with_installation else 0.0

    # Urgencia
    urgency_rate      = _get_urgency_surcharge_rate(req.urgency_days)
    urgency_surcharge = material_cost * urgency_rate

    subtotal = material_cost + install_cost + urgency_surcharge
    iva      = subtotal * IVA_RATE
    total    = subtotal + iva

    breakdown = {
        "area_unit_m2":     round(area_unit, 4),
        "area_total_m2":    round(area_total, 4),
        "price_m2":         price_m2,
        "material_cost":    round(material_cost, 2),
        "install_unit":     install_unit,
        "install_cost":     round(install_cost, 2),
        "urgency_rate_pct": urgency_rate * 100,
        "urgency_surcharge":round(urgency_surcharge, 2),
        "subtotal":         round(subtotal, 2),
        "iva":              round(iva, 2),
        "total":            round(total, 2),
    }

    return QuotationResult(
        folio            = _generate_folio(),
        request          = req,
        area_m2          = round(area_total, 4),
        base_price_m2    = price_m2,
        material_cost    = round(material_cost, 2),
        installation_cost= round(install_cost, 2),
        urgency_surcharge= round(urgency_surcharge, 2),
        subtotal         = round(subtotal, 2),
        iva              = round(iva, 2),
        total            = round(total, 2),
        breakdown        = breakdown,
    )
