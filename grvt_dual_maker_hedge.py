import io
import json
import logging
import os
import random
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, InvalidOperation
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import requests
from dotenv import load_dotenv
from eth_account import Account

from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_env import GrvtEnv
from pysdk.grvt_raw_signing import sign_order
from pysdk.grvt_raw_sync import GrvtRawSync
from pysdk.grvt_raw_types import (
    AckResponse,
    ApiCancelOrderRequest,
    ApiCreateOrderRequest,
    ApiGetAllInstrumentsRequest,
    ApiGetInstrumentRequest,
    ApiGetOrderRequest,
    ApiOpenOrdersRequest,
    ApiOrderbookLevelsRequest,
    ApiPositionsRequest,
    EmptyRequest,
    Kind,
    Order,
    OrderLeg,
    OrderMetadata,
    OrderStatus,
    Signature,
    TimeInForce,
)


if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


BEIJING_TZ = timezone(timedelta(hours=8))
ORDER_PREFIX = "HEDGEV1"
ORDER_ID_MASK = 0xF000000000000000
ORDER_ID_PREFIX = 0xE000000000000000
DEFAULT_LOOP_INTERVAL_SEC = 2
DEFAULT_POST_ONLY_MAX_RETRY = 5
DEFAULT_POST_ONLY_COOLDOWN_SEC = 300
DEFAULT_PARTIAL_FILL_TIMEOUT_SEC = 1800
DEFAULT_STUCK_HOURS = 6
DEFAULT_MMR_ALERT_THRESHOLD = Decimal("0.70")
DEFAULT_ORDERBOOK_DEPTH = 10
TELEGRAM_LOCAL_ENDPOINT = "http://localhost:3000/send-message"


@dataclass
class AccountConfig:
    name: str
    account_type: str
    api_key: str
    account_id: str
    private_key: Optional[str] = None
    env: str = "prod"


@dataclass
class SymbolConfig:
    instrument: str
    enabled: bool
    order_notional_usdt: Decimal
    imbalance_limit_usdt: Decimal
    max_total_position_usdt: Decimal
    min_total_position_usdt: Decimal
    a_side_when_equal: str
    position_mode: str


@dataclass
class FillLot:
    source_account: str
    source_side: str
    price: Decimal
    remaining_notional: Decimal
    created_at: float
    synthetic: bool = False


@dataclass
class ManagedOrder:
    order_id: str
    client_order_id: str
    account_label: str
    instrument: str
    side: str
    price: Decimal
    size: Decimal
    notional_usdt: Decimal
    created_at: float
    strategy_owned: bool
    last_seen_at: float = 0.0
    applied_traded_size: Decimal = Decimal("0")
    partial_since: Optional[float] = None
    closed: bool = False
    close_reason: Optional[str] = None


@dataclass
class SymbolState:
    config: SymbolConfig
    lots: Deque[FillLot] = field(default_factory=deque)
    managed_orders: Dict[str, ManagedOrder] = field(default_factory=dict)
    cooldown_until: float = 0.0
    unhedged_since: Optional[float] = None
    stuck_alert_sent: bool = False
    non_strategy_alerted: bool = False


@dataclass
class AlertState:
    last_sent_by_key: Dict[str, float] = field(default_factory=dict)
    last_daily_report_day: Optional[str] = None


@dataclass
class PositionSnapshot:
    size: Decimal = Decimal("0")
    mark_price: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    signed_notional: Decimal = Decimal("0")
    abs_notional: Decimal = Decimal("0")


@dataclass
class AccountRuntime:
    label: str
    config: AccountConfig
    client: Any
    signer: Any
    instruments: Dict[str, Any] = field(default_factory=dict)


class DualMakerHedgeEngine:
    def __init__(self) -> None:
        load_dotenv(override=True)
        self._setup_logging()
        self.stop_flag = False
        self.alert_state = AlertState()
        self.symbol_states: Dict[str, SymbolState] = {}
        self.loop_interval_sec = int(os.getenv("GRVT_HEDGE_LOOP_INTERVAL_SEC", str(DEFAULT_LOOP_INTERVAL_SEC)))
        self.post_only_max_retry = int(os.getenv("GRVT_HEDGE_POST_ONLY_MAX_RETRY", str(DEFAULT_POST_ONLY_MAX_RETRY)))
        self.post_only_cooldown_sec = int(os.getenv("GRVT_HEDGE_POST_ONLY_COOLDOWN_SEC", str(DEFAULT_POST_ONLY_COOLDOWN_SEC)))
        self.partial_fill_timeout_sec = int(
            os.getenv("GRVT_HEDGE_PARTIAL_FILL_TIMEOUT_SEC", str(DEFAULT_PARTIAL_FILL_TIMEOUT_SEC))
        )
        self.stuck_hours = int(os.getenv("GRVT_HEDGE_STUCK_HOURS", str(DEFAULT_STUCK_HOURS)))
        self.mmr_alert_threshold = self._to_decimal(
            os.getenv("GRVT_HEDGE_MMR_ALERT_THRESHOLD", str(DEFAULT_MMR_ALERT_THRESHOLD)),
            Decimal("0.70"),
        )
        self.orderbook_depth = int(os.getenv("GRVT_HEDGE_ORDERBOOK_DEPTH", str(DEFAULT_ORDERBOOK_DEPTH)))
        if self.orderbook_depth <= 0:
            self.orderbook_depth = DEFAULT_ORDERBOOK_DEPTH
        self.single_order_diff_threshold_usdt = self._to_decimal(
            os.getenv("GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT", "20"),
            Decimal("20"),
        )
        self.sdk_log_level = os.getenv("GRVT_HEDGE_SDK_LOG_LEVEL", "ERROR").upper()
        self.cancel_on_stop = str(os.getenv("GRVT_HEDGE_CANCEL_ON_STOP", "1")).strip().lower() not in {"0", "false", "no"}
        self.stop_keep_strategy_orders = max(0, int(os.getenv("GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS", "0") or "0"))
        self.max_runtime_sec = max(0, int(os.getenv("GRVT_HEDGE_MAX_RUNTIME_SEC", "0") or "0"))
        self.started_at = time.time()
        if not os.getenv("CHAT_ID") or not os.getenv("API_KEY"):
            logging.warning("Telegram alert is not fully configured: CHAT_ID/API_KEY missing")
        self.instrument_alias_map: Dict[str, str] = {}
        self.accounts = self._load_two_trading_accounts()
        self.instrument_alias_map = self._load_instrument_aliases()
        self.symbol_states = self._load_symbol_states()
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _setup_logging(self) -> None:
        log_level = os.getenv("GRVT_LOG_LEVEL", "INFO").upper()
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        log_file = logs_dir / "grvt_dual_maker_hedge.log"
        handlers = [
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ]
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=handlers,
        )

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        if self.stop_flag:
            return
        logging.info("Received signal %s, stopping hedge engine...", signum)
        self.stop_flag = True

    def _to_decimal(self, value: Any, default: Decimal) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default

    def _load_two_trading_accounts(self) -> Dict[str, AccountRuntime]:
        configs = self._load_trading_account_configs()
        if len(configs) < 2:
            raise RuntimeError("Dual maker hedge requires at least 2 trading accounts")
        selected = configs[:2]
        result: Dict[str, AccountRuntime] = {}
        for idx, cfg in enumerate(selected):
            if not cfg.private_key:
                raise RuntimeError(f"Trading account {cfg.name} missing private key")
            client = self._build_client(cfg)
            label = "A" if idx == 0 else "B"
            runtime = AccountRuntime(
                label=label,
                config=cfg,
                client=client,
                signer=Account.from_key(cfg.private_key),
            )
            result[label] = runtime
        return result

    def _load_trading_account_configs(self) -> List[AccountConfig]:
        configs: List[AccountConfig] = []
        index = 1
        while True:
            api_key = os.getenv(f"GRVT_TRADING_API_KEY_{index}")
            private_key = os.getenv(f"GRVT_TRADING_PRIVATE_KEY_{index}")
            account_id = os.getenv(f"GRVT_TRADING_ACCOUNT_ID_{index}")
            if not api_key and not account_id:
                break
            if api_key and account_id:
                env = os.getenv(f"GRVT_ENV_{index}", os.getenv("GRVT_ENV", "prod"))
                suffix = account_id[-4:] if len(account_id) > 4 else str(index)
                configs.append(
                    AccountConfig(
                        name=f"Trading_{suffix}",
                        account_type="trading",
                        api_key=api_key,
                        private_key=private_key,
                        account_id=account_id,
                        env=env,
                    )
                )
            index += 1
        if not configs:
            old_api = os.getenv("GRVT_API_KEY")
            old_pk = os.getenv("GRVT_PRIVATE_KEY")
            old_id = os.getenv("GRVT_TRADING_ACCOUNT_ID")
            if old_api and old_id:
                configs.append(
                    AccountConfig(
                        name="Trading_legacy",
                        account_type="trading",
                        api_key=old_api,
                        private_key=old_pk,
                        account_id=old_id,
                        env=os.getenv("GRVT_ENV", "prod"),
                    )
                )
        return configs

    def _build_client(self, config: AccountConfig) -> GrvtRawSync:
        if not config.private_key:
            raise RuntimeError(f"{config.name} missing private key")
        try:
            env = GrvtEnv(config.env.lower())
        except ValueError as exc:
            raise RuntimeError(f"Unsupported env {config.env}") from exc
        sdk_logger = logging.getLogger(f"grvt_raw_{config.name}")
        sdk_logger.setLevel(getattr(logging, self.sdk_log_level, logging.ERROR))
        sdk_logger.propagate = False
        if not sdk_logger.handlers:
            sdk_logger.addHandler(logging.NullHandler())
        api_config = GrvtApiConfig(
            env=env,
            trading_account_id=config.account_id,
            private_key=config.private_key,
            api_key=config.api_key,
            logger=sdk_logger,
        )
        return GrvtRawSync(api_config)

    def _load_instrument_aliases(self) -> Dict[str, str]:
        if not self.accounts:
            return {}
        runtime = self.accounts.get("A") or next(iter(self.accounts.values()))
        response = runtime.client.get_all_instruments_v1(ApiGetAllInstrumentsRequest(is_active=True))
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.get_all_instruments_v1(ApiGetAllInstrumentsRequest(is_active=True))
        if isinstance(response, GrvtError):
            logging.warning(
                "Failed to preload instruments, continue without alias map: account=%s code=%s status=%s msg=%s",
                runtime.config.name,
                response.code,
                response.status,
                response.message,
            )
            return {}
        alias: Dict[str, str] = {}
        for item in response.result:
            name = str(getattr(item, "instrument", "")).strip()
            if not name:
                continue
            alias[name] = name
            alias[name.upper()] = name
            alias[name.lower()] = name
        logging.info("Loaded %d active instruments for symbol normalization", len(set(alias.values())))
        return alias

    def _suggest_instruments(self, raw_instrument: str, limit: int = 6) -> List[str]:
        if not self.instrument_alias_map:
            return []
        token = raw_instrument.strip().split("_")[0].upper()
        canonical = sorted(set(self.instrument_alias_map.values()))
        if not token:
            return canonical[:limit]
        prefix = f"{token}_"
        suggestions = [name for name in canonical if name.upper().startswith(prefix)]
        if len(suggestions) < limit:
            for name in canonical:
                if token in name.upper() and name not in suggestions:
                    suggestions.append(name)
                if len(suggestions) >= limit:
                    break
        return suggestions[:limit]

    def _resolve_instrument_name(self, raw_instrument: str) -> str:
        instrument = raw_instrument.strip()
        if not instrument:
            return ""
        if instrument.upper().endswith("_PERP"):
            instrument = f"{instrument[:-5]}_Perp"
        if not self.instrument_alias_map:
            return instrument
        resolved = (
            self.instrument_alias_map.get(instrument)
            or self.instrument_alias_map.get(instrument.upper())
            or self.instrument_alias_map.get(instrument.lower())
        )
        return resolved or ""

    def _load_symbol_states(self) -> Dict[str, SymbolState]:
        symbols_file = os.getenv("GRVT_HEDGE_SYMBOLS_FILE", "config/hedge_symbols.json").strip()
        if not symbols_file:
            raise RuntimeError("GRVT_HEDGE_SYMBOLS_FILE is required")
        config_path = Path(symbols_file)
        if not config_path.is_absolute():
            config_path = Path(__file__).parent / config_path
        if not config_path.exists():
            raise RuntimeError(f"Symbols config file not found: {config_path}")
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid symbols config JSON ({config_path}): {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to read symbols config file ({config_path}): {exc}") from exc
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"Symbols config file must be a non-empty JSON array: {config_path}")
        states: Dict[str, SymbolState] = {}
        for item in data:
            if not isinstance(item, dict):
                raise RuntimeError("Each symbol config must be an object")
            raw_instrument = str(item.get("instrument", "")).strip()
            if not raw_instrument:
                raise RuntimeError("Symbol config missing instrument")
            instrument = self._resolve_instrument_name(raw_instrument)
            if not instrument:
                suggestions = self._suggest_instruments(raw_instrument)
                suffix = f", maybe: {', '.join(suggestions)}" if suggestions else ""
                raise RuntimeError(f"Unknown instrument '{raw_instrument}'{suffix}")
            if raw_instrument != instrument:
                logging.info("Normalized instrument %s -> %s", raw_instrument, instrument)
            cfg = SymbolConfig(
                instrument=instrument,
                enabled=bool(item.get("enabled", True)),
                order_notional_usdt=self._to_decimal(item.get("order_notional_usdt"), Decimal("1000")),
                imbalance_limit_usdt=self._to_decimal(item.get("imbalance_limit_usdt"), Decimal("1000")),
                max_total_position_usdt=self._to_decimal(item.get("max_total_position_usdt"), Decimal("20000")),
                min_total_position_usdt=self._to_decimal(item.get("min_total_position_usdt"), Decimal("0")),
                a_side_when_equal=str(item.get("a_side_when_equal", "buy")).strip().lower(),
                position_mode=str(item.get("position_mode", "increase")).strip().lower(),
            )
            if cfg.a_side_when_equal not in {"buy", "sell"}:
                raise RuntimeError(f"{instrument} invalid a_side_when_equal: {cfg.a_side_when_equal}")
            if cfg.position_mode not in {"increase", "decrease"}:
                raise RuntimeError(f"{instrument} invalid position_mode: {cfg.position_mode}")
            if cfg.max_total_position_usdt < 0:
                raise RuntimeError(f"{instrument} invalid max_total_position_usdt: {cfg.max_total_position_usdt}")
            if cfg.min_total_position_usdt < 0:
                raise RuntimeError(f"{instrument} invalid min_total_position_usdt: {cfg.min_total_position_usdt}")
            if cfg.min_total_position_usdt > cfg.max_total_position_usdt:
                raise RuntimeError(
                    f"{instrument} min_total_position_usdt > max_total_position_usdt: "
                    f"{cfg.min_total_position_usdt} > {cfg.max_total_position_usdt}"
                )
            states[instrument] = SymbolState(config=cfg)
        return states

    def _opposite_side(self, side: str) -> str:
        return "sell" if side == "buy" else "buy"

    def _decide_equal_sides(
        self,
        cfg: SymbolConfig,
        pos_a: PositionSnapshot,
        pos_b: PositionSnapshot,
    ) -> Optional[Dict[str, str]]:
        # increase: use configured baseline direction.
        if cfg.position_mode == "increase":
            side_a = cfg.a_side_when_equal
            return {"A": side_a, "B": self._opposite_side(side_a)}
        # decrease: prefer sides that reduce existing opposite positions.
        if pos_a.abs_notional == 0 and pos_b.abs_notional == 0:
            return None
        if pos_a.size > 0 and pos_b.size < 0:
            return {"A": "sell", "B": "buy"}
        if pos_a.size < 0 and pos_b.size > 0:
            return {"A": "buy", "B": "sell"}
        # Fallback for unexpected same-direction inventory.
        if pos_a.size != 0 and pos_b.size != 0 and (pos_a.size * pos_b.size) > 0:
            self._notify(
                title=f"GRVT decrease mode direction mismatch {cfg.instrument}",
                message=f"A.size={pos_a.size} B.size={pos_b.size}, fallback to configured baseline",
                alert_key=f"decrease_direction_fallback:{cfg.instrument}",
                cooldown_sec=1800,
            )
        side_a = self._opposite_side(cfg.a_side_when_equal)
        return {"A": side_a, "B": self._opposite_side(side_a)}

    def _send_telegram(self, message: str) -> None:
        chat_id = os.getenv("CHAT_ID")
        api_key = os.getenv("API_KEY")
        if not chat_id or not api_key:
            return
        headers = {"Content-Type": "application/json", "X-API-Key": api_key}
        payload = {"chatId": chat_id, "message": message}
        try:
            requests.post(TELEGRAM_LOCAL_ENDPOINT, json=payload, headers=headers, timeout=6)
        except Exception as exc:
            logging.debug("Telegram alert failed: %s", exc)

    def _notify(self, title: str, message: str, alert_key: str, cooldown_sec: int = 300) -> None:
        now = time.time()
        last_ts = self.alert_state.last_sent_by_key.get(alert_key, 0.0)
        if now - last_ts < cooldown_sec:
            return
        self.alert_state.last_sent_by_key[alert_key] = now
        self._send_telegram(f"{title}\n{message}")
        logging.warning("%s | %s", title, message)

    def _ensure_client(self, runtime: AccountRuntime) -> None:
        return

    def _is_auth_error(self, response: GrvtError) -> bool:
        msg = str(getattr(response, "message", "") or "").lower()
        code = str(getattr(response, "code", "") or "")
        status = str(getattr(response, "status", "") or "")
        return status == "401" or code == "1000" or "authenticate" in msg or "unauthorized" in msg

    def _fetch_instrument(self, runtime: AccountRuntime, instrument: str) -> Optional[Any]:
        if instrument in runtime.instruments:
            return runtime.instruments[instrument]
        response = runtime.client.get_instrument_v1(ApiGetInstrumentRequest(instrument=instrument))
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.get_instrument_v1(ApiGetInstrumentRequest(instrument=instrument))
        if isinstance(response, GrvtError):
            self._notify(
                title=f"GRVT hedge instrument query failed {instrument}",
                message=f"account={runtime.config.name} code={response.code} status={response.status} msg={response.message}",
                alert_key=f"instrument:{runtime.config.name}:{instrument}",
                cooldown_sec=600,
            )
            return None
        runtime.instruments[instrument] = response.result
        return response.result

    def _query_positions(self, runtime: AccountRuntime) -> Dict[str, PositionSnapshot]:
        response = runtime.client.positions_v1(
            ApiPositionsRequest(sub_account_id=runtime.config.account_id, kind=[Kind.PERPETUAL])
        )
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.positions_v1(
                ApiPositionsRequest(sub_account_id=runtime.config.account_id, kind=[Kind.PERPETUAL])
            )
        result: Dict[str, PositionSnapshot] = {}
        if isinstance(response, GrvtError):
            self._notify(
                title=f"GRVT hedge positions failed {runtime.config.name}",
                message=f"code={response.code} status={response.status} msg={response.message}",
                alert_key=f"positions:{runtime.config.name}",
                cooldown_sec=120,
            )
            return result
        for pos in response.result:
            size = self._to_decimal(getattr(pos, "size", "0"), Decimal("0"))
            mark_price = self._to_decimal(getattr(pos, "mark_price", "0"), Decimal("0"))
            entry_price = self._to_decimal(getattr(pos, "entry_price", "0"), Decimal("0"))
            if mark_price <= 0:
                mark_price = entry_price
            signed_notional = size * mark_price
            result[getattr(pos, "instrument")] = PositionSnapshot(
                size=size,
                mark_price=mark_price,
                entry_price=entry_price,
                signed_notional=signed_notional,
                abs_notional=abs(signed_notional),
            )
        return result

    def _query_open_orders(self, runtime: AccountRuntime) -> Dict[str, List[Order]]:
        response = runtime.client.open_orders_v1(
            ApiOpenOrdersRequest(sub_account_id=runtime.config.account_id, kind=[Kind.PERPETUAL])
        )
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.open_orders_v1(
                ApiOpenOrdersRequest(sub_account_id=runtime.config.account_id, kind=[Kind.PERPETUAL])
            )
        grouped: Dict[str, List[Order]] = {}
        if isinstance(response, GrvtError):
            self._notify(
                title=f"GRVT hedge open orders failed {runtime.config.name}",
                message=f"code={response.code} status={response.status} msg={response.message}",
                alert_key=f"open_orders:{runtime.config.name}",
                cooldown_sec=120,
            )
            return grouped
        for order in response.result:
            if not getattr(order, "legs", None):
                continue
            instrument = getattr(order.legs[0], "instrument", "")
            grouped.setdefault(instrument, []).append(order)
        return grouped

    def _cancel_order_by_id(self, runtime: AccountRuntime, order_id: str) -> bool:
        if not order_id:
            return False
        if self._is_placeholder_order_id(order_id):
            return True
        response = runtime.client.cancel_order_v1(
            ApiCancelOrderRequest(
                sub_account_id=runtime.config.account_id,
                order_id=order_id,
            )
        )
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.cancel_order_v1(
                ApiCancelOrderRequest(
                    sub_account_id=runtime.config.account_id,
                    order_id=order_id,
                )
            )
        if isinstance(response, GrvtError):
            msg = str(getattr(response, "message", "") or "").lower()
            # Already gone/closed orders are effectively cancelled for cleanup.
            if any(k in msg for k in ["not found", "does not exist", "already closed", "already canceled", "already cancelled"]):
                return True
            logging.warning(
                "Cancel order failed account=%s order_id=%s code=%s status=%s msg=%s",
                runtime.config.name,
                order_id,
                response.code,
                response.status,
                response.message,
            )
            return False
        return isinstance(response, AckResponse)

    def _cancel_order(self, runtime: AccountRuntime, order: Order) -> bool:
        order_id = str(getattr(order, "order_id", "") or "")
        return self._cancel_order_by_id(runtime, order_id)

    def _order_create_ns(self, order: Order) -> int:
        metadata = getattr(order, "metadata", None)
        value = str(getattr(metadata, "create_time", "") or "").strip()
        if not value:
            return 0
        if value.endswith("Z") or "T" in value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1_000_000_000)
            except Exception:
                return 0
        try:
            return int(value)
        except ValueError:
            return 0

    def _is_placeholder_order_id(self, order_id: str) -> bool:
        oid = str(order_id or "").strip().lower()
        return oid in {"", "0", "0x0", "0x00"} or oid.startswith("0x00")

    def _cleanup_strategy_orders_on_stop(self) -> None:
        if not self.cancel_on_stop:
            logging.info("Skip stop cleanup because GRVT_HEDGE_CANCEL_ON_STOP=0")
            return
        keep_n = self.stop_keep_strategy_orders
        total_candidates = 0
        total_cancelled = 0
        for label, runtime in self.accounts.items():
            grouped = self._query_open_orders(runtime)
            for symbol, orders in grouped.items():
                strategy_orders: List[Order] = []
                for order in orders:
                    metadata = getattr(order, "metadata", None)
                    client_order_id = str(getattr(metadata, "client_order_id", "") or "")
                    if self._is_strategy_order(client_order_id):
                        strategy_orders.append(order)
                if not strategy_orders:
                    continue
                strategy_orders.sort(key=self._order_create_ns, reverse=True)
                to_cancel = strategy_orders[keep_n:] if keep_n > 0 else strategy_orders
                total_candidates += len(to_cancel)
                for order in to_cancel:
                    if self._cancel_order(runtime, order):
                        total_cancelled += 1
                        logging.info(
                            "Cancelled strategy order on stop account=%s symbol=%s order_id=%s",
                            label,
                            symbol,
                            getattr(order, "order_id", ""),
                        )
        logging.info(
            "Stop cleanup finished: cancelled=%s candidate=%s keep_per_symbol=%s",
            total_cancelled,
            total_candidates,
            keep_n,
        )

    def _query_account_summary(self, runtime: AccountRuntime) -> Optional[Dict[str, Decimal]]:
        response = runtime.client.aggregated_account_summary_v1(EmptyRequest())
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.aggregated_account_summary_v1(EmptyRequest())
        if isinstance(response, GrvtError):
            self._notify(
                title=f"GRVT hedge account summary failed {runtime.config.name}",
                message=f"code={response.code} status={response.status} msg={response.message}",
                alert_key=f"summary:{runtime.config.name}",
                cooldown_sec=120,
            )
            return None
        total_equity = self._to_decimal(getattr(response.result, "total_equity", "0"), Decimal("0"))
        maintenance_margin = self._to_decimal(getattr(response.result, "maintenance_margin", "0"), Decimal("0"))
        available_balance = self._to_decimal(getattr(response.result, "available_balance", "0"), Decimal("0"))
        return {
            "equity": total_equity,
            "maintenance_margin": maintenance_margin,
            "available_balance": available_balance,
        }

    def _fetch_book_top(self, runtime: AccountRuntime, instrument: str) -> Optional[Dict[str, Decimal]]:
        response = runtime.client.orderbook_levels_v1(
            ApiOrderbookLevelsRequest(instrument=instrument, depth=self.orderbook_depth)
        )
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            response = runtime.client.orderbook_levels_v1(
                ApiOrderbookLevelsRequest(instrument=instrument, depth=self.orderbook_depth)
            )
        if isinstance(response, GrvtError):
            self._notify(
                title=f"GRVT hedge orderbook failed {instrument}",
                message=f"account={runtime.config.name} code={response.code} status={response.status} msg={response.message}",
                alert_key=f"book:{runtime.config.name}:{instrument}",
                cooldown_sec=60,
            )
            return None
        if not response.result.bids or not response.result.asks:
            return None
        bid1 = self._to_decimal(response.result.bids[0].price, Decimal("0"))
        ask1 = self._to_decimal(response.result.asks[0].price, Decimal("0"))
        if bid1 <= 0 or ask1 <= 0:
            return None
        return {"bid1": bid1, "ask1": ask1}

    def _is_strategy_order(self, client_order_id: str) -> bool:
        if client_order_id.startswith(f"{ORDER_PREFIX}_"):
            return True
        try:
            value = int(client_order_id)
            return (value & ORDER_ID_MASK) == ORDER_ID_PREFIX
        except (TypeError, ValueError):
            return False

    def _parse_order_side(self, order: Order) -> str:
        if not order.legs:
            return "buy"
        return "buy" if bool(order.legs[0].is_buying_asset) else "sell"

    def _order_status_name(self, order: Order) -> str:
        status = getattr(getattr(order, "state", None), "status", None)
        if status is None:
            return "OPEN"
        if isinstance(status, OrderStatus):
            return status.name
        return str(status)

    def _order_traded_size(self, order: Order) -> Decimal:
        state = getattr(order, "state", None)
        if not state:
            return Decimal("0")
        traded = getattr(state, "traded_size", None) or []
        if not traded:
            return Decimal("0")
        return self._to_decimal(traded[0], Decimal("0"))

    def _order_avg_fill_price(self, order: Order) -> Decimal:
        state = getattr(order, "state", None)
        if state:
            avg_fill = getattr(state, "avg_fill_price", None) or []
            if avg_fill:
                value = self._to_decimal(avg_fill[0], Decimal("0"))
                if value > 0:
                    return value
        if getattr(order, "legs", None):
            return self._to_decimal(getattr(order.legs[0], "limit_price", "0"), Decimal("0"))
        return Decimal("0")

    def _order_book_size(self, order: Order) -> Decimal:
        state = getattr(order, "state", None)
        if not state:
            return Decimal("0")
        book_size = getattr(state, "book_size", None) or []
        if not book_size:
            return Decimal("0")
        return self._to_decimal(book_size[0], Decimal("0"))

    def _to_order_notional(self, size: Decimal, price: Decimal) -> Decimal:
        return (size * price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

    def _quantize_price(self, price: Decimal, tick: Decimal, side: str) -> Decimal:
        if tick <= 0:
            return price
        units = price / tick
        if side == "sell":
            units = units.to_integral_value(rounding=ROUND_CEILING)
        else:
            units = units.to_integral_value(rounding=ROUND_DOWN)
        return (units * tick).quantize(tick)

    def _size_from_notional(self, notional: Decimal, price: Decimal, instrument: Any) -> Decimal:
        if price <= 0 or notional <= 0:
            return Decimal("0")
        base_decimals = int(getattr(instrument, "base_decimals", 6))
        min_size = self._to_decimal(getattr(instrument, "min_size", "0"), Decimal("0"))
        quantum = Decimal(1).scaleb(-base_decimals)
        step = min_size if min_size > 0 else quantum
        if step < quantum:
            step = quantum
        raw_size = notional / price
        size = (raw_size / step).to_integral_value(rounding=ROUND_DOWN) * step
        size = size.quantize(quantum, rounding=ROUND_DOWN)
        if size < min_size:
            size = min_size
        return size

    def _mmr_check(self, runtime: AccountRuntime, summary: Optional[Dict[str, Decimal]]) -> None:
        if not summary:
            return
        equity = summary.get("equity", Decimal("0"))
        maintenance = summary.get("maintenance_margin", Decimal("0"))
        if equity <= 0:
            return
        ratio = maintenance / equity
        if ratio >= self.mmr_alert_threshold:
            self._notify(
                title=f"GRVT {runtime.config.name} MMR ALERT {ratio:.2%}",
                message=f"maintenance_margin={maintenance} equity={equity} threshold={self.mmr_alert_threshold:.2%}",
                alert_key=f"mmr:{runtime.config.name}",
                cooldown_sec=1800,
            )

    def _sync_state_orders(
        self,
        state: SymbolState,
        account_label: str,
        live_orders: List[Order],
    ) -> None:
        now = time.time()
        live_ids = set()
        for order in live_orders:
            order_id = str(getattr(order, "order_id", "") or "")
            if not order_id:
                continue
            live_ids.add(order_id)
            metadata = getattr(order, "metadata", None)
            client_order_id = str(getattr(metadata, "client_order_id", "") or "")
            strategy_owned = self._is_strategy_order(client_order_id)
            if not strategy_owned:
                if not state.non_strategy_alerted:
                    state.non_strategy_alerted = True
                    self._notify(
                        title=f"GRVT non-strategy order detected {state.config.instrument}",
                        message=f"account={account_label} order_id={order_id} preserved and ignored by strategy",
                        alert_key=f"non_strategy:{state.config.instrument}:{account_label}",
                        cooldown_sec=3600,
                    )
                continue
            side = self._parse_order_side(order)
            price = self._to_decimal(getattr(order.legs[0], "limit_price", "0"), Decimal("0"))
            size = self._to_decimal(getattr(order.legs[0], "size", "0"), Decimal("0"))
            managed = state.managed_orders.get(order_id)
            if managed is None and client_order_id:
                # Reconcile provisional local order_id (e.g. 0x00) with real exchange order_id.
                for old_key, old_managed in list(state.managed_orders.items()):
                    if old_managed.account_label != account_label:
                        continue
                    if old_managed.client_order_id != client_order_id:
                        continue
                    if not self._is_placeholder_order_id(old_managed.order_id):
                        continue
                    old_managed.order_id = order_id
                    state.managed_orders[order_id] = old_managed
                    del state.managed_orders[old_key]
                    managed = old_managed
                    break
            if managed is None:
                managed = ManagedOrder(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    account_label=account_label,
                    instrument=state.config.instrument,
                    side=side,
                    price=price,
                    size=size,
                    notional_usdt=self._to_order_notional(size, price),
                    created_at=now,
                    strategy_owned=strategy_owned,
                )
                state.managed_orders[order_id] = managed
            managed.last_seen_at = now
            managed.closed = False
            managed.side = side
            managed.price = price
            managed.size = size
            managed.notional_usdt = self._to_order_notional(size, price)
            self._process_order_fill_delta(state, managed, order)
        for order_id, managed in list(state.managed_orders.items()):
            if managed.account_label != account_label:
                continue
            if managed.closed:
                continue
            if self._is_placeholder_order_id(order_id):
                # If still provisional and not observed in snapshots for long enough, mark closed.
                if now - managed.created_at > 60:
                    managed.closed = True
                    managed.close_reason = "PROVISIONAL_TIMEOUT"
                continue
            if order_id in live_ids:
                continue
            runtime = self.accounts[account_label]
            response = runtime.client.get_order_v1(
                ApiGetOrderRequest(sub_account_id=runtime.config.account_id, order_id=order_id)
            )
            if isinstance(response, GrvtError) and self._is_auth_error(response):
                runtime.client = self._build_client(runtime.config)
                response = runtime.client.get_order_v1(
                    ApiGetOrderRequest(sub_account_id=runtime.config.account_id, order_id=order_id)
                )
            if isinstance(response, GrvtError):
                continue
            order = response.result
            self._process_order_fill_delta(state, managed, order)
            status_name = self._order_status_name(order)
            if status_name in {"FILLED", "CANCELLED", "REJECTED"}:
                managed.closed = True
                managed.close_reason = status_name

    def _process_order_fill_delta(self, state: SymbolState, managed: ManagedOrder, order: Order) -> None:
        traded = self._order_traded_size(order)
        if traded <= managed.applied_traded_size:
            return
        status_name = self._order_status_name(order)
        book_size = self._order_book_size(order)
        is_partial_open = status_name == "OPEN" and book_size > 0 and traded < managed.size
        now = time.time()
        if is_partial_open:
            if managed.partial_since is None:
                managed.partial_since = now
            if now - managed.partial_since < self.partial_fill_timeout_sec:
                return
        delta_size = traded - managed.applied_traded_size
        fill_price = self._order_avg_fill_price(order)
        if delta_size > 0 and fill_price > 0:
            fill_notional = self._to_order_notional(delta_size, fill_price)
            self._apply_fill_to_lots(
                state=state,
                source_account=managed.account_label,
                source_side=managed.side,
                fill_price=fill_price,
                fill_notional=fill_notional,
            )
        managed.applied_traded_size = traded
        if status_name in {"FILLED", "CANCELLED", "REJECTED"}:
            managed.closed = True
            managed.close_reason = status_name

    def _apply_fill_to_lots(
        self,
        state: SymbolState,
        source_account: str,
        source_side: str,
        fill_price: Decimal,
        fill_notional: Decimal,
    ) -> None:
        remaining = fill_notional
        opposite = "sell" if source_side == "buy" else "buy"
        new_queue: Deque[FillLot] = deque()
        while state.lots and remaining > 0:
            lot = state.lots.popleft()
            if lot.remaining_notional <= 0:
                continue
            is_candidate = lot.source_account != source_account and lot.source_side == opposite
            price_ok = True
            if is_candidate:
                if source_side == "sell":
                    price_ok = fill_price >= lot.price
                else:
                    price_ok = fill_price <= lot.price
            if not is_candidate or not price_ok:
                new_queue.append(lot)
                continue
            matched = min(remaining, lot.remaining_notional)
            lot.remaining_notional -= matched
            remaining -= matched
            if lot.remaining_notional > 0:
                new_queue.append(lot)
        while state.lots:
            new_queue.append(state.lots.popleft())
        state.lots = new_queue
        if remaining > 0:
            state.lots.append(
                FillLot(
                    source_account=source_account,
                    source_side=source_side,
                    price=fill_price,
                    remaining_notional=remaining,
                    created_at=time.time(),
                    synthetic=False,
                )
            )

    def _bootstrap_symbol_state(self, state: SymbolState, snapshots: Dict[str, Dict[str, Any]]) -> None:
        instrument = state.config.instrument
        for label in ("A", "B"):
            pos = snapshots[label]["positions"].get(instrument, PositionSnapshot())
            if pos.abs_notional > 0 and pos.entry_price > 0:
                side = "buy" if pos.size > 0 else "sell"
                state.lots.append(
                    FillLot(
                        source_account=label,
                        source_side=side,
                        price=pos.entry_price,
                        remaining_notional=pos.abs_notional,
                        created_at=time.time(),
                        synthetic=True,
                    )
                )
            self._sync_state_orders(state, label, snapshots[label]["open_orders"].get(instrument, []))

    def _build_client_order_id(self, symbol: str, account_label: str, side: str) -> str:
        # GRVT expects numeric client_order_id. Use a dedicated high-bit namespace to
        # identify strategy-owned orders while keeping account/side bits for debugging.
        acc_bit = 0 if account_label == "A" else 1
        side_bit = 0 if side == "buy" else 1
        entropy = (time.time_ns() ^ random.getrandbits(32)) & ((1 << 58) - 1)
        value = ORDER_ID_PREFIX | (acc_bit << 59) | (side_bit << 58) | entropy
        return str(value)

    def _create_signed_order(
        self,
        runtime: AccountRuntime,
        instrument_info: Any,
        symbol: str,
        side: str,
        price: Decimal,
        notional: Decimal,
    ) -> Optional[ManagedOrder]:
        size = self._size_from_notional(notional, price, instrument_info)
        if size <= 0:
            return None
        adjusted_notional = self._to_order_notional(size, price)
        if adjusted_notional <= 0:
            return None
        client_order_id = self._build_client_order_id(symbol, runtime.label, side)
        expiration_ns = str(int(time.time_ns() + 15 * 60 * 1_000_000_000))
        nonce = random.randint(1, 2**31 - 1)
        order = Order(
            sub_account_id=runtime.config.account_id,
            time_in_force=TimeInForce.GOOD_TILL_TIME,
            legs=[
                OrderLeg(
                    instrument=symbol,
                    size=str(size),
                    is_buying_asset=(side == "buy"),
                    limit_price=str(price),
                )
            ],
            signature=Signature(signer="", r="0x", s="0x", v=0, expiration=expiration_ns, nonce=nonce),
            metadata=OrderMetadata(
                client_order_id=client_order_id,
                create_time=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
            is_market=False,
            post_only=True,
            reduce_only=False,
        )
        try:
            signed_order = sign_order(order, runtime.client.config, runtime.signer, {symbol: instrument_info})
        except Exception as exc:
            raise RuntimeError(f"sign_order_failed: {exc}") from exc
        response = runtime.client.create_order_v1(ApiCreateOrderRequest(order=signed_order))
        if isinstance(response, GrvtError) and self._is_auth_error(response):
            runtime.client = self._build_client(runtime.config)
            try:
                signed_order = sign_order(order, runtime.client.config, runtime.signer, {symbol: instrument_info})
            except Exception as exc:
                raise RuntimeError(f"sign_order_failed_after_reauth: {exc}") from exc
            response = runtime.client.create_order_v1(ApiCreateOrderRequest(order=signed_order))
        if isinstance(response, GrvtError):
            raise RuntimeError(
                f"create_order_failed code={response.code} status={response.status} message={response.message}"
            )
        result_order = response.result
        order_id = str(getattr(result_order, "order_id", "") or "")
        if not order_id:
            return None
        return ManagedOrder(
            order_id=order_id,
            client_order_id=client_order_id,
            account_label=runtime.label,
            instrument=symbol,
            side=side,
            price=price,
            size=size,
            notional_usdt=adjusted_notional,
            created_at=time.time(),
            strategy_owned=True,
        )

    def _place_post_only_with_retry(
        self,
        state: SymbolState,
        runtime: AccountRuntime,
        side: str,
        guard_price: Optional[Decimal],
        notional: Decimal,
    ) -> bool:
        symbol = state.config.instrument
        instrument_info = self._fetch_instrument(runtime, symbol)
        if not instrument_info:
            return False
        tick = self._to_decimal(getattr(instrument_info, "tick_size", "0.1"), Decimal("0.1"))
        for attempt in range(1, self.post_only_max_retry + 1):
            book = self._fetch_book_top(runtime, symbol)
            if not book:
                time.sleep(0.2)
                continue
            bid1 = book["bid1"]
            ask1 = book["ask1"]
            if side == "sell":
                raw_price = ask1 if guard_price is None else max(ask1, guard_price)
            else:
                raw_price = bid1 if guard_price is None else min(bid1, guard_price)
            price = self._quantize_price(raw_price, tick, side)
            if price <= 0:
                continue
            try:
                managed = self._create_signed_order(runtime, instrument_info, symbol, side, price, notional)
                if managed:
                    state.managed_orders[managed.order_id] = managed
                    logging.info(
                        "[%s] Placed %s %s %.4f USDT @ %s",
                        symbol,
                        runtime.label,
                        side,
                        float(managed.notional_usdt),
                        managed.price,
                    )
                    return True
            except RuntimeError as exc:
                msg = str(exc).lower()
                if any(k in msg for k in ["post", "maker", "would match", "taker"]):
                    logging.debug("[%s] post-only reject on attempt %d/%d", symbol, attempt, self.post_only_max_retry)
                    time.sleep(0.2)
                    continue
                self._notify(
                    title=f"GRVT hedge order failed {symbol}",
                    message=f"account={runtime.label} side={side} error={exc}",
                    alert_key=f"order_failed:{symbol}:{runtime.label}:{side}",
                    cooldown_sec=120,
                )
                return False
        state.cooldown_until = time.time() + self.post_only_cooldown_sec
        self._notify(
            title=f"GRVT hedge cooldown {symbol}",
            message=f"post-only failed after {self.post_only_max_retry} retries, cooldown {self.post_only_cooldown_sec}s",
            alert_key=f"cooldown:{symbol}",
            cooldown_sec=120,
        )
        return False

    def _active_order_count(self, state: SymbolState, account_label: str) -> int:
        return sum(1 for m in self._active_strategy_orders(state) if m.account_label == account_label)

    def _active_strategy_orders(self, state: SymbolState) -> List[ManagedOrder]:
        now = time.time()
        result: List[ManagedOrder] = []
        for managed in state.managed_orders.values():
            if not managed.strategy_owned:
                continue
            if managed.closed:
                continue
            if managed.last_seen_at > 0 and now - managed.last_seen_at > 3600:
                continue
            # Newly placed orders may not be in open_orders snapshot yet; still count them.
            if managed.last_seen_at <= 0 and now - managed.created_at > 600:
                continue
            result.append(managed)
        return result

    def _cancel_managed_order(self, state: SymbolState, managed: ManagedOrder, reason: str) -> bool:
        runtime = self.accounts.get(managed.account_label)
        if not runtime:
            return False
        ok = self._cancel_order_by_id(runtime, managed.order_id)
        if ok:
            managed.closed = True
            managed.close_reason = reason
        return ok

    def _enforce_account_order_cap(self, state: SymbolState, account_label: str, max_orders: int) -> None:
        active_orders = [m for m in self._active_strategy_orders(state) if m.account_label == account_label]
        if len(active_orders) <= max_orders:
            return
        overflow_count = len(active_orders) - max_orders
        # Cancel oldest strategy orders first to keep the most recent intention.
        to_cancel = sorted(active_orders, key=lambda x: x.created_at)[:overflow_count]
        for managed in to_cancel:
            ok = self._cancel_managed_order(state, managed, reason="low_diff_account_order_cap")
            if ok:
                logging.info(
                    "[%s] Cancelled extra strategy order due to low diff account cap: account=%s order_id=%s",
                    state.config.instrument,
                    managed.account_label,
                    managed.order_id,
                )
            else:
                logging.warning(
                    "[%s] Failed to cancel extra strategy order due to low diff account cap: account=%s order_id=%s",
                    state.config.instrument,
                    managed.account_label,
                    managed.order_id,
                )

    def _active_hedge_notional(self, state: SymbolState, account_label: str, side: str) -> Decimal:
        total = Decimal("0")
        for managed in state.managed_orders.values():
            if managed.account_label != account_label:
                continue
            if not managed.strategy_owned:
                continue
            if managed.closed:
                continue
            if managed.side != side:
                continue
            total += managed.notional_usdt
        return total

    def _project_abs_notional(self, signed_notional: Decimal, side: str, order_notional: Decimal) -> Decimal:
        delta = order_notional if side == "buy" else -order_notional
        return abs(signed_notional + delta)

    def _clip_order_notional_to_total_bound(
        self,
        side: str,
        order_notional: Decimal,
        signed_notional: Decimal,
        other_abs: Decimal,
        mode: str,
        bound_total: Decimal,
    ) -> Decimal:
        if order_notional <= 0:
            return Decimal("0")
        candidate = order_notional
        steps = 50
        step = order_notional / Decimal(steps)
        if step <= 0:
            step = order_notional
        for _ in range(steps + 1):
            projected_total = other_abs + self._project_abs_notional(signed_notional, side, candidate)
            if mode == "increase":
                if projected_total <= bound_total:
                    return candidate
            else:
                if projected_total >= bound_total:
                    return candidate
            candidate -= step
            if candidate <= 0:
                return Decimal("0")
        return Decimal("0")

    def _required_hedge_side_guard(
        self,
        state: SymbolState,
        target_account: str,
        pos_a: PositionSnapshot,
        pos_b: PositionSnapshot,
    ) -> Dict[str, Optional[Decimal]]:
        for lot in state.lots:
            if lot.remaining_notional <= 0:
                continue
            if lot.source_account == target_account:
                continue
            return {"side": "sell" if lot.source_side == "buy" else "buy", "guard": lot.price}
        larger = pos_a if pos_a.abs_notional >= pos_b.abs_notional else pos_b
        if larger.size > 0:
            return {"side": "sell", "guard": larger.entry_price if larger.entry_price > 0 else None}
        if larger.size < 0:
            return {"side": "buy", "guard": larger.entry_price if larger.entry_price > 0 else None}
        return {"side": None, "guard": None}

    def _check_unhedged_alert(self, state: SymbolState, abs_a: Decimal, abs_b: Decimal) -> None:
        now = time.time()
        if abs_a == abs_b:
            state.unhedged_since = None
            state.stuck_alert_sent = False
            return
        if state.unhedged_since is None:
            state.unhedged_since = now
            return
        if now - state.unhedged_since >= self.stuck_hours * 3600 and not state.stuck_alert_sent:
            state.stuck_alert_sent = True
            self._notify(
                title=f"GRVT unhedged>{self.stuck_hours}h {state.config.instrument}",
                message=f"abs_a={abs_a} abs_b={abs_b} since={datetime.fromtimestamp(state.unhedged_since).isoformat()}",
                alert_key=f"stuck:{state.config.instrument}",
                cooldown_sec=3600,
            )

    def _send_daily_stuck_report(self) -> None:
        beijing_now = datetime.now(BEIJING_TZ)
        day_key = beijing_now.strftime("%Y-%m-%d")
        if self.alert_state.last_daily_report_day == day_key:
            return
        lines: List[str] = []
        for symbol, state in self.symbol_states.items():
            if not state.unhedged_since:
                continue
            hours = (time.time() - state.unhedged_since) / 3600.0
            if hours < self.stuck_hours:
                continue
            lines.append(f"{symbol}: unhedged {hours:.2f}h")
        if not lines:
            return
        body = "Daily stuck hedge report:\n" + "\n".join(lines)
        self._send_telegram(body)
        self.alert_state.last_daily_report_day = day_key
        logging.warning(body)

    def _bootstrap(self) -> None:
        snapshots = self._collect_snapshots()
        for state in self.symbol_states.values():
            if not state.config.enabled:
                continue
            self._bootstrap_symbol_state(state, snapshots)
        logging.info("Bootstrap completed for %d symbols", len(self.symbol_states))

    def _collect_snapshots(self) -> Dict[str, Dict[str, Any]]:
        snapshots: Dict[str, Dict[str, Any]] = {}
        for label, runtime in self.accounts.items():
            self._ensure_client(runtime)
            positions = self._query_positions(runtime)
            open_orders = self._query_open_orders(runtime)
            summary = self._query_account_summary(runtime)
            self._mmr_check(runtime, summary)
            snapshots[label] = {
                "positions": positions,
                "open_orders": open_orders,
                "summary": summary,
            }
        return snapshots

    def _process_symbol(self, state: SymbolState, snapshots: Dict[str, Dict[str, Any]]) -> None:
        cfg = state.config
        if not cfg.enabled:
            return
        now = time.time()
        symbol = cfg.instrument
        if now < state.cooldown_until:
            return
        for label in ("A", "B"):
            self._sync_state_orders(state, label, snapshots[label]["open_orders"].get(symbol, []))
        pos_a = snapshots["A"]["positions"].get(symbol, PositionSnapshot())
        pos_b = snapshots["B"]["positions"].get(symbol, PositionSnapshot())
        abs_a = pos_a.abs_notional
        abs_b = pos_b.abs_notional
        position_diff = abs(abs_a - abs_b)
        per_account_cap = 1 if position_diff < self.single_order_diff_threshold_usdt else 2
        self._enforce_account_order_cap(state, "A", per_account_cap)
        self._enforce_account_order_cap(state, "B", per_account_cap)
        self._check_unhedged_alert(state, abs_a, abs_b)
        total_position = abs_a + abs_b
        increase_limit_reached = cfg.position_mode == "increase" and total_position >= cfg.max_total_position_usdt
        decrease_limit_reached = cfg.position_mode == "decrease" and total_position <= cfg.min_total_position_usdt
        if increase_limit_reached:
            self._notify(
                title=f"GRVT max_total_position exceeded {symbol}",
                message=f"mode=increase total={total_position} max={cfg.max_total_position_usdt}",
                alert_key=f"max_total:{symbol}",
                cooldown_sec=900,
            )
        if decrease_limit_reached:
            self._notify(
                title=f"GRVT min_total_position reached {symbol}",
                message=f"mode=decrease total={total_position} min={cfg.min_total_position_usdt}",
                alert_key=f"min_total:{symbol}",
                cooldown_sec=900,
            )
        if abs_a == abs_b:
            # At limits, block expansion-style equal-position re-seeding.
            if increase_limit_reached or decrease_limit_reached:
                return
            equal_sides = self._decide_equal_sides(cfg, pos_a, pos_b)
            if not equal_sides:
                return
            side_a = equal_sides["A"]
            side_b = equal_sides["B"]
            if self._active_order_count(state, "A") < per_account_cap:
                self._place_post_only_with_retry(
                    state=state,
                    runtime=self.accounts["A"],
                    side=side_a,
                    guard_price=None,
                    notional=cfg.order_notional_usdt,
                )
            if self._active_order_count(state, "B") < per_account_cap:
                self._place_post_only_with_retry(
                    state=state,
                    runtime=self.accounts["B"],
                    side=side_b,
                    guard_price=None,
                    notional=cfg.order_notional_usdt,
                )
            return
        small_label = "A" if abs_a < abs_b else "B"
        large_abs = abs_b if small_label == "A" else abs_a
        small_abs = abs_a if small_label == "A" else abs_b
        side_guard = self._required_hedge_side_guard(state, small_label, pos_a, pos_b)
        side = side_guard.get("side")
        guard_price = side_guard.get("guard")
        if side is None:
            return
        active_small_count = self._active_order_count(state, small_label)
        hedge_open = self._active_hedge_notional(state, small_label, side)
        gap = large_abs - (small_abs + hedge_open / Decimal("2"))
        if gap <= 0:
            return
        diff = large_abs - small_abs
        # Keep filling the small side up to per-account cap before imbalance_limit suppression.
        if diff <= cfg.imbalance_limit_usdt and hedge_open > 0 and active_small_count >= per_account_cap:
            return
        # When diff is above low-diff threshold and small side has not reached per-account cap,
        # prioritize standard notional to ensure the second order can be established.
        if diff >= self.single_order_diff_threshold_usdt and active_small_count < per_account_cap:
            order_notional = cfg.order_notional_usdt
        else:
            order_notional = min(cfg.order_notional_usdt, gap * Decimal("2"))
        if order_notional <= 0:
            return
        small_pos = pos_a if small_label == "A" else pos_b
        signed_small = small_pos.signed_notional
        old_abs_small = abs(signed_small)
        other_abs = total_position - old_abs_small
        if cfg.position_mode == "increase":
            clipped = self._clip_order_notional_to_total_bound(
                side=side,
                order_notional=order_notional,
                signed_notional=signed_small,
                other_abs=other_abs,
                mode="increase",
                bound_total=cfg.max_total_position_usdt,
            )
        else:
            clipped = self._clip_order_notional_to_total_bound(
                side=side,
                order_notional=order_notional,
                signed_notional=signed_small,
                other_abs=other_abs,
                mode="decrease",
                bound_total=cfg.min_total_position_usdt,
            )
        order_notional = clipped
        if order_notional <= 0:
            return
        if active_small_count >= per_account_cap:
            return
        self._place_post_only_with_retry(
            state=state,
            runtime=self.accounts[small_label],
            side=side,
            guard_price=guard_price,
            notional=order_notional,
        )

    def run(self) -> None:
        logging.info("GRVT dual maker hedge started")
        symbol_modes = ",".join([f"{s.config.instrument}:{s.config.position_mode}" for s in self.symbol_states.values()])
        logging.info(
            "Symbols=%s, modes=%s, loop=%ss, book_depth=%s, per_account_cap_when_diff<%s=>1, post_only_retry=%s, cooldown=%ss, partial_timeout=%ss, stuck=%sh, mmr=%.2f",
            ",".join(self.symbol_states.keys()),
            symbol_modes,
            self.loop_interval_sec,
            self.orderbook_depth,
            self.single_order_diff_threshold_usdt,
            self.post_only_max_retry,
            self.post_only_cooldown_sec,
            self.partial_fill_timeout_sec,
            self.stuck_hours,
            float(self.mmr_alert_threshold),
        )
        self._bootstrap()
        while not self.stop_flag:
            try:
                if self.max_runtime_sec > 0 and (time.time() - self.started_at) >= self.max_runtime_sec:
                    logging.info("Reached max runtime %ss, stopping hedge engine...", self.max_runtime_sec)
                    self.stop_flag = True
                    continue
                snapshots = self._collect_snapshots()
                for state in self.symbol_states.values():
                    self._process_symbol(state, snapshots)
                self._send_daily_stuck_report()
            except Exception as exc:
                self._notify(
                    title="GRVT dual hedge loop error",
                    message=str(exc),
                    alert_key="main_loop_error",
                    cooldown_sec=120,
                )
                logging.exception("Main loop error: %s", exc)
            time.sleep(self.loop_interval_sec)
        try:
            self._cleanup_strategy_orders_on_stop()
        except Exception as exc:
            logging.exception("Stop cleanup error: %s", exc)
        logging.info("GRVT dual maker hedge stopped")


def main() -> None:
    engine = DualMakerHedgeEngine()
    engine.run()


if __name__ == "__main__":
    main()
