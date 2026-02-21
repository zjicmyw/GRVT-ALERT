# 快速开始指南

## 运行环境已配置完成 ✅

项目已创建虚拟环境并安装所有依赖。

## 使用方法

### 1. 激活虚拟环境

```bash
source venv/bin/activate
```

### 2. 运行脚本

#### 余额轮询脚本
```bash
python3 grvt_balance_poll.py
```

#### 双做市对冲引擎
```bash
python3 grvt_dual_maker_hedge.py
```

### 3. 退出虚拟环境

```bash
deactivate
```

## 配置文件

### .env 文件
需要配置 API 密钥和账户信息。如果不存在，请创建：

```bash
cp .env.example .env  # 如果有示例文件
# 然后编辑 .env 文件
```

### config/hedge_symbols.json
如果使用对冲引擎，需要配置交易对：

```bash
cp config/hedge_symbols.example.json config/hedge_symbols.json  # 如果有示例文件
# 然后编辑配置文件
```

## 重新设置环境

如果需要重新设置环境，运行：

```bash
./setup_env.sh
```

或者手动操作：

```bash
# 删除旧虚拟环境
rm -rf venv

# 创建新虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 依赖列表

- grvt-pysdk: GRVT Python SDK
- python-dotenv: 环境变量管理
- requests: HTTP 请求库
- eth-account: 以太坊账户管理

所有依赖已安装在虚拟环境中。
