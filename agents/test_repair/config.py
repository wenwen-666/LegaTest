"""
测试修复模块配置管理
专门用于测试修复所需的配置
"""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Config:
    """测试修复配置管理类"""
    
    def __init__(self):
        # API配置 - 只保留修复LLM调用所需的配置
        self.api = {
            "key": os.getenv("DEEPSEEK_API_KEY", "your api key"),
            "base_url": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            "model": os.getenv("API_MODEL", "deepseek-chat"),
            "timeout": int(os.getenv("API_REQUEST_TIMEOUT", "180"))
        }
    
    def get_api_config(self) -> Dict[str, Any]:
        """获取API配置"""
        return self.api.copy()

# 创建全局配置实例
config = Config()