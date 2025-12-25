import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import requests

from dotenv import load_dotenv

from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_env import GrvtEnv
from pysdk.grvt_raw_sync import GrvtRawSync
from pysdk.grvt_raw_types import EmptyRequest, SpotBalance

POLL_INTERVAL_SECONDS = 60
ALERT_URL_TEMPLATE = "https://api.day.app/{device_key}/{title}?call=1&level=critical&sound=birdsong"


@dataclass
class AccountConfig:
    """账户配置信息"""
    name: str  # 账户名称/标识
    api_key: str
    trading_account_id: str
    private_key: str | None = None
    env: str = "prod"
    threshold: float | None = None  # 余额限定值，低于此值发送提醒


def build_client(account_config: AccountConfig) -> GrvtRawSync:
    """使用官方 GRVT Raw SDK 构建同步客户端，避免硬编码密钥。"""
    if account_config.private_key == "":  # 空字符串转为 None
        private_key = None
    else:
        private_key = account_config.private_key

    env_raw = account_config.env.lower()

    try:
        env = GrvtEnv(env_raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported GRVT_ENV '{env_raw}', expected one of {[e.value for e in GrvtEnv]}") from exc

    config = GrvtApiConfig(
        env=env,
        trading_account_id=account_config.trading_account_id,
        private_key=private_key,  # 可以为 None
        api_key=account_config.api_key,
        logger=logging.getLogger(f"grvt_raw_{account_config.name}"),
    )
    return GrvtRawSync(config)


def load_account_configs() -> List[AccountConfig]:
    """从环境变量加载所有账户配置。"""
    accounts = []
    index = 1
    
    while True:
        # 尝试读取账户配置，使用索引格式：GRVT_API_KEY_1, GRVT_TRADING_ACCOUNT_ID_1
        api_key = os.getenv(f"GRVT_API_KEY_{index}")
        trading_account_id = os.getenv(f"GRVT_TRADING_ACCOUNT_ID_{index}")
        private_key = os.getenv(f"GRVT_PRIVATE_KEY_{index}")
        env = os.getenv(f"GRVT_ENV_{index}", os.getenv("GRVT_ENV", "prod"))
        threshold_str = os.getenv(f"GRVT_THRESHOLD_{index}")
        
        # 如果第一个账户不存在，尝试读取旧格式（向后兼容）
        if index == 1 and not api_key:
            api_key = os.getenv("GRVT_API_KEY")
            trading_account_id = os.getenv("GRVT_TRADING_ACCOUNT_ID")
            private_key = os.getenv("GRVT_PRIVATE_KEY")
            env = os.getenv("GRVT_ENV", "prod")
            threshold_str = os.getenv("GRVT_THRESHOLD")
        
        # 如果都没有找到，停止
        if not api_key or not trading_account_id:
            if index == 1:
                raise ValueError("No account configuration found. Please set GRVT_API_KEY_1 and GRVT_TRADING_ACCOUNT_ID_1 (or GRVT_API_KEY and GRVT_TRADING_ACCOUNT_ID for single account)")
            break
        
        # 解析限定值
        threshold = None
        if threshold_str:
            try:
                threshold = float(threshold_str)
            except ValueError:
                logging.warning("Invalid threshold value for account %d: %s, ignoring", index, threshold_str)
        
        accounts.append(AccountConfig(
            name=f"Account_{index}" if len(trading_account_id) <= 4 else f"Account_{trading_account_id[-4:]}",
            api_key=api_key,
            trading_account_id=trading_account_id,
            private_key=private_key,
            env=env,
            threshold=threshold,
        ))
        index += 1
    
    return accounts


def send_alert(account_name: str, total_equity: float, threshold: float) -> None:
    """发送余额低于限定值的提醒。"""
    try:
        # 从环境变量读取设备码和 URL 模板
        device_key = os.getenv("GRVT_ALERT_DEVICE_KEY", "JTUG68ZG3ZAP2ALeKRWc6U")
        alert_url_template = os.getenv("GRVT_ALERT_URL", ALERT_URL_TEMPLATE)
        
        # 构建消息内容：GRVT账户余额低于多少
        title = f"GRVT账户{account_name}余额{total_equity:.2f}低于限定值{threshold:.2f}"
        
        # 将标题编码
        encoded_title = requests.utils.quote(title)
        
        # 替换 URL 模板中的占位符
        url = alert_url_template.format(device_key=device_key, title=encoded_title)
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            logging.warning("[%s] Alert sent: Total Equity %.2f is below threshold %.2f", 
                          account_name, total_equity, threshold)
        else:
            logging.error("[%s] Failed to send alert: HTTP %d", account_name, response.status_code)
    except Exception as exc:
        logging.error("[%s] Error sending alert: %s", account_name, exc)


def log_balances(account_name: str, total_equity: str, balances: Iterable[SpotBalance], threshold: float | None = None) -> None:
    """显示账户总权益信息，并检查是否需要发送提醒。"""
    logging.info("[%s] Total Equity: %s", account_name, total_equity)
    
    # 检查是否低于限定值
    if threshold is not None:
        try:
            equity_float = float(total_equity)
            if equity_float < threshold:
                send_alert(account_name, equity_float, threshold)
        except ValueError:
            logging.warning("[%s] Cannot parse total equity value: %s", account_name, total_equity)


def main() -> None:
    # 加载 .env 文件，override=True 确保覆盖已存在的环境变量
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path, override=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stop_flag = {"stop": False}

    def handle_signal(signum, frame):
        stop_flag["stop"] = True
        logging.info("Received signal %s, preparing to stop", signum)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        account_configs = load_account_configs()
        clients = {}
        for account_config in account_configs:
            try:
                clients[account_config.name] = {
                    "client": build_client(account_config),
                    "config": account_config
                }
                logging.info("Initialized client for %s (Trading Account ID: %s)", 
                           account_config.name, account_config.trading_account_id)
            except Exception as exc:
                logging.error("Failed to initialize client for %s: %s", account_config.name, exc)
                sys.exit(1)
    except Exception as exc:
        logging.error("Failed to load account configurations: %s", exc)
        sys.exit(1)

    if not clients:
        logging.error("No valid account configurations found")
        sys.exit(1)

    logging.info("GRVT balance polling started for %d account(s) (interval %ss)", 
                len(clients), POLL_INTERVAL_SECONDS)
    
    while not stop_flag["stop"]:
        for account_name, account_data in clients.items():
            try:
                response = account_data["client"].aggregated_account_summary_v1(EmptyRequest())
                if isinstance(response, GrvtError):
                    logging.error("[%s] API error fetching balance: code=%s status=%s", 
                                account_name, response.code, response.status)
                else:
                    account_config = account_data["config"]
                    log_balances(account_name, response.result.total_equity, 
                               response.result.spot_balances, account_config.threshold)
            except Exception as exc:
                logging.error("[%s] Error fetching balance: %s", account_name, exc)
        time.sleep(POLL_INTERVAL_SECONDS)

    logging.info("GRVT balance polling stopped")


if __name__ == "__main__":
    main()

