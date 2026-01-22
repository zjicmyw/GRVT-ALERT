"""
GRVT 资金账户全部余额转账测试脚本

功能：将指定 Funding 账户的全部余额转到对应的 Trading 账户
"""

import os
import sys
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 添加项目根目录到路径，以便导入 grvt_balance_poll 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from grvt_balance_poll import (
    AccountConfig, build_client, get_funding_account_balance,
    get_account_summary, transfer_all_funding_to_trading
)

def main():
    print("=" * 60)
    print("GRVT 资金账户全部余额转账测试脚本")
    print("=" * 60)
    print()
    
    # 默认使用账户1，可以通过命令行参数指定账户索引
    account_index = 1
    if len(sys.argv) > 1:
        try:
            account_index = int(sys.argv[1])
        except ValueError:
            print(f"❌ 错误: 无效的账户索引 '{sys.argv[1]}'，使用默认值 1")
            account_index = 1
    
    print(f"📋 使用账户配置: 账户 {account_index}")
    print()
    
    # 加载配置
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
    if not trading_api_key:
        print(f"❌ 错误: 未配置 GRVT_TRADING_API_KEY_{account_index}")
        return
    if not trading_private_key:
        print(f"❌ 错误: 未配置 GRVT_TRADING_PRIVATE_KEY_{account_index}")
        return
    if not trading_account_id:
        print(f"❌ 错误: 未配置 GRVT_TRADING_ACCOUNT_ID_{account_index}")
        return
    if not main_account_id:
        print(f"❌ 错误: 未配置 GRVT_RELATED_MAIN_ACCOUNT_ID_{account_index}")
        return
    if not funding_api_key:
        print(f"❌ 错误: 未配置 GRVT_FUNDING_API_KEY_{account_index}")
        return
    if not funding_private_key:
        print(f"❌ 错误: 未配置 GRVT_FUNDING_PRIVATE_KEY_{account_index}")
        return
    if not related_funding_address:
        print(f"❌ 错误: 未配置 GRVT_RELATED_FUNDING_ACCOUNT_ID_{account_index}（这是funding账户的地址）")
        return
    if not funding_account_id:
        print(f"❌ 错误: 未配置 GRVT_FUNDING_ACCOUNT_ID_{account_index}")
        print("\n💡 说明:")
        print("   funding账户有两个标识符：")
        print(f"   1. 内部ID (account_id): 用于API调用，需要在.env中配置为 GRVT_FUNDING_ACCOUNT_ID_{account_index}")
        print(f"   2. 地址 (funding_address): 以太坊地址，用于外部转账，已配置为 GRVT_FUNDING_ACCOUNT_ADDRESS_{account_index}")
        print("\n📝 如何获取funding账户的内部ID：")
        print("   1. 登录GRVT网页端")
        print("   2. 进入账户设置或API设置页面")
        print("   3. 查看funding账户的内部ID（通常是一个数字字符串，不是以太坊地址）")
        print(f"   4. 在.env文件中添加: GRVT_FUNDING_ACCOUNT_ID_{account_index}=你的内部ID")
        return
    
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
    
    print("✅ 配置验证通过")
    print(f"   Trading账户ID: {trading_account_id}")
    print(f"   Main账户ID: {main_account_id}")
    print(f"   Funding账户地址: {funding_account_address}")
    print(f"   Funding账户ID: {funding_account_id}")
    print()
    
    # 查询转账前余额
    print(f"📈 查询转账前余额...")
    print("-" * 60)
    
    funding_client = build_client(funding_config)
    trading_client = build_client(trading_config)
    
    funding_balance = get_funding_account_balance(funding_client, currency)
    if funding_balance is None:
        print(f"❌ 无法查询 Funding 账户余额")
        return
    
    # 查询 Trading 账户余额
    trading_summary = get_account_summary(trading_client)
    trading_balance = trading_summary.get(currency, 0.0) if trading_summary else 0.0
    
    print(f"   Funding账户余额: {funding_balance:.2f} {currency}")
    print(f"   Trading账户余额: {trading_balance:.2f} {currency}")
    print()
    
    if funding_balance <= 0:
        print("ℹ️  Funding账户余额为0或负数，无需转账")
        return
    
    # 确认转账
    print(f"📊 转账信息:")
    print(f"   金额: {funding_balance:.2f} {currency}")
    print(f"   方向: Funding → Trading")
    print(f"   使用: Funding账户的API key（需要Internal Transfer权限）")
    print()
    
    # 执行转账
    print(f"🔄 开始执行转账...")
    print("-" * 60)
    
    success, result = transfer_all_funding_to_trading(
        funding_config=funding_config,
        trading_config=trading_config,
        main_account_id=main_account_id,
        currency=currency
    )
    
    print("-" * 60)
    
    if success:
        tx_id = result.get("tx_id")
        amount_transferred = result.get("amount_transferred", 0.0)
        print(f"\n✅ 转账成功！")
        print(f"   转账金额: {amount_transferred:.2f} {currency}")
        if tx_id:
            print(f"   交易ID: {tx_id}")
        
        # 查询转账后余额
        print(f"\n📈 查询转账后余额...")
        funding_balance_after = get_funding_account_balance(funding_client, currency)
        trading_summary_after = get_account_summary(trading_client)
        trading_balance_after = trading_summary_after.get(currency, 0.0) if trading_summary_after else 0.0
        
        print(f"   Funding账户余额: {funding_balance_after or 0.0:.2f} {currency}")
        print(f"   Trading账户余额: {trading_balance_after:.2f} {currency}")
    else:
        error = result.get("error", {})
        error_code = error.get("code") if isinstance(error, dict) else None
        error_status = error.get("status") if isinstance(error, dict) else None
        error_msg = error.get("message") if isinstance(error, dict) else str(error)
        
        print(f"\n❌ 转账失败！")
        if error_code:
            print(f"   错误代码: {error_code}")
        if error_status:
            print(f"   状态码: {error_status}")
        if error_msg:
            print(f"   错误消息: {error_msg}")
    
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
