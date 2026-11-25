from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class OfferStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    CONFLICTING = "CONFLICTING"
    UNAVAILABLE = "UNAVAILABLE"
    NO_ANSWER = "NO_ANSWER"
    CALLBACK_PROMISED = "CALLBACK_PROMISED"


class ExtractedField(BaseModel):
    value: Any = None
    source_quote: str = ""
    confidence: float = 1.0


class Supplier(BaseModel):
    name: str
    phone: str
    region: str = "IN"
    locale: str = "en-IN"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Supplier phone number is required")
        return value


class RecoveryRequest(BaseModel):
    mode: Optional[str] = None
    chaos_scenario: Optional[str] = "standard"
    machine: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    part_description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    max_hours: float = Field(gt=0)
    downtime_cost_per_hour: float = Field(ge=0)
    compatibility_notes: str = ""
    suppliers: List[Supplier] = Field(min_length=1)
    available_technicians: int = Field(ge=0, default=3)
    required_technicians_override: Optional[int] = Field(default=None, ge=0)
    installation_minutes_override: Optional[int] = Field(default=None, ge=0)
    idempotency_key: Optional[str] = Field(default=None, min_length=1)
    live_confirmed: bool = False


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)


class TestCallRequest(BaseModel):
    phone: str
    supplier_name: str = "Test Supplier"

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return value.strip()


class Offer(BaseModel):
    supplier: str
    phone: str
    quantity_available: int = Field(ge=0, default=0)
    unit_price: float = Field(ge=0, default=0)
    currency: str = "INR"
    availability_hours: float = Field(ge=0, default=999)
    delivery_method: str = "unknown"
    compatible: bool = False
    compatibility_confidence: float = Field(ge=0, le=1, default=0)
    confirmed: bool = False
    status: str = "UNAVAILABLE"
    source: str = "demo"
    call_id: Optional[str] = None
    notes: str = ""
    transcript: str = ""
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0


class PlanLeg(BaseModel):
    supplier: str
    quantity: int
    unit_price: float
    arrival_hours: float
    delivery_method: str
    compatibility_confidence: float


class RecoveryPlan(BaseModel):
    legs: List[PlanLeg]
    total_purchase_cost: float
    material_arrival_hours: float
    installation_minutes: int
    recovery_time_hours: float
    downtime_exposure: float
    total_exposure: float
    compatibility_confidence: float
    required_technicians: int
    available_technicians: int
    feasible: bool
    infeasibility_reasons: List[str] = []
    required_technician_capability: Optional[str] = None
    installation_required: Optional[bool] = None
    technician_status: str = "not configured"
    plan_type: str = "best_expected"
    risk_adjusted: bool = False


class FaultEventRequest(BaseModel):
    machine_id: str = "cnc-line-4"
    fault_code: Optional[str] = None
    sensor_id: Optional[str] = None
    severity: str = "critical"
    message: Optional[str] = None
    telemetry_value: Optional[float] = None
    auto_start: bool = True
    mode: str = "demo"
    quantity: Optional[int] = None
    max_hours: Optional[float] = None
    downtime_cost_per_hour: Optional[float] = None
    available_technicians: Optional[int] = None

