"""简单的内部划转测试脚本 - 从 Trading 账户转到 Funding 账户"""
import os
import sys
import logging
from dotenv import load_dotenv

# 修复 Windows PowerShell 编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 导入必要的函数和类
from grvt_balance_poll import (
    AccountConfig,
    build_client,
    transfer_trading_to_funding,
    get_account_summary,
    get_funding_account_balance
)
from pysdk.grvt_raw_types import EmptyRequest
from pysdk.grvt_raw_base import GrvtError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 加载环境变量
load_dotenv()

def main():
    """主函数：执行110 USDT的内部划转（Trading → Funding）"""
    print("=" * 60)
    print("GRVT 内部划转测试脚本")
    print("=" * 60)
    
    # 加载配置
    trading_api_key = os.getenv("GRVT_TRADING_API_KEY_2")
    trading_private_key = os.getenv("GRVT_TRADING_PRIVATE_KEY_2")
    trading_account_id = os.getenv("GRVT_TRADING_ACCOUNT_ID_2")
    related_funding_address = os.getenv("GRVT_RELATED_FUNDING_ACCOUNT_ID_2")  # 注意：这是地址
    main_account_id = os.getenv("GRVT_RELATED_MAIN_ACCOUNT_ID_2")
    
    funding_api_key = os.getenv("GRVT_FUNDING_API_KEY_2")
    funding_private_key = os.getenv("GRVT_FUNDING_PRIVATE_KEY_2")
    funding_account_address = os.getenv("GRVT_FUNDING_ACCOUNT_ADDRESS_2")
    funding_account_id = os.getenv("GRVT_FUNDING_ACCOUNT_ID_2")  # 内部ID（可选）
    
    env = os.getenv("GRVT_ENV", "prod")
    
    # 验证必需配置
    if not trading_api_key:
        print("❌ 错误: 未配置 GRVT_TRADING_API_KEY_2")
        return
    if not trading_private_key:
        print("❌ 错误: 未配置 GRVT_TRADING_PRIVATE_KEY_2")
        return
    if not trading_account_id:
        print("❌ 错误: 未配置 GRVT_TRADING_ACCOUNT_ID_2")
        return
    if not main_account_id:
        print("❌ 错误: 未配置 GRVT_RELATED_MAIN_ACCOUNT_ID_2")
        return
    if not funding_api_key:
        print("❌ 错误: 未配置 GRVT_FUNDING_API_KEY_2")
        return
    if not funding_private_key:
        print("❌ 错误: 未配置 GRVT_FUNDING_PRIVATE_KEY_2")
        return
    if not related_funding_address:
        print("❌ 错误: 未配置 GRVT_RELATED_FUNDING_ACCOUNT_ID_2（这是funding账户的地址）")
        return
    
    print("\n✅ 配置验证通过")
    print(f"   Trading账户ID: {trading_account_id}")
    print(f"   Main账户ID: {main_account_id}")
    print(f"   Funding账户地址: {related_funding_address}")
    
    # 创建trading账户配置
    trading_config = AccountConfig(
        name="Trading_Test",
        account_type="trading",
        api_key=trading_api_key,
        account_id=trading_account_id,
        private_key=trading_private_key,
        env=env,
        related_funding_account_id=related_funding_address,  # 存储地址
        related_main_account_id=main_account_id
    )
    
    # 创建funding账户配置（用于查询account_id）
    # 如果未配置funding_account_id，需要提示用户配置
    if not funding_account_id:
        print("\n❌ 错误: 未配置 GRVT_FUNDING_ACCOUNT_ID_2")
        print("\n💡 说明:")
        print("   funding账户有两个标识符：")
        print("   1. 内部ID (account_id): 用于API调用，需要在.env中配置为 GRVT_FUNDING_ACCOUNT_ID_2")
        print("   2. 地址 (funding_address): 以太坊地址，用于外部转账，已配置为 GRVT_FUNDING_ACCOUNT_ADDRESS_2")
        print("\n📝 如何获取funding账户的内部ID：")
        print("   1. 登录GRVT网页端")
        print("   2. 进入账户设置或API设置页面")
        print("   3. 查看funding账户的内部ID（通常是一个数字字符串，不是以太坊地址）")
        print("   4. 在.env文件中添加: GRVT_FUNDING_ACCOUNT_ID_2=你的内部ID")
        print("\n   注意：内部ID和地址是不同的！")
        print(f"   地址: {funding_account_address}")
        print("   内部ID: 需要在网页端查看")
        return
    
    # 创建funding账户配置
    funding_config = AccountConfig(
        name="Funding_Test",
        account_type="funding",
        api_key=funding_api_key,
        account_id=funding_account_id,
        private_key=funding_private_key,
        env=env,
        funding_address=funding_account_address
    )
    
    print(f"   Funding账户ID: {funding_account_id}")
    
    # 转账金额
    transfer_amount = 110.0
    currency = "USDT"
    
    print(f"\n📊 转账信息:")
    print(f"   金额: {transfer_amount} {currency}")
    print(f"   方向: Trading → Funding")
    print(f"   使用: Trading账户的API key（需要Internal Transfer权限）")
    
    # 查询转账前余额
    print("\n📈 查询转账前余额...")
    try:
        trading_client = build_client(trading_config)
        trading_summary = get_account_summary(trading_client)
        if trading_summary:
            print(f"   Trading账户余额: {trading_summary.get('equity', 0):.2f} USDT")
            print(f"   可用余额: {trading_summary.get('available_balance', 0):.2f} USDT")
        
        funding_client = build_client(funding_config)
        funding_balance = get_funding_account_balance(funding_client, currency)
        if funding_balance is not None:
            print(f"   Funding账户余额: {funding_balance:.2f} USDT")
    except Exception as e:
        print(f"   ⚠️  查询余额时出错: {e}")
        print("   继续执行转账...")
    
    # 执行转账
    print(f"\n🔄 开始执行转账...")
    print("-" * 60)
    
    success, tx_info = transfer_trading_to_funding(
        trading_config=trading_config,
        main_account_id=main_account_id,
        trading_account_id=trading_account_id,
        funding_account_id=funding_account_id,
        amount=transfer_amount,
        currency=currency
    )
    
    print("-" * 60)
    
    if success:
        tx_id = tx_info.get("tx_id")
        print(f"\n✅ 转账成功！")
        print(f"   交易ID: {tx_id or 'N/A'}")
        
        # 查询转账后余额
        print("\n📈 查询转账后余额...")
        try:
            trading_summary_post = get_account_summary(trading_client)
            if trading_summary_post:
                print(f"   Trading账户余额: {trading_summary_post.get('equity', 0):.2f} USDT")
                print(f"   可用余额: {trading_summary_post.get('available_balance', 0):.2f} USDT")
            
            funding_balance_post = get_funding_account_balance(funding_client, currency)
            if funding_balance_post is not None:
                print(f"   Funding账户余额: {funding_balance_post:.2f} USDT")
        except Exception as e:
            print(f"   ⚠️  查询余额时出错: {e}")
    else:
        print(f"\n❌ 转账失败！")
        error_code = tx_info.get("code")
        error_status = tx_info.get("status")
        error_msg = tx_info.get("message", "")
        print(f"   错误代码: {error_code}")
        print(f"   状态码: {error_status}")
        print(f"   错误消息: {error_msg}")
        
        if error_code == 1001 or error_status == 403:
            print("\n💡 提示:")
            print("   这可能是API key权限问题。")
            print("   请确保Trading账户的API key具有'Internal Transfer'权限（从Trading到Funding）。")
            print("   在GRVT网页端: Settings > API Keys 中检查并更新权限。")
    
    print("\n" + "=" * 60)


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
