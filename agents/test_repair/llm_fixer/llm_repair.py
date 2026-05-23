"""
LLM修复实现模块

负责使用LLM修复测试代码中的错误
"""

import os
import logging
from typing import Dict, Any
import re

# 导入必要的模块
import sys
import os

# 添加test_repair目录到sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 使用绝对导入避免相对导入错误
try:
    import llm_interface
except ImportError:
    import sys
    import os
    # 添加test_repair模块路径
    test_repair_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if test_repair_dir not in sys.path:
        sys.path.insert(0, test_repair_dir)
    import llm_interface

# 配置日志
logger = logging.getLogger(__name__)

def _extract_error_relevant_code(source_code, error_messages):
    """智能提取错误相关的源代码片段"""
    if not source_code or not error_messages:
        return _extract_method_signatures_only(source_code)
    
    # 从错误信息中提取关键信息
    error_info = _analyze_error_context(error_messages)
    
    # 根据错误类型决定提取策略
    if error_info['missing_symbols']:
        return _extract_relevant_members(source_code, error_info['missing_symbols'])
    elif error_info['access_violations']:
        return _extract_class_structure_with_access(source_code, error_info['access_violations'])
    else:
        # 默认：只提取方法签名和公开API
        return _extract_method_signatures_only(source_code)

def _analyze_error_context(error_messages):
    """分析错误信息，提取关键上下文"""
    context = {
        'missing_symbols': set(),
        'access_violations': set(),
        'missing_methods': set(),
        'error_types': set()
    }
    
    for line in error_messages.split('\n'):
        # 提取missing symbol
        if 'cannot find symbol' in line:
            # 从后续行提取symbol详情
            if 'symbol:' in line:
                symbol_match = re.search(r'symbol:\s*(?:variable|method|class)\s+(\w+)', line)
                if symbol_match:
                    context['missing_symbols'].add(symbol_match.group(1))
        
        # 提取访问权限违规
        if 'has private access' in line or 'has protected access' in line:
            member_match = re.search(r'(\w+)(?:\([^)]*\))?\s+has\s+(?:private|protected)\s+access', line)
            if member_match:
                context['access_violations'].add(member_match.group(1))
        
        # 提取类型信息
        if 'COMPILATION_ERROR' in line:
            context['error_types'].add('compilation')
        if 'ACCESS_VIOLATION' in line:
            context['error_types'].add('access')
    
    return context

def _extract_relevant_members(source_code, symbols):
    """提取与特定符号相关的类成员"""
    lines = source_code.split('\n')
    result_lines = []
    
    # 1. 保留基础结构
    for line in lines:
        if (line.strip().startswith('package ') or 
            line.strip().startswith('import ') or 
            'class ' in line and 'public' in line):
            result_lines.append(line)
    
    # 2. 查找相关的字段和方法
    in_class = False
    brace_count = 0
    current_member = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # 跟踪类内部
        if 'class ' in line:
            in_class = True
        
        if in_class:
            brace_count += line.count('{') - line.count('}')
            
            # 检查是否是相关的成员
            is_relevant = any(symbol in line for symbol in symbols)
            
            if is_relevant or any(keyword in stripped for keyword in ['public static final', 'public static', 'public']):
                # 提取整个成员定义
                if stripped.startswith('public'):
                    current_member = [line]
                    
                    # 如果是方法，提取到方法签名结束
                    if '(' in line:
                        if '{' in line:
                            result_lines.append(line.replace('{', ' { ... }'))
                        else:
                            # 多行方法签名
                            j = i + 1
                            while j < len(lines) and '{' not in lines[j] and ';' not in lines[j]:
                                current_member.append(lines[j])
                                j += 1
                            if j < len(lines):
                                current_member.append(lines[j].replace('{', ' { ... }'))
                            result_lines.extend(current_member)
                    else:
                        # 字段或常量
                        result_lines.append(line)
            
            # 类结束
            if brace_count == 0 and in_class:
                result_lines.append('}')
                break
    
    return '\n'.join(result_lines)

def _extract_class_structure_with_access(source_code, members):
    """提取类结构，重点关注访问权限"""
    lines = source_code.split('\n')
    result_lines = []
    
    # 提取类声明和所有public成员签名
    in_class = False
    
    for line in lines:
        stripped = line.strip()
        
        # 基础结构
        if (stripped.startswith('package ') or 
            stripped.startswith('import ') or 
            'class ' in stripped):
            result_lines.append(line)
            if 'class ' in stripped:
                in_class = True
            continue
        
        if in_class:
            # 提取所有访问权限声明
            if any(access in stripped for access in ['public', 'protected', 'private']):
                if '(' in stripped:  # 方法
                    method_signature = line.split('{')[0].strip()
                    if not method_signature.endswith(';'):
                        method_signature += ';'
                    result_lines.append('    ' + method_signature)
                else:  # 字段
                    result_lines.append(line)
            elif stripped == '}':
                result_lines.append(line)
                break
    
    return '\n'.join(result_lines)

def _extract_method_signatures_only(source_code):
    """Extract method signatures and constructors, without implementation"""
    if not source_code:
        return source_code
    
    lines = source_code.split('\n')
    result_lines = []
    in_class = False
    class_name = None
    brace_count = 0
    in_method = False
    method_brace_count = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Keep basic structure
        if (stripped.startswith('package ') or 
            stripped.startswith('import ') or 
            stripped.startswith('/*') or stripped.startswith('*') or stripped.startswith('//')):
            result_lines.append(line)
            continue
        
        # Detect class declaration
        if ('class ' in stripped or 'interface ' in stripped) and not in_class:
            result_lines.append(line)
            in_class = True
            # Extract class name for constructor detection
            class_match = re.search(r'\b(?:class|interface)\s+(\w+)', stripped)
            if class_match:
                class_name = class_match.group(1)
            brace_count += line.count('{') - line.count('}')
            continue
        
        if in_class and not in_method:
            # Extract methods, constructors, and fields
            is_method_or_constructor = (
                ('(' in stripped and ')' in stripped) and  # Has method signature
                (stripped.startswith('public ') or stripped.startswith('private ') or 
                 stripped.startswith('protected ') or 'static ' in stripped or
                 (class_name and class_name in stripped))  # Constructor
            )
            
            is_field = (
                ';' in stripped and '(' not in stripped and 
                ('public ' in stripped or 'private ' in stripped or 'protected ' in stripped)
            )
            
            if is_method_or_constructor:
                # Extract signature without implementation
                if '{' in line:
                    signature = line.split('{')[0].strip()
                    if not signature.endswith(';'):
                        signature += ';'
                    result_lines.append('    ' + signature)
                    in_method = True
                    method_brace_count = line.count('{') - line.count('}')
                else:
                    # Multi-line method signature - collect until we find opening brace
                    result_lines.append('    ' + stripped + ';')
            elif is_field:
                result_lines.append(line)
            elif stripped == '' or stripped.startswith('//'):
                result_lines.append(line)  # Keep empty lines and comments
            
        elif in_method:
            # Skip method body content
            method_brace_count += line.count('{') - line.count('}')
            if method_brace_count <= 0:
                in_method = False
                method_brace_count = 0
        
        # Track overall class brace count
        if in_class:
            brace_count += line.count('{') - line.count('}')
            
            # Add closing brace when class ends
            if brace_count <= 0 and in_class:
                result_lines.append('}')
                break
    
    return '\n'.join(result_lines)

def _simplify_source_code(source_code):
    """保留所有方法签名，移除实现体"""
    if not source_code:
        return source_code
    
    lines = source_code.split('\n')
    simplified_lines = []
    in_method = False
    method_brace_count = 0
    class_brace_count = 0
    
    for line in lines:
        stripped = line.strip()
        
        # 保留：package、import、类声明、字段声明
        if (stripped.startswith('package ') or 
            stripped.startswith('import ') or 
            'class ' in stripped or 'interface ' in stripped or
            'enum ' in stripped or stripped.startswith('*') or
            stripped.startswith('/*') or stripped.startswith('/')):
            simplified_lines.append(line)
            continue
        
        # 计算大括号数量来判断是否在类内
        if '{' in line:
            class_brace_count += line.count('{')
        if '}' in line:
            class_brace_count -= line.count('}')
        
        # 在类内部
        if class_brace_count > 0:
            # 字段声明（包含 private/protected/public 字段）
            if (('private ' in stripped or 'protected ' in stripped or 'public ' in stripped) and 
                '(' not in stripped and (';' in stripped or '=' in stripped)):
                simplified_lines.append(line)
                continue
            
            # 方法声明检测
            if (('public ' in stripped or 'protected ' in stripped or 'private ' in stripped) and 
                '(' in stripped and not in_method):
                simplified_lines.append(line)
                if '{' in line:
                    in_method = True
                    method_brace_count = line.count('{')
                    simplified_lines.append('        // ... implementation ...')
                continue
            
            # 在方法内部
            if in_method:
                if '{' in line:
                    method_brace_count += line.count('{')
                if '}' in line:
                    method_brace_count -= line.count('}')
                    if method_brace_count <= 0:
                        simplified_lines.append(line)  # 方法结束的大括号
                        in_method = False
                continue
            
            # 类结束或其他重要结构
            if stripped == '}' or stripped.startswith('}'):
                simplified_lines.append(line)
                
        else:
            # 类外部的内容
            simplified_lines.append(line)
    
    return '\n'.join(simplified_lines)

def _extract_actual_failed_methods(error_messages):
    """精准提取真实失败的测试方法名"""
    failed_methods = set()
    
    # 修复正则表达式，确保能正确匹配
    patterns = [
        # Maven Surefire失败报告：testXxx Time elapsed: x.x s <<< FAILURE!
        r'^(test\w+)\s+Time elapsed:.*?<<<\s*(?:FAILURE|ERROR)',
        # 行号匹配：ClassName.testMethodName:123
        r'\.(test\w+):(\d+)',
        # 失败测试列表（修复：匹配缩进的测试名）
        r'^\s+(test\w+)$',
        # JUnit测试失败：testXxx(ClassName) <<< FAILURE
        r'(test\w+)\([^)]*\)\s*<<<\s*(?:FAILURE|ERROR)',
        # ERROR日志中的测试失败
        r'\[ERROR\]\s+(test\w+)\s+Time elapsed',
    ]
    
    for error_line in error_messages.split('\n'):
        error_line = error_line.strip()
        if not error_line:
            continue
            
        for pattern in patterns:
            match = re.search(pattern, error_line, re.IGNORECASE | re.MULTILINE)
            if match:
                method_name = match.group(1)
                # 验证是有效的测试方法名（允许下划线）
                if (method_name.startswith('test') and 
                    len(method_name) > 4 and 
                    method_name.replace('_', '').isalnum()):
                    failed_methods.add(method_name)
                    print(f"  Detected failed method: {method_name}")
                    break
                    
    return failed_methods

def _determine_extraction_strategy(total_methods, error_count, error_types):
    """激进优化Token使用量的代码提取策略
    
    Args:
        total_methods: 总方法数
        error_count: 错误方法数
        error_types: 错误类型分析结果
        
    Returns:
        str: 提取策略 ('full', 'smart', 'minimal')
    """
    if total_methods == 0:
        return 'full'
        
    error_ratio = error_count / total_methods
    
    # 策略1：极小规模或极复杂错误 -> 完整保护（大幅降低阈值）
    if (total_methods <= 8 or 
        error_count >= 10 or  # 错误很多时才需要更多上下文
        'compilation' in error_types and len(error_types['compilation']) > 8):  # 极复杂编译错误
        return 'full'
    
    # 策略2：小规模或高错误比例 -> 智能提取（降低阈值）
    if total_methods <= 20 or error_ratio > 0.3:
        return 'smart'
    
    # 策略3：默认使用最小化提取（优先控制Token）
    return 'minimal'

def _classify_error_types(error_messages):
    """智能分类错误类型，用于确定提取策略
    
    Args:
        error_messages: 错误信息字符串
        
    Returns:
        dict: 错误类型分类结果
    """
    classification = {
        'compilation': [],
        'runtime': [], 
        'assertion': [],
        'access': [],
        'import': []
    }
    
    if not error_messages:
        return classification
    
    for error_line in error_messages.split('\n'):
        error_line = error_line.strip()
        if not error_line:
            continue
            
        if 'cannot find symbol' in error_line or 'package does not exist' in error_line:
            classification['import'].append(error_line)
        elif 'has private access' in error_line or 'has protected access' in error_line:
            classification['access'].append(error_line)
        elif 'expected:' in error_line and 'but was:' in error_line:
            classification['assertion'].append(error_line)
        elif any(exc in error_line for exc in ['Exception', 'Error']) and 'Time elapsed' in error_line:
            classification['runtime'].append(error_line)
        else:
            classification['compilation'].append(error_line)
    
    return classification

def _analyze_method_dependencies(test_code, failed_methods):
    """分析失败方法的依赖关系
    
    Args:
        test_code: 测试代码
        failed_methods: 失败的方法列表
        
    Returns:
        dict: 依赖关系分析结果
    """
    dependencies = {
        'helper_methods': set(),
        'setup_methods': set(), 
        'field_dependencies': set(),
        'called_methods': set()
    }
    
    # 提取所有方法
    all_methods = re.findall(r'((?:public|private|protected)?\s*(?:static\s+)?void\s+(\w+)\s*\([^)]*\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', 
                           test_code, re.MULTILINE | re.DOTALL)
    
    for method_match, method_name in all_methods:
        if method_name in failed_methods:
            method_code = method_match
            
            # 分析方法调用
            called_methods = re.findall(r'(\w+)\s*\(', method_code)
            dependencies['called_methods'].update(called_methods)
            
            # 分析字段使用
            field_uses = re.findall(r'this\.(\w+)|(\w+)\.(?:get|set|is)', method_code)
            dependencies['field_dependencies'].update(field for field_tuple in field_uses for field in field_tuple if field)
    
    # 识别辅助方法和setup方法
    for method_match, method_name in all_methods:
        if method_name not in failed_methods:
            # 辅助方法：被失败方法调用的非测试方法
            if method_name in dependencies['called_methods'] and not method_name.startswith('test'):
                dependencies['helper_methods'].add(method_name)
            
            # Setup方法：包含setup/init/prepare等关键词
            if any(keyword in method_name.lower() for keyword in ['setup', 'init', 'prepare', 'before', 'after']):
                dependencies['setup_methods'].add(method_name)
            
            # 或者有相关注解
            if any(annotation in method_match for annotation in ['@Before', '@After', '@BeforeEach', '@AfterEach']):
                dependencies['setup_methods'].add(method_name)
    
    return dependencies

def _smart_extract_test_methods(test_code, error_formatted, strategy='smart'):
    """智能提取测试方法，平衡上下文完整性与Token效率
    
    Args:
        test_code: 原始测试代码
        error_formatted: 格式化的错误信息
        strategy: 提取策略 ('full', 'smart', 'minimal')
        
    Returns:
        str: 提取后的代码
    """
    if strategy == 'full':
        return test_code
    
    # 识别失败方法
    failed_methods = _extract_actual_failed_methods(error_formatted)
    if not failed_methods:
        return test_code  # 无法识别失败方法，保持原样
    
    # 分析依赖关系
    dependencies = _analyze_method_dependencies(test_code, failed_methods)
    
    # 根据策略确定包含的方法
    if strategy == 'smart':
        # 智能策略：核心方法 + 直接依赖 + 部分辅助方法
        include_methods = failed_methods.copy()
        include_methods.update(dependencies['helper_methods'])
        include_methods.update(dependencies['setup_methods'])
        
        # 限制辅助方法数量（避免包含过多）
        if len(dependencies['helper_methods']) > 5:
            # 只包含最相关的辅助方法
            include_methods = failed_methods.copy()
            include_methods.update(list(dependencies['helper_methods'])[:3])
            include_methods.update(dependencies['setup_methods'])
    
    elif strategy == 'minimal':
        # 最小策略：只包含失败方法 + 必要的setup方法
        include_methods = failed_methods.copy()
        include_methods.update(dependencies['setup_methods'])
    
    else:
        # 默认包含所有相关方法
        include_methods = failed_methods.copy()
        include_methods.update(dependencies['helper_methods'])
        include_methods.update(dependencies['setup_methods'])
    
    # 构建提取后的代码
    extracted_code = _build_extracted_code(test_code, include_methods, dependencies['field_dependencies'])
    
    # Token控制机制：如果代码太长，进一步压缩
    estimated_tokens = len(extracted_code) // 4  # 粗略估算：4个字符≈1个token
    if estimated_tokens > 4000:  # Token限制：4000个token
        print(f"⚠️ Extracted code too long ({estimated_tokens}≈tokens), enabling compression mode")
        # 压缩：只保留核心失败方法
        compressed_methods = failed_methods.copy()
        compressed_methods.update(dependencies['setup_methods'])  # 只保留setup方法
        extracted_code = _build_extracted_code(test_code, compressed_methods, set())  # 移除字段依赖
        
        # 二次检查
        estimated_tokens_compressed = len(extracted_code) // 4
        print(f"📦 After compression: {estimated_tokens_compressed}≈tokens")
        
    return extracted_code

def _build_extracted_code(test_code, include_methods, field_dependencies):
    """构建提取后的代码
    
    Args:
        test_code: 原始代码
        include_methods: 要包含的方法集合
        field_dependencies: 字段依赖集合
        
    Returns:
        str: 构建后的代码
    """
    lines = test_code.split('\n')
    result_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # 保留基础结构和字段
        if (stripped.startswith('package ') or 
            stripped.startswith('import ') or 
            'class ' in stripped or stripped == '' or
            stripped.startswith('/*') or stripped.startswith('//') or
            stripped.startswith('*') or
            # 保留所有字段声明（简化策略）
            (('private ' in stripped or 'public ' in stripped or 'protected ' in stripped) and ';' in stripped) or
            # Evolution模式特殊保护
            'static final' in stripped or
            '@BeforeEach' in stripped or '@AfterEach' in stripped):
            result_lines.append(line)
            i += 1
            continue
        
        # 检测方法开始
        if stripped.startswith('@') or ('void ' in stripped and '(' in stripped):
            # 收集完整方法
            method_start = i
            current_method_lines = []
            method_name = None
            brace_count = 0
            method_started = False
            
            while i < len(lines):
                method_line = lines[i]
                current_method_lines.append(method_line)
                
                # 提取方法名
                if method_name is None and 'void ' in method_line and '(' in method_line:
                    method_match = re.search(r'void\s+(\w+)\s*\(', method_line)
                    if method_match:
                        method_name = method_match.group(1)
                
                # 大括号计数
                if '{' in method_line and not method_started:
                    method_started = True
                    brace_count = method_line.count('{') - method_line.count('}')
                elif method_started:
                    brace_count += method_line.count('{') - method_line.count('}')
                
                i += 1
                
                # 方法结束
                if method_started and brace_count <= 0:
                    break
                
                # 安全检查
                if i - method_start > 500:  # 单个方法不应超过500行
                    break
            
            # 决定是否包含该方法
            if method_name and method_name in include_methods:
                result_lines.extend(current_method_lines)
                print(f"  [Smart extraction] Include method: {method_name}")
            else:
                # 添加方法占位符（保持结构完整性）
                if method_name and not method_name.startswith('test'):
                    result_lines.append(f"    // Method {method_name} omitted for Token efficiency")
        else:
            result_lines.append(line)
            i += 1
    
    return '\n'.join(result_lines)

def _analyze_error_types(error_messages):
    """Analyze error types and provide targeted repair guidance
    
    Args:
        error_messages: Error message string
        
    Returns:
        list: List of repair guidance
    """
    guidance = []
    error_lower = error_messages.lower()
    
    # Null pointer exceptions
    if "nullpointerexception" in error_lower or "nullpointer" in error_lower:
        guidance.append("• Check null value handling: Add necessary null checks or mock configuration")
        
    # Assertion failures
    if "expected:" in error_messages and "but was:" in error_messages:
        guidance.append("• Check assertion expected values: Ensure they match actual output format")
        
    # ResultSet mock issues
    if "resultset" in error_lower and ("mock" in error_lower or "nullpointer" in error_lower):
        guidance.append("• Check ResultSet mock configuration: Ensure getMetaData() returns correct mock object")
        
    # Type conversion issues
    if "classcastexception" in error_lower:
        guidance.append("• Check type conversion: Ensure parameter types are correct")
        
    # Compilation errors
    if "cannot find symbol" in error_messages or "compilation error" in error_lower:
        guidance.append("• Check compilation errors: Fix missing imports, incorrect method calls or type mismatches")
    
    # Access permission issues
    if "has private access" in error_messages or "has protected access" in error_messages:
        guidance.append("• Check access permissions: Only use public/protected members, avoid accessing private members")
        
    # Character encoding issues 
    if "charset" in error_lower or "encoding" in error_lower:
        guidance.append("• Check character encoding: Use correct StandardCharsets constants")
    
    return guidance

def _extract_error_relevant_test_methods(test_code, error_messages, preserve_context=True):
    """根据错误信息只保留相关的测试方法
    
    智能提取策略：
    1. 解析错误行号和方法名
    2. 只保留有错误的测试方法
    3. 保持类结构完整（package, imports, class declaration）
    4. 大幅减少提示词长度，提高LLM修复成功率
    
    Args:
        preserve_context: 是否保留相关上下文方法（默认True，更保守）
    """
    if not test_code or not error_messages:
        return test_code
    
    # 使用更精确的方法提取真实失败的测试方法
    actual_failed_methods = _extract_actual_failed_methods(error_messages)
    
    # 智能决策：使用新的提取策略（已在主流程中处理）
    total_methods = len(re.findall(r'void\s+test\w*\s*\(', test_code, re.IGNORECASE))
    error_count = len(actual_failed_methods)
    
    # 注意：新的智能提取策略已经在主流程中处理，这里不需要额外覆盖
    # preserve_context参数将根据主流程的extraction_strategy确定
    
    # 提取错误行号和方法名
    error_lines = set()
    error_methods = actual_failed_methods.copy()  # 优先使用精确提取的结果
    
    for error in error_messages.split('\n'):
        # 提取行号：支持多种格式
        # 格式1: [行号,列号] (编译错误)
        line_match1 = re.search(r'\[(\d+),\d+\]', error)
        if line_match1:
            error_lines.add(int(line_match1.group(1)))
        
        # 格式2: 类名.方法名:行号 (测试失败/错误)
        line_match2 = re.search(r'\.(\w+):(\d+)', error)
        if line_match2:
            method_name = line_match2.group(1)
            line_num = int(line_match2.group(2))
            error_lines.add(line_num)
            if method_name.startswith('test'):
                error_methods.add(method_name)
        
        # 格式3: 类名.方法名:行号 » 错误类型 (TargetClassTest_Crossover_Gen7_6x9.testMethod:57 » NullPointer)
        line_match3 = re.search(r'\.(test\w+):(\d+)\s*»', error)
        if line_match3:
            method_name = line_match3.group(1)
            line_num = int(line_match3.group(2))
            error_lines.add(line_num)
            error_methods.add(method_name)
        
        # 格式4: 测试方法失败信息 - 更精确的匹配
        failure_patterns = [
            r'(test\w+)\s+.*?(?:FAILURE|ERROR)',  # Maven surefire 失败报告
            r'(test\w+)\s+.*?Time elapsed.*?<<<\s*(?:FAILURE|ERROR)', # 详细失败报告
            r'Tests run:.*?Failures:.*?Errors:.*?(test\w+)', # 测试总结中的失败
            r'Failed tests:\s+(test\w+)', # 明确的失败测试列表
            r'\[(test\w+)\].*?(?:failed|error)', # 方括号中的测试名称
        ]
        
        for pattern in failure_patterns:
            method_match = re.search(pattern, error, re.IGNORECASE)
            if method_match:
                error_methods.add(method_match.group(1))
                break
        
        # 格式5: 精确的错误方法名提取（移除过于宽泛的堆栈跟踪模式）
        # 只匹配明确指向测试失败的模式，避免捕获堆栈跟踪中的无关方法
        precise_patterns = [
            r'in test method\s+(test\w+)',  # 明确指向测试方法的错误
            r'(test\w+)\s*\([^)]*\)\s*(?:has|cannot)',  # 测试方法访问错误
            r'Failed:\s+(test\w+)',  # 明确的测试失败
        ]
        
        for pattern in precise_patterns:
            method_match = re.search(pattern, error)
            if method_match:
                method_name = method_match.group(1)
                error_methods.add(method_name)
                break
    
    if not error_lines and not error_methods and not actual_failed_methods:
        return test_code
    
    lines = test_code.split('\n')
    result_lines = []
    current_method_lines = []
    current_method_name = None
    method_start_line = -1
    brace_count = 0
    class_level = True
    
    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1
        stripped = line.strip()
        
        # 保留类结构（package, imports, class declaration, 字段）
        # Evolution模式下强化字段和辅助方法保护
        if (stripped.startswith('package ') or 
            stripped.startswith('import ') or 
            'class ' in stripped or stripped == '' or
            stripped.startswith('/*') or stripped.startswith('//') or
            stripped.startswith('*') or
            # 强化字段保护：所有类级别声明
            (class_level and ('private ' in stripped or 'public ' in stripped or 'protected ' in stripped) and ';' in stripped) or
            # Evolution模式特殊保护：静态常量、Setup/TearDown方法
            'static final' in stripped or
            '@BeforeEach' in stripped or '@AfterEach' in stripped or
            '@Before' in stripped or '@After' in stripped or
            'setUp' in stripped.lower() or 'tearDown' in stripped.lower()):
            result_lines.append(line)
            i += 1
            continue
        
        # 检测方法开始（@Test注解或方法签名）
        if stripped.startswith('@') or ('public ' in stripped and 'void ' in stripped and '(' in stripped):
            class_level = False
            
            # 收集整个方法（包括注解）
            method_start_line = i
            current_method_lines = []
            current_method_name = None
            brace_count = 0
            method_started = False
            
            # 收集方法直到结束
            while i < len(lines):
                method_line = lines[i]
                current_method_lines.append(method_line)
                stripped_method_line = method_line.strip()
                
                # 提取方法名
                if current_method_name is None and 'void ' in method_line and '(' in method_line:
                    method_match = re.search(r'void\s+(\w+)\s*\(', method_line)
                    if method_match:
                        current_method_name = method_match.group(1)
                
                # 开始计算大括号（只有遇到第一个{后才开始计算）
                if '{' in method_line and not method_started:
                    method_started = True
                    brace_count = method_line.count('{') - method_line.count('}')
                elif method_started:
                    brace_count += method_line.count('{') - method_line.count('}')
                
                i += 1
                
                # 方法结束条件：已开始方法体且大括号平衡
                if method_started and brace_count <= 0:
                    break
                    
                # 安全检查：避免无限循环
                if i - method_start_line > 1000:  # 单个方法不应超过1000行
                    print(f"  Warning: Method {current_method_name or 'unknown'} has too many lines, force ending")
                    break
            
            # 判断该方法是否需要修复
            needs_repair = False
            
            # 方法1：优先检查是否在精确识别的失败方法中
            if current_method_name and current_method_name in actual_failed_methods:
                needs_repair = True
            # 方法1b：再检查是否在其他识别的错误方法中
            elif current_method_name and current_method_name in error_methods:
                needs_repair = True
            
            # 方法2：检查该方法的行号范围是否包含错误行
            if not needs_repair:
                method_end_line = i
                for err_line in error_lines:
                    if method_start_line <= err_line <= method_end_line:
                        needs_repair = True
                        break
            
            # 方法3：仅当错误行完全在方法范围内才认为需要修复
            # 移除模糊匹配，避免包含无关方法
            
            # 根据是否需要修复决定是否包含该方法 - 优化激进模式
            if needs_repair:
                result_lines.extend(current_method_lines)
                print(f"  Include method to repair: {current_method_name} (lines {method_start_line}-{i})")
            elif preserve_context:
                # 保守模式：保留更多上下文，包含更完整的方法签名和关键逻辑
                method_signature_lines = []
                key_logic_lines = []
                
                # 收集方法签名（注解、方法声明）
                for idx, method_line in enumerate(current_method_lines):
                    stripped_line = method_line.strip()
                    # 保留注解、方法声明、重要的变量声明
                    if (stripped_line.startswith('@') or 
                        'void ' in stripped_line or
                        '{' in stripped_line and idx < 5 or  # 开头几行的大括号
                        # Evolution模式特殊保护：保留关键的测试设置
                        'factory' in stripped_line.lower() or
                        'mock' in stripped_line.lower() or
                        'byte[]' in stripped_line or
                        'InputStream' in stripped_line or
                        'createArchive' in stripped_line):
                        method_signature_lines.append(method_line)
                    # 限制签名行数，避免过多
                    if len(method_signature_lines) >= 8:
                        break
                
                result_lines.extend(method_signature_lines)
                result_lines.append(f"        // ... {current_method_name} implementation preserved for Evolution context ...")
                result_lines.append("    }")
            else:
                # 激进模式：完全跳过无错误的方法，不生成任何占位符代码
                # 这样可以最大化减少Token使用
                pass  # 完全跳过，不添加任何内容
        else:
            # 类结束或其他内容
            result_lines.append(line)
            i += 1
    
    extracted_code = '\n'.join(result_lines)
    
    # 统计信息 - 修复：准确计算实际错误方法数量
    original_methods = len(re.findall(r'void\s+test\w*\s*\(', test_code, re.IGNORECASE))
    extracted_methods_count = len(re.findall(r'void\s+test\w*\s*\(', extracted_code, re.IGNORECASE))
    
    # 使用精确识别的失败方法数量
    actual_failed_count = len(actual_failed_methods)
    
    # 如果精确识别没有结果，再尝试其他方式
    if actual_failed_count == 0:
        # 统计所有识别的错误方法
        actual_failed_count = len(error_methods.intersection(
            {match.group(1) for match in re.finditer(r'void\s+(test\w*)\s*\(', test_code, re.IGNORECASE)}
        ))
        
        # 如果还是0，通过行号识别
        if actual_failed_count == 0 and error_lines:
            methods_with_errors = set()
            for match in re.finditer(r'void\s+(test\w*)\s*\(', test_code, re.IGNORECASE):
                method_start = match.start()
                method_lines = test_code[:method_start].count('\n') + 1
                method_end = method_lines + 50
                if any(method_lines <= err_line <= method_end for err_line in error_lines):
                    methods_with_errors.add(match.group(1))
            actual_failed_count = len(methods_with_errors)
    
    print(f"Smart extraction completed: {original_methods} methods → {actual_failed_count} actual failed methods (extracted {extracted_methods_count} methods for repair)")
    
    return extracted_code

def _simplify_evolution_test_code(test_code):
    """DEPRECATED: 这个函数会破坏完整的测试实现，已停用
    原本用于简化Evolution模式的测试代码：保留结构，移除实现
    现在直接返回原始代码以避免破坏LLM生成的完整实现
    """
    # 修复：不再简化代码，直接返回原始完整代码
    return test_code
    
    # 以下代码已被注释，因为它会破坏LLM生成的完整测试实现
    # 原始的简化逻辑会将完整的测试方法替换为 "// ... test implementation ..." 占位符
    # 这导致交叉操作生成的完整代码被破坏成空壳实现
    """
    lines = test_code.split('\n')
    simplified_lines = []
    # ... 原始简化逻辑已注释 ...
    return '\n'.join(simplified_lines)
    """

def _remove_license_header(test_code: str) -> tuple[str, str]:
    """移除License头部节省Token"""
    lines = test_code.split('\n')
    package_line = -1
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('package '):
            package_line = i
            break
        # 如果遇到代码内容，说明没有license头
        elif stripped and not stripped.startswith('/*') and not stripped.startswith('*') and not stripped.startswith('//'):
            return test_code, ""
    
    # 如果package前有超过10行注释，可能是license头
    if package_line > 10:
        license_header = '\n'.join(lines[:package_line])
        code_without_license = '\n'.join(lines[package_line:])
        return code_without_license, license_header
    
    return test_code, ""

def _restore_license_header(fixed_code: str, license_header: str) -> str:
    """恢复License头部"""
    if license_header:
        return license_header + '\n' + fixed_code
    return fixed_code

def _is_source_code_useful(source_code: str) -> bool:
    """Check if the extracted source code contains useful information beyond just imports and basic structure"""
    if not source_code or len(source_code.strip()) < 50:
        return False
    
    lines = source_code.strip().split('\n')
    useful_lines = 0
    basic_structure_lines = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Count basic structure lines (package, imports, class declaration, closing braces)
        if any([
            stripped.startswith('package '),
            stripped.startswith('import '),
            stripped.startswith('public class ') or stripped.startswith('public interface '),
            stripped == '}',
            stripped.startswith('/*') or stripped.startswith('*') or stripped.startswith('//'),
        ]):
            basic_structure_lines += 1
            
        # Count lines that provide useful API information
        elif any([
            stripped.endswith(';') and '(' in stripped and ('public ' in stripped or 'protected ' in stripped),  # Method signatures  
            stripped.startswith('public static final') or stripped.startswith('protected static final'),  # Constants
            ('private ' in stripped or 'public ' in stripped or 'protected ' in stripped) and (';' in stripped and 'final' not in stripped),  # Fields
        ]):
            useful_lines += 1
    
    # Must have at least 2 useful API lines to be worth including
    if useful_lines < 2:
        return False
        
    # If more than 80% is just basic structure, it's not useful
    total_content_lines = useful_lines + basic_structure_lines
    if total_content_lines == 0:
        return False
        
    useful_ratio = useful_lines / total_content_lines
    print(f"  Source code analysis: {useful_lines} useful lines, {basic_structure_lines} basic lines, ratio: {useful_ratio:.2f}")
    return useful_ratio > 0.2

def _create_concise_repair_prompt(error_formatted: str, test_code: str, temp_class_name: str, 
                                 source_code: str = "", is_evolution: bool = False, 
                                 is_second_attempt: bool = False) -> str:
    """Create concise repair prompt with different handling for test failures vs compilation errors"""
    
    attempt_text = " (Second Attempt)" if is_second_attempt else ""
    mode_text = " - Evolution Mode" if is_evolution else ""
    
    # Determine if this is a test failure or compilation error
    is_test_failure = "TEST_FAILURE:" in error_formatted
    
    if is_test_failure:
        # Simplified prompt for test failures - no source code needed
        repair_prompt = f"""Fix Java test assertion failures{attempt_text}{mode_text}

{error_formatted}

Fix Strategy:
- Update expected values in assertions to match actual method behavior
- For "expected <X> but was <Y>" - change expected value from X to Y
- Keep test logic unchanged, only adjust assertion values
- Preserve all test method structure and functionality

Test code to fix:
```java
{test_code}
```

Requirements: Keep class name {temp_class_name}, only fix assertion failures, return complete working code."""
        
    else:
        # Detailed prompt for compilation errors with specific guidance
        repair_prompt = f"""Fix Java test compilation errors{attempt_text}{mode_text}

{error_formatted}

Fix Strategy:"""
        
        # Add specific guidance based on error types
        
        if "Missing import:" in error_formatted:
            repair_prompt += """
- Add missing import statements based on error details
- Common imports: java.util.zip.ZipEntry, java.nio.charset.StandardCharsets"""
        
        if "Cannot find symbol:" in error_formatted:
            repair_prompt += """
- Add missing imports or remove references to non-existent symbols
- Check for typos in class/method names
- Use available public methods from the source class (see source code context below)"""
        
        if "Syntax error:" in error_formatted:
            repair_prompt += """
- Fix syntax issues: missing semicolons, brackets, parentheses
- Ensure proper Java statement structure"""
        
        if "Duplicate method definition:" in error_formatted:
            repair_prompt += """
- Remove duplicate method definitions: keep only one version of each method
- If methods have similar names, rename one to make it unique"""
        
        if "Missing abstract method implementation:" in error_formatted or "Invalid @Override annotation" in error_formatted:
            repair_prompt += """
- Implement missing abstract methods from interface/superclass
- Remove incorrect @Override annotations for non-overriding methods
- Ensure method signatures match exactly with supertype (name, parameters, return type)"""
        
        # Add source code context only for compilation errors that actually need API information
        # Skip source code for self-contained errors that don't require understanding the source class API
        skip_source_code = any([
            "Duplicate method definition:" in error_formatted,  # Problem in test code itself
            "Invalid @Override annotation" in error_formatted,  # Annotation issue, not API issue
            "Missing semicolons, brackets, parentheses" in error_formatted,  # Basic syntax
            "Access violation:" in error_formatted,  # Private/protected access - don't show private methods
            "has private access" in error_formatted,  # Alternative format
            "has protected access" in error_formatted,  # Alternative format
            "no suitable constructor found" in error_formatted,  # Constructor signature mismatch - self-contained error
            "constructor" in error_formatted and "is not applicable" in error_formatted,  # Constructor issues
            "actual and formal argument lists differ" in error_formatted,  # Parameter count mismatch
            "Missing imports/packages:" in error_formatted,  # Import/class not found errors - don't need source API
            "cannot find symbol" in error_formatted and "class " in error_formatted,  # Class not found
            "package" in error_formatted and "does not exist" in error_formatted,  # Package errors
            "unreported exception" in error_formatted and "must be caught or declared" in error_formatted,  # Exception handling
            "Syntax error:" in error_formatted and len([e for e in error_formatted.split('\n') if e.strip()]) == 1,  # Simple single syntax errors
        ])
        
        if source_code and not skip_source_code:
            simplified_source = _extract_error_relevant_code(source_code, error_formatted)
            
            # Check if extracted source code is actually useful
            # Skip if it's mostly just imports and basic class structure
            if _is_source_code_useful(simplified_source):
                repair_prompt += f"""

Source code context:
```java
{simplified_source}
```"""
            else:
                print("  Skipping low-value source code (only imports/basic structure)")
        
        repair_prompt += f"""

Test code to fix:
```java
{test_code}
```

Requirements: Keep class name {temp_class_name}, fix compilation errors only, preserve test intent, return complete working code."""
    
    return repair_prompt


def repair_with_llm(test_code: str, error_formatted: str, temp_class_name: str, source_code: str = "", is_second_attempt: bool = False, repair_stats=None, cls_info: Dict[str, Any] = None) -> str:
    """
    Use LLM to repair test code
    
    Args:
        test_code: Test code to repair
        error_formatted: Formatted error information
        temp_class_name: Temporary class name
        source_code: Source code of class under test (optional)
        is_second_attempt: Whether this is a second repair attempt
        repair_stats: Repair statistics object (optional)
        cls_info: Class information dictionary (optional), includes stats_collector etc
        
    Returns:
        Repaired code
    """    
    # Use the provided class name directly
    real_class_name = temp_class_name
    
    # Auto-detect repair mode
    def _detect_repair_mode(class_name):
        """Auto-detect repair mode based on class name"""
        if "Crossover" in class_name or "Mutation" in class_name:
            return "evolution"
        elif re.match(r".*TestV\d+", class_name):
            return "evolution"
        elif class_name.endswith("Temp"):
            return "generation"
        else:
            return "generation"
    
    repair_mode = _detect_repair_mode(temp_class_name)
    is_evolution = (repair_mode == "evolution")
    
    # Log class name and mode
    logger.info(f"Repair class: {temp_class_name}, mode: {repair_mode}")
    
    # Check error information
    if not error_formatted or error_formatted.strip() == "":
        error_formatted = "Maven build failed but no specific error information was detected. Please check code syntax, import statements and class names."
    
    # Step 1: Remove License header to save tokens
    code_without_license, license_header = _remove_license_header(test_code)
    if license_header:
        logger.info(f"Removed License header to save tokens: {len(license_header)} characters")
    
    # Step 2: Create repair prompt with appropriate context
    processed_test_code = code_without_license
    repair_prompt = _create_concise_repair_prompt(
        error_formatted, processed_test_code, temp_class_name, 
        source_code, is_evolution, is_second_attempt
    )
    
    # Simplified token statistics
    estimated_tokens = len(repair_prompt) // 3.5
    original_tokens = len(test_code) // 3.5
    token_saved = original_tokens - estimated_tokens if estimated_tokens < original_tokens else 0
    
    # Prepare cls_info
    if cls_info is None:
        cls_info = {'className': real_class_name, 'temp_class_name': temp_class_name}
    else:
        cls_info.setdefault('className', real_class_name)
        cls_info.setdefault('temp_class_name', temp_class_name)
    
    # Simplified output
    attempt_text = "Second" if is_second_attempt else "First"
    print(f"\n{'='*80}")
    print(f"🔧 Test Repair Phase - LLM Repair Prompt")
    print("="*80)
    print(repair_prompt)
    print("="*80)
    print(f"{attempt_text} LLM repair - {temp_class_name} ({repair_mode} mode, {estimated_tokens:.0f} tokens)")
    if token_saved > 0:
        print(f"Token optimization: saved {token_saved:.0f} tokens")
    print("="*80 + "\n")
    
    # Simplified logging
    logger.info(f"Prompt statistics: {len(repair_prompt)} characters, {estimated_tokens:.0f} tokens")
    
    # Call LLM for repair
    stats_collector = cls_info.get('stats_collector')
    
    try:
        if stats_collector:
            # Use test_generator LLM interface
            import sys, os
            agents_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            test_gen_dir = os.path.join(agents_dir, 'test_generator')
            
            if test_gen_dir not in sys.path:
                sys.path.insert(0, test_gen_dir)
            
            import llm_interface as test_gen_llm
            repair_cls_info = cls_info.copy()
            repair_cls_info['call_type'] = 'repair'
            llm_response = test_gen_llm.generate_test_code(repair_prompt, repair_cls_info)
        else:
            # Use local LLM interface
            llm_response = llm_interface.generate_test_code(repair_prompt, cls_info)
            
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        # Restore License header and return original code
        return _restore_license_header(test_code, license_header)
    
    # Extract fixed code directly
    fixed_code = llm_interface.extract_java_code(llm_response, cls_info, None, False)
    
    # Update statistics
    if repair_stats:
        repair_stats.llm_repair_time += 0  # Time statistics handled by LLM interface
        if hasattr(repair_stats, 'tokens_used'):
            repair_stats.tokens_used += estimated_tokens
        if hasattr(repair_stats, 'tokens_saved'):
            repair_stats.tokens_saved += token_saved
    
    # Restore License header and return result
    if fixed_code and len(fixed_code.strip()) > 100:
        final_code = _restore_license_header(fixed_code, license_header)
        logger.info(f"LLM {attempt_text} repair successful - {repair_mode} mode ({estimated_tokens:.0f} tokens)")
        return final_code
    else:
        logger.warning(f"LLM {attempt_text} repair failed")
        return _restore_license_header(test_code, license_header) 
