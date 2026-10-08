"""Response and webhook payload shapes. They drive the generated OpenAPI file and docs pages,
so every field a customer can rely on is described here."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

BookingStatus = Literal["confirmed", "checked_in", "checked_out", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid"]
MessageStatus = Literal["queued", "sent", "delivered", "read", "failed", "received"]


class PageMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class Property(BaseModel):
    id: str
    name: str
    type: Optional[str] = Field(None, description="villa, caravan, room, ...")
    is_active: bool


class PropertyList(BaseModel):
    data: list[Property]


class PropertyRef(BaseModel):
    id: str
    name: str
    type: Optional[str] = None


class Guest(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = Field(None, description="E.164, e.g. +919876543210")
    email: Optional[str] = None


class Financials(BaseModel):
    stay_charge: float = Field(description="Price of the stay itself")
    addons_total: float
    total: float = Field(description="stay_charge + addons_total")
    paid: float = Field(description="Payments received minus refunds")
    outstanding: float = Field(description="total - paid, never below zero")
    payment_status: PaymentStatus


class NextPayment(BaseModel):
    amount: float
    due_date: str
    overdue: bool
    label: str


class AddOn(BaseModel):
    name: str
    quantity: int
    unit_price: float
    total: float


class Payment(BaseModel):
    id: str
    type: Literal["payment", "refund"]
    amount: float
    method: str = Field(description="upi, cash, card, bank_transfer, razorpay, other")
    reference: Optional[str] = None
    date: str


class ServiceRequest(BaseModel):
    id: str
    title: str
    status: Literal["open", "done"]
    due_date: Optional[str] = None


class Deposit(BaseModel):
    amount: float
    status: Literal["pending", "held", "released", "forfeited"]
    deducted: float


class Booking(BaseModel):
    id: str
    number: Optional[int] = Field(None, description="Short booking number shown in HAIP")
    status: BookingStatus
    channel: str = Field(description="direct, airbnb, booking, vrbo")
    property: Optional[PropertyRef] = None
    check_in: str = Field(description="YYYY-MM-DD")
    check_out: str = Field(description="YYYY-MM-DD (the guest leaves this morning)")
    nights: int
    check_in_time: Optional[str] = Field(None, description="HH:MM, local time")
    check_out_time: Optional[str] = None
    adults: int
    children: int
    guest: Optional[Guest] = None
    guest_message: Optional[str] = None
    reason_for_travel: Optional[str] = None
    concierge_notes: Optional[str] = Field(None, description="Notes for the on-site team")
    currency: str
    financials: Financials
    next_payment: Optional[NextPayment] = None
    addons: list[AddOn]
    payments: list[Payment]
    service_requests: list[ServiceRequest]
    deposit: Optional[Deposit] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BookingList(BaseModel):
    data: list[Booking]
    meta: PageMeta


class BookingResponse(BaseModel):
    data: Booking


class Template(BaseModel):
    name: str
    language: str
    category: str
    body: Optional[str] = Field(None, description="Template text with {{1}}, {{2}} placeholders")
    body_variables: int = Field(description="How many values `variables` must contain")
    header_variables: int = Field(description="Templates with header variables can't be sent through the API yet")


class TemplateList(BaseModel):
    data: list[Template]


class Message(BaseModel):
    id: str
    conversation_id: str
    channel: Literal["whatsapp", "instagram"]
    direction: Literal["inbound", "outbound"]
    status: MessageStatus = Field(description="Outbound: queued, sent, delivered, read or failed. Inbound: received")
    error: Optional[str] = Field(None, description="Why it failed, when status is failed")
    to: Optional[str] = None
    text: Optional[str] = None
    template_name: Optional[str] = None
    local_message_id: Optional[str] = Field(None, description="The id you supplied when sending")
    created_at: Optional[str] = None


class MessageResponse(BaseModel):
    data: Message
    idempotent_replay: Optional[bool] = Field(None, description="True when this local_message_id was already sent and the original is returned")


class MessageList(BaseModel):
    data: list[Message]
    meta: PageMeta


class ConversationRef(BaseModel):
    id: str
    channel: str
    is_open: bool
    last_message_at: Optional[str] = None
    reply_window_open: bool = Field(description="True while free-text replies are allowed (24 hours from the guest's last message)")


class ConversationList(BaseModel):
    data: list[ConversationRef]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[list[dict]] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ── Webhook events ───────────────────────────────────────────────────────────

class _Envelope(BaseModel):
    id: str = Field(description="Unique id of this event. The same event sent twice (a retry) has the same id: dedupe on it.")
    created_at: str


class BookingEvent(_Envelope):
    type: Literal["booking.created", "booking.updated", "booking.cancelled"]
    data: Booking


class PaymentReceived(BaseModel):
    id: str
    booking_id: str
    amount: float
    method: str
    reference: Optional[str] = None
    date: str
    via_gateway: bool = Field(description="True for online payments (Razorpay)")


class PaymentEvent(_Envelope):
    type: Literal["payment.received"]
    data: PaymentReceived


class MessageReceived(BaseModel):
    id: str
    conversation_id: str
    channel: Literal["whatsapp", "instagram"]
    guest: Optional[Guest] = None
    text: Optional[str] = None
    media_url: Optional[str] = None
    received_at: Optional[str] = None


class MessageReceivedEvent(_Envelope):
    type: Literal["message.received"]
    data: MessageReceived


class MessageStatusChange(BaseModel):
    id: str
    conversation_id: str
    channel: Literal["whatsapp", "instagram"]
    guest: Optional[Guest] = None
    status: MessageStatus
    error: Optional[str] = None
    template_name: Optional[str] = None
    local_message_id: Optional[str] = None


class MessageStatusEvent(_Envelope):
    type: Literal["message.status"]
    data: MessageStatusChange
