"""
GRVT 跨账户转账测试脚本

功能：
1. 将账户2的110 USDT从Trading账户转到Funding账户（内部转账）
2. 将账户2的Funding账户的110 USDT转到账户1的Funding账户（外部转账）
"""

import os
import sys
import logging
import json
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 先导入主模块（它会处理编码问题）
from grvt_balance_poll import (
    AccountConfig,
    build_client,
    transfer_trading_to_funding,
    transfer_funding_to_funding,
    get_account_summary,
    get_funding_account_balance,
    get_trading_account_balance
)

# 配置日志（在导入主模块之后，避免冲突）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def load_account_config(account_index: int):
    """加载指定账户的配置"""
    trading_api_key = os.getenv(f"GRVT_TRADING_API_KEY_{account_index}")
    trading_private_key = os.getenv(f"GRVT_TRADING_PRIVATE_KEY_{account_index}")
    trading_account_id = os.getenv(f"GRVT_TRADING_ACCOUNT_ID_{account_index}")
    related_funding_address = os.getenv(f"GRVT_RELATED_FUNDING_ACCOUNT_ID_{account_index}")
    main_account_id = os.getenv(f"GRVT_RELATED_MAIN_ACCOUNT_ID_{account_index}")
    
    funding_api_key = os.getenv(f"GRVT_FUNDING_API_KEY_{account_index}")
    funding_private_key = os.getenv(f"GRVT_FUNDING_PRIVATE_KEY_{account_index}")
    funding_account_address = os.getenv(f"GRVT_FUNDING_ACCOUNT_ADDRESS_{account_index}")
    funding_account_id = os.getenv(f"GRVT_FUNDING_ACCOUNT_ID_{account_index}")
    
    env = os.getenv("GRVT_ENV", "prod")
    currency = os.getenv("GRVT_CURRENCY", "USDT")
    
    # 验证必需配置
    missing_configs = []
    if not trading_api_key:
        missing_configs.append(f"GRVT_TRADING_API_KEY_{account_index}")
    if not trading_private_key:
        missing_configs.append(f"GRVT_TRADING_PRIVATE_KEY_{account_index}")
    if not trading_account_id:
        missing_configs.append(f"GRVT_TRADING_ACCOUNT_ID_{account_index}")
    if not main_account_id:
        missing_configs.append(f"GRVT_RELATED_MAIN_ACCOUNT_ID_{account_index}")
    if not funding_api_key:
        missing_configs.append(f"GRVT_FUNDING_API_KEY_{account_index}")
    if not funding_private_key:
        missing_configs.append(f"GRVT_FUNDING_PRIVATE_KEY_{account_index}")
    if not related_funding_address:
        missing_configs.append(f"GRVT_RELATED_FUNDING_ACCOUNT_ID_{account_index}")
    if not funding_account_id:
        missing_configs.append(f"GRVT_FUNDING_ACCOUNT_ID_{account_index}")
    if not funding_account_address:
        missing_configs.append(f"GRVT_FUNDING_ACCOUNT_ADDRESS_{account_index}")
    
    if missing_configs:
        raise ValueError(f"账户{account_index}缺少以下配置: {', '.join(missing_configs)}")
    
    # 创建账户配置
    trading_config = AccountConfig(
        name=f"Trading_{account_index}",
        account_type="trading",
        api_key=trading_api_key,
        account_id=trading_account_id,
        private_key=trading_private_key,
        env=env,
        related_funding_account_id=related_funding_address,
        related_main_account_id=main_account_id
    )
    
    funding_config = AccountConfig(
        name=f"Funding_{account_index}",
        account_type="funding",
        api_key=funding_api_key,
        account_id=funding_account_id,
        private_key=funding_private_key,
        env=env,
        funding_address=funding_account_address,
        related_trading_account_id=trading_account_id,
        related_main_account_id=main_account_id
    )
    
    return trading_config, funding_config, main_account_id, currency

def print_balances(account_name, trading_client, funding_client, currency):
    """打印账户余额"""
    try:
        # 获取账户摘要（用于显示总权益和可用余额）
        trading_summary = get_account_summary(trading_client) if trading_client else None
        trading_equity = trading_summary.get("equity", 0.0) if trading_summary else 0.0
        trading_available = trading_summary.get("available_balance", 0.0) if trading_summary else 0.0
        
        # 获取 Trading 账户的 USDT 余额（从 spot_balances 中获取，用于显示单个币种余额）
        trading_usdt_balance = get_trading_account_balance(trading_client, currency) if trading_client else None
        trading_usdt_balance = trading_usdt_balance if trading_usdt_balance is not None else 0.0
        
        # 确保可用余额不超过总权益
        if trading_available > trading_equity:
            trading_available = trading_equity
        
        # 使用总权益作为 Trading 账户余额（更准确）
        trading_balance = trading_equity
        
        # 获取 Funding 账户余额
        funding_balance = get_funding_account_balance(funding_client, currency) if funding_client else None
        funding_balance = funding_balance if funding_balance is not None else 0.0
        
        print(f"   {account_name} Trading账户总权益: {trading_balance:.2f} {currency}")
        print(f"   {account_name} Trading可用余额: {trading_available:.2f} {currency}")
        if trading_usdt_balance > 0:
            print(f"   {account_name} Trading USDT余额: {trading_usdt_balance:.2f} {currency}")
        print(f"   {account_name} Funding账户余额: {funding_balance:.2f} {currency}")
    except Exception as e:
        print(f"   ⚠️  查询{account_name}余额时出错: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 70)
    print("GRVT 跨账户转账测试脚本")
    print("=" * 70)
    print()
    print("流程:")
    print("  步骤1: 账户2 Trading → 账户2 Funding (110 USDT)")
    print("  步骤2: 账户2 Funding → 账户1 Funding (110 USDT)")
    print()
    
    # 转账金额
    transfer_amount = 110.0
    currency = "USDT"
    
    try:
        # 加载账户配置
        print("📋 加载账户配置...")
        trading_config_2, funding_config_2, main_account_id_2, currency = load_account_config(2)
        trading_config_1, funding_config_1, main_account_id_1, _ = load_account_config(1)
        
        print("✅ 配置验证通过")
        print(f"   账户2 Trading账户ID: {trading_config_2.account_id}")
        print(f"   账户2 Main账户ID: {main_account_id_2}")
        print(f"   账户2 Funding地址: {funding_config_2.funding_address}")
        print(f"   账户1 Funding地址: {funding_config_1.funding_address}")
        print()
        
        # 创建客户端
        trading_client_2 = build_client(trading_config_2)
        funding_client_2 = build_client(funding_config_2)
        funding_client_1 = build_client(funding_config_1)
        
        # 尝试创建账户1的Trading客户端（如果配置了）
        trading_client_1 = None
        try:
            trading_config_1, _, _, _ = load_account_config(1)
            trading_client_1 = build_client(trading_config_1)
        except (ValueError, Exception) as e:
            # 账户1可能没有配置Trading账户，这是正常的
            logging.debug("账户1未配置Trading账户或创建客户端失败: %s", e)
        
        # 查询转账前余额
        print("📈 查询转账前余额...")
        print("-" * 70)
        print("账户2:")
        print_balances("账户2", trading_client_2, funding_client_2, currency)
        print()
        print("账户1:")
        print_balances("账户1", trading_client_1, funding_client_1, currency)
        print()
        
        # ========== 步骤1: 账户2 Trading → 账户2 Funding ==========
        print("=" * 70)
        print("步骤1: 账户2 Trading → 账户2 Funding")
        print("=" * 70)
        print(f"📊 转账信息:")
        print(f"   金额: {transfer_amount} {currency}")
        print(f"   方向: Trading_2 → Funding_2")
        print(f"   使用: Trading账户的API key（需要Internal Transfer权限）")
        print()
        
        print("🔄 开始执行转账...")
        print("-" * 70)
        
        success_1, tx_info_1 = transfer_trading_to_funding(
            trading_config=trading_config_2,
            main_account_id=main_account_id_2,
            trading_account_id=trading_config_2.account_id,
            funding_account_id=funding_config_2.account_id,
            amount=transfer_amount,
            currency=currency
        )
        
        print("-" * 70)
        
        if not success_1:
            error_code = tx_info_1.get("code")
            error_status = tx_info_1.get("status")
            error_msg = tx_info_1.get("message", "")
            print(f"\n❌ 步骤1失败！")
            print(f"   错误代码: {error_code}")
            print(f"   状态码: {error_status}")
            print(f"   错误消息: {error_msg}")
            if error_code == 1001 or error_status == 403:
                print("\n💡 提示:")
                print("   这可能是API key权限问题。")
                print("   请确保账户2的Trading账户API key具有'Internal Transfer'权限。")
            return
        
        tx_id_1 = tx_info_1.get("tx_id")
        print(f"\n✅ 步骤1成功！")
        print(f"   交易ID: {tx_id_1 or 'N/A'}")
        
        # 查询步骤1后的余额
        print(f"\n📈 步骤1后余额...")
        print("-" * 70)
        print("账户2:")
        print_balances("账户2", trading_client_2, funding_client_2, currency)
        print()
        
        # 等待一下，确保转账完成
        import time
        print("\n⏳ 等待3秒，确保转账完成...")
        time.sleep(3)
        
        # ========== 步骤2: 账户2 Funding → 账户1 Funding ==========
        print()
        print("=" * 70)
        print("步骤2: 账户2 Funding → 账户1 Funding")
        print("=" * 70)
        print(f"📊 转账信息:")
        print(f"   金额: {transfer_amount} {currency}")
        print(f"   方向: Funding_2 → Funding_1")
        print(f"   使用: 账户2 Funding账户的API key（需要External Transfer权限）")
        print(f"   目标地址: {funding_config_1.funding_address}")
        print()
        print("⚠️  注意: 目标地址必须在GRVT的Address Book中预先登记！")
        print()
        
        print("🔄 开始执行转账...")
        print("-" * 70)
        
        success_2, tx_info_2 = transfer_funding_to_funding(
            from_funding_config=funding_config_2,
            from_main_account_id=main_account_id_2,
            to_funding_address=funding_config_1.funding_address,
            amount=transfer_amount,
            currency=currency,
            to_main_account_id=main_account_id_1  # 传入目标账户的主账户ID
        )
        
        print("-" * 70)
        
        if not success_2:
            error = tx_info_2.get("error", {})
            error_code = error.get("code") if isinstance(error, dict) else tx_info_2.get("code")
            error_status = error.get("status") if isinstance(error, dict) else tx_info_2.get("status")
            error_msg = error.get("message") if isinstance(error, dict) else tx_info_2.get("message", str(error))
            
            print(f"\n❌ 步骤2失败！")
            print(f"   完整错误信息:")
            print(f"   {json.dumps(tx_info_2, indent=2, default=str)}")
            if error_code:
                print(f"   错误代码: {error_code}")
            if error_status:
                print(f"   状态码: {error_status}")
            if error_msg:
                print(f"   错误消息: {error_msg}")
            
            # 检查是否是Address Book问题
            error_msg_lower = error_msg.lower() if error_msg else ""
            if any(keyword in error_msg_lower for keyword in ['address', 'address book', 'whitelist', 'not found']):
                print("\n💡 提示:")
                print("   目标地址可能未在Address Book中登记。")
                print("   请在GRVT网页端: Settings > Address Book 中添加目标地址。")
            elif error_code == 1001 or error_status == 403:
                print("\n💡 提示:")
                print("   这可能是API key权限问题。")
                print("   请确保账户2的Funding账户API key具有'External Transfer'权限。")
            return
        
        tx_id_2 = tx_info_2.get("tx_id")
        print(f"\n✅ 步骤2成功！")
        print(f"   交易ID: {tx_id_2 or 'N/A'}")
        
        # 查询最终余额
        print(f"\n📈 最终余额...")
        print("-" * 70)
        print("账户2:")
        print_balances("账户2", trading_client_2, funding_client_2, currency)
        print()
        print("账户1:")
        print_balances("账户1", trading_client_1, funding_client_1, currency)
        print()
        
        print("=" * 70)
        print("✅ 所有步骤完成！")
        print("=" * 70)
        print(f"步骤1交易ID: {tx_id_1 or 'N/A'}")
        print(f"步骤2交易ID: {tx_id_2 or 'N/A'}")
        
    except ValueError as e:
        print(f"\n❌ 配置错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
