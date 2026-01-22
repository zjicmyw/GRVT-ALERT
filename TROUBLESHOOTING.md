# 故障排查指南

## 常见问题

### 问题：`sudo: unable to execute ./deploy.sh: No such file or directory`

**原因**：这通常是因为文件使用了 Windows 行尾符（CRLF）而不是 Unix 行尾符（LF）。

**解决方法**：

```bash
# 方法 1: 使用 dos2unix 修复（推荐）
sudo apt install -y dos2unix
dos2unix deploy.sh install_service.sh uninstall_service.sh
chmod +x deploy.sh
sudo ./deploy.sh

# 方法 2: 使用 sed 修复
sed -i 's/\r$//' deploy.sh
chmod +x deploy.sh
sudo ./deploy.sh

# 方法 3: 使用 bash 直接运行（不依赖 shebang）
sudo bash deploy.sh
```

**诊断步骤**：

```bash
# 1. 检查文件是否存在
ls -la deploy.sh

# 2. 检查文件类型和行尾符
file deploy.sh
cat -A deploy.sh | head -n 1  # 如果看到 ^M$，说明是 Windows 行尾符

# 3. 检查文件内容
head -n 1 deploy.sh  # 应该显示 #!/bin/bash

# 4. 尝试直接运行
bash deploy.sh  # 如果这样可以运行，说明是行尾符问题
```

### 问题：`bash: deploy.sh: /bin/bash^M: bad interpreter`

**原因**：文件使用了 Windows 行尾符（CRLF），shebang 行包含 `^M` 字符。

**解决方法**：

```bash
# 安装并运行 dos2unix
sudo apt install -y dos2unix
dos2unix deploy.sh
chmod +x deploy.sh
sudo ./deploy.sh
```

### 问题：文件上传后找不到

**检查步骤**：

```bash
# 1. 确认当前目录
pwd

# 2. 列出所有文件
ls -la

# 3. 查找 deploy.sh
find . -name "deploy.sh"

# 4. 检查文件权限
ls -l deploy.sh
```

### 问题：权限不足

**解决方法**：

```bash
# 确保文件有执行权限
chmod +x deploy.sh install_service.sh uninstall_service.sh

# 使用 sudo 运行
sudo ./deploy.sh
```

### 问题：Python 模块导入失败

**解决方法**：

```bash
# 检查 Python 版本
python3 --version

# 检查模块是否安装
python3 -c "import grvt_pysdk"
python3 -c "import dotenv"

# 如果未安装，手动安装
sudo pip3 install grvt-pysdk python-dotenv
```

### 问题：服务无法启动

**诊断步骤**：

```bash
# 1. 查看服务状态
sudo systemctl status grvt-balance-poll

# 2. 查看详细日志
sudo journalctl -u grvt-balance-poll -n 50 --no-pager

# 3. 检查 .env 文件
sudo cat /opt/grvt-balance-poll/.env | head -n 5

# 4. 手动测试运行
cd /opt/grvt-balance-poll
sudo -u grvt python3 grvt_balance_poll.py
```

## 快速修复脚本

如果遇到行尾符问题，可以运行以下命令快速修复：

```bash
# 安装 dos2unix
sudo apt install -y dos2unix

# 修复所有脚本文件
for file in deploy.sh install_service.sh uninstall_service.sh; do
    if [ -f "$file" ]; then
        echo "修复 $file..."
        dos2unix "$file"
        chmod +x "$file"
    fi
done

# 现在可以运行
sudo ./deploy.sh
```
