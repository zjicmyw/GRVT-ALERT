import json
import logging
import logging.handlers
import os
import random
import re
import signal
import sys
import time
import io
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, List, Dict, Any, Tuple

import requests
from eth_account import Account

from dotenv import load_dotenv

# 修复 Windows PowerShell 编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_env import GrvtEnv
from pysdk.grvt_raw_sync import GrvtRawSync
from pysdk.grvt_raw_types import EmptyRequest, SpotBalance, TransferType, Signature
from pysdk.grvt_fixed_types import Transfer
from pysdk.grvt_raw_signing import sign_transfer

ALERT_URL_TEMPLATE = "https://api.day.app/{device_key}/{title}?call=1&level=critical&sound=birdsong"
# 北京时间 UTC+8
BEIJING_TZ = timezone(timedelta(hours=8))


@dataclass
class AccountConfig:
    """账户配置信息"""
    name: str  # 账户名称/标识
    account_type: str  # "trading" 或 "funding"
    api_key: str  # 该账户类型的API密钥
    account_id: str  # 交易账户ID或资金账户ID（内部标识）
    private_key: str | None = None  # 该账户类型的私钥
    env: str = "prod"
    threshold: float | None = None  # 余额限定值，低于此值发送提醒
    # 关联账户ID（用于转账）
    related_trading_account_id: str | None = None  # 资金账户关联的交易账户ID
    related_funding_account_id: str | None = None  # 交易账户关联的资金账户地址（注意：虽然变量名是ID，但实际存储的是funding_address，即以太坊地址）
    related_main_account_id: str | None = None  # 关联的主账户ID
    # 资金账户地址（用于外部转账和提币）
    funding_address: str | None = None  # 资金账户的链上地址（以太坊地址），用于外部转账


def build_client(account_config: AccountConfig) -> GrvtRawSync:
    """使用官方 GRVT Raw SDK 构建同步客户端。
    
    参考 grvt-transfer 仓库的实现方式。
    
    Args:
        account_config: 账户配置
    """
    # 处理私钥：空字符串转为 None，但确保 private_key 不为 None（SDK 可能需要）
    if not account_config.private_key or account_config.private_key == "":
        # 如果私钥未配置，尝试使用一个默认值或抛出错误
        # 根据 grvt-transfer 的实现，即使只读查询，SDK 也可能需要私钥
        raise ValueError(f"[{account_config.name}] Private key is required for GRVT SDK authentication. "
                        f"Please configure GRVT_{account_config.account_type.upper()}_PRIVATE_KEY")
    
    private_key = account_config.private_key
    
    # 检查 API key
    if not account_config.api_key:
        raise ValueError(f"[{account_config.name}] API key is required")

    env_raw = account_config.env.lower()

    try:
        env = GrvtEnv(env_raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported GRVT_ENV '{env_raw}', expected one of {[e.value for e in GrvtEnv]}") from exc

    # 对于交易账户和资金账户，都使用 account_id 作为 trading_account_id
    # GRVT SDK 的 GrvtApiConfig 使用 trading_account_id 字段，但实际可以用于资金账户
    # 参考 grvt-transfer：确保所有必需参数都正确传递
    config = GrvtApiConfig(
        env=env,
        trading_account_id=account_config.account_id,
        private_key=private_key,  # 必须提供，不能为 None
        api_key=account_config.api_key,
        logger=logging.getLogger(f"grvt_raw_{account_config.name}"),
    )
    
    # 创建客户端
    # 参考 grvt-transfer：直接创建客户端，认证会在第一次 API 调用时自动进行
    client = GrvtRawSync(config)
    
    # 尝试进行一次测试调用以验证认证是否成功
    # 如果认证失败，会在第一次调用时发现
    try:
        if account_config.account_type == "trading":
            # 对于交易账户，尝试获取账户摘要
            test_response = client.aggregated_account_summary_v1(EmptyRequest())
            if isinstance(test_response, GrvtError):
                error_msg = getattr(test_response, 'message', '') or ''
                error_code = getattr(test_response, 'code', '')
                logging.warning("[%s] Authentication test failed: code=%s status=%s message=%s", 
                              account_config.name, error_code, test_response.status, error_msg)
                
                # 检查是否是 IP 白名单问题
                # 注意：code=1000 且登录返回 text/plain 时，通常是 IP 白名单问题
                if error_code == 1008 or 'whitelist' in error_msg.lower() or 'ip' in error_msg.lower() or (error_code == 1000 and 'authenticate' in error_msg.lower()):
                    # INSERT_YOUR_CODE
                    logging.error("[%s] (调试) 当前 API key: %s", account_config.name, account_config.api_key)
                    logging.error("[%s] ⚠️  IP 地址未在白名单中！", account_config.name)
                    logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单。", account_config.name)
                    logging.error("[%s] 查看当前 IP：https://api.ipify.org", account_config.name)
                    logging.error("[%s] 或者移除 IP 白名单限制（如果允许）。", account_config.name)
                
                # 不抛出异常，让主循环处理
            else:
                logging.debug("[%s] Authentication test successful", account_config.name)
        elif account_config.account_type == "funding":
            # 对于资金账户，尝试获取资金账户摘要
            test_response = client.funding_account_summary_v1(EmptyRequest())
            if isinstance(test_response, GrvtError):
                error_msg = getattr(test_response, 'message', '') or ''
                error_code = getattr(test_response, 'code', '')
                logging.warning("[%s] Authentication test failed: code=%s status=%s message=%s", 
                              account_config.name, error_code, test_response.status, error_msg)
                
                # 检查是否是 IP 白名单问题
                # 注意：code=1000 且登录返回 text/plain 时，通常是 IP 白名单问题
                if error_code == 1008 or 'whitelist' in error_msg.lower() or 'ip' in error_msg.lower() or (error_code == 1000 and 'authenticate' in error_msg.lower()):
                    logging.error("[%s] (调试) 当前 API key: %s", account_config.name, account_config.api_key)
                    logging.error("[%s] ⚠️  IP 地址未在白名单中！", account_config.name)
                    logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单。", account_config.name)
                    logging.error("[%s] 查看当前 IP：https://api.ipify.org", account_config.name)
                    logging.error("[%s] 或者移除 IP 白名单限制（如果允许）。", account_config.name)
                
                # 不抛出异常，让主循环处理
            else:
                logging.debug("[%s] Authentication test successful", account_config.name)
    except Exception as exc:
        # 记录异常但不阻止客户端创建（可能是网络问题等临时错误）
        error_msg = str(exc)
        logging.warning("[%s] Authentication test exception (may be temporary): %s", 
                       account_config.name, error_msg)
        
        # 检查异常消息中是否包含 IP 白名单相关信息
        if 'whitelist' in error_msg.lower() or 'IP' in error_msg:
            logging.error("[%s] ⚠️  可能是 IP 地址未在白名单中的问题！", account_config.name)
            logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单。", account_config.name)
    
    return client


def load_account_configs() -> List[AccountConfig]:
    """从环境变量加载所有账户配置（支持交易账户和资金账户独立配置）。"""
    accounts = []
    index = 1
    
    while True:
        # 尝试读取交易账户配置
        trading_api_key = os.getenv(f"GRVT_TRADING_API_KEY_{index}")
        trading_private_key = os.getenv(f"GRVT_TRADING_PRIVATE_KEY_{index}")
        trading_account_id = os.getenv(f"GRVT_TRADING_ACCOUNT_ID_{index}")
        
        # 尝试读取资金账户配置
        funding_api_key = os.getenv(f"GRVT_FUNDING_API_KEY_{index}")
        funding_private_key = os.getenv(f"GRVT_FUNDING_PRIVATE_KEY_{index}")
        funding_account_id = os.getenv(f"GRVT_FUNDING_ACCOUNT_ID_{index}")  # 内部账户ID（用于API调用）
        funding_address = os.getenv(f"GRVT_FUNDING_ACCOUNT_ADDRESS_{index}")  # 链上地址（用于外部转账）
        
        # 向后兼容：如果第一个账户不存在新格式，尝试读取旧格式
        if index == 1 and not trading_api_key:
            old_api_key = os.getenv("GRVT_API_KEY")
            old_trading_account_id = os.getenv("GRVT_TRADING_ACCOUNT_ID")
            old_private_key = os.getenv("GRVT_PRIVATE_KEY")
            old_transfer_api_key = os.getenv("GRVT_TRANSFER_API_KEY")
            old_transfer_private_key = os.getenv("GRVT_TRANSFER_PRIVATE_KEY")
            old_funding_account_id = os.getenv("GRVT_FUNDING_ACCOUNT_ID")
            
            # 如果找到旧格式，转换为交易账户配置
            if old_api_key and old_trading_account_id:
                trading_api_key = old_api_key
                trading_account_id = old_trading_account_id
                trading_private_key = old_private_key
                # 如果有转账配置，也作为交易账户的转账权限
                if old_transfer_api_key:
                    trading_api_key = old_transfer_api_key
                    trading_private_key = old_transfer_private_key
                funding_account_id = old_funding_account_id
        
        # 读取关联配置和通用配置
        related_trading_account_id = os.getenv(f"GRVT_RELATED_TRADING_ACCOUNT_ID_{index}")
        # related_funding_account_id 应该是地址，不是ID（虽然变量名是ID，但实际存储的是地址）
        related_funding_account_id = os.getenv(f"GRVT_RELATED_FUNDING_ACCOUNT_ID_{index}")
        # 向后兼容：如果没有配置 GRVT_RELATED_FUNDING_ACCOUNT_ID_X，尝试使用同索引的 funding_address
        if not related_funding_account_id:
            related_funding_account_id = funding_address
        related_main_account_id = os.getenv(f"GRVT_RELATED_MAIN_ACCOUNT_ID_{index}")
        env = os.getenv(f"GRVT_ENV_{index}", os.getenv("GRVT_ENV", "prod"))
        threshold_str = os.getenv(f"GRVT_THRESHOLD_{index}")
        
        # 向后兼容：读取旧格式的阈值
        if index == 1 and not threshold_str:
            threshold_str = os.getenv("GRVT_THRESHOLD")
        
        # 解析限定值
        threshold = None
        if threshold_str:
            try:
                threshold = float(threshold_str)
            except ValueError:
                logging.warning("Invalid threshold value for account %d: %s, ignoring", index, threshold_str)
        
        # 处理私钥空字符串
        if trading_private_key == "":
            trading_private_key = None
        if funding_private_key == "":
            funding_private_key = None
        
        # 加载交易账户配置
        if trading_api_key and trading_account_id:
            account_name = f"Trading_{index}" if len(trading_account_id) <= 4 else f"Trading_{trading_account_id[-4:]}"
            accounts.append(AccountConfig(
                name=account_name,
                account_type="trading",
                api_key=trading_api_key,
                private_key=trading_private_key,
                account_id=trading_account_id,
                env=env,
                threshold=threshold,
                related_funding_account_id=related_funding_account_id,  # 应该是地址，不是ID
                related_main_account_id=related_main_account_id,
            ))
        
        # 加载资金账户配置
        if funding_api_key and funding_account_id:
            account_name = f"Funding_{index}" if len(funding_account_id) <= 4 else f"Funding_{funding_account_id[-4:]}"
            accounts.append(AccountConfig(
                name=account_name,
                account_type="funding",
                api_key=funding_api_key,
                private_key=funding_private_key,
                account_id=funding_account_id,  # 内部账户ID（用于API调用）
                env=env,
                threshold=None,  # 资金账户通常不设置阈值
                related_trading_account_id=related_trading_account_id or trading_account_id,
                related_main_account_id=related_main_account_id,
                funding_address=funding_address,  # 链上地址（用于外部转账）
            ))
        
        # 如果第一个索引都没有找到任何配置，提供详细的错误提示
        if index == 1 and not accounts:
            error_msg = "未找到任何账户配置。\n"
            error_msg += "\n请确保在 .env 文件中配置了以下至少一项：\n"
            error_msg += "\n【交易账户配置（必需）】\n"
            error_msg += "  GRVT_TRADING_API_KEY_1=你的trading_api_key\n"
            error_msg += "  GRVT_TRADING_PRIVATE_KEY_1=你的trading_private_key\n"
            error_msg += "  GRVT_TRADING_ACCOUNT_ID_1=你的trading_account_id\n"
            error_msg += "\n【资金账户配置（可选，用于转账功能）】\n"
            error_msg += "  GRVT_FUNDING_API_KEY_1=你的funding_api_key\n"
            error_msg += "  GRVT_FUNDING_PRIVATE_KEY_1=你的funding_private_key\n"
            error_msg += "  GRVT_FUNDING_ACCOUNT_ID_1=你的funding账户内部ID\n"
            error_msg += "  GRVT_FUNDING_ACCOUNT_ADDRESS_1=你的funding账户地址（0x开头）\n"
            error_msg += "\n【关联配置（用于转账功能）】\n"
            error_msg += "  GRVT_RELATED_FUNDING_ACCOUNT_ID_1=你的funding账户地址（0x开头）\n"
            error_msg += "  GRVT_RELATED_MAIN_ACCOUNT_ID_1=你的主账户ID\n"
            raise ValueError(error_msg)
        
        # 如果当前索引没有找到任何配置，停止
        if not trading_api_key and not funding_api_key:
            break
        
        index += 1
    
    return accounts


def send_alert(account_name: str, total_equity: float, threshold: float) -> None:
    """发送余额低于限定值的提醒。"""
    try:
        # 从环境变量读取设备码和 URL 模板
        device_key = os.getenv("GRVT_ALERT_DEVICE_KEY")
        if not device_key:
            logging.error("[%s] GRVT_ALERT_DEVICE_KEY not configured, cannot send alert", account_name)
            return
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


def send_daily_summary(account_balances: Dict[str, float]) -> None:
    """发送每日余额正常汇总消息。"""
    try:
        device_key = os.getenv("GRVT_ALERT_DEVICE_KEY")
        if not device_key:
            logging.error("GRVT_ALERT_DEVICE_KEY not configured, cannot send daily summary")
            return
        alert_url_template = os.getenv("GRVT_ALERT_URL", ALERT_URL_TEMPLATE)
        
        # 构建消息内容：账户余额正常，分别是：[账户1] 余额, [账户2] 余额...
        balance_list = ", ".join([f"[{name}] {balance:.2f}" for name, balance in account_balances.items()])
        title = f"账户余额正常，分别是：{balance_list}"
        
        # 将标题编码
        encoded_title = requests.utils.quote(title)
        
        # 替换 URL 模板中的占位符
        url = alert_url_template.format(device_key=device_key, title=encoded_title)
        
        # 为每日汇总添加特殊参数：isArchive=0（不保存）和 volume=0（静音）
        if "?" in url:
            url += "&isArchive=0&volume=0"
        else:
            url += "?isArchive=0&volume=0"
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            logging.info("Daily summary sent: %d account(s) with normal balance", len(account_balances))
        else:
            logging.error("Failed to send daily summary: HTTP %d", response.status_code)
    except Exception as exc:
        logging.error("Error sending daily summary: %s", exc)


def should_send_daily_summary() -> bool:
    """检查是否到了发送每日汇总的时间（北京时间）。"""
    try:
        # 获取配置的发送时间，格式：HH:MM，默认 16:30
        send_time_str = os.getenv("GRVT_DAILY_SUMMARY_TIME", "16:30")
        hour, minute = map(int, send_time_str.split(":"))
        
        # 获取当前北京时间
        beijing_now = datetime.now(BEIJING_TZ)
        current_hour = beijing_now.hour
        current_minute = beijing_now.minute
        
        # 检查是否到了发送时间（允许在指定时间的1分钟内发送）
        if current_hour == hour and current_minute >= minute and current_minute < minute + 1:
            return True
        return False
    except Exception as exc:
        logging.warning("Error checking daily summary time: %s", exc)
        return False


def query_funding_account_balance(client: GrvtRawSync) -> float:
    """查询资金账户余额。"""
    try:
        logging.debug("Calling funding_account_summary_v1...")
        response = client.funding_account_summary_v1(EmptyRequest())
        logging.debug("funding_account_summary_v1 response type: %s", type(response).__name__)
        
        if isinstance(response, GrvtError):
            logging.error("Failed to query funding account balance: code=%s status=%s message=%s", 
                        response.code, response.status, getattr(response, 'message', ''))
            return 0.0
        
        logging.debug("funding_account_summary_v1 success: total_equity=%s", response.result.total_equity)
        return float(response.result.total_equity)
    except Exception as exc:
        # 只记录错误的第一行，避免泄露敏感信息
        error_msg = str(exc).split('\n')[0] if exc else str(exc)
        logging.error("Error querying funding account balance: %s", error_msg)
        logging.debug("Exception details: %s", exc, exc_info=True)
        return 0.0


def get_funding_account_balance(client: GrvtRawSync, currency: str = "USDT") -> float | None:
    """获取资金账户的指定币种余额。
    
    Args:
        client: GRVT客户端（资金账户）
        currency: 币种，默认USDT
    
    Returns:
        余额（float），如果失败返回None
    """
    try:
        response = client.funding_account_summary_v1(EmptyRequest())
        if isinstance(response, GrvtError):
            logging.debug("Failed to get funding account balance: code=%s status=%s message=%s",
                        response.code, response.status, getattr(response, 'message', ''))
            return None
        
        # 查找指定币种的余额
        if hasattr(response, 'result') and hasattr(response.result, 'spot_balances'):
            for balance in response.result.spot_balances:
                if balance.currency == currency:
                    return float(balance.balance)
        
        return None
    except Exception as exc:
        logging.debug("Error getting funding account balance: %s", exc)
        return None


def get_trading_account_balance(client: GrvtRawSync, currency: str = "USDT") -> float | None:
    """获取交易账户的指定币种余额。
    
    Args:
        client: GRVT客户端（交易账户）
        currency: 币种，默认USDT
    
    Returns:
        余额（float），如果失败返回None
    """
    try:
        response = client.aggregated_account_summary_v1(EmptyRequest())
        if isinstance(response, GrvtError):
            logging.debug("Failed to get trading account balance: code=%s status=%s message=%s",
                        response.code, response.status, getattr(response, 'message', ''))
            return None
        
        # 查找指定币种的余额
        if hasattr(response, 'result') and hasattr(response.result, 'spot_balances'):
            for balance in response.result.spot_balances:
                if balance.currency == currency:
                    return float(balance.balance)
        
        return None
    except Exception as exc:
        logging.debug("Error getting trading account balance: %s", exc)
        return None


def get_account_summary(client: GrvtRawSync) -> Dict[str, float] | None:
    """获取账户摘要信息（总权益、可用余额、维持保证金）。
    
    Returns:
        包含 equity, available_balance, maintenance_margin 的字典，失败返回 None
    """
    try:
        logging.debug("Calling aggregated_account_summary_v1...")
        response = client.aggregated_account_summary_v1(EmptyRequest())
        logging.debug("aggregated_account_summary_v1 response type: %s", type(response).__name__)
        
        if isinstance(response, GrvtError):
            logging.error("Failed to get account summary: code=%s status=%s message=%s", 
                        response.code, response.status, getattr(response, 'message', ''))
            return None
        
        result = response.result
        logging.debug("Account summary result: total_equity=%s, has_available_balance=%s, has_maintenance_margin=%s",
                     result.total_equity, 
                     hasattr(result, 'available_balance'),
                     hasattr(result, 'maintenance_margin'))
        
        # 尝试获取可用余额，如果不存在则使用总权益
        available_balance = float(result.available_balance) if hasattr(result, 'available_balance') and result.available_balance else float(result.total_equity)
        # 尝试获取维持保证金，如果不存在则使用0
        maintenance_margin = float(result.maintenance_margin) if hasattr(result, 'maintenance_margin') and result.maintenance_margin else 0.0
        
        summary = {
            "equity": float(result.total_equity),
            "available_balance": available_balance,
            "maintenance_margin": maintenance_margin,
        }
        logging.debug("Account summary extracted: %s", summary)
        return summary
    except Exception as exc:
        # 只记录错误的第一行，避免泄露敏感信息
        error_msg = str(exc).split('\n')[0] if exc else str(exc)
        logging.error("Error getting account summary: %s", error_msg)
        logging.debug("Exception details: %s", exc, exc_info=True)
        return None


def verify_transfer_balance(
    client: GrvtRawSync,
    required_amount: float,
    currency: str = "USDT"
) -> bool:
    """验证账户是否有足够的余额进行转账。
    
    参考 grvt-transfer 仓库的做法，在转账前检查余额。
    
    Args:
        client: GRVT客户端
        required_amount: 需要的转账金额
        currency: 币种，默认USDT
    
    Returns:
        是否有足够的余额
    """
    try:
        summary = get_account_summary(client)
        if not summary:
            logging.warning("Cannot verify balance: failed to get account summary")
            return True  # 如果无法获取，假设有余额（避免阻塞转账）
        
        available_balance = summary.get("available_balance", 0.0)
        
        if available_balance < required_amount:
            logging.warning("Insufficient balance: available=%.2f, required=%.2f %s",
                          available_balance, required_amount, currency)
            return False
        
        return True
    except Exception as exc:
        # 只记录错误的第一行，避免泄露敏感信息
        error_msg = str(exc).split('\n')[0] if exc else str(exc)
        logging.warning("Error verifying balance: %s", error_msg)
        return True  # 如果验证失败，假设有余额（避免阻塞转账）


def calculate_safe_transfer_amount(
    equity: float,
    available_balance: float,
    maintenance_margin: float,
    target_amount: float
) -> float:
    """计算安全的转账金额，考虑可用余额和维持保证金。
    
    参考 grvt-transfer 仓库的安全约束逻辑：
    - 不能超过可用余额
    - 预留至少2倍维持保证金，避免转账后保证金使用率过高
    
    Args:
        equity: 总权益
        available_balance: 可用余额
        maintenance_margin: 维持保证金
        target_amount: 目标转账金额
    
    Returns:
        安全的转账金额
    """
    # 限制1: 不能超过可用余额
    max_by_avail = available_balance
    
    # 限制2: 预留至少2倍维持保证金（参考 grvt-transfer 的做法）
    max_by_mm = equity - 2 * maintenance_margin if maintenance_margin > 0 else equity
    
    # 取最小值
    safe_amount = min(target_amount, max_by_avail, max_by_mm)
    
    if safe_amount < 0:
        return 0.0
    
    return safe_amount


def sweep_funding_to_trading(
    funding_config: AccountConfig,
    trading_config: AccountConfig,
    main_account_id: str,
    threshold: float = 100.0,
    currency: str = "USDT"
) -> bool:
    """将 funding 账户资金归集到 trading 账户（如果超过阈值）。
    
    参考 grvt-transfer 仓库的 Funding Sweep 机制，避免资金"卡"在 funding 账户
    导致 trading 可用余额不足。
    
    Args:
        funding_config: 资金账户配置
        trading_config: 交易账户配置
        main_account_id: 主账户ID
        threshold: 触发归集的阈值（默认100 USDT）
        currency: 币种，默认USDT
    
    Returns:
        是否成功执行归集
    """
    try:
        if funding_config.account_type != "funding":
            logging.error("[%s] Config must be a funding account config for sweep", funding_config.name)
            return False
        
        if not funding_config.private_key:
            logging.error("[%s] Private key not configured, cannot sweep", funding_config.name)
            return False
        
        client = build_client(funding_config)
        response = client.funding_account_summary_v1(EmptyRequest())
        
        if isinstance(response, GrvtError):
            logging.error("[%s] Failed to query funding balance for sweep: code=%s status=%s",
                        funding_config.name, response.code, response.status)
            return False
        
        funding_balance = float(response.result.total_equity)
        
        if funding_balance > threshold:
            logging.info("[Funding Sweep] %s funding balance %.2f exceeds threshold %.2f, sweeping to trading",
                        funding_config.name, funding_balance, threshold)
            success, tx_info = transfer_funding_to_trading(
                funding_config, main_account_id,
                funding_config.account_id,
                trading_config.account_id,
                funding_balance, currency
            )
            if success:
                tx_id = tx_info.get("tx_id")
                logging.info("[Funding Sweep] Sweep completed (tx_id: %s)", tx_id or "N/A")
            return success
        
        return True
    except Exception as exc:
        logging.error("[%s] Error in funding sweep: %s", funding_config.name, exc)
        return False


def transfer_all_funding_to_trading(
    funding_config: AccountConfig,
    trading_config: AccountConfig,
    main_account_id: str,
    currency: str = "USDT"
) -> Tuple[bool, Dict[str, Any]]:
    """将 funding 账户的全部余额转到 trading 账户。
    
    与 sweep_funding_to_trading 不同，此函数会无条件地将所有余额转出，
    不管余额多少（只要 > 0）。
    
    Args:
        funding_config: 资金账户配置
        trading_config: 交易账户配置
        main_account_id: 主账户ID
        currency: 币种，默认USDT
    
    Returns:
        (是否成功, 详细信息字典)
        详细信息包含：
        - success: 是否成功
        - balance: 转账前的余额
        - amount_transferred: 实际转账金额
        - tx_id: 交易ID（如果成功）
        - error: 错误信息（如果失败）
    """
    try:
        if funding_config.account_type != "funding":
            error_msg = f"Config must be a funding account config, got: {funding_config.account_type}"
            logging.error("[%s] %s", funding_config.name, error_msg)
            return False, {"success": False, "error": error_msg, "balance": 0.0, "amount_transferred": 0.0}
        
        if trading_config.account_type != "trading":
            error_msg = f"Trading config must be a trading account config, got: {trading_config.account_type}"
            logging.error("[%s] %s", funding_config.name, error_msg)
            return False, {"success": False, "error": error_msg, "balance": 0.0, "amount_transferred": 0.0}
        
        if not funding_config.private_key:
            error_msg = "Private key not configured for funding account"
            logging.error("[%s] %s", funding_config.name, error_msg)
            return False, {"success": False, "error": error_msg, "balance": 0.0, "amount_transferred": 0.0}
        
        # 查询 funding 账户余额
        client = build_client(funding_config)
        response = client.funding_account_summary_v1(EmptyRequest())
        
        if isinstance(response, GrvtError):
            error_msg = f"Failed to query funding balance: code={response.code} status={response.status}"
            logging.error("[%s] %s", funding_config.name, error_msg)
            return False, {"success": False, "error": error_msg, "balance": 0.0, "amount_transferred": 0.0}
        
        # 获取指定币种的余额
        funding_balance = 0.0
        if hasattr(response, 'result') and hasattr(response.result, 'spot_balances'):
            for balance in response.result.spot_balances:
                if balance.currency == currency:
                    funding_balance = float(balance.balance)
                    break
        
        # 如果没有找到指定币种，尝试使用 total_equity
        if funding_balance == 0.0 and hasattr(response, 'result') and hasattr(response.result, 'total_equity'):
            funding_balance = float(response.result.total_equity)
        
        logging.info("[Transfer All] %s funding balance: %.2f %s", 
                    funding_config.name, funding_balance, currency)
        
        # 如果余额为0或负数，直接返回成功（无需转账）
        if funding_balance <= 0:
            logging.info("[Transfer All] %s funding balance is %.2f, no transfer needed", 
                        funding_config.name, funding_balance)
            return True, {
                "success": True,
                "balance": funding_balance,
                "amount_transferred": 0.0,
                "tx_id": None,
                "message": "Balance is zero or negative, no transfer needed"
            }
        
        # 执行转账
        logging.info("[Transfer All] Transferring %.2f %s from %s funding to %s trading", 
                    funding_balance, currency, funding_config.name, trading_config.name)
        
        success, tx_info = transfer_funding_to_trading(
            funding_config, main_account_id,
            funding_config.account_id,
            trading_config.account_id,
            funding_balance, currency
        )
        
        if success:
            tx_id = tx_info.get("tx_id")
            logging.info("[Transfer All] Successfully transferred %.2f %s from %s funding to %s trading (tx_id: %s)", 
                        funding_balance, currency, funding_config.name, trading_config.name, tx_id or "N/A")
            return True, {
                "success": True,
                "balance": funding_balance,
                "amount_transferred": funding_balance,
                "tx_id": tx_id,
                "message": "Transfer completed successfully"
            }
        else:
            error_code = tx_info.get("code")
            error_status = tx_info.get("status")
            error_msg = tx_info.get("message", "Unknown error")
            logging.error("[Transfer All] Failed to transfer %.2f %s from %s funding to %s trading: code=%s status=%s message=%s",
                        funding_balance, currency, funding_config.name, trading_config.name, 
                        error_code, error_status, error_msg)
            return False, {
                "success": False,
                "balance": funding_balance,
                "amount_transferred": 0.0,
                "tx_id": None,
                "error": {
                    "code": error_code,
                    "status": error_status,
                    "message": error_msg
                }
            }
        
    except Exception as exc:
        error_msg = str(exc)
        logging.error("[%s] Error in transfer_all_funding_to_trading: %s", funding_config.name, error_msg)
        return False, {
            "success": False,
            "error": {"exception": error_msg},
            "balance": 0.0,
            "amount_transferred": 0.0,
            "tx_id": None
        }


def check_and_balance_accounts(
    account1_name: str, account1_balance: float,
    account2_name: str, account2_balance: float,
    threshold_percent: float, target_percent: float
) -> Dict[str, Any] | None:
    """检查并平衡两个账户的余额（基础版本，不考虑安全约束）。
    
    Returns:
        如果需要转账，返回转账信息字典；否则返回None
    """
    # 计算总资金
    total_balance = account1_balance + account2_balance
    if total_balance == 0:
        logging.debug("[Auto-Balance] Total balance is zero, skipping balance check")
        return None
    
    # 计算每个账户当前百分比
    account1_percent = (account1_balance / total_balance) * 100
    account2_percent = (account2_balance / total_balance) * 100
    
    logging.debug("[Auto-Balance] Basic balance check: %s=%.2f (%.2f%%), %s=%.2f (%.2f%%), threshold=%.2f%%, target=%.2f%%",
                 account1_name, account1_balance, account1_percent,
                 account2_name, account2_balance, account2_percent,
                 threshold_percent, target_percent)
    
    # 检查是否有账户低于阈值
    transfer_info = None
    
    if account1_percent < threshold_percent:
        # 账户1低于阈值，需要从账户2转账
        target_balance = total_balance * (target_percent / 100)
        transfer_amount = target_balance - account1_balance
        if transfer_amount > 0 and account2_balance >= transfer_amount:
            logging.info("[Auto-Balance] %s balance %.2f%% is below threshold %.2f%%, transferring %.2f from %s",
                        account1_name, account1_percent, threshold_percent, transfer_amount, account2_name)
            transfer_info = {
                "from_account": account2_name,
                "to_account": account1_name,
                "amount": transfer_amount,
                "reason": f"Account {account1_name} balance {account1_percent:.2f}% below threshold {threshold_percent}%"
            }
        else:
            logging.warning("[Auto-Balance] Cannot transfer: transfer_amount=%.2f, account2_balance=%.2f",
                          transfer_amount, account2_balance)
    elif account2_percent < threshold_percent:
        # 账户2低于阈值，需要从账户1转账
        target_balance = total_balance * (target_percent / 100)
        transfer_amount = target_balance - account2_balance
        if transfer_amount > 0 and account1_balance >= transfer_amount:
            logging.info("[Auto-Balance] %s balance %.2f%% is below threshold %.2f%%, transferring %.2f from %s",
                        account2_name, account2_percent, threshold_percent, transfer_amount, account1_name)
            transfer_info = {
                "from_account": account1_name,
                "to_account": account2_name,
                "amount": transfer_amount,
                "reason": f"Account {account2_name} balance {account2_percent:.2f}% below threshold {threshold_percent}%"
            }
        else:
            logging.warning("[Auto-Balance] Cannot transfer: transfer_amount=%.2f, account1_balance=%.2f",
                          transfer_amount, account1_balance)
    else:
        logging.debug("[Auto-Balance] Both accounts are above threshold (%.2f%% and %.2f%% >= %.2f%%), no transfer needed",
                     account1_percent, account2_percent, threshold_percent)
    
    return transfer_info


def check_and_balance_accounts_improved(
    account1_name: str, account1_summary: Dict[str, float],
    account2_name: str, account2_summary: Dict[str, float],
    threshold_percent: float, target_percent: float
) -> Dict[str, Any] | None:
    """改进的余额平衡检查，考虑可用余额和维持保证金。
    
    检查每个账户的余额占比是否低于阈值，如果低于阈值则从另一个账户转账。
    使用 target_percent 计算目标转账金额，并考虑可用余额和维持保证金的安全约束。
    
    Args:
        account1_name: 账户1名称
        account1_summary: 账户1摘要（包含 equity, available_balance, maintenance_margin）
        account2_name: 账户2名称
        account2_summary: 账户2摘要（包含 equity, available_balance, maintenance_margin）
        threshold_percent: 触发阈值百分比（账户余额占比低于此值时触发转账）
        target_percent: 目标百分比（转账后账户余额占比应达到此值）
    
    Returns:
        如果需要转账，返回转账信息字典；否则返回None
    """
    account1_equity = account1_summary.get("equity", 0.0)
    account1_available = account1_summary.get("available_balance", 0.0)
    account1_mm = account1_summary.get("maintenance_margin", 0.0)
    
    account2_equity = account2_summary.get("equity", 0.0)
    account2_available = account2_summary.get("available_balance", 0.0)
    account2_mm = account2_summary.get("maintenance_margin", 0.0)
    
    # 计算总资金
    total_equity = account1_equity + account2_equity
    if total_equity == 0:
        logging.debug("[Auto-Balance] Total equity is zero, skipping balance check")
        return None
    
    # 计算每个账户的余额占比
    account1_percent = (account1_equity / total_equity) * 100
    account2_percent = (account2_equity / total_equity) * 100
    
    logging.debug("[Auto-Balance] Balance check: %s=%.2f (%.2f%%), %s=%.2f (%.2f%%), threshold=%.2f%%, target=%.2f%%",
                 account1_name, account1_equity, account1_percent,
                 account2_name, account2_equity, account2_percent,
                 threshold_percent, target_percent)
    
    # 检查是否有账户低于阈值
    transfer_info = None
    
    if account1_percent < threshold_percent:
        # 账户1低于阈值，需要从账户2转账到账户1
        target_balance = total_equity * (target_percent / 100)
        needed = target_balance - account1_equity
        
        # 使用账户2的可用余额和维持保证金计算安全转账金额
        transfer_amount = calculate_safe_transfer_amount(
            account2_equity, account2_available, account2_mm, needed
        )
        
        if transfer_amount <= 0:
            logging.warning("[Auto-Balance] Cannot transfer from %s: insufficient available balance (%.2f) or safety margin (equity: %.2f, mm: %.2f), needed: %.2f",
                           account2_name, account2_available, account2_equity, account2_mm, needed)
            return None
        
        transfer_info = {
            "from_account": account2_name,
            "to_account": account1_name,
            "amount": transfer_amount,
            "account1_percent": account1_percent,
            "account2_percent": account2_percent,
            "reason": f"Account {account1_name} balance {account1_percent:.2f}% below threshold {threshold_percent}% (needed: {needed:.2f}, safe: {transfer_amount:.2f})"
        }
        
    elif account2_percent < threshold_percent:
        # 账户2低于阈值，需要从账户1转账到账户2
        target_balance = total_equity * (target_percent / 100)
        needed = target_balance - account2_equity
        
        # 使用账户1的可用余额和维持保证金计算安全转账金额
        transfer_amount = calculate_safe_transfer_amount(
            account1_equity, account1_available, account1_mm, needed
        )
        
        if transfer_amount <= 0:
            logging.warning("[Auto-Balance] Cannot transfer from %s: insufficient available balance (%.2f) or safety margin (equity: %.2f, mm: %.2f), needed: %.2f",
                           account1_name, account1_available, account1_equity, account1_mm, needed)
            return None
        
        transfer_info = {
            "from_account": account1_name,
            "to_account": account2_name,
            "amount": transfer_amount,
            "account1_percent": account1_percent,
            "account2_percent": account2_percent,
            "reason": f"Account {account2_name} balance {account2_percent:.2f}% below threshold {threshold_percent}% (needed: {needed:.2f}, safe: {transfer_amount:.2f})"
        }
    else:
        logging.debug("[Auto-Balance] Both accounts are above threshold (%.2f%% and %.2f%% >= %.2f%%), no transfer needed",
                     account1_percent, account2_percent, threshold_percent)
    
    return transfer_info


def try_transfer_with_retry(
    client: GrvtRawSync,
    transfer_request,
    retries: int = 2,
    backoff_ms: int = 1500,
    account_name: str = ""
) -> Tuple[bool, Dict[str, Any]]:
    """执行转账并支持重试机制。
    
    Args:
        client: GRVT客户端
        transfer_request: 转账请求
        retries: 重试次数
        backoff_ms: 初始退避时间（毫秒）
        account_name: 账户名称（用于日志）
    
    Returns:
        (success: bool, tx_info: dict) - 成功状态和交易信息
    """
    attempt = 0
    while True:
        try:
            response = client.transfer_v1(transfer_request)
            
            # 成功响应
            if not isinstance(response, GrvtError):
                try:
                    # 尝试提取tx_id和响应信息
                    tx_id = None
                    result_dict = {}
                    
                    # 尝试多种方式提取tx_id
                    if hasattr(response, 'result'):
                        if hasattr(response.result, 'tx_id'):
                            tx_id = response.result.tx_id
                        elif hasattr(response.result, 'transaction_id'):
                            tx_id = response.result.transaction_id
                        try:
                            result_dict = asdict(response.result)
                        except Exception:
                            result_dict = {"tx_id": tx_id} if tx_id else {}
                    elif hasattr(response, 'tx_id'):
                        tx_id = response.tx_id
                    elif hasattr(response, 'transaction_id'):
                        tx_id = response.transaction_id
                    
                    # 如果还没有找到tx_id，尝试从字典中获取
                    if not tx_id:
                        try:
                            if hasattr(response, 'result'):
                                result_dict = asdict(response.result) if hasattr(response.result, '__dict__') else {}
                            else:
                                result_dict = asdict(response) if hasattr(response, '__dict__') else {}
                            tx_id = result_dict.get('tx_id') or result_dict.get('transaction_id') or None
                        except Exception:
                            pass
                    
                    return True, {
                        "success": True,
                        "tx_id": str(tx_id) if tx_id else None,
                        "result": result_dict,
                        "response": asdict(response) if hasattr(response, '__dict__') else str(response)
                    }
                except Exception as e:
                    # 如果无法解析响应，至少返回成功状态
                    logging.debug("[%s] Could not parse transfer response: %s", account_name, e)
                    return True, {
                        "success": True,
                        "tx_id": None,
                        "result": {},
                        "response": str(response)
                    }
            
            # 错误响应
            error_dict = asdict(response) if hasattr(response, '__dict__') else {}
            code = error_dict.get("code")
            status = error_dict.get("status")
            message = error_dict.get("message", "")
            
            # 记录详细的错误信息（包括请求参数）
            logging.info("[%s] Transfer request details (on error): from_account_id=%s, from_sub_account_id=%s, to_account_id=%s, to_sub_account_id=%s, currency=%s, num_tokens=%s",
                        account_name, 
                        getattr(transfer_request, 'from_account_id', 'N/A'),
                        getattr(transfer_request, 'from_sub_account_id', 'N/A'),
                        getattr(transfer_request, 'to_account_id', 'N/A'),
                        getattr(transfer_request, 'to_sub_account_id', 'N/A'),
                        getattr(transfer_request, 'currency', 'N/A'),
                        getattr(transfer_request, 'num_tokens', 'N/A'))
            
            # 可重试的错误：网络错误或限流错误
            if attempt < retries and (code == 1006 or status == 429):
                wait_time = backoff_ms / 1000.0
                logging.warning("[%s] Transfer failed (code=%s, status=%s), retrying in %.2f seconds (attempt %d/%d)",
                              account_name, code, status, wait_time, attempt + 1, retries)
                time.sleep(wait_time)
                attempt += 1
                backoff_ms = int(backoff_ms * 1.5)  # 指数退避
                continue
            
            # 不可重试的错误
            return False, {
                "success": False,
                "tx_id": None,
                "error": error_dict,
                "code": code,
                "status": status,
                "message": error_dict.get("message", "")
            }
            
        except Exception as e:
            # 异常错误
            if attempt < retries:
                wait_time = backoff_ms / 1000.0
                logging.warning("[%s] Transfer exception: %s, retrying in %.2f seconds (attempt %d/%d)",
                              account_name, str(e), wait_time, attempt + 1, retries)
                time.sleep(wait_time)
                attempt += 1
                backoff_ms = int(backoff_ms * 1.5)
                continue
            
            logging.error("[%s] Transfer exception after %d retries: %s", account_name, retries, str(e))
            return False, {
                "success": False,
                "tx_id": None,
                "error": {"exception": str(e)},
                "code": None,
                "status": None,
                "message": str(e)
            }


def transfer_between_trading_accounts(
    from_config: AccountConfig,
    to_config: AccountConfig,
    from_main_account_id: str,
    from_trading_account_id: str,
    to_main_account_id: str,
    to_trading_account_id: str,
    amount: float,
    currency: str = "USDT"
) -> bool:
    """在两个交易账户之间转账。
    
    Args:
        from_config: 转出交易账户配置
        to_config: 转入交易账户配置
        from_main_account_id: 转出账户的主账户ID
        from_trading_account_id: 转出账户的交易账户ID
        to_main_account_id: 转入账户的主账户ID
        to_trading_account_id: 转入账户的交易账户ID
        amount: 转账金额
        currency: 币种，默认USDT
    """
    try:
        # 验证转账金额
        if amount <= 0:
            logging.error("[%s] Transfer amount must be positive, got: %.2f", from_config.name, amount)
            return False
        
        # 验证主账户ID
        if not from_main_account_id or not to_main_account_id:
            logging.error("[%s] Main account IDs are required for transfer", from_config.name)
            return False
        
        # 验证账户类型
        if from_config.account_type != "trading":
            logging.error("[%s] Source account must be a trading account", from_config.name)
            return False
        
        if not from_config.private_key:
            logging.error("[%s] Private key not configured, cannot transfer", from_config.name)
            return False
        
        # 使用转出交易账户的客户端
        from_client = build_client(from_config)
        
        # 验证余额（可选，如果余额不足会在API调用时失败）
        if not verify_transfer_balance(from_client, amount, currency):
            logging.warning("[%s] Balance verification failed, but proceeding with transfer (API will reject if insufficient)",
                          from_config.name)
        
        # 创建账户对象用于签名
        account = Account.from_key(from_config.private_key)
        
        # 构建转账请求
        # from_account_id 和 to_account_id 使用主账户ID
        # from_sub_account_id 和 to_sub_account_id 使用交易账户ID
        transfer = Transfer(
            from_account_id=from_main_account_id,
            from_sub_account_id=from_trading_account_id,
            to_account_id=to_main_account_id,
            to_sub_account_id=to_trading_account_id,
            currency=currency,
            num_tokens=str(amount),
            signature=Signature(
                signer="",
                r="0x",
                s="0x",
                v=0,
                expiration=str(int(time.time_ns() + 15 * 60 * 1_000_000_000)),
                nonce=random.randint(1, 2**31 - 1)
            ),
            transfer_type=TransferType.STANDARD,
            transfer_metadata=""
        )
        
        # 签名转账
        config = GrvtApiConfig(
            env=GrvtEnv(from_config.env.lower()),
            trading_account_id=from_config.account_id,
            private_key=from_config.private_key,
            api_key=from_config.api_key,
            logger=logging.getLogger(f"grvt_transfer_{from_config.name}"),
        )
        
        signed_transfer = sign_transfer(transfer, config, account)
        
        # 转换为ApiTransferRequest
        from pysdk.grvt_raw_types import ApiTransferRequest
        transfer_request = ApiTransferRequest(
            from_account_id=signed_transfer.from_account_id,
            from_sub_account_id=signed_transfer.from_sub_account_id,
            to_account_id=signed_transfer.to_account_id,
            to_sub_account_id=signed_transfer.to_sub_account_id,
            currency=signed_transfer.currency,
            num_tokens=signed_transfer.num_tokens,
            signature=signed_transfer.signature,
            transfer_type=signed_transfer.transfer_type,
            transfer_metadata=signed_transfer.transfer_metadata
        )
        
        # 执行转账
        response = from_client.transfer_v1(transfer_request)
        
        if isinstance(response, GrvtError):
            error_msg = getattr(response, 'message', '') or ''
            error_code = getattr(response, 'code', '')
            error_status = getattr(response, 'status', '')
            logging.error("[%s] Transfer failed: code=%s status=%s message=%s", 
                        from_config.name, error_code, error_status, error_msg)
            # 根据错误类型给出更明确的提示
            error_msg_lower = error_msg.lower()
            # 检查权限错误：code=1001 或 status=403 或消息中包含 permission/unauthorized
            if (error_code == 1001 or error_status == 403 or 
                'permission' in error_msg_lower or 'unauthorized' in error_msg_lower or 'not authorized' in error_msg_lower):
                logging.error("[%s] ⚠️  API key 没有转账权限！", from_config.name)
                logging.error("[%s] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                            from_config.name, from_config.api_key[:8] + "...", from_config.account_type, from_config.account_id)
                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 Transfer 权限）。", from_config.name)
            elif 'insufficient' in error_msg_lower or 'balance' in error_msg_lower:
                logging.error("[%s] Insufficient balance for transfer. Please check account balance.",
                            from_config.name)
            return False
        
        logging.info("[%s] Transferred %.2f %s from %s to %s", 
                    from_config.name, amount, currency, from_trading_account_id, to_trading_account_id)
        return True
        
    except Exception as exc:
        error_msg = str(exc)
        logging.error("[%s] Error transferring: %s", from_config.name, error_msg)
        # 检查是否是 API key 相关错误
        if 'api' in error_msg.lower() or 'key' in error_msg.lower() or 'permission' in error_msg.lower():
            logging.error("[%s] ⚠️  可能是 API key 问题！", from_config.name)
            logging.error("[%s] 出问题的 API key: %s (账户类型: %s)", 
                        from_config.name, from_config.api_key[:8] + "...", from_config.account_type)
        return False


def transfer_trading_to_funding(
    trading_config: AccountConfig,
    main_account_id: str,
    trading_account_id: str,
    funding_account_id: str,
    amount: float,
    currency: str = "USDT"
) -> Tuple[bool, Dict[str, Any]]:
    """从交易账户转到资金账户（使用交易账户的API key，因为trading账户有内部划转到funding的权限）。
    
    注意：根据 grvt-transfer 参考代码，内部转账（trading → funding）时，
    to_sub_account_id 应该使用 "0"，而不是 funding_account_id。
    因此 funding_account_id 参数虽然保留但不再使用。
    
    Args:
        trading_config: 交易账户配置（使用交易账户的API key）
        main_account_id: 主账户ID
        trading_account_id: 交易账户ID
        funding_account_id: 资金账户ID（保留参数，但不再使用，内部转账时 to_sub_account_id 固定为 "0"）
        amount: 转账金额
        currency: 币种，默认USDT
    """
    try:
        # 验证转账金额
        if amount <= 0:
            logging.error("[%s] Transfer amount must be positive, got: %.2f", trading_config.name, amount)
            return False, {"success": False, "error": "Invalid amount", "amount": amount}
        
        # 验证主账户ID
        if not main_account_id:
            logging.error("[%s] Main account ID is required for transfer", trading_config.name)
            return False, {"success": False, "error": "Missing main account ID"}
        
        # 验证账户类型
        if trading_config.account_type != "trading":
            logging.error("[%s] Config must be a trading account config", trading_config.name)
            return False, {"success": False, "error": "Invalid account type", "account_type": trading_config.account_type}
        
        if not trading_config.private_key:
            logging.error("[%s] Private key not configured, cannot transfer", trading_config.name)
            return False, {"success": False, "error": "Private key not configured"}
        
        # 使用交易账户的客户端
        client = build_client(trading_config)
        
        # 验证余额（可选，如果余额不足会在API调用时失败）
        if not verify_transfer_balance(client, amount, currency):
            logging.warning("[%s] Balance verification failed, but proceeding with transfer (API will reject if insufficient)",
                          trading_config.name)
        
        account = Account.from_key(trading_config.private_key)
        
        # 根据 grvt-transfer 参考代码，内部转账（trading → funding）时，
        # to_sub_account_id 应该使用 "0"，而不是 funding_account_id
        # 参考：req_a_internal = TransferService.build_req(..., a_funding_addr, "0", ...)
        expiration_ns = str(int(time.time_ns() + 15 * 60 * 1_000_000_000))
        nonce = random.randint(1, 2**31 - 1)
        
        logging.debug("[%s] Building transfer request: from_account_id=%s, from_sub_account_id=%s, to_account_id=%s, to_sub_account_id=%s, amount=%s, expiration=%s, nonce=%s",
                     trading_config.name, main_account_id, trading_account_id, main_account_id, "0", amount, expiration_ns, nonce)
        
        transfer = Transfer(
            from_account_id=main_account_id,
            from_sub_account_id=trading_account_id,
            to_account_id=main_account_id,
            to_sub_account_id="0",  # 内部转账到funding账户时，使用"0"而不是funding_account_id
            currency=currency,
            num_tokens=str(amount),
            signature=Signature(
                signer="",
                r="0x",
                s="0x",
                v=0,
                expiration=expiration_ns,
                nonce=nonce
            ),
            transfer_type=TransferType.STANDARD,
            transfer_metadata=""
        )
        
        grvt_config = GrvtApiConfig(
            env=GrvtEnv(trading_config.env.lower()),
            trading_account_id=trading_config.account_id,
            private_key=trading_config.private_key,
            api_key=trading_config.api_key,
            logger=logging.getLogger(f"grvt_transfer_{trading_config.name}"),
        )
        
        signed_transfer = sign_transfer(transfer, grvt_config, account)
        
        from pysdk.grvt_raw_types import ApiTransferRequest
        transfer_request = ApiTransferRequest(
            from_account_id=signed_transfer.from_account_id,
            from_sub_account_id=signed_transfer.from_sub_account_id,
            to_account_id=signed_transfer.to_account_id,
            to_sub_account_id=signed_transfer.to_sub_account_id,
            currency=signed_transfer.currency,
            num_tokens=signed_transfer.num_tokens,
            signature=signed_transfer.signature,
            transfer_type=signed_transfer.transfer_type,
            transfer_metadata=signed_transfer.transfer_metadata
        )
        
        # 使用重试机制执行转账
        success, tx_info = try_transfer_with_retry(
            client, transfer_request, retries=2, backoff_ms=1500, account_name=trading_config.name
        )
        
        if not success:
            error_code = tx_info.get("code")
            error_status = tx_info.get("status")
            error_msg = tx_info.get("message", "")
            logging.error("[%s] Transfer to funding account failed: code=%s status=%s message=%s", 
                        trading_config.name, error_code, error_status, error_msg)
            # 根据错误类型给出更明确的提示
            error_msg_lower = error_msg.lower() if error_msg else ""
            # 检查权限错误：code=1001 或 status=403 或消息中包含 permission/unauthorized
            if (error_code == 1001 or error_status == 403 or 
                'permission' in error_msg_lower or 'unauthorized' in error_msg_lower or 'not authorized' in error_msg_lower):
                logging.error("[%s] ⚠️  API key 没有转账权限！", trading_config.name)
                logging.error("[%s] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                            trading_config.name, trading_config.api_key[:8] + "...", trading_config.account_type, trading_config.account_id)
                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 Internal Transfer 权限，从 Trading 到 Funding）。", trading_config.name)
            elif 'insufficient' in error_msg_lower or 'balance' in error_msg_lower:
                logging.error("[%s] Insufficient balance for transfer. Please check account balance.",
                            trading_config.name)
            return False, tx_info
        
        tx_id = tx_info.get("tx_id")
        # Success log removed - will be logged at TransferFlow level
        return True, tx_info
        
    except Exception as exc:
        error_msg = str(exc)
        logging.error("[%s] Error transferring to funding account: %s", trading_config.name, error_msg)
        # 检查是否是 API key 相关错误
        if 'api' in error_msg.lower() or 'key' in error_msg.lower() or 'permission' in error_msg.lower():
            logging.error("[%s] ⚠️  可能是 API key 问题！", trading_config.name)
            logging.error("[%s] 出问题的 API key: %s (账户类型: %s)", 
                        trading_config.name, trading_config.api_key[:8] + "...", trading_config.account_type)
        return False, {"success": False, "error": {"exception": error_msg}, "message": error_msg}


def transfer_funding_to_trading(
    funding_config: AccountConfig,
    main_account_id: str,
    funding_account_id: str,
    trading_account_id: str,
    amount: float,
    currency: str = "USDT"
) -> Tuple[bool, Dict[str, Any]]:
    """从资金账户转到交易账户（使用资金账户的API key，因为资金账户支持内部转账）。
    
    注意：根据 grvt-transfer 参考代码，内部转账（funding → trading）时，
    from_sub_account_id 应该使用 "0"，而不是 funding_account_id。
    因此 funding_account_id 参数虽然保留但不再使用。
    
    Args:
        funding_config: 资金账户配置（使用资金账户的API key）
        main_account_id: 主账户ID
        funding_account_id: 资金账户ID（保留参数，但不再使用，内部转账时 from_sub_account_id 固定为 "0"）
        trading_account_id: 交易账户ID
        amount: 转账金额
        currency: 币种，默认USDT
    """
    try:
        # 验证转账金额
        if amount <= 0:
            logging.error("[%s] Transfer amount must be positive, got: %.2f", funding_config.name, amount)
            return False, {"success": False, "error": "Invalid amount", "amount": amount}
        
        # 验证主账户ID
        if not main_account_id:
            logging.error("[%s] Main account ID is required for transfer", funding_config.name)
            return False, {"success": False, "error": "Missing main account ID"}
        
        # 验证账户类型
        if funding_config.account_type != "funding":
            logging.error("[%s] Config must be a funding account config", funding_config.name)
            return False, {"success": False, "error": "Invalid account type", "account_type": funding_config.account_type}
        
        if not funding_config.private_key:
            logging.error("[%s] Private key not configured, cannot transfer", funding_config.name)
            return False, {"success": False, "error": "Private key not configured"}
        
        # 使用资金账户的客户端
        client = build_client(funding_config)
        
        account = Account.from_key(funding_config.private_key)
        
        # 根据 grvt-transfer 参考代码，内部转账（funding → trading）时，
        # from_sub_account_id 应该使用 "0"，而不是 funding_account_id
        # 参考：req_b_deposit = TransferService.build_req(..., b_funding_addr, "0", b_funding_addr, b_trading_sub, ...)
        expiration_ns = str(int(time.time_ns() + 15 * 60 * 1_000_000_000))
        nonce = random.randint(1, 2**31 - 1)
        
        logging.debug("[%s] Building transfer request: from_account_id=%s, from_sub_account_id=%s, to_account_id=%s, to_sub_account_id=%s, amount=%s, expiration=%s, nonce=%s",
                     funding_config.name, main_account_id, "0", main_account_id, trading_account_id, amount, expiration_ns, nonce)
        
        transfer = Transfer(
            from_account_id=main_account_id,
            from_sub_account_id="0",  # 内部转账从funding账户转出时，使用"0"而不是funding_account_id
            to_account_id=main_account_id,
            to_sub_account_id=trading_account_id,
            currency=currency,
            num_tokens=str(amount),
            signature=Signature(
                signer="",
                r="0x",
                s="0x",
                v=0,
                expiration=expiration_ns,
                nonce=nonce
            ),
            transfer_type=TransferType.STANDARD,
            transfer_metadata=""
        )
        
        grvt_config = GrvtApiConfig(
            env=GrvtEnv(funding_config.env.lower()),
            trading_account_id=funding_config.account_id,
            private_key=funding_config.private_key,
            api_key=funding_config.api_key,
            logger=logging.getLogger(f"grvt_transfer_{funding_config.name}"),
        )
        
        signed_transfer = sign_transfer(transfer, grvt_config, account)
        
        from pysdk.grvt_raw_types import ApiTransferRequest
        transfer_request = ApiTransferRequest(
            from_account_id=signed_transfer.from_account_id,
            from_sub_account_id=signed_transfer.from_sub_account_id,
            to_account_id=signed_transfer.to_account_id,
            to_sub_account_id=signed_transfer.to_sub_account_id,
            currency=signed_transfer.currency,
            num_tokens=signed_transfer.num_tokens,
            signature=signed_transfer.signature,
            transfer_type=signed_transfer.transfer_type,
            transfer_metadata=signed_transfer.transfer_metadata
        )
        
        # 使用重试机制执行转账
        success, tx_info = try_transfer_with_retry(
            client, transfer_request, retries=2, backoff_ms=1500, account_name=funding_config.name
        )
        
        if not success:
            error_code = tx_info.get("code")
            error_status = tx_info.get("status")
            error_msg = tx_info.get("message", "")
            logging.error("[%s] Transfer from funding account failed: code=%s status=%s message=%s", 
                        funding_config.name, error_code, error_status, error_msg)
            # 根据错误类型给出更明确的提示
            error_msg_lower = error_msg.lower() if error_msg else ""
            if 'insufficient' in error_msg_lower or 'balance' in error_msg_lower:
                logging.error("[%s] Insufficient balance for transfer. Please check funding account balance.",
                            funding_config.name)
            # 检查权限错误：code=1001 或 status=403 或消息中包含 permission/unauthorized
            elif (error_code == 1001 or error_status == 403 or 
                  'permission' in error_msg_lower or 'unauthorized' in error_msg_lower or 'not authorized' in error_msg_lower):
                logging.error("[%s] ⚠️  API key 没有转账权限！", funding_config.name)
                logging.error("[%s] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                            funding_config.name, funding_config.api_key[:8] + "...", funding_config.account_type, funding_config.account_id)
                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 Internal Transfer 权限，从 Funding 到 Trading）。", funding_config.name)
            return False, tx_info
        
        tx_id = tx_info.get("tx_id")
        # Success log removed - will be logged at TransferFlow level
        return True, tx_info
        
    except Exception as exc:
        error_msg = str(exc)
        logging.error("[%s] Error transferring from funding account: %s", funding_config.name, error_msg)
        # 检查是否是 API key 相关错误
        if 'api' in error_msg.lower() or 'key' in error_msg.lower() or 'permission' in error_msg.lower():
            logging.error("[%s] ⚠️  可能是 API key 问题！", funding_config.name)
            logging.error("[%s] 出问题的 API key: %s (账户类型: %s)", 
                        funding_config.name, funding_config.api_key[:8] + "...", funding_config.account_type)
        return False, {"success": False, "error": {"exception": error_msg}, "message": error_msg}


def transfer_between_trading_accounts_via_funding(
    from_trading_config: AccountConfig,
    from_funding_config: AccountConfig,
    to_funding_config: AccountConfig,
    to_trading_config: AccountConfig,
    from_main_account_id: str,
    to_main_account_id: str,
    amount: float,
    currency: str = "USDT"
) -> bool:
    """通过 funding 账户在两个交易账户之间转账。
    
    参考 grvt-transfer 仓库的转账路径：
    A-trading → A-funding → B-funding → B-trading
    
    这样做的好处：
    1. 更安全，符合 GRVT 的账户结构
    2. 支持外部转账（通过 funding 账户）
    3. 可以控制权限，避免权限过大
    
    Args:
        from_trading_config: 转出交易账户配置
        from_funding_config: 转出资金账户配置
        to_funding_config: 转入资金账户配置
        to_trading_config: 转入交易账户配置
        from_main_account_id: 转出账户的主账户ID
        to_main_account_id: 转入账户的主账户ID
        amount: 转账金额
        currency: 币种，默认USDT
    
    Returns:
        是否成功完成所有转账步骤
    """
    try:
        # 验证转账金额
        if amount <= 0:
            logging.error("[Transfer] Transfer amount must be positive, got: %.2f", amount)
            return False
        
        # 验证主账户ID
        if not from_main_account_id or not to_main_account_id:
            logging.error("[Transfer] Main account IDs are required for transfer")
            return False
        
        # 验证账户类型
        if from_trading_config.account_type != "trading":
            logging.error("[Transfer] Source trading account must be trading type")
            return False
        if from_funding_config.account_type != "funding":
            logging.error("[Transfer] Source funding account must be funding type")
            return False
        if to_funding_config.account_type != "funding":
            logging.error("[Transfer] Target funding account must be funding type")
            return False
        if to_trading_config.account_type != "trading":
            logging.error("[Transfer] Target trading account must be trading type")
            return False
        
        # 验证私钥配置
        if not from_funding_config.private_key:
            logging.error("[Transfer] Source funding account private key not configured")
            return False
        if not to_funding_config.private_key:
            logging.error("[Transfer] Target funding account private key not configured")
            return False
        
        # 记录转账开始时间和转账前余额
        start_time = datetime.now(BEIJING_TZ).isoformat()
        from_trading_client = build_client(from_trading_config)
        to_trading_client = build_client(to_trading_config)
        from_funding_client = build_client(from_funding_config)
        to_funding_client = build_client(to_funding_config)
        
        # 获取转账前余额
        from_trading_pre = get_account_summary(from_trading_client)
        to_trading_pre = get_account_summary(to_trading_client)
        from_funding_pre = get_funding_account_balance(from_funding_client, currency)
        to_funding_pre = get_funding_account_balance(to_funding_client, currency)
        
        # 步骤1: A-trading → A-funding（使用A-trading的API key）
        logging.info("[Transfer] Step 1/3: %s → %s", 
                    from_trading_config.name, from_funding_config.name)
        step1_success, step1_info = transfer_trading_to_funding(
            from_trading_config, from_main_account_id,
            from_trading_config.account_id,
            from_funding_config.account_id, amount, currency
        )
        
        if not step1_success:
            logging.error("[Transfer] Step 1/3 failed: trading → funding")
            logging.error("[Transfer] ⚠️  这需要使用 %s 的 trading 账户 API key，需要 Internal Transfer 权限（从 Trading 到 Funding）", from_trading_config.name)
            logging.error("[Transfer] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                        from_trading_config.api_key[:8] + "...", from_trading_config.account_type, from_trading_config.account_id)
            logging.error("[Transfer] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限")
            
            # 记录失败信息（仅在 DEBUG 模式下记录完整日志）
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                transfer_log = {
                    "event_time": start_time,
                    "success": False,
                    "transfer_usdt": str(amount),
                    "step": 1,
                    "step_name": "trading_to_funding",
                    "from_trading": from_trading_config.name,
                    "to_trading": to_trading_config.name,
                    "error": step1_info.get("error", {}),
                    "tx_ids": {},
                    "balances_pre": {
                        "from_trading": from_trading_pre,
                        "to_trading": to_trading_pre,
                        "from_funding": from_funding_pre,
                        "to_funding": to_funding_pre
                    }
                }
                logging.debug("[Transfer] Transfer log: %s", json.dumps(transfer_log, default=str))
            return False
        
        step1_tx_id = step1_info.get("tx_id")
        logging.info("[Transfer] Step 1/3: %s → %s (tx_id: %s)", 
                    from_trading_config.name, from_funding_config.name, step1_tx_id or "N/A")
        
        # 等待一下，确保步骤1的转账完成（参考测试脚本）
        time.sleep(3)
        
        # 步骤2: A-funding → B-funding (外部转账，使用地址)
        logging.info("[Transfer] Step 2/3: %s → %s", 
                    from_funding_config.name, to_funding_config.name)
        
        # 获取目标资金账户地址
        if not to_funding_config.funding_address:
            logging.error("[Transfer] Target funding account address not configured. Please set GRVT_FUNDING_ACCOUNT_ADDRESS")
            # 回滚：A-funding → A-trading
            logging.warning("[Transfer] Attempting rollback: funding → trading")
            rollback_success, _ = transfer_funding_to_trading(
                from_funding_config, from_main_account_id,
                from_funding_config.account_id,
                from_trading_config.account_id, amount, currency
            )
            if not rollback_success:
                logging.error("[Transfer] Rollback failed! Funds may be stuck in %s funding account", from_funding_config.name)
            
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                transfer_log = {
                    "event_time": start_time,
                    "success": False,
                    "transfer_usdt": str(amount),
                    "step": 2,
                    "step_name": "funding_to_funding",
                    "error": "Target funding address not configured",
                    "rollback_attempted": True,
                    "rollback_success": rollback_success,
                    "tx_ids": {"step1": step1_tx_id}
                }
                logging.debug("[Transfer] Transfer log: %s", json.dumps(transfer_log, default=str))
            return False
        
        step2_success, step2_info = transfer_funding_to_funding(
            from_funding_config=from_funding_config,
            from_main_account_id=from_main_account_id,
            to_funding_address=to_funding_config.funding_address,
            amount=amount,
            currency=currency,
            to_main_account_id=to_main_account_id  # 传入目标账户的主账户ID（如果知道）
        )
        
        if not step2_success:
            logging.error("[Transfer] Step 2/3 failed: funding → funding (external)")
            logging.error("[Transfer] ⚠️  这需要使用 %s 的 funding 账户 API key，需要 External Transfer 权限", from_funding_config.name)
            logging.error("[Transfer] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                        from_funding_config.api_key[:8] + "...", from_funding_config.account_type, from_funding_config.account_id)
            logging.error("[Transfer] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 External Transfer 权限）")
            logging.error("[Transfer] 注意：目标地址 %s 必须在 Address Book 中预先登记", to_funding_config.funding_address)
            # 如果失败，尝试回滚：A-funding → A-trading
            logging.warning("[Transfer] Attempting rollback: funding → trading")
            rollback_success, _ = transfer_funding_to_trading(
                from_funding_config, from_main_account_id,
                from_funding_config.account_id,
                from_trading_config.account_id, amount, currency
            )
            if not rollback_success:
                logging.error("[Transfer] Rollback failed! Funds may be stuck in %s funding account", from_funding_config.name)
            
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                transfer_log = {
                    "event_time": start_time,
                    "success": False,
                    "transfer_usdt": str(amount),
                    "step": 2,
                    "step_name": "funding_to_funding",
                    "error": step2_info.get("error", {}),
                    "rollback_attempted": True,
                    "rollback_success": rollback_success,
                    "tx_ids": {"step1": step1_tx_id}
                }
                logging.debug("[Transfer] Transfer log: %s", json.dumps(transfer_log, default=str))
            return False
        
        step2_tx_id = step2_info.get("tx_id")
        logging.info("[Transfer] Step 2/3: %s → %s (tx_id: %s)", 
                    from_funding_config.name, to_funding_config.name, step2_tx_id or "N/A")
        
        # 步骤3: B-funding → B-trading
        logging.info("[Transfer] Step 3/3: %s → %s", 
                    to_funding_config.name, to_trading_config.name)
        step3_success, step3_info = transfer_funding_to_trading(
            to_funding_config, to_main_account_id,
            to_funding_config.account_id,
            to_trading_config.account_id, amount, currency
        )
        
        if not step3_success:
            logging.error("[Transfer] Step 3/3 failed: funding → trading")
            logging.error("[Transfer] ⚠️  这需要使用 %s 的 funding 账户 API key，需要 Internal Transfer 权限", to_funding_config.name)
            logging.error("[Transfer] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                        to_funding_config.api_key[:8] + "...", to_funding_config.account_type, to_funding_config.account_id)
            logging.error("[Transfer] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 Internal Transfer 权限，从 Funding 到 Trading）")
            # 如果失败，资金已经在 B-funding，记录错误但前两步已成功
            logging.warning("[Transfer] Funds are in %s funding account, manual intervention may be needed",
                          to_funding_config.name)
            
            # 获取转账后余额
            from_trading_post = get_account_summary(from_trading_client)
            to_trading_post = get_account_summary(to_trading_client)
            from_funding_post = get_funding_account_balance(from_funding_client, currency)
            to_funding_post = get_funding_account_balance(to_funding_client, currency)
            
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                transfer_log = {
                    "event_time": start_time,
                    "success": False,
                    "transfer_usdt": str(amount),
                    "step": 3,
                    "step_name": "funding_to_trading",
                    "error": step3_info.get("error", {}),
                    "funds_location": f"{to_funding_config.name} funding account",
                    "tx_ids": {
                        "step1": step1_tx_id,
                        "step2": step2_tx_id
                    },
                    "balances_pre": {
                        "from_trading": from_trading_pre,
                        "to_trading": to_trading_pre,
                        "from_funding": from_funding_pre,
                        "to_funding": to_funding_pre
                    },
                    "balances_post": {
                        "from_trading": from_trading_post,
                        "to_trading": to_trading_post,
                        "from_funding": from_funding_post,
                        "to_funding": to_funding_post
                    }
                }
                logging.debug("[Transfer] Transfer log: %s", json.dumps(transfer_log, default=str))
            return False
        
        step3_tx_id = step3_info.get("tx_id")
        logging.info("[Transfer] Step 3/3: %s → %s (tx_id: %s)", 
                    to_funding_config.name, to_trading_config.name, step3_tx_id or "N/A")
        
        # 获取转账后余额
        from_trading_post = get_account_summary(from_trading_client)
        to_trading_post = get_account_summary(to_trading_client)
        from_funding_post = get_funding_account_balance(from_funding_client, currency)
        to_funding_post = get_funding_account_balance(to_funding_client, currency)
        
        # 记录完整的转账日志（仅在 DEBUG 模式下）
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            transfer_log = {
                "event_time": start_time,
                "success": True,
                "transfer_usdt": str(amount),
                "currency": currency,
                "from_trading": from_trading_config.name,
                "to_trading": to_trading_config.name,
                "tx_ids": {
                    "step1_trading_to_funding": step1_tx_id,
                    "step2_funding_to_funding": step2_tx_id,
                    "step3_funding_to_trading": step3_tx_id
                },
                "balances_pre": {
                    "from_trading": from_trading_pre,
                    "to_trading": to_trading_pre,
                    "from_funding": from_funding_pre,
                    "to_funding": to_funding_pre
                },
                "balances_post": {
                    "from_trading": from_trading_post,
                    "to_trading": to_trading_post,
                    "from_funding": from_funding_post,
                    "to_funding": to_funding_post
                }
            }
            logging.debug("[Transfer] Transfer log: %s", json.dumps(transfer_log, default=str))
        
        # 简洁的完成日志
        logging.info("[Transfer] ✓ Completed: %.2f %s from %s to %s (tx_ids: %s, %s, %s)",
                    amount, currency, from_trading_config.name, to_trading_config.name,
                    step1_tx_id or "N/A", step2_tx_id or "N/A", step3_tx_id or "N/A")
        return True
        
    except Exception as exc:
        logging.error("[Transfer] Error in transfer via funding: %s", exc)
        return False


def validate_ethereum_address(address: str) -> bool:
    """验证以太坊地址格式。
    
    Args:
        address: 地址字符串
    
    Returns:
        是否为有效的以太坊地址格式
    """
    if not address:
        return False
    # 以太坊地址格式：0x + 40个十六进制字符
    pattern = r'^0x[a-fA-F0-9]{40}$'
    return bool(re.match(pattern, address))


def transfer_funding_to_funding(
    from_funding_config: AccountConfig,
    from_main_account_id: str,
    to_funding_address: str,
    amount: float,
    currency: str = "USDT",
    to_main_account_id: str | None = None
) -> Tuple[bool, Dict[str, Any]]:
    """从一个资金账户转到另一个GRVT账户的资金账户（外部转账，使用转出资金账户的API key）。
    
    注意：资金账户之间的外部转账使用地址（address）而不是账户ID。
    目标地址必须在Address Book中预先登记。
    
    参考 grvt-transfer 仓库的实现（flow.py 第82行）：
    req_ff = TransferService.build_req(..., a_funding_addr, "0", b_funding_addr, "0", ...)
    外部转账（funding → funding）时：
    - from_account_id: 转出账户的主账户ID
    - from_sub_account_id: "0"（外部转账从funding账户转出时，使用"0"而不是funding_account_id）
    - to_account_id: 对于外部转账，使用目标地址（或目标账户的主账户ID，如果知道）
    - to_sub_account_id: "0"（外部转账到funding账户时，使用"0"而不是目标地址）
    
    Args:
        from_funding_config: 转出资金账户配置（使用转出资金账户的API key）
        from_main_account_id: 转出账户的主账户ID
        to_funding_address: 转入账户的资金账户地址（以太坊地址，必须在Address Book中）
        amount: 转账金额
        currency: 币种，默认USDT
        to_main_account_id: 转入账户的主账户ID（可选，如果知道可以传入以提高成功率）
    
    Returns:
        (是否成功, 详细信息字典)
    """
    try:
        # 验证转账金额
        if amount <= 0:
            logging.error("[%s] Transfer amount must be positive, got: %.2f", from_funding_config.name, amount)
            return False, {"success": False, "error": "Invalid amount", "amount": amount}
        
        # 验证主账户ID
        if not from_main_account_id:
            logging.error("[%s] Main account ID is required for transfer", from_funding_config.name)
            return False, {"success": False, "error": "Missing main account ID"}
        
        # 验证账户类型
        if from_funding_config.account_type != "funding":
            logging.error("[%s] Config must be a funding account config", from_funding_config.name)
            return False, {"success": False, "error": "Invalid account type", "account_type": from_funding_config.account_type}
        
        if not from_funding_config.private_key:
            logging.error("[%s] Private key not configured, cannot transfer", from_funding_config.name)
            return False, {"success": False, "error": "Private key not configured"}
        
        # 验证 from_funding_config.funding_address 必须存在（外部转账必须使用以太坊地址）
        if not from_funding_config.funding_address:
            logging.error("[%s] funding_address is required for external transfer", from_funding_config.name)
            return False, {"success": False, "error": "Missing funding_address", "message": "funding_address is required for external transfer"}
        
        # 验证 from_funding_address 格式
        if not validate_ethereum_address(from_funding_config.funding_address):
            logging.error("[%s] Invalid from_funding_address format: %s (must be 0x followed by 40 hex characters)",
                        from_funding_config.name, from_funding_config.funding_address)
            return False, {"success": False, "error": "Invalid from_funding_address format", "address": from_funding_config.funding_address}
        
        # 验证目标地址格式
        if not validate_ethereum_address(to_funding_address):
            logging.error("[%s] Invalid Ethereum address format: %s (must be 0x followed by 40 hex characters)",
                        from_funding_config.name, to_funding_address)
            return False, {"success": False, "error": "Invalid address format", "address": to_funding_address}
        
        # 使用转出资金账户的客户端
        client = build_client(from_funding_config)
        
        # 验证余额（可选，如果余额不足会在API调用时失败）
        if not verify_transfer_balance(client, amount, currency):
            logging.warning("[%s] Balance verification failed, but proceeding with transfer (API will reject if insufficient)",
                          from_funding_config.name)
        
        account = Account.from_key(from_funding_config.private_key)
        
        # 构建外部转账请求
        # 参考 grvt-transfer 仓库：req_ff = TransferService.build_req(..., a_funding_addr, "0", b_funding_addr, "0", ...)
        # 外部转账（funding → funding）时：
        # - from_account_id: 转出账户的 funding_address（主账户地址）
        # - from_sub_account_id: "0"
        # - to_account_id: 目标账户的主账户ID或funding_address（根据API文档，应该是main account）
        # - to_sub_account_id: "0"
        # 注意：根据API文档，to_account_id 应该是 "The main account"，如果提供了 to_main_account_id，优先使用它
        # 如果 to_main_account_id 和 to_funding_address 相同，使用 to_funding_address 也可以
        to_account_id = to_main_account_id if to_main_account_id else to_funding_address
        
        # 根据参考代码，from_account_id 必须使用 funding_address（外部转账必须使用以太坊地址）
        # 不再回退到 from_main_account_id，因为外部转账必须使用地址格式
        from_account_id = from_funding_config.funding_address
        
        expiration_ns = str(int(time.time_ns() + 15 * 60 * 1_000_000_000))
        nonce = random.randint(1, 2**31 - 1)
        
        # 确保所有参数都转换为字符串（参考实现使用 str() 转换所有参数）
        transfer = Transfer(
            from_account_id=str(from_account_id),  # 转出账户的 funding_address（根据参考代码，应该使用 funding_address）
            from_sub_account_id=str("0"),  # 外部转账从funding账户转出时，使用"0"而不是funding_account_id
            to_account_id=str(to_account_id),  # 外部转账：优先使用 to_main_account_id，否则使用 to_funding_address（根据API文档，应该是main account）
            to_sub_account_id=str("0"),  # 外部转账到funding账户时，使用"0"而不是目标地址
            currency=str(currency),
            num_tokens=str(amount),
            signature=Signature(
                signer="",
                r="0x",
                s="0x",
                v=0,
                expiration=expiration_ns,
                nonce=nonce
            ),
            transfer_type=TransferType.STANDARD,  # 外部转账也使用STANDARD类型
            transfer_metadata=""
        )
        
        grvt_config = GrvtApiConfig(
            env=GrvtEnv(from_funding_config.env.lower()),
            trading_account_id=from_funding_config.account_id,
            private_key=from_funding_config.private_key,
            api_key=from_funding_config.api_key,
            logger=logging.getLogger(f"grvt_transfer_{from_funding_config.name}"),
        )
        
        signed_transfer = sign_transfer(transfer, grvt_config, account)
        
        from pysdk.grvt_raw_types import ApiTransferRequest
        transfer_request = ApiTransferRequest(
            from_account_id=signed_transfer.from_account_id,
            from_sub_account_id=signed_transfer.from_sub_account_id,
            to_account_id=signed_transfer.to_account_id,
            to_sub_account_id=signed_transfer.to_sub_account_id,
            currency=signed_transfer.currency,
            num_tokens=signed_transfer.num_tokens,
            signature=signed_transfer.signature,
            transfer_type=signed_transfer.transfer_type,
            transfer_metadata=signed_transfer.transfer_metadata
        )
        
        # 使用重试机制执行转账
        success, tx_info = try_transfer_with_retry(
            client, transfer_request, retries=2, backoff_ms=1500, account_name=from_funding_config.name
        )
        
        if not success:
            error_code = tx_info.get("code")
            error_status = tx_info.get("status")
            error_msg = tx_info.get("message", "")
            error_dict = tx_info.get("error", {})
            
            # 输出详细的错误信息
            logging.error("[%s] External transfer from funding account failed", from_funding_config.name)
            logging.error("[%s] Error details: code=%s, status=%s, message=%s", 
                        from_funding_config.name, error_code, error_status, error_msg)
            if error_dict:
                logging.error("[%s] Full error dict: %s", from_funding_config.name, json.dumps(error_dict, default=str))
            logging.error("[%s] Full tx_info: %s", from_funding_config.name, json.dumps(tx_info, default=str))
            
            # 根据错误类型给出更明确的提示
            error_msg_lower = error_msg.lower() if error_msg else ""
            if any(keyword in error_msg_lower for keyword in ['address', 'address book', 'whitelist', 'not found', 'invalid']):
                logging.error("[%s] Target address %s may not be in Address Book. Please add it in GRVT web interface (Settings > Address Book).",
                            from_funding_config.name, to_funding_address)
            # 检查权限错误：code=1001 或 status=403 或消息中包含 permission/unauthorized
            elif (error_code == 1001 or error_status == 403 or 
                  'permission' in error_msg_lower or 'unauthorized' in error_msg_lower or 'not authorized' in error_msg_lower):
                logging.error("[%s] ⚠️  API key 没有外部转账权限！", from_funding_config.name)
                logging.error("[%s] 出问题的 API key: %s (账户类型: %s, 账户ID: %s)", 
                            from_funding_config.name, from_funding_config.api_key[:8] + "...", from_funding_config.account_type, from_funding_config.account_id)
                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）检查并更新此 API key 的权限（需要 External Transfer 权限）。", from_funding_config.name)
            elif 'insufficient' in error_msg_lower or 'balance' in error_msg_lower:
                logging.error("[%s] Insufficient balance for transfer. Please check funding account balance.",
                            from_funding_config.name)
            elif 'account' in error_msg_lower and 'id' in error_msg_lower:
                logging.warning("[%s] API may require target account's main account ID instead of address. Consider providing to_main_account_id.",
                            from_funding_config.name)
            
            return False, tx_info
        
        tx_id = tx_info.get("tx_id")
        # Success log removed - will be logged at TransferFlow level
        return True, tx_info
        
    except Exception as exc:
        # 只记录错误的第一行，避免泄露敏感信息
        error_msg = str(exc).split('\n')[0] if exc else str(exc)
        logging.error("[%s] Error transferring from funding to external funding account: %s", 
                     from_funding_config.name, error_msg)
        # 检查是否是 API key 相关错误
        if 'api' in error_msg.lower() or 'key' in error_msg.lower() or 'permission' in error_msg.lower():
            logging.error("[%s] ⚠️  可能是 API key 问题！", from_funding_config.name)
            logging.error("[%s] 出问题的 API key: %s (账户类型: %s)", 
                        from_funding_config.name, from_funding_config.api_key[:8] + "...", from_funding_config.account_type)
        return False, {"success": False, "error": {"exception": error_msg}, "message": error_msg}


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
    
    # 读取轮询间隔配置（默认30秒）
    poll_interval = int(os.getenv("GRVT_POLL_INTERVAL", "30"))
    
    # 读取余额平衡配置
    balance_threshold_percent = float(os.getenv("GRVT_BALANCE_THRESHOLD_PERCENT", "43"))
    balance_target_percent = float(os.getenv("GRVT_BALANCE_TARGET_PERCENT", "48"))
    
    # 读取日志级别（默认 INFO，可以设置为 DEBUG 来排查问题）
    log_level = os.getenv("GRVT_LOG_LEVEL", "INFO").upper()
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    log_level_value = log_level_map.get(log_level, logging.INFO)
    
    # 创建日志目录
    script_dir = Path(__file__).parent
    logs_dir = script_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # 日志格式
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level_value)
    
    # 清除已有的处理器（避免重复）
    root_logger.handlers.clear()
    
    # 文件日志处理器（带轮转，每天一个文件，保留30天）
    log_file = logs_dir / "grvt_balance_poll.log"
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level_value)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)
    
    # 控制台日志处理器（仅在有终端时添加）
    if sys.stdout.isatty():
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level_value)
        console_handler.setFormatter(logging.Formatter(log_format, date_format))
        root_logger.addHandler(console_handler)
    
    # 设置 GRVT SDK 的日志级别（默认完全静默，减少冗余日志）
    # SDK 使用 'grvt_raw_' 前缀的 logger
    # 设置为 ERROR 级别以完全静默 SDK 内部的 cookie 刷新和 HTTP 请求日志
    sdk_log_level = logging.ERROR if log_level_value != logging.DEBUG else log_level_value
    # 预先设置已知的 SDK logger 名称
    logging.getLogger('grvt_raw_').setLevel(sdk_log_level)
    logging.getLogger('pysdk').setLevel(sdk_log_level)
    # 遍历已存在的 logger 并设置级别
    for logger_name in logging.Logger.manager.loggerDict:
        if 'grvt' in logger_name.lower() or 'pysdk' in logger_name.lower():
            logging.getLogger(logger_name).setLevel(sdk_log_level)
    
    if log_level_value == logging.DEBUG:
        logging.info("Debug logging enabled. Set GRVT_LOG_LEVEL=INFO to reduce verbosity.")
        logging.info("SDK internal logs will be shown to help diagnose authentication issues.")
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
                logging.info("Initialized client for %s (%s Account ID: %s)", 
                           account_config.name, account_config.account_type.capitalize(), account_config.account_id)
                
                # 验证配置：记录关键信息（不泄露完整密钥）
                api_key_preview = account_config.api_key[:8] + "..." if len(account_config.api_key) > 8 else account_config.api_key
                private_key_preview = account_config.private_key[:8] + "..." if account_config.private_key and len(account_config.private_key) > 8 else (account_config.private_key or "None")
                logging.debug("[%s] Config check: API key starts with '%s', Private key starts with '%s', Account ID='%s'", 
                            account_config.name, api_key_preview, private_key_preview, account_config.account_id)
            except Exception as exc:
                logging.error("Failed to initialize client for %s: %s", account_config.name, exc)
                sys.exit(1)
    except Exception as exc:
        logging.error("Failed to load account configurations: %s", exc)
        sys.exit(1)

    if not clients:
        logging.error("No valid account configurations found")
        sys.exit(1)

    # 检查是否配置了两个账户用于自动平衡
    if len(clients) < 2:
        logging.warning("Auto-balance requires at least 2 accounts, but only %d configured", len(clients))
    
    logging.info("GRVT balance polling started for %d account(s) (interval %ss)", 
                len(clients), poll_interval)
    logging.info("Balance threshold: %.1f%%, target: %.1f%%", balance_threshold_percent, balance_target_percent)
    
    last_summary_date = None  # 记录上次发送每日汇总的日期
    last_transfer_time = {}  # 记录上次转账时间，防止频繁转账
    
    while not stop_flag["stop"]:
        account_balances = {}  # 存储所有交易账户的余额信息（用于自动平衡）
        account_summaries = {}  # 存储账户摘要（包含 equity, available_balance, maintenance_margin）
        account_main_ids = {}  # 存储所有账户的主账户ID
        all_accounts_normal = True  # 标记是否所有账户余额都正常
        
        # 分别查询交易账户和资金账户余额
        trading_account_balances = {}  # 只存储交易账户余额，用于自动平衡
        funding_account_balances = {}  # 存储资金账户余额，仅用于显示
        
        # 先执行 Funding Sweep（在查询余额之前）
        # 读取 Funding Sweep 阈值（默认100 USDT）
        funding_sweep_threshold = float(os.getenv("GRVT_FUNDING_SWEEP_THRESHOLD", "100"))
        
        for account_name, account_data in clients.items():
            try:
                account_config = account_data["config"]
                client = account_data["client"]
                
                logging.debug("[%s] Starting balance query for %s account", 
                            account_config.name, account_config.account_type)
                
                if account_config.account_type == "trading":
                    # 查询交易账户余额
                    logging.debug("[%s] Calling aggregated_account_summary_v1 for trading account...", account_name)
                    try:
                        response = client.aggregated_account_summary_v1(EmptyRequest())
                        logging.debug("[%s] Response received: type=%s", account_name, type(response).__name__)
                        
                        if isinstance(response, GrvtError):
                            error_msg = getattr(response, 'message', '') or ''
                            logging.error("[%s] API error fetching trading balance: code=%s status=%s message=%s", 
                                        account_name, response.code, response.status, error_msg)
                            
                            # 根据错误类型给出更明确的提示
                            error_msg_lower = error_msg.lower()
                            # code=1000 且包含 "authenticate" 时，通常是 IP 白名单问题（登录返回 text/plain）
                            if response.code == 1008 or 'whitelist' in error_msg_lower or 'ip' in error_msg_lower or (response.code == 1000 and 'authenticate' in error_msg_lower):
                                logging.error("[%s] (调试) 当前 API key: %s", account_config.name, account_config.api_key)
                                logging.error("[%s] ⚠️  IP 地址未在白名单中！", account_name)
                                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单。", account_name)
                                logging.error("[%s] 查看当前 IP：https://api.ipify.org", account_name)
                                logging.error("[%s] 或者移除 IP 白名单限制（如果允许）。", account_name)
                            elif response.code == 1000:
                                logging.error("[%s] Authentication failed. Please check:", account_name)
                                logging.error("  1. IP address is whitelisted (most common issue)")
                                logging.error("  2. API key is correct and matches the account ID")
                                logging.error("  3. API key has 'View' or 'Trade' permission")
                                logging.error("  4. Account type (trading/funding) matches the API key type")
                            
                            all_accounts_normal = False
                        else:
                            total_equity_str = response.result.total_equity
                            main_account_id = response.result.main_account_id
                            account_main_ids[account_name] = main_account_id
                            
                            log_balances(account_name, total_equity_str, 
                                       response.result.spot_balances, account_config.threshold)
                            
                            # 获取账户摘要（用于安全约束检查）
                            summary = get_account_summary(client)
                            if summary:
                                account_summaries[account_name] = summary
                                logging.debug("[%s] Account summary retrieved: equity=%.2f, available=%.2f, mm=%.2f",
                                            account_name, summary.get("equity", 0.0), 
                                            summary.get("available_balance", 0.0),
                                            summary.get("maintenance_margin", 0.0))
                            else:
                                logging.warning("[%s] Failed to get account summary, will use basic balance check for auto-balance",
                                              account_name)
                            
                            # 记录交易账户余额（用于自动平衡）
                            try:
                                total_equity_float = float(total_equity_str)
                                account_balances[account_name] = total_equity_float
                                trading_account_balances[account_name] = total_equity_float
                                
                                # 检查是否低于限定值
                                if account_config.threshold is not None and total_equity_float < account_config.threshold:
                                    all_accounts_normal = False
                            except ValueError:
                                all_accounts_normal = False
                            
                            # Funding Sweep: 检查关联的资金账户并归集资金
                            if account_config.related_funding_account_id:
                                # 查找对应的资金账户配置（使用地址匹配，不是ID）
                                funding_config = None
                                for name, data in clients.items():
                                    if (data["config"].account_type == "funding" and 
                                        data["config"].funding_address == account_config.related_funding_account_id):
                                        funding_config = data["config"]
                                        break
                                
                                if funding_config and funding_config.private_key:
                                    sweep_funding_to_trading(
                                        funding_config, account_config,
                                        main_account_id, funding_sweep_threshold
                                    )
                    except Exception as exc:
                        logging.error("[%s] Exception during trading API call: %s", account_name, exc)
                        logging.debug("[%s] Exception details: %s", account_name, exc, exc_info=True)
                        all_accounts_normal = False
                            
                elif account_config.account_type == "funding":
                    # 查询资金账户余额
                    logging.debug("[%s] Calling funding_account_summary_v1 for funding account...", account_name)
                    try:
                        response = client.funding_account_summary_v1(EmptyRequest())
                        logging.debug("[%s] Response received: type=%s", account_name, type(response).__name__)
                        
                        if isinstance(response, GrvtError):
                            error_msg = getattr(response, 'message', '') or ''
                            logging.error("[%s] API error fetching funding balance: code=%s status=%s message=%s", 
                                        account_name, response.code, response.status, error_msg)
                            
                            # 根据错误类型给出更明确的提示
                            error_msg_lower = error_msg.lower()
                            # code=1000 且包含 "authenticate" 时，通常是 IP 白名单问题（登录返回 text/plain）
                            if response.code == 1008 or 'whitelist' in error_msg_lower or 'ip' in error_msg_lower or (response.code == 1000 and 'authenticate' in error_msg_lower):
                                logging.error("[%s] (调试) 当前 API key: %s", account_config.name, account_config.api_key)
                                logging.error("[%s] ⚠️  IP 地址未在白名单中！", account_name)
                                logging.error("[%s] 请在 GRVT 网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单。", account_name)
                                logging.error("[%s] 查看当前 IP：https://api.ipify.org", account_name)
                                logging.error("[%s] 或者移除 IP 白名单限制（如果允许）。", account_name)
                            elif response.code == 1000:
                                logging.error("[%s] Authentication failed. Please check:", account_name)
                                logging.error("  1. IP address is whitelisted (most common issue)")
                                logging.error("  2. API key is correct and matches the funding account ID")
                                logging.error("  3. API key has 'View' or 'Internal Transfer' permission")
                                logging.error("  4. Account type is correctly set to 'funding'")
                            
                            all_accounts_normal = False
                        else:
                            total_equity_str = response.result.total_equity
                            main_account_id = response.result.main_account_id
                            account_main_ids[account_name] = main_account_id
                            
                            logging.info("[%s] Funding Account Total Equity: %s", account_name, total_equity_str)
                            
                            # 记录资金账户余额（仅用于显示，不用于自动平衡）
                            try:
                                total_equity_float = float(total_equity_str)
                                funding_account_balances[account_name] = total_equity_float
                            except ValueError:
                                pass
                    except Exception as exc:
                        logging.error("[%s] Exception during funding API call: %s", account_name, exc)
                        logging.debug("[%s] Exception details: %s", account_name, exc, exc_info=True)
                        all_accounts_normal = False
            except Exception as exc:
                logging.error("[%s] Error fetching balance: %s", account_name, exc)
                all_accounts_normal = False
        
        # 自动余额平衡：如果有两个交易账户，检查是否需要转账
        # 只对交易账户进行自动平衡
        trading_account_names = [name for name in account_balances.keys() 
                                 if clients[name]["config"].account_type == "trading"]
        
        logging.debug("[Auto-Balance] Found %d trading account(s): %s", len(trading_account_names), trading_account_names)
        logging.debug("[Auto-Balance] Account summaries available: %s", list(account_summaries.keys()))
        
        if len(trading_account_names) == 2:
            account1_name = trading_account_names[0]
            account2_name = trading_account_names[1]
            
            logging.debug("[Auto-Balance] Checking balance between %s and %s", account1_name, account2_name)
            
            # 优先使用改进的再平衡逻辑（考虑安全约束）
            transfer_info = None
            if account1_name in account_summaries and account2_name in account_summaries:
                logging.debug("[Auto-Balance] Using improved balance check with account summaries")
                transfer_info = check_and_balance_accounts_improved(
                    account1_name, account_summaries[account1_name],
                    account2_name, account_summaries[account2_name],
                    balance_threshold_percent, balance_target_percent
                )
            else:
                # 如果没有摘要信息，使用基础版本
                missing_summaries = []
                if account1_name not in account_summaries:
                    missing_summaries.append(account1_name)
                if account2_name not in account_summaries:
                    missing_summaries.append(account2_name)
                
                logging.warning("[Auto-Balance] Account summaries not available for: %s, falling back to basic balance check",
                              missing_summaries)
                
                account1_balance = account_balances[account1_name]
                account2_balance = account_balances[account2_name]
                
                logging.debug("[Auto-Balance] Using basic balance check: %s=%.2f, %s=%.2f",
                            account1_name, account1_balance, account2_name, account2_balance)
                
                transfer_info = check_and_balance_accounts(
                    account1_name, account1_balance,
                    account2_name, account2_balance,
                    balance_threshold_percent, balance_target_percent
                )
            
            if transfer_info:
                # 检查是否在冷却期内（防止频繁转账，至少间隔30s冷却期）
                transfer_key = f"{transfer_info['from_account']}_to_{transfer_info['to_account']}"
                current_time = time.time()
                if transfer_key in last_transfer_time:
                    time_since_last = current_time - last_transfer_time[transfer_key]
                    if time_since_last < 30:  # 30s冷却期
                        logging.info("[Auto-Balance] Transfer skipped: cooling down (%.0f seconds remaining)", 30 - time_since_last)
                        transfer_info = None
                
                if transfer_info:
                    from_account_name = transfer_info["from_account"]
                    to_account_name = transfer_info["to_account"]
                    transfer_amount = transfer_info["amount"]
                    account1_percent = transfer_info.get("account1_percent", 0)
                    account2_percent = transfer_info.get("account2_percent", 0)
                    
                    # 单条清晰的再平衡日志
                    from_percent = account1_percent if from_account_name == account1_name else account2_percent
                    to_percent = account1_percent if to_account_name == account1_name else account2_percent
                    logging.info("[Auto-Balance] Rebalancing: Transferring %.2f USDT from %s to %s (%s: %.2f%%, %s: %.2f%%)",
                                transfer_amount, from_account_name, to_account_name,
                                from_account_name, from_percent, to_account_name, to_percent)
                    
                    from_config = clients[from_account_name]["config"]
                    to_config = clients[to_account_name]["config"]
                    
                    # 获取主账户ID，如果不存在则使用配置中的关联主账户ID
                    from_main_id = account_main_ids.get(from_account_name)
                    if not from_main_id and from_config.related_main_account_id:
                        from_main_id = from_config.related_main_account_id
                        logging.warning("[Auto-Balance] Using configured main account ID for %s", from_account_name)
                    
                    to_main_id = account_main_ids.get(to_account_name)
                    if not to_main_id and to_config.related_main_account_id:
                        to_main_id = to_config.related_main_account_id
                        logging.warning("[Auto-Balance] Using configured main account ID for %s", to_account_name)
                    
                    if not from_main_id or not to_main_id:
                        logging.error("[Auto-Balance] Missing main account ID for transfer (from: %s, to: %s)",
                                    from_account_name, to_account_name)
                        continue
                    
                    # 尝试使用通过 funding 账户中转的转账路径（更安全）
                    # 查找关联的资金账户配置
                    from_funding_config = None
                    to_funding_config = None
                    
                    if from_config.related_funding_account_id:
                        # related_funding_account_id 应该是地址（funding_address），不是ID
                        for name, data in clients.items():
                            if (data["config"].account_type == "funding" and 
                                data["config"].funding_address == from_config.related_funding_account_id):
                                from_funding_config = data["config"]
                                break
                    
                    if to_config.related_funding_account_id:
                        # related_funding_account_id 应该是地址（funding_address），不是ID
                        for name, data in clients.items():
                            if (data["config"].account_type == "funding" and 
                                data["config"].funding_address == to_config.related_funding_account_id):
                                to_funding_config = data["config"]
                                break
                    
                    # 强制要求配置资金账户，因为trading账户没有直接转账到另一个trading账户的权限
                    # 正确的转账流程：A-trading → A-funding → B-funding → B-trading
                    if not from_funding_config:
                        logging.error("[Auto-Balance] ❌ 无法执行转账：源账户 %s 的资金账户未配置", from_account_name)
                        logging.error("[Auto-Balance] 请在 .env 文件中配置 GRVT_RELATED_FUNDING_ACCOUNT_ID_*（注意：这个值应该是资金账户的地址，即 GRVT_FUNDING_ACCOUNT_ADDRESS_* 的值，不是ID）")
                        logging.error("[Auto-Balance] 例如：如果资金账户地址是 0x1234...，则 GRVT_RELATED_FUNDING_ACCOUNT_ID_1=0x1234...")
                        logging.error("[Auto-Balance] Trading账户的API key只有内部划转到funding账户的权限，必须通过资金账户中转")
                        continue
                    
                    if not to_funding_config:
                        logging.error("[Auto-Balance] ❌ 无法执行转账：目标账户 %s 的资金账户未配置", to_account_name)
                        logging.error("[Auto-Balance] 请在 .env 文件中配置 GRVT_RELATED_FUNDING_ACCOUNT_ID_*（注意：这个值应该是资金账户的地址，即 GRVT_FUNDING_ACCOUNT_ADDRESS_* 的值，不是ID）")
                        logging.error("[Auto-Balance] 例如：如果资金账户地址是 0x1234...，则 GRVT_RELATED_FUNDING_ACCOUNT_ID_1=0x1234...")
                        logging.error("[Auto-Balance] Trading账户的API key只有内部划转到funding账户的权限，必须通过资金账户中转")
                        continue
                    
                    if not from_funding_config.private_key:
                        logging.error("[Auto-Balance] ❌ 无法执行转账：源账户 %s 的资金账户私钥未配置", from_account_name)
                        logging.error("[Auto-Balance] 请在 .env 文件中配置对应的 GRVT_FUNDING_PRIVATE_KEY")
                        continue
                    
                    if not to_funding_config.private_key:
                        logging.error("[Auto-Balance] ❌ 无法执行转账：目标账户 %s 的资金账户私钥未配置", to_account_name)
                        logging.error("[Auto-Balance] 请在 .env 文件中配置对应的 GRVT_FUNDING_PRIVATE_KEY")
                        continue
                    
                    if not to_funding_config.funding_address:
                        logging.error("[Auto-Balance] ❌ 无法执行转账：目标账户 %s 的资金账户地址未配置", to_account_name)
                        logging.error("[Auto-Balance] 请在 .env 文件中配置对应的 GRVT_FUNDING_ACCOUNT_ADDRESS（以太坊地址）")
                        logging.error("[Auto-Balance] 该地址必须在GRVT的Address Book中预先登记")
                        continue
                    
                    # 使用通过 funding 账户中转的转账路径（必需）
                    # Using transfer via funding accounts (required path)
                    success = transfer_between_trading_accounts_via_funding(
                        from_config, from_funding_config,
                        to_funding_config, to_config,
                        from_main_id, to_main_id,
                        transfer_amount, "USDT"
                    )
                    
                    if success:
                        last_transfer_time[transfer_key] = current_time
                        logging.info("[Auto-Balance] Transfer completed successfully")
                    else:
                        logging.error("[Auto-Balance] Transfer failed")
        
        # 检查是否需要发送每日汇总（余额正常时）
        if all_accounts_normal and account_balances:
            beijing_now = datetime.now(BEIJING_TZ)
            current_date = beijing_now.date()
            
            # 如果到了发送时间且今天还没发送过
            if should_send_daily_summary() and last_summary_date != current_date:
                send_daily_summary(account_balances)
                last_summary_date = current_date
        
        time.sleep(poll_interval)

    logging.info("GRVT balance polling stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

