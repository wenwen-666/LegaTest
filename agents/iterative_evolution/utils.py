"""
工具函数模块
只包含真正需要且不重复的通用辅助函数
"""

import os
import json
import shutil
import sys
from typing import Dict, Optional

def get_project_root() -> str:
    """获取项目根目录，避免复杂的相对路径计算"""
    current_file = os.path.abspath(__file__)
    # 从 agents/iterative_evolution/utils.py 向上找到项目根目录
    return os.path.dirname(os.path.dirname(os.path.dirname(current_file)))

def get_agents_path() -> str:
    """获取agents目录路径"""
    return os.path.join(get_project_root(), "agents")

def setup_test_repair_import():
    """设置test_repair模块的导入路径"""
    agents_path = get_agents_path()
    if agents_path not in sys.path:
        sys.path.insert(0, agents_path)

def ensure_dir(directory: str) -> None:
    """确保目录存在，如果不存在则创建"""
    os.makedirs(directory, exist_ok=True)

def copy_file(src_path: str, dst_path: str) -> bool:
    """复制文件，确保目标目录存在"""
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return True
    except Exception as e:
        print(f"复制文件失败: {e}")
        return False

def load_json(file_path: str) -> Optional[Dict]:
    """
    加载JSON文件，失败时返回None而不是空字典
    避免生成错误的预定义数据
    """
    try:
        if not os.path.exists(file_path):
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载JSON文件失败 {file_path}: {e}")
        return None

def save_json(data: Dict, file_path: str) -> bool:
    """保存数据到JSON文件"""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"保存JSON文件失败: {e}")
        return False