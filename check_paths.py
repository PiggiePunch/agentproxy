#!/usr/bin/env python3
"""
诊断脚本 - 检查 proxy_server.py 的路径问题
"""

import os
import sys
from pathlib import Path

print("="*80)
print("路径诊断工具")
print("="*80)

# 1. 当前工作目录
print(f"\n1. 当前工作目录 (CWD):")
print(f"   {os.getcwd()}")
print(f"   是否可写: {os.access(os.getcwd(), os.W_OK)}")

# 2. 脚本所在目录
script_path = Path(__file__).resolve()
print(f"\n2. 脚本所在目录:")
print(f"   {script_path.parent}")

# 3. 检查相对路径 "logs" 会在哪里创建
logs_relative = Path("logs").resolve()
print(f"\n3. 相对路径 'logs' 会创建在:")
print(f"   {logs_relative}")

# 4. 检查绝对路径创建（建议方案）
logs_absolute = Path(__file__).parent / "logs"
print(f"\n4. 建议的绝对路径 'logs':")
print(f"   {logs_absolute}")
print(f"   是否存在: {logs_absolute.exists()}")

# 5. 检查 dashboard.html
dashboard_relative = Path("dashboard.html").resolve()
dashboard_absolute = Path(__file__).parent / "dashboard.html"

print(f"\n5. dashboard.html 路径:")
print(f"   相对路径查找: {dashboard_relative}")
print(f"   存在: {dashboard_relative.exists()}")
print(f"   绝对路径查找: {dashboard_absolute}")
print(f"   存在: {dashboard_absolute.exists()}")

# 6. 检查 static 目录
static_relative = Path("static").resolve()
static_absolute = Path(__file__).parent / "static"

print(f"\n6. static 目录:")
print(f"   相对路径查找: {static_relative}")
print(f"   存在: {static_relative.exists()}")
print(f"   绝对路径查找: {static_absolute}")
print(f"   存在: {static_absolute.exists()}")

# 7. 权限检查
print(f"\n7. 权限检查:")
cwd = Path(os.getcwd())
print(f"   工作目录可写: {os.access(cwd, os.W_OK)}")
if script_path.parent != cwd:
    print(f"   脚本目录可写: {os.access(script_path.parent, os.W_OK)}")

# 8. 查找已有的 logs 目录（可能在其他地方）
print(f"\n8. 查找已有的 logs 目录:")
for root, dirs, files in os.walk(script_path.parent):
    if "logs" in dirs:
        full_path = Path(root) / "logs"
        print(f"   找到: {full_path}")
        if root != str(script_path.parent):
            print(f"   警告: logs 目录不在项目根目录！")

print("\n" + "="*80)
print("建议:")
print("="*80)
if script_path.parent != cwd:
    print("问题：工作目录与脚本目录不一致！")
    print(f"\n解决方案：")
    print(f"1. 在脚本目录启动：cd {script_path.parent}")
    print(f"2. 或使用绝对路径修改代码")
else:
    print("工作目录正确，请检查文件权限")
print("="*80)
