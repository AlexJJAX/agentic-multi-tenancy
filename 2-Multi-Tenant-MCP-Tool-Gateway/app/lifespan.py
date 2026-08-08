"""Idempotent one-process bootstrap and application-owned resource cleanup."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from app.agent.graph import ChatResponseBackend, ChatService, OpenAIChatBackend
from app.agent.rag import TenantRAGService
from app.agent.tools import GatewayToolLoader
from app.audit.repository import AuditRepository
from app.auth.jwks import ensure_rsa_keypair
from app.auth.service import IdentityService
from app.auth.sessions import BrowserSessionRepository
from app.auth.tokens import JWKSCache, RSATokenAuthority
from app.gateway.registry import TargetRegistry
from app.gateway.routing import GatewayRouter
from app.gateway.service_tokens import ServiceTokenCache
from app.gateway.target_clients import OrdersHTTPClient, PropertiesMCPClient
from app.history.repository import HistoryRepository
from app.settings import Settings
from app.shared.runtime_secrets import RuntimeSecrets, load_or_create_runtime_secrets
from app.stores.order_store import EmbeddedOrderStore
from app.stores.property_store import SQLitePropertyStore
from app.stores.sqlite import SQLiteStore
from app.targets.orders.service import OrdersTargetService
from app.targets.properties.service import PropertiesTargetService
from app.tvm.service import TVMService


@dataclass
class AppRuntime:
    """Explicit application-owned dependencies shared by mounted components."""

    settings: Settings
    secrets: RuntimeSecrets
    store: SQLiteStore
    identity_authority: RSATokenAuthority
    gateway_authority: RSATokenAuthority
    identity: IdentityService
    gateway_user_jwks: JWKSCache
    properties_user_jwks: JWKSCache
    browser_sessions: BrowserSessionRepository
    audit: AuditRepository
    history: HistoryRepository
    rag: TenantRAGService
    order_store: EmbeddedOrderStore
    property_store: SQLitePropertyStore
    service_tokens: ServiceTokenCache
    tvm: TVMService
    orders_target: OrdersTargetService
    orders_client: OrdersHTTPClient
    properties_target: PropertiesTargetService
    properties_client: PropertiesMCPClient
    gateway_router: GatewayRouter
    chat: ChatService
    indexed_chunks: dict[str, int]
    ready: bool = False

    async def close(self) -> None:
        """Close application-owned clients and clear credential caches."""

        self.service_tokens.clear()
        await self.order_store.close()
        self.ready = False


@dataclass(frozen=True)
class RuntimeDependencies:
    """Optional model doubles supplied explicitly by automated tests."""

    embeddings: Embeddings | None = None
    chat_backend: ChatResponseBackend | None = None


async def build_runtime(
    settings: Settings,
    dependencies: RuntimeDependencies | None = None,
) -> AppRuntime:
    """Perform the complete idempotent local initialization sequence."""

    selected_dependencies = dependencies or RuntimeDependencies()
    if (
        selected_dependencies.embeddings is None
        or selected_dependencies.chat_backend is None
    ):
        settings.validate_runtime_requirements()
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "cache").mkdir(exist_ok=True)
    (settings.runtime_dir / "logs").mkdir(exist_ok=True)
    ensure_rsa_keypair(
        settings.identity_private_key_path,
        settings.identity_public_key_path,
        generate=settings.dev_generate_keys,
    )
    ensure_rsa_keypair(
        settings.gateway_capability_private_key_path,
        settings.gateway_capability_public_key_path,
        generate=settings.dev_generate_keys,
    )
    secrets = load_or_create_runtime_secrets(settings)
    store = SQLiteStore(settings.sqlite_path)
    if settings.dev_auto_migrate:
        store.migrate()
    if settings.dev_auto_seed:
        store.seed()
    identity_authority = RSATokenAuthority(
        settings.identity_private_key_path,
        settings.identity_public_key_path,
        settings.identity_issuer,
    )
    gateway_authority = RSATokenAuthority(
        settings.gateway_capability_private_key_path,
        settings.gateway_capability_public_key_path,
        "local-mcp-gateway",
    )
    identity = IdentityService(
        store=store,
        authority=identity_authority,
        settings=settings,
        secrets=secrets,
    )
    gateway_user_jwks = JWKSCache(identity_authority.jwks)
    properties_user_jwks = JWKSCache(identity_authority.jwks)
    browser_sessions = BrowserSessionRepository(store, settings.session_ttl_seconds)
    audit = AuditRepository(store)
    history = HistoryRepository(store)
    rag = TenantRAGService(
        settings=settings,
        store=store,
        embeddings=selected_dependencies.embeddings,
    )
    indexed_chunks = rag.initialize()
    order_store = EmbeddedOrderStore(gateway_authority)
    await order_store.seed()
    property_store = SQLitePropertyStore(store)
    service_tokens = ServiceTokenCache(identity)
    tvm = TVMService(
        identity=identity,
        gateway_authority=gateway_authority,
        settings=settings,
    )
    properties_target = PropertiesTargetService(
        identity=identity,
        user_jwks=properties_user_jwks,
        store=store,
        property_store=property_store,
        settings=settings,
    )
    properties_client = PropertiesMCPClient(
        settings=settings,
        in_process_service=properties_target,
    )
    orders_target = OrdersTargetService(
        identity=identity,
        gateway_authority=gateway_authority,
        token_cache=service_tokens,
        tvm=tvm,
        order_store=order_store,
        settings=settings,
        secrets=secrets,
    )
    orders_client = OrdersHTTPClient(
        settings=settings,
        in_process_service=orders_target,
    )
    gateway_router = GatewayRouter(
        registry=TargetRegistry.load(),
        token_cache=service_tokens,
        gateway_authority=gateway_authority,
        orders_client=orders_client,
        properties_client=properties_client,
        audit=audit,
        settings=settings,
        secrets=secrets,
    )
    tool_loader = GatewayToolLoader(settings)
    response_backend = selected_dependencies.chat_backend or OpenAIChatBackend(
        settings=settings,
        tool_loader=tool_loader,
    )
    chat = ChatService(
        settings=settings,
        rag=rag,
        history=history,
        gateway_router=gateway_router,
        audit=audit,
        response_backend=response_backend,
    )
    runtime = AppRuntime(
        settings=settings,
        secrets=secrets,
        store=store,
        identity_authority=identity_authority,
        gateway_authority=gateway_authority,
        identity=identity,
        gateway_user_jwks=gateway_user_jwks,
        properties_user_jwks=properties_user_jwks,
        browser_sessions=browser_sessions,
        audit=audit,
        history=history,
        rag=rag,
        order_store=order_store,
        property_store=property_store,
        service_tokens=service_tokens,
        tvm=tvm,
        orders_target=orders_target,
        orders_client=orders_client,
        properties_target=properties_target,
        properties_client=properties_client,
        gateway_router=gateway_router,
        chat=chat,
        indexed_chunks=indexed_chunks,
    )
    runtime.ready = (
        store.health()
        and rag.ready()
        and set(indexed_chunks) == {"tenant-A", "tenant-B"}
        and all(indexed_chunks.values())
    )
    if not runtime.ready:
        await runtime.close()
        raise RuntimeError("Application bootstrap did not satisfy readiness checks")
    return runtime
