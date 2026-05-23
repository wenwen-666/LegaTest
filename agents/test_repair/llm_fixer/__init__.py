"""
LLM修复模块

负责使用LLM修复测试代码中的错误
"""

# 使用绝对导入避免相对导入错误
try:
    from .llm_repair import repair_with_llm
except ImportError:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    from llm_repair import repair_with_llm

__all__ = [
    'repair_with_llm'
] 