"""
简单的LLM接口，专门用于基于Maven错误信息修复Java代码
"""

import os
import re
import logging
import asyncio
import aiohttp
from typing import Dict, Any

# 使用绝对导入避免相对导入错误
try:
    from . import config
except ImportError:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    import config

logger = logging.getLogger(__name__)

class SimpleLLMInterface:
    """简单的LLM接口，专门用于代码修复"""
    
    def __init__(self):
        """初始化LLM接口"""
        self.config = config.config.get_api_config()
        
    async def _make_api_request(self, prompt: str) -> str:
        """发送API请求"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['key']}"
        }
        
        # 精简的系统提示词
        system_prompt = """You are a Java expert. Fix compilation errors with minimal changes, preserve all test logic and method names.

KEY RULES:
1. Keep test method names unchanged
2. Fix only compilation/syntax errors  
3. Use public APIs only
4. Preserve test logic and assertions
5. Add missing imports as needed

Return complete fixed Java code only."""
        
        data = {
            "model": self.config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 8000  # 添加max_tokens参数，与其他模块保持一致
        }
        
        timeout = aiohttp.ClientTimeout(total=self.config.get("timeout", 180))
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.config['base_url']}/v1/chat/completions",
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        llm_content = response_data["choices"][0]["message"]["content"]
                        
                        # 输出LLM响应便于调试
                        print(f"\n{'='*80}")
                        print(f"LLM修复响应")
                        print(f"{'='*80}")
                        print(llm_content[:2000] + ("..." if len(llm_content) > 2000 else ""))
                        print(f"{'='*80}\n")
                        
                        return llm_content
                    else:
                        error_text = await response.text()
                        raise Exception(f"API请求失败 ({response.status}): {error_text}")
        except aiohttp.ClientError as e:
            error_msg = f"LLM API连接错误: {e}"
            print(error_msg)
            logger.error(error_msg)
            raise Exception(error_msg)
        except asyncio.TimeoutError as e:
            error_msg = f"LLM API超时错误: {e}"
            print(error_msg)
            logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"LLM API请求失败: {e}"
            print(error_msg)
            logger.error(error_msg)
            raise

# 创建全局实例
llm_interface = SimpleLLMInterface()

def generate_test_code(prompt: str, cls_info: Dict[str, Any]) -> str:
    """
    基于错误信息修复代码（保持函数名兼容性）
    
    Args:
        prompt: 包含错误信息和代码的修复提示
        cls_info: 类信息（为了兼容性保留，但不使用）
        
    Returns:
        修复后的代码
    """
    max_retries = 5  # 增加重试次数到5次
    retry_delay = 5  # 增加初始延迟到5秒
    for attempt in range(max_retries):
        try:
            result = asyncio.run(llm_interface._make_api_request(prompt))
            # 移除固定延迟，与 test_generator 保持一致
            return result
        except (asyncio.TimeoutError, aiohttp.ClientError, Exception) as e:
            print(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                print("所有LLM API重试均失败，跳过LLM修复")
                raise
            wait_time = retry_delay * (2 ** attempt)  # 指数退避
            print(f"等待 {wait_time} 秒后重试...")
            import time
            time.sleep(wait_time)

def _merge_test_methods(fixed_code: str, original_code: str) -> str:
    """
    合并LLM修复的代码和原始完整代码
    保留原始代码的所有方法，用LLM修复的方法替换对应的方法
    
    Args:
        fixed_code: LLM修复后的代码（可能缺少一些方法）
        original_code: 原始完整代码
        
    Returns:
        合并后的完整代码
    """
    try:
        # 解析固定代码中的方法
        fixed_methods = _extract_methods_from_code(fixed_code)
        original_methods = _extract_methods_from_code(original_code)
        
        # 获取基础结构（package, imports, class declaration等）- 使用原始代码保证完整性
        base_structure = _extract_base_structure(original_code)
        
        # 如果LLM修复代码看起来完整（包含package声明），则尝试合并import
        # 否则直接使用原始基础结构，避免破坏代码结构
        if 'package ' in fixed_code and 'class ' in fixed_code:
            # 看起来是完整代码，尝试智能合并
            fixed_base_structure = _extract_base_structure(fixed_code)
            merged_base_structure = _merge_base_structures(base_structure, fixed_base_structure)
            print(f"[合并模式] 智能合并 - 检测到完整LLM代码，合并import语句")
        else:
            # 看起来是代码片段，使用原始结构保证安全
            merged_base_structure = base_structure
            print(f"[合并模式] 安全模式 - LLM代码不完整，保持原始结构")
        
        # 合并方法：优先使用修复后的方法，补充原始方法
        merged_methods = original_methods.copy()
        fixed_method_count = 0
        
        for method_name, method_code in fixed_methods.items():
            if method_name in original_methods:
                # 替换原有方法
                merged_methods[method_name] = method_code
                fixed_method_count += 1
            else:
                # 新方法（理论上不应该出现，但防御性处理）
                merged_methods[method_name] = method_code
                print(f"  发现新方法: {method_name}")
        
        # 验证修复质量：检查关键测试方法是否保持断言逻辑
        _validate_test_assertion_integrity(original_methods, fixed_methods)
        
        # 检查是否有方法被遗漏
        missing_methods = set(original_methods.keys()) - set(merged_methods.keys())
        if missing_methods:
            print(f"  警告：发现遗漏方法: {missing_methods}")
        
        # 重建完整代码：保持原始方法顺序
        merged_code = merged_base_structure + "\n"
        
        # 按原始代码中的方法出现顺序重建
        original_lines = original_code.split('\n')
        method_order = []
        
        # 提取原始代码中方法的顺序
        for line in original_lines:
            stripped = line.strip()
            if 'void ' in stripped and '(' in stripped:
                method_match = re.search(r'\b(\w+)\s*\(', stripped)
                if method_match:
                    method_name = method_match.group(1)
                    if method_name in merged_methods and method_name not in method_order:
                        method_order.append(method_name)
        
        # 添加任何遗漏的方法
        for method_name in merged_methods:
            if method_name not in method_order:
                method_order.append(method_name)
        
        # 按顺序添加方法
        for method_name in method_order:
            if method_name in merged_methods:
                merged_code += "\n" + merged_methods[method_name] + "\n"
        
        merged_code += "\n}"
        
        print(f"\n[合并结果] 原始方法数: {len(original_methods)}, 修复方法数: {len(fixed_methods)}, 最终方法数: {len(merged_methods)}")
        print(f"[合并详情] 修复了 {fixed_method_count} 个方法，保留了 {len(merged_methods) - fixed_method_count} 个原始方法")
        
        # 验证合并后的代码是否保持原始测试意图
        validation_warnings = _validate_merge_integrity(original_methods, fixed_methods, merged_methods)
        if validation_warnings:
            print(f"[合并验证警告] 发现以下问题:")
            for warning in validation_warnings:
                print(f"  - {warning}")
        
        return merged_code
        
    except Exception as e:
        print(f"\n[合并失败] {e}，回退到LLM修复代码")
        import traceback
        print(f"[合并错误详情] {traceback.format_exc()}")
        return fixed_code

def _validate_merge_integrity(original_methods, fixed_methods, merged_methods):
    """
    验证合并后的代码是否保持原始测试意图
    
    Args:
        original_methods: 原始方法字典
        fixed_methods: 修复后的方法字典  
        merged_methods: 合并后的方法字典
        
    Returns:
        list: 验证警告列表
    """
    warnings = []
    
    # 检查1：确保所有原始方法都被保留
    missing_methods = set(original_methods.keys()) - set(merged_methods.keys())
    if missing_methods:
        warnings.append(f"遗漏了原始方法: {missing_methods}")
    
    # 检查2：验证修复后的方法是否保持了基本结构
    for method_name in fixed_methods.keys():
        if method_name in original_methods:
            original_method = original_methods[method_name]
            fixed_method = fixed_methods[method_name]
            
            # 检查测试方法名是否被改变
            original_test_name = _extract_test_method_name(original_method)
            fixed_test_name = _extract_test_method_name(fixed_method)
            
            if original_test_name != fixed_test_name:
                warnings.append(f"方法 {method_name} 的测试名称被改变: {original_test_name} -> {fixed_test_name}")
            
            # 检查关键断言是否被保留
            original_assertions = _extract_assertions(original_method)
            fixed_assertions = _extract_assertions(fixed_method)
            
            if len(original_assertions) > 0 and len(fixed_assertions) == 0:
                warnings.append(f"方法 {method_name} 的断言被完全移除")
            elif len(fixed_assertions) < len(original_assertions) * 0.5:
                warnings.append(f"方法 {method_name} 的断言数量大幅减少: {len(original_assertions)} -> {len(fixed_assertions)}")
    
    return warnings

def _extract_test_method_name(method_code):
    """从方法代码中提取测试方法名"""
    match = re.search(r'void\s+(\w+)\s*\(', method_code)
    return match.group(1) if match else "unknown"

def _extract_assertions(method_code):
    """从方法代码中提取断言语句"""
    assertions = []
    assertion_patterns = [
        r'assert\w+\s*\(',
        r'assertTrue\s*\(',
        r'assertFalse\s*\(',
        r'assertEquals\s*\(',
        r'assertNotNull\s*\(',
        r'assertNull\s*\(',
        r'assertThrows\s*\(',
    ]
    
    for pattern in assertion_patterns:
        matches = re.findall(pattern, method_code, re.IGNORECASE)
        assertions.extend(matches)
    
    return assertions

def _merge_base_structures(original_base: str, fixed_base: str) -> str:
    """
    合并基础结构，确保包含所有必要的import语句
    注意：保持原始结构的顺序，只添加缺失的import
    """
    try:
        # 策略改变：以原始结构为主，只提取修复代码中的新import语句
        original_lines = original_base.split('\n')
        fixed_lines = fixed_base.split('\n')
        
        # 提取原始代码中的import语句
        original_imports = set()
        for line in original_lines:
            if line.strip().startswith('import '):
                original_imports.add(line.strip())
        
        # 提取修复代码中的新import语句
        new_imports = set()
        for line in fixed_lines:
            if line.strip().startswith('import '):
                import_statement = line.strip()
                if import_statement not in original_imports:
                    new_imports.add(import_statement)
        
        if not new_imports:
            # 没有新的import，直接返回原始结构
            return original_base
        
        # 在原始结构中插入新的import语句
        result_lines = []
        import_section_ended = False
        
        for line in original_lines:
            stripped = line.strip()
            
            # 如果是import语句区域
            if stripped.startswith('import '):
                result_lines.append(line)
            elif stripped.startswith('package ') or stripped.startswith('/*') or stripped.startswith('//') or stripped.startswith('*') or stripped == '':
                # package声明、注释、空行，直接保留
                result_lines.append(line)
            else:
                # 非import语句区域，如果还没插入新import，现在插入
                if not import_section_ended and new_imports:
                    # 插入新的import语句
                    for new_import in sorted(new_imports):
                        result_lines.append(new_import)
                    result_lines.append('')  # 添加空行分隔
                    import_section_ended = True
                
                result_lines.append(line)
        
        return '\n'.join(result_lines)
        
    except Exception as e:
        print(f"[基础结构合并失败] {e}，使用原始结构")
        return original_base

def _extract_methods_from_code(code: str) -> Dict[str, str]:
    """
    从Java代码中提取所有测试方法
    
    Returns:
        {method_name: method_full_code}
    """
    methods = {}
    lines = code.split('\n')
    current_method = None
    method_lines = []
    brace_count = 0
    in_method = False
    method_started = False
    
    for line in lines:
        stripped = line.strip()
        
        # 检测注解开始（包括@DisplayName, @Tag等所有注解）
        if stripped.startswith('@'):
            # 如果是第一个注解，初始化状态
            if not method_lines:
                method_lines = []
                current_method = None
                method_started = False
                brace_count = 0
                in_method = False
            # 始终添加注解行，累积收集所有注解
            method_lines.append(line)
            continue
        
        # 检测方法签名
        if (current_method is None and 
            ('void ' in stripped or 'public ' in stripped or 'private ' in stripped) and
            '(' in stripped and ')' in stripped):
            
            # 提取方法名
            method_match = re.search(r'\b(\w+)\s*\(', stripped)
            if method_match:
                current_method = method_match.group(1)
                method_lines.append(line)
                
                # 开始计算大括号（只有遇到第一个{后才开始计算）
                if '{' in line:
                    method_started = True
                    brace_count = line.count('{') - line.count('}')
                    in_method = True
                else:
                    in_method = True  # 方法签名行，等待开始大括号
                continue
        
        # 在方法内部
        if in_method and current_method:
            method_lines.append(line)
            
            # 开始计算大括号（只有遇到第一个{后才开始计算）
            if '{' in line and not method_started:
                method_started = True
                brace_count = line.count('{') - line.count('}')
            elif method_started:
                brace_count += line.count('{') - line.count('}')
            
            # 方法结束条件：已开始方法体且大括号平衡
            if method_started and brace_count <= 0:
                methods[current_method] = '\n'.join(method_lines)
                current_method = None
                method_lines = []
                in_method = False
                brace_count = 0
                method_started = False
        else:
            # 如果收集了注解但还没有方法签名，继续等待
            if method_lines and current_method is None:
                # 可能是方法前的其他内容，继续等待方法签名
                if stripped and not stripped.startswith('//') and not stripped.startswith('/*'):
                    method_lines.append(line)
            else:
                # 重置状态，可能遇到了类级别的内容
                if not stripped or stripped.startswith('//') or stripped.startswith('/*'):
                    pass  # 空行或注释，继续
                else:
                    method_lines = []  # 重置，准备收集下一个方法
                    current_method = None
                    method_started = False
                    brace_count = 0
                    in_method = False
    
    return methods

def _extract_base_structure(code: str) -> str:
    """
    提取代码的基础结构（package, imports, class declaration, fields等）
    确保所有import语句都被正确保留
    """
    lines = code.split('\n')
    base_lines = []
    class_found = False
    imports_complete = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # 始终保留：package声明
        if stripped.startswith('package '):
            base_lines.append(line)
            continue
            
        # 始终保留：import语句（不管位置在哪里）
        if stripped.startswith('import '):
            base_lines.append(line)
            continue
            
        # 保留：注释和空行
        if (stripped.startswith('/*') or
            stripped.startswith('//') or
            stripped.startswith('*') or
            stripped == ''):
            base_lines.append(line)
            continue
            
        # 保留：类声明
        if 'class ' in stripped and '{' in stripped:
            base_lines.append(line)
            class_found = True
            continue
        elif 'class ' in stripped:  # 类声明可能跨多行
            base_lines.append(line)
            continue
            
        # 在类内部：保留字段声明
        if class_found:
            if (('private ' in stripped or 'public ' in stripped or 'protected ' in stripped) 
                and ';' in stripped and '(' not in stripped):  # 字段声明，不是方法
                base_lines.append(line)
                continue
            elif ('static ' in stripped and ';' in stripped and '(' not in stripped):  # 静态字段
                base_lines.append(line)
                continue
                
            # 遇到方法定义就停止（但要确保import都已处理完）
            if (stripped.startswith('@') or 
                (('public ' in stripped or 'private ' in stripped or 'protected ' in stripped) 
                 and '(' in stripped and 'void ' in stripped)):
                # 检查后续是否还有import（虽然不规范，但要处理）
                remaining_lines = lines[i:]
                for remaining_line in remaining_lines:
                    if remaining_line.strip().startswith('import '):
                        base_lines.append(remaining_line)
                break
        
        # 如果还没找到类声明，继续保留可能的内容
        if not class_found:
            base_lines.append(line)
    
    return '\n'.join(base_lines)

def extract_java_code(llm_response: str, cls_info: Dict[str, Any], original_code: str = None, was_simplified: bool = False) -> str:
    """
    从LLM响应中提取Java代码，如果输入被简化过则进行智能合并
    
    Args:
        llm_response: LLM响应
        cls_info: 类信息（为了兼容性保留，但不使用）
        original_code: 原始完整代码（用于合并）
        was_simplified: 是否对输入进行了简化
        
    Returns:
        提取的Java代码
    """
    if not llm_response:
        return ""
        
    # 尝试从代码块中提取
    code_blocks = re.findall(r'```(?:java)?\s*([\s\S]*?)```', llm_response)
    
    if code_blocks:
        # 使用最长的代码块
        fixed_code = max(code_blocks, key=len).strip()
    else:
        # 没有代码块就使用整个响应
        fixed_code = llm_response.strip()
    
    # 如果输入被简化过且有原始代码，进行智能合并
    if was_simplified and original_code and original_code.strip():
        print(f"\n[代码合并] 检测到简化输入，开始合并修复后代码和原始代码...")
        return _merge_test_methods(fixed_code, original_code)
    
    return fixed_code

def _validate_test_assertion_integrity(original_methods: dict, fixed_methods: dict) -> None:
    """
    验证修复后的测试方法是否保持了原始的断言逻辑
    
    Args:
        original_methods: 原始方法字典
        fixed_methods: 修复后方法字典
    """
    warnings = []
    
    for method_name, fixed_code in fixed_methods.items():
        if method_name not in original_methods:
            continue
            
        original_code = original_methods[method_name]
        
        # 检查1: 关键断言是否被移除
        original_asserts = len([line for line in original_code.split('\n') if 'assert' in line.lower()])
        fixed_asserts = len([line for line in fixed_code.split('\n') if 'assert' in line.lower()])
        
        if fixed_asserts < original_asserts:
            warnings.append(f"方法 {method_name} 可能丢失了断言 (原:{original_asserts} → 修复后:{fixed_asserts})")
        
        # 检查2: 期望值是否被错误修改 (assertTrue变成assertFalse等)
        if 'assertTrue' in original_code and 'assertFalse' in fixed_code:
            warnings.append(f"方法 {method_name} 的断言逻辑可能被错误反转 (assertTrue → assertFalse)")
        
        if 'assertEquals(true' in original_code and 'assertEquals(false' in fixed_code:
            warnings.append(f"方法 {method_name} 的期望值可能被错误修改 (true → false)")
            
        # 检查3: 方法名中出现的核心类型是否被移除
        referenced_types = set(re.findall(r'\b[A-Z][A-Za-z0-9_]*\b', method_name))
        for type_name in referenced_types:
            if type_name in original_code and type_name not in fixed_code:
                warnings.append(f"方法 {method_name} 的 {type_name} 相关逻辑可能被改变")
    
    if warnings:
        print("⚠️  断言完整性验证警告:")
        for warning in warnings:
            print(f"    - {warning}")
    else:
        print("✅ 断言完整性验证通过")
