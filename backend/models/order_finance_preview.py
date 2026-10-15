"""Read-only quotation contracts. A preview neither admits nor pays an order."""

from typing import Annotated, Literal

from pydantic import Field

from models.order_finance import FinanceContract, FinancialCreateRequest, Identifier, MoneyBani
from models.order_mutation import MAX_ORDER_VERSION, StrictOrderCreate
from models.order_remakes import RemakeItem


class CreateFinancePreview(FinanceContract):
    order: StrictOrderCreate
    financial: FinancialCreateRequest


class RemakeFinancePreview(FinanceContract):
    expected_order_version: Annotated[int, Field(strict=True, ge=0, le=MAX_ORDER_VERSION)]
    problem_type: Literal["missing_product", "new_product"]
    description: Annotated[str, Field(min_length=3, max_length=1000)]
    items: list[RemakeItem] = Field(min_length=1, max_length=200)
    payment_type: Literal["CASH", "CARD"]
    collection_basis: Literal["new_receipt", "prepaid_new_order"]
    client_collection_bani: MoneyBani
    advance_required_bani: MoneyBani
    financial: FinancialCreateRequest


class FinanceCapabilities(FinanceContract):
    contract_version: Literal[1] = 1
    actor_id: Identifier
    restaurant_id: Identifier
    finance_enabled: bool
    create_quote_enabled: bool
    remake_quote_enabled: bool
    quote_informational: Literal[True] = True
    supported_basis: list[Literal["zone"]] = Field(default_factory=lambda: ["zone"])


class TariffMetadata(FinanceContract):
    version: Identifier
    currency: Literal["RON"]
    zone_ids: list[Identifier] = Field(max_length=500)


class FinanceTariffs(FinanceContract):
    contract_version: Literal[1] = 1
    actor_id: Identifier
    restaurant_id: Identifier
    tariffs: list[TariffMetadata] = Field(max_length=50)


class FinancePreview(FinanceContract):
    contract_version: Literal[1] = 1
    kind: Literal["create", "remake"]
    informational: Literal[True] = True
    # Stable across workers using a domain-separated server key. Rotation requires
    # a new preview; F1 never accepts this fingerprint as an admission token.
    fingerprint_scope: Literal["server_key_v1"] = "server_key_v1"
    quote_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    actor_id: Identifier
    restaurant_id: Identifier
    parent_order_id: Identifier | None
    parent_order_version: Annotated[int, Field(strict=True, ge=0, le=MAX_ORDER_VERSION)] | None
    currency: Literal["RON"]
    tariff_version: Identifier
    products_bani: MoneyBani
    collection_mode: Literal["cash", "prepaid"]
    client_collection_bani: MoneyBani
    restaurant_transport_bani: MoneyBani
    advance_required_bani: MoneyBani
    advance_paid_bani: None
    refund_due_bani: None
    refund_paid_bani: None
    basis: Literal["zone"]
    zone_id: Identifier
    zone_name: Annotated[str, Field(min_length=1, max_length=160)]
    zone_sector: Annotated[str, Field(max_length=80)] | None
    zone_level: Annotated[int, Field(strict=True, ge=0, le=50)] | None


class AdminFinancePreview(FinancePreview):
    courier_remuneration_bani: MoneyBani
