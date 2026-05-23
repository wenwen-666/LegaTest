"""
规则修复模块

负责使用预定义规则修复测试代码中的错误
"""

# 使用绝对导入避免相对导入错误
try:
    from .error_categories import ERROR_CATEGORIES
    from .classify_and_fix import classify_error, fix_by_category
    from .rule_repair import RuleFixer, process_test
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    
    from error_categories import ERROR_CATEGORIES
    from classify_and_fix import classify_error, fix_by_category
    from rule_repair import RuleFixer, process_test

__all__ = [
    'ERROR_CATEGORIES',
    'classify_error',
    'fix_by_category',
    'RuleFixer',
    'process_test'
] 