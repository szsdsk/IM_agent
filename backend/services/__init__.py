"""
Backend Services
"""
from backend.services.llm_service import llm_service, LLMService
from backend.services.rocket_chat_service import rocket_chat_service, RocketChatService
from backend.services.affine_service import affine_service, AFFiNEService
from backend.services.deck_spec import DeckSpec, SlideSpec, create_default_deck
from backend.services.deck_renderer import slidev_renderer, pptx_renderer, render_deck
from backend.services.delivery_service import delivery_service, DeliveryService, DeliveryCard
from backend.services.sync_service import sync_service, SyncService, EventType

__all__ = [
    # LLM
    "llm_service",
    "LLMService",
    # IM
    "rocket_chat_service",
    "RocketChatService",
    # Doc
    "affine_service",
    "AFFiNEService",
    # PPT
    "DeckSpec",
    "SlideSpec",
    "create_default_deck",
    "slidev_renderer",
    "pptx_renderer",
    "render_deck",
    # Delivery
    "delivery_service",
    "DeliveryService",
    "DeliveryCard",
    # Sync
    "sync_service",
    "SyncService",
    "EventType",
]
