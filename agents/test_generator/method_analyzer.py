"""
方法分析器模块
分析方法的复杂度并给出建议的测试用例数量
"""
from typing import Dict, Any, List, Tuple, Union, Optional
import re

# 方法复杂度等级
SIMPLE = "SIMPLE"      # 简单方法
CONDITIONAL = "CONDITIONAL"  # 含条件分支
EXCEPTION = "EXCEPTION"    # 含异常处理
DEPENDENT = "DEPENDENT"    # 存在外部依赖

# 每个复杂度等级建议的测试用例数量
METHOD_TEST_COUNT = {
    SIMPLE: (1, 2),       # 简单方法: 1-2个测试
    CONDITIONAL: (2, 4),  # 含条件分支: 2-4个测试
    EXCEPTION: (3, 5),    # 含异常处理: 3-5个测试
    DEPENDENT: (2, 3)     # 存在外部依赖: 2-3个测试
}

def prioritize_methods(methods: List[Union[Dict[str, Any], str]]) -> List[Union[Dict[str, Any], str]]:
    """
    对方法列表进行优先级排序
    
    排序标准 (基于valid_classes.json中实际可用的字段):
    1. 公开(public)方法优先于非公开方法
    2. 非getter/setter方法优先
    3. 参数较多的方法优先
    4. 行数较多的方法优先
    
    Args:
        methods: 方法信息列表
        
    Returns:
        排序后的方法列表
    """
    # 检查方法列表类型
    if not methods:
        return []
    
    # 如果方法列表是字符串列表（简单形式），直接按规则排序
    if isinstance(methods[0], str):
        # 对于字符串列表，我们可以简单地根据名称和参数数量排序
        def method_priority(method_str: str):
            # 首先检查是否包含可见性信息
            visibility_keywords = ["public", "protected", "private", "package-private"]
            has_visibility = any(method_str.strip().startswith(kw) for kw in visibility_keywords)
            
            if has_visibility:
                parts = method_str.strip().split(" ", 1)
                visibility = parts[0]
                method_part = parts[1] if len(parts) > 1 else method_str
                is_public = visibility == "public"
            else:
                # 没有可见性信息，默认为public
                method_part = method_str
                is_public = True
            
            # 根据方法名称判断是否为getter/setter
            method_name = method_part.split('(')[0] if '(' in method_part else method_part
            is_accessor = method_name.startswith('get') or method_name.startswith('set') or method_name.startswith('is')
            
            # 估计参数数量
            params_part = method_part[method_part.find('(')+1:method_part.rfind(')')] if '(' in method_part else ''
            param_count = len(params_part.split(',')) if params_part.strip() else 0
            
            # 计算优先级分数
            # 1. 公开方法优先
            # 2. 非getter/setter的方法优先
            # 3. 参数较多的方法优先
            return (is_public, not is_accessor, param_count)
            
        return sorted(methods, key=method_priority, reverse=True)
    
    # 如果方法列表是字典列表（复杂形式），按valid_classes.json中的可用字段排序
    processed_methods = []
    for method in methods:
        if isinstance(method, dict):
            # 复制原始方法信息，避免修改原始数据
            processed_method = method.copy()
            
            # 处理可见性信息 - 直接使用'visibility'字段
            visibility = processed_method.get('visibility', 'public')  # 默认为public
            processed_method['is_public'] = visibility == 'public'
            
            # 标记getter/setter方法 - 直接使用'is_getter_setter'字段或根据名称判断
            if 'is_getter_setter' not in processed_method:
                name = processed_method.get('name', '')
                processed_method['is_accessor'] = (name.startswith('get') or 
                                              name.startswith('set') or 
                                              name.startswith('is'))
            else:
                processed_method['is_accessor'] = processed_method['is_getter_setter']
            
            # 参数数量 - 根据'params'或'param_names'字段判断
            param_count = 0
            if 'params' in processed_method:
                param_count = len(processed_method['params'])
            elif 'param_names' in processed_method:
                param_count = len(processed_method['param_names'])
            elif 'parameters' in processed_method:
                param_count = len(processed_method['parameters'])
            processed_method['param_count'] = param_count
            
            # 方法行数 - 使用'line_count'字段
            processed_method['complexity_score'] = processed_method.get('line_count', 0)
            
            processed_methods.append(processed_method)
    
    # 按照优先级排序
    sorted_methods = sorted(processed_methods, 
                        key=lambda m: (
                            m.get('is_public', True),            # 公开方法优先
                            not m.get('is_accessor', False),     # 非访问器方法优先
                            m.get('param_count', 0),             # 参数较多的方法优先
                            m.get('complexity_score', 0),        # 行数较多的方法优先
                            m.get('name', '')                    # 按名称排序以确保结果稳定
                        ),
                        reverse=True)
    
    # 将可能的非字典元素（例如字符串）附加到排序后列表的末尾
    non_dict_methods = [m for m in methods if not isinstance(m, dict)]
    return sorted_methods + non_dict_methods

def analyze_method_complexity(method_info: Union[Dict[str, Any], str]) -> str:
    """
    分析方法复杂度，基于方法信息而非源代码
    
    Args:
        method_info: 方法信息字典或方法签名字符串
        
    Returns:
        复杂度等级: SIMPLE, CONDITIONAL, EXCEPTION, DEPENDENT
    """
    # 提取方法名
    method_name = ""
    if isinstance(method_info, dict):
        method_name = method_info.get("name", "")
        # 如果是getter/setter方法，直接返回简单方法
        if method_info.get("is_getter_setter", False):
            return SIMPLE
        
        # 检查是否为构造函数
        if method_name.startswith("new"):
            return DEPENDENT
        
        # 基于行数判断复杂度
        line_count = method_info.get("line_count", 0)
        if line_count > 30:  # 非常长的方法，可能包含各种逻辑
            return EXCEPTION
        elif line_count > 15:  # 较长方法，可能有条件分支
            return CONDITIONAL
        elif line_count > 5:  # 中等长度，可能有简单条件
            return DEPENDENT
            
        # 基于参数数量判断
        params = method_info.get("params", method_info.get("parameters", method_info.get("param_names", [])))
        if len(params) > 3:  # 多参数方法，可能有复杂逻辑
            return CONDITIONAL
            
        # 检查返回类型
        return_type = method_info.get("return_type", "void")
        primitive_types = ["void", "boolean", "int", "long", "float", "double", "char", "byte", "short"]
        if return_type and return_type not in primitive_types and not return_type.startswith("java.lang."):
            return DEPENDENT
    else:
        # 从字符串中提取方法名
        parts = str(method_info).split("(")[0].split()
        method_name = parts[-1] if parts else ""
        
        # 计算参数数量
        params_part = str(method_info).split("(")[1].split(")")[0] if "(" in str(method_info) and ")" in str(method_info) else ""
        params = [p.strip() for p in params_part.split(",") if p.strip()]
        if len(params) > 3:
            return CONDITIONAL
    
    # 基于方法名的启发式规则
    
    # 1. 检查方法名中是否包含异常相关词汇
    exception_keywords = ["exception", "error", "throw", "catch", "try", "validate", "check", "assert"]
    if any(keyword in method_name.lower() for keyword in exception_keywords):
        return EXCEPTION
    
    # 2. 检查方法名中是否包含条件判断相关词汇
    conditional_keywords = ["if", "is", "has", "should", "can", "contains", "equals", "compare", "validate", "verify"]
    if any(keyword in method_name.lower() for keyword in conditional_keywords):
        return CONDITIONAL
    
    # 3. 检查简单方法模式
    if method_name.lower().startswith(("get", "is", "has")) and len(method_name) > 3:
        return SIMPLE  # 简单访问器
    elif method_name.lower().startswith("set") and len(method_name) > 3:
        return SIMPLE  # 简单设置器
    elif method_name.lower() in ["equals", "hashcode", "tostring"]:
        return SIMPLE  # 常见的Object方法
    
    # 默认返回条件方法
    return CONDITIONAL

def get_method_test_count(complexity: str) -> Tuple[int, int]:
    """
    根据方法复杂度获取建议的测试用例数量
    
    Args:
        complexity: 复杂度等级
        
    Returns:
        (最小测试数, 最大测试数)
    """
    return METHOD_TEST_COUNT.get(complexity, (1, 2))

def calculate_test_distribution(methods: List[Union[Dict[str, Any], str]]) -> Dict[str, Any]:
    """
    计算类中各方法的测试用例分布
    
    Args:
        methods: 方法信息列表
        
    Returns:
        测试分布信息，包括每个方法建议的测试数量
    """
    if not methods:
        return {"total_min": 0, "total_max": 0, "methods": {}}
    
    # 分析每个方法并计算建议的测试数量
    method_test_counts = {}
    total_min = 0
    total_max = 0
    
    for method in methods:
        # 提取方法名
        if isinstance(method, dict):
            name = method.get("name", "")
        else:
            # 从字符串中提取方法名
            method_str = str(method)
            parts = method_str.split("(")[0].split()
            name = parts[-1] if parts else method_str
        
        # 分析方法复杂度
        complexity = analyze_method_complexity(method)
        
        # 获取测试数量范围
        min_tests, max_tests = get_method_test_count(complexity)
        
        # 创建方法测试信息
        method_info = {
            "complexity": complexity,
            "min_tests": min_tests,
            "max_tests": max_tests
        }
        
        # 将方法名作为键保存测试信息
        method_test_counts[name] = method_info
        
        # 累计总测试数
        total_min += min_tests
        total_max += max_tests
        
    # 构建并返回结果
    return {
        "total_min": total_min,
        "total_max": total_max,
        "methods": method_test_counts
    }

def format_test_distribution(test_distribution: Dict[str, Any], methods: List[Union[Dict[str, Any], str]]) -> str:
    """
    将测试分布格式化为可读文本
    
    Args:
        test_distribution: 测试分布信息
        methods: 方法信息列表
        
    Returns:
        格式化后的测试分布文本
    """
    if not test_distribution or not methods:
        return ""
    
    # 格式化输出
    lines = ["方法列表（按照优先级排序）："]
    
    # 收集公开方法和非公开方法
    public_methods = []
    non_public_methods = []
    
    # 显示所有方法，不再限制数量
    for i, method in enumerate(methods, 1):
        try:
            # 处理方法是字典的情况
            if isinstance(method, dict):
                method_name = method.get('name', '')
                signature = method.get("signature", method.get("name", ""))
                visibility = method.get("visibility", "")
                
                # 构建方法签名
                method_signature = signature
                if visibility and not method_signature.startswith(visibility):
                    method_signature = f"{visibility} {method_signature}"
                
            # 处理方法是字符串的情况
            else:
                method_str = str(method)
                # 检查字符串是否已经包含可见性信息
                visibility_keywords = ["public", "protected", "private", "package-private"]
                has_visibility = any(method_str.strip().startswith(kw) for kw in visibility_keywords)
                
                if has_visibility:
                    # 已经包含可见性信息
                    parts = method_str.strip().split(" ", 1)
                    visibility = parts[0]
                    method_signature = method_str
                    method_name = method_signature.split('(')[0].split()[-1] if '(' in method_signature else method_signature.split()[-1]
                else:
                    # 不包含可见性信息，默认为公开方法
                    method_name = method_str.split('(')[0] if '(' in method_str else method_str
                    visibility = "public"  # 默认为公开
                    method_signature = method_str
            
            # 从测试分布中获取方法信息
            method_info = None
            if isinstance(test_distribution, dict) and "methods" in test_distribution:
                methods_dict = test_distribution["methods"]
                if isinstance(methods_dict, dict):
                    # 尝试通过名称或签名查找
                    method_info = methods_dict.get(method_name, None)
                    if method_info is None and signature:
                        method_info = methods_dict.get(signature, None)
                    
                    # 如果还没找到，尝试前缀匹配
                    if method_info is None:
                        for key, value in methods_dict.items():
                            if isinstance(key, str) and key.startswith(method_name):
                                method_info = value
                                break
            
            # 确定测试用例范围
            if method_info and isinstance(method_info, dict):
                min_tests = method_info.get('min_tests', 2)
                max_tests = method_info.get('max_tests', 3)
                test_range_str = f"{min_tests}-{max_tests}"
            else:
                test_range_str = "2-3"
            
            # 创建方法条目
            method_entry = f"{method_signature} (需要 {test_range_str} 个测试用例)"
            
            # 判断方法是否是公开的
            is_public = visibility.lower() == "public"
            
            # 分别添加到公开方法和非公开方法列表
            if is_public:
                public_methods.append((i, method_entry))
            else:
                non_public_note = " (非公开，需通过公开方法间接测试)"
                non_public_methods.append((i, f"{method_entry}{non_public_note}"))
            
        except Exception as e:
            # 如果处理单个方法失败，继续处理其他方法
            lines.append(f"{i}. {method_name if 'method_name' in locals() else f'方法{i}'} (处理错误)")
            continue
    
    # 先添加公开方法
    for i, entry in public_methods:
        lines.append(f"{i}. {entry}")
    
    # 如果有非公开方法，添加分隔标题
    if non_public_methods:
        lines.append("\n【非公开方法（仅供参考，不要直接测试）】:")
        for j, (i, entry) in enumerate(non_public_methods, 1):
            # 使用新的编号，从1开始
            lines.append(f"{j}. {entry}")
    
    # 添加总测试用例数量信息
    if isinstance(test_distribution, dict) and "total_min" in test_distribution and "total_max" in test_distribution:
        total_min = test_distribution["total_min"]
        total_max = test_distribution["total_max"]
        lines.append(f"\n总计需要提供 {total_min}-{total_max} 个测试用例")
    
    return "\n".join(lines)

def get_method_complexity_description(complexity: str) -> str:
    """
    获取方法复杂度的描述
    
    Args:
        complexity: 复杂度等级
        
    Returns:
        复杂度描述
    """
    descriptions = {
        SIMPLE: "简单方法，建议1-2个测试用例，涵盖正常输入与典型边界值",
        CONDITIONAL: "含条件分支的方法，建议为每条主要逻辑路径编写测试，总计2-4个测试用例",
        EXCEPTION: "含异常处理的方法，应覆盖正常流程与异常路径，建议3-5个测试用例",
        DEPENDENT: "存在外部依赖的方法，建议测试stub/mock场景和真实依赖，推荐2-3个测试用例"
    }
    return descriptions.get(complexity, "未知复杂度类型")

def generate_test_distribution_summary(distribution: Dict[str, Any]) -> str:
    """
    生成测试分布摘要信息
    
    Args:
        distribution: 测试分布信息
        
    Returns:
        测试分布摘要字符串
    """
    class_size = distribution.get("class_size", "unknown")
    total_min = distribution.get("total_min", 0)
    total_max = distribution.get("total_max", 0)
    methods = distribution.get("methods", {})
    
    summary = f"类规模: {class_size}，推荐总测试数量: {total_min}-{total_max}个\n\n"
    summary += "方法测试分布:\n"
    
    # 按复杂度排序（从高到低）
    complexity_order = {
        EXCEPTION: 3, 
        DEPENDENT: 2, 
        CONDITIONAL: 1, 
        SIMPLE: 0
    }
    
    # 安全地提取方法名和信息
    method_items = []
    for signature, info in methods.items():
        # 提取方法名 - 从signature中提取，避免依赖info中的name字段
        name = signature.split("(")[0].strip() if isinstance(signature, str) and "(" in signature else signature
        # 复制info并添加name键，防止缺失时报错
        method_info = info.copy() if isinstance(info, dict) else {"complexity": SIMPLE, "min_tests": 1, "max_tests": 2}
        if "name" not in method_info:
            method_info["name"] = name
        method_items.append((signature, method_info))
    
    # 排序方法
    sorted_methods = sorted(
        method_items, 
        key=lambda x: (-complexity_order.get(x[1]["complexity"], -1), x[1].get("name", ""))
    )
    
    # 生成每个方法的测试分布信息
    for signature, info in sorted_methods:
        name = info.get("name", signature)
        complexity = info.get("complexity", SIMPLE)
        min_tests = info.get("min_tests", 1)
        max_tests = info.get("max_tests", 2)
        summary += f"{complexity} {name}: {min_tests}-{max_tests}个测试用例\n"
    
    return summary 