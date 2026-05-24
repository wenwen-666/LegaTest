"""
错误分类和修复功能

负责识别Java错误类型并应用相应的修复规则
只处理能够精确匹配和修复的错误类别
"""

import re
# 使用绝对导入避免相对导入错误
try:
    from .error_categories import ERROR_CATEGORIES
except ImportError:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    from error_categories import ERROR_CATEGORIES
from typing import List, Dict, Any, Optional

# 常用Java库的导入语句（保留基本的导入）
COMMON_IMPORTS = {
    "List": "import java.util.List;",
    "ArrayList": "import java.util.ArrayList;",
    "Map": "import java.util.Map;",
    "HashMap": "import java.util.HashMap;",
    "Set": "import java.util.Set;",
    "HashSet": "import java.util.HashSet;",
    "Test": "import org.junit.Test;",
    "Assert": "import org.junit.Assert;",
    "Before": "import org.junit.Before;",
    "After": "import org.junit.After;",
    "jupiter": "import org.junit.jupiter.api.Test;"
}

# 测试工具类的导入语句
TEST_RELATED_IMPORTS = [
    "import org.junit.Test;",
    "import org.junit.Before;",
    "import org.junit.After;",
    "import org.junit.jupiter.api.Test;",
    "import org.junit.jupiter.api.BeforeEach;",
    "import org.junit.jupiter.api.AfterEach;",
    "import org.junit.Assert;",
    "import static org.junit.Assert.*;",
    "import static org.junit.jupiter.api.Assertions.*;",
    "import org.mockito.Mockito;",
    "import static org.mockito.Mockito.*;",
    "import org.mockito.MockitoAnnotations;",
    "import org.mockito.Mock;",
    "import org.mockito.InjectMocks;"
]

# 中文错误关键词映射到错误类别
CHINESE_ERROR_KEYWORDS = {
    # 保留与剩余错误类别相关的中文关键词
    "已定义具有相同简名的类型": "DUPLICATE_DEFINITION_ERRORS",
    "重复的修饰符": "ACCESS_MODIFIER_ERRORS",
    "重复的注释": "DUPLICATE_DEFINITION_ERRORS",
    "重复的注解": "DUPLICATE_DEFINITION_ERRORS",
    "未使用的导入": "IMPORT_ERRORS",
    "重复的导入": "IMPORT_ERRORS"
}

def match_error_category(error_message: str) -> Optional[str]:
    """
    匹配错误类别，使用更精确的匹配策略
    
    Args:
        error_message: 错误信息
        
    Returns:
        匹配到的错误类别，如果没有匹配项则返回None
    """
    if not error_message:
        return None
        
    error_message = error_message.lower()
    
    # 记录每个类别的匹配结果，包括匹配度评分
    category_matches = []
    
    for category, patterns in ERROR_CATEGORIES.items():
        for pattern in patterns:
            match = re.search(pattern, error_message, re.IGNORECASE)
            if match:
                # 计算匹配度评分
                # 1. 使用匹配组的数量作为基础分
                score = len(match.groups()) if match.groups() else 1
                
                # 2. 使用匹配字符串的长度作为加权
                score += len(pattern) / 100
                
                # 3. 匹配类别的额外加分
                if category == "IMPORT_ERRORS" and any(kw in error_message 
                                                     for kw in ["import", "unused"]):
                    score += 5
                elif category == "DUPLICATE_DEFINITION_ERRORS" and any(kw in error_message 
                                                                    for kw in ["duplicate", "repeated"]):
                    score += 3
                elif category == "ACCESS_MODIFIER_ERRORS" and any(kw in error_message 
                                                               for kw in ["modifier", "repeated", "duplicate"]):
                    score += 3
                
                category_matches.append((category, score, pattern))
    
    if not category_matches:
        # 尝试使用中文错误关键词匹配
        for keyword, category in CHINESE_ERROR_KEYWORDS.items():
            if re.search(keyword, error_message, re.IGNORECASE):
                return category
        return None
    
    # 按评分排序，返回最高分的类别
    category_matches.sort(key=lambda x: x[1], reverse=True)
    return category_matches[0][0]

def classify_error(error_output: str) -> Optional[str]:
    """
    从编译器输出中找出最可能的错误类别
    
    Args:
        error_output: 编译器输出
        
    Returns:
        错误类别，如果无法分类则返回None
    """
    # 如果输入为空，直接返回None
    if not error_output:
        return None
        
    # 首先清理错误输出，只保留关键信息
    clean_error = clean_error_output(error_output)
    
    # 尝试匹配错误类别
    category = match_error_category(clean_error)
    
    # 如果成功匹配到类别，直接返回
    if category:
        return category
    
    # 如果未匹配到类别，尝试提取单个错误进行匹配
    errors = extract_individual_errors(clean_error)
    
    # 如果有多个错误，尝试逐个匹配
    for error in errors:
        category = match_error_category(error)
        if category:
            return category
    
    # 如果仍然无法匹配，返回None表示无法分类
    return None

def extract_individual_errors(error_output: str) -> List[str]:
    """
    从错误输出中提取单个错误消息
    
    Args:
        error_output: 错误输出
        
    Returns:
        单个错误消息列表
    """
    errors = []
    
    # 尝试按错误行分割，更精确地提取错误信息
    error_patterns = [
        r'error:.*',
        r'\[ERROR\].*',
        r'Exception:.*',
        r'.*\.java:\d+:.*'
    ]
    
    for pattern in error_patterns:
        matches = re.findall(pattern, error_output, re.MULTILINE)
        errors.extend(matches)
    
    # 去重
    return list(set(errors)) if errors else [error_output]

def clean_error_output(error_output: str) -> str:
    """
    清理错误输出，移除无关信息
    
    Args:
        error_output: 原始错误输出
        
    Returns:
        清理后的错误输出
    """
    # 移除ANSI颜色代码
    clean_output = re.sub(r'\x1b\[[0-9;]*m', '', error_output)
    
    # 移除多余的空白行
    clean_output = re.sub(r'\n\s*\n', '\n', clean_output)
    
    return clean_output.strip()

def add_imports(code: str, error_message=None) -> str:
    """
    简化的导入添加功能
    只添加基本的测试相关导入
    """
    if not code or "import" in code:
        return code
    
    # 如果代码中没有导入但包含测试注解，添加基本导入
    if "@Test" in code and "import" not in code:
        package_match = re.search(r'package\s+[\w.]+;', code)
        if package_match:
            insert_pos = package_match.end()
            basic_imports = "\n\nimport org.junit.Test;\nimport static org.junit.Assert.*;\n\n"
            code = code[:insert_pos] + basic_imports + code[insert_pos:]
    
    return code

def fix_by_category(code, category, error_message=None):
    """
    根据错误类别修复代码
    只处理能够精确匹配和修复的错误类别
    
    Args:
        code: 源代码
        category: 错误类别
        error_message: 错误信息
        
    Returns:
        修复后的代码
    """
    fixed_code = code
    
    # 只处理精确可修复的错误类别
    if category == "IMPORT_ERRORS":
        # 处理导入相关的错误
        if "unused import" in str(error_message) or "Unused import" in str(error_message):
            # 移除未使用的导入
            unused_match = re.search(r'[Uu]nused import:\s*([^\s;]+)', str(error_message))
            if unused_match:
                unused_import = unused_match.group(1)
                # 移除这个导入语句
                import_pattern = rf'import\s+{re.escape(unused_import)}\s*;?\s*\n?'
                fixed_code = re.sub(import_pattern, '', fixed_code)
        
        if "duplicate import" in str(error_message) or "repeated import" in str(error_message):
            # 处理重复导入
            duplicate_match = re.search(r'(?:duplicate|repeated) import:\s*([^\s;]+)', str(error_message))
            if duplicate_match:
                duplicate_import = duplicate_match.group(1)
                # 只保留第一个导入语句
                import_pattern = rf'import\s+{re.escape(duplicate_import)}\s*;'
                imports_found = list(re.finditer(import_pattern, fixed_code))
                if len(imports_found) > 1:
                    # 移除除第一个之外的所有重复导入
                    for match in reversed(imports_found[1:]):
                        start, end = match.span()
                        fixed_code = fixed_code[:start] + fixed_code[end:]
    
    elif category == "DUPLICATE_DEFINITION_ERRORS":
        # 处理重复定义错误
        fixed_code = fix_duplicate_modifiers(fixed_code)
        fixed_code = fix_duplicate_annotations(fixed_code, {"message": error_message})
        fixed_code = fix_duplicate_imports(fixed_code, {"message": error_message})
    
    elif category == "ACCESS_MODIFIER_ERRORS":
        # 处理访问修饰符错误
        fixed_code = fix_duplicate_modifiers(fixed_code)
    
    elif category == "API_COMPATIBILITY_ERRORS":
        # 处理API兼容性错误
        fixed_code = fix_api_compatibility_errors(fixed_code, error_message)
    
    elif category == "PRIVATE_ACCESS_ERRORS":
        # 处理私有访问错误
        fixed_code = fix_private_access_errors(fixed_code, error_message)
    
    elif category == "CONSTRUCTOR_ERRORS":
        # 处理构造器错误
        fixed_code = fix_constructor_errors(fixed_code, error_message)
    
    elif category == "RESOURCE_MANAGEMENT_ERRORS":
        # 处理资源管理错误
        fixed_code = fix_resource_management_errors(fixed_code, error_message)
    
    # 返回修复后的代码
    return fixed_code

def fix_duplicate_modifiers(code):
    """
    修复重复的修饰符
    
    Args:
        code: 源代码
        
    Returns:
        修复后的代码
    """
    # 修复重复的public修饰符
    code = re.sub(r'(public\s+)+', 'public ', code)
    # 修复重复的private修饰符
    code = re.sub(r'(private\s+)+', 'private ', code)
    # 修复重复的protected修饰符
    code = re.sub(r'(protected\s+)+', 'protected ', code)
    # 修复重复的static修饰符
    code = re.sub(r'(static\s+)+', 'static ', code)
    # 修复重复的final修饰符
    code = re.sub(r'(final\s+)+', 'final ', code)
    # 修复重复的abstract修饰符
    code = re.sub(r'(abstract\s+)+', 'abstract ', code)
    return code

def fix_unused_imports(test_code: str, error: Dict[str, Any] = None) -> str:
    """
    修复未使用的导入问题
    
    Args:
        test_code: 测试代码
        error: 错误信息
        
    Returns:
        修复后的代码
    """
    if error is None:
        # 如果没有提供错误信息，尝试进行静态分析
        unused_imports = detect_unused_imports(test_code)
        if not unused_imports:
            return test_code
        # 使用第一个检测到的未使用导入
        error = unused_imports[0] if unused_imports else {}
    
    # 从错误信息中提取未使用的导入类
    unused_import = error.get("match_data", {}).get("unused_import", "")
    if not unused_import and "match" in error:
        # 尝试从匹配文本中提取
        match_text = error.get("match", "")
        match = re.search(r"Unused import: ([^\s;]+)", match_text)
        if match:
            unused_import = match.group(1)
    
    if not unused_import:
        return test_code
    
    # 构建匹配模式，精确匹配整个导入语句
    import_pattern = fr'import\s+{re.escape(unused_import)};(\s*\n)?'
    
    # 从代码中移除未使用的导入
    fixed_code = re.sub(import_pattern, '', test_code)
    
    # 清理可能留下的连续空行
    fixed_code = re.sub(r'\n\s*\n\s*\n', '\n\n', fixed_code)
    
    return fixed_code

def detect_unused_imports(test_code: str) -> List[Dict[str, Any]]:
    """
    检测未使用的导入（简化版本）
    
    Args:
        test_code: 测试代码
        
    Returns:
        未使用导入的列表
    """
    unused = []
    
    # 提取所有导入
    imports = re.findall(r'import\s+([^;]+);', test_code)
    
    for import_stmt in imports:
        # 提取类名
        class_name = import_stmt.split('.')[-1]
        # 检查是否在代码中使用
        if class_name not in test_code.replace(f"import {import_stmt};", ""):
            unused.append({
                "match_data": {"unused_import": import_stmt}
            })
    
    return unused

def fix_duplicate_annotations(test_code: str, error: Dict[str, Any] = None) -> str:
    """
    修复重复注解问题
    
    Args:
        test_code: 测试代码
        error: 错误信息
        
    Returns:
        修复后的代码
    """
    # 查找并移除重复的注解
    annotations = ['@Test', '@Before', '@After', '@Override', '@Mock', '@InjectMocks']
    
    for annotation in annotations:
        # 使用正则表达式查找重复的注解
        pattern = rf'({re.escape(annotation)}\s*\n\s*)+{re.escape(annotation)}'
        test_code = re.sub(pattern, annotation, test_code)
    
    return test_code

def fix_duplicate_imports(test_code: str, error: Dict[str, Any] = None) -> str:
    """
    修复重复导入问题
    
    Args:
        test_code: 测试代码
        error: 错误信息
        
    Returns:
        修复后的代码
    """
    # 提取所有导入语句
    import_lines = re.findall(r'import\s+([^;]+);', test_code)
    unique_imports = []
    seen = set()
    
    # 去除重复导入
    for imp in import_lines:
        if imp not in seen:
            seen.add(imp)
            unique_imports.append(f"import {imp};")
    
    # 重建导入部分
    import_block = "\n".join(unique_imports)
    
    # 查找包声明的位置
    package_end = 0
    package_match = re.search(r'package\s+[\w.]+;', test_code)
    if package_match:
        package_end = package_match.end()
    
    # 移除原有的导入语句
    code_without_imports = re.sub(r'import\s+[^;]+;\s*\n?', '', test_code)
    
    # 重新插入去重的导入
    if package_match:
        package_part = test_code[:package_end]
        rest_part = code_without_imports[package_end:]
        result = package_part + "\n\n" + import_block + "\n\n" + rest_part.lstrip()
    else:
        result = import_block + "\n\n" + code_without_imports.lstrip()
    
    return result

def fix_api_compatibility_errors(code: str, error_message=None) -> str:
    """
    修复API兼容性错误
    
    Args:
        code: 源代码
        error_message: 错误信息
        
    Returns:
        修复后的代码
    """
    if not error_message:
        return code
    
    fixed_code = code
    error_str = str(error_message)
    
    # Java 8 方法兼容性修复
    if "String.repeat" in error_str or "repeat(" in error_str:
        fixed_code = re.sub(r'(\w+)\.repeat\((\d+)\)', r'repeatString(\1, \2)', fixed_code)
        if 'String repeatString(String value, int count)' not in fixed_code:
            helper_method = '''
    private static String repeatString(String value, int count) {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < count; i++) {
            builder.append(value);
        }
        return builder.toString();
    }
'''
            fixed_code = fixed_code.rstrip().rsplit('}', 1)[0] + helper_method + "}\n" if '}' in fixed_code else fixed_code
    
    # Path.of() -> Paths.get() (Java 8兼容)
    if "Path.of" in error_str or "cannot find symbol.*Path" in error_str:
        fixed_code = re.sub(r'Path\.of\(', 'Paths.get(', fixed_code)
    
    # CSV库方法兼容性修复
    if "CSVFormat" in error_str and "withAllowDuplicateHeaderNames" in error_str:
        # 移除不支持的方法调用
        fixed_code = re.sub(r'\.withAllowDuplicateHeaderNames\([^)]*\)', '', fixed_code)
    
    # 通用builder模式修复
    if "builder()" in error_str:
        # .builder().setX(y).build() -> .withX(y)
        fixed_code = re.sub(r'\.builder\(\)\.([a-zA-Z]+)\(([^)]*)\)\.build\(\)', r'.with\1(\2)', fixed_code)
        # 移除单独的.builder()调用
        fixed_code = re.sub(r'\.builder\(\)', '', fixed_code)
    
    # 移除不存在的方法调用
    if "cannot find symbol: method" in error_str:
        # 提取方法名
        method_match = re.search(r"cannot find symbol:\s*method\s+([^(]+)", error_str)
        if method_match:
            method_name = method_match.group(1).strip()
            # 移除该方法的调用（保守处理）
            method_pattern = rf'\.{re.escape(method_name)}\([^)]*\)'
            fixed_code = re.sub(method_pattern, '', fixed_code)
    
    return fixed_code

def fix_private_access_errors(code: str, error_message=None) -> str:
    """
    修复私有访问错误
    
    Args:
        code: 源代码
        error_message: 错误信息
        
    Returns:
        修复后的代码
    """
    if not error_message:
        return code
    
    fixed_code = code
    error_str = str(error_message)
    
    # 提取私有成员名和类名
    private_match = re.search(r'(\w+)(?:\(\))? has (?:private|protected) access in (\w+)', error_str)
    if private_match:
        private_member = private_match.group(1)
        target_class = private_match.group(2)
        
        # 根据错误类型采用不同的修复策略
        lines = fixed_code.split('\n')
        filtered_lines = []
        removed_variables = set()  # 跟踪被移除的变量
        
        for line_idx, line in enumerate(lines):
            original_line = line
            
            # 检查是否包含私有访问
            if private_member in line:
                
                # 策略1: 私有类实例化 (如 new OffsetEntry())
                if f'new {private_member}(' in line or f'new {target_class}.{private_member}(' in line:
                    # 提取变量名（如果有）
                    var_match = re.search(rf'(\w+)\s*=.*new.*{re.escape(private_member)}', line)
                    if var_match:
                        removed_variables.add(var_match.group(1))
                    
                    # 替换为注释，避免语法错误
                    indent = len(line) - len(line.lstrip())
                    filtered_lines.append(f"{' ' * indent}// Removed private class instantiation: {private_member}")
                    continue
                
                # 策略2: 私有类声明 (如 OffsetEntry entry)
                elif f'{private_member} ' in line and '=' in line:
                    # 替换类型声明
                    if f'{private_member} ' in line:
                        # 将私有类型替换为Object或注释掉
                        modified_line = re.sub(rf'\b{re.escape(private_member)}\b', 'Object', line)
                        filtered_lines.append(modified_line + ' // Changed from private type')
                        continue
                
                # 策略3: 私有方法调用
                elif f'.{private_member}(' in line:
                    # 处理方法调用
                    if '=' in line:
                        # 赋值语句：设为null
                        assignment_part = line.split('=')[0].strip()
                        indent = len(line) - len(line.lstrip())
                        filtered_lines.append(f"{' ' * indent}{assignment_part} = null; // Removed private method call")
                    else:
                        # 独立调用：注释掉
                        indent = len(line) - len(line.lstrip())
                        filtered_lines.append(f"{' ' * indent}// Removed private method call: {private_member}()")
                    continue
                
                # 策略4: 其他情况，用注释替换
                else:
                    indent = len(line) - len(line.lstrip())
                    filtered_lines.append(f"{' ' * indent}// Removed line with private access: {private_member}")
                    continue
            
            # 检查是否使用了被移除的变量
            elif any(f'{var}.' in line or f'{var})' in line or f'{var};' in line or f' {var} ' in line for var in removed_variables):
                # 使用了被移除的变量，注释掉这行
                indent = len(line) - len(line.lstrip())
                filtered_lines.append(f"{' ' * indent}// Removed line using undefined variable")
            else:
                # 没有问题，保持原样
                filtered_lines.append(line)
        
        fixed_code = '\n'.join(filtered_lines)
        
        # 策略2：尝试替换为常见的公共方法
        public_alternatives = {
            'annotationArrayMemberEquals': 'equals',
            'arrayMemberHash': 'hashCode',
            'isInstance': 'isAssignableFrom',
        }
        
        if private_member in public_alternatives:
            alt_method = public_alternatives[private_member]
            fixed_code = re.sub(rf'\.{re.escape(private_member)}\(', f'.{alt_method}(', fixed_code)
    
    return fixed_code

def add_import(code: str, import_statement: str) -> str:
    """
    向代码中添加导入语句
    
    Args:
        code: 源代码
        import_statement: 要添加的导入语句
        
    Returns:
        添加导入后的代码
    """
    if import_statement in code:
        return code
    
    # 查找包声明的位置
    lines = code.split('\n')
    package_end = 0
    
    for i, line in enumerate(lines):
        if line.strip().startswith('package '):
            package_end = i + 1
            break
    
    # 在包声明后插入导入
    if package_end > 0:
        lines.insert(package_end, '')
        lines.insert(package_end + 1, import_statement)
        lines.insert(package_end + 2, '')
    else:
        # 如果没有包声明，在文件开头插入
        lines.insert(0, import_statement)
        lines.insert(1, '')
    
    return '\n'.join(lines)

def fix_constructor_errors(code: str, error_message=None) -> str:
    """
    修复构造器错误
    
    Args:
        code: 源代码
        error_message: 错误信息
        
    Returns:
        修复后的代码
    """
    if not error_message:
        return code
    
    fixed_code = code
    error_str = str(error_message)
    
    # 提取构造器名称
    constructor_match = re.search(r'(?:no suitable constructor found for|constructor|is undefined).*?(\w+)', error_str)
    if constructor_match:
        class_name = constructor_match.group(1)
        
        # 策略1：移除无参构造器调用，替换为工厂方法或静态方法
        if "no arguments" in error_str or "is undefined" in error_str:
            # 移除 new ClassName() 调用
            no_arg_pattern = rf'new\s+{re.escape(class_name)}\(\)'
            
            fixed_code = re.sub(no_arg_pattern, f'// Removed invalid {class_name} constructor', fixed_code)
        
        # 策略2：添加必需的参数
        elif "cannot be applied to" in error_str:
            # 尝试修复参数不匹配的构造器
            lines = fixed_code.split('\n')
            for i, line in enumerate(lines):
                if f'new {class_name}(' in line and re.search(rf'new\s+{re.escape(class_name)}\([^)]*\)', line):
                    # 简单策略：添加注释说明需要参数
                    lines[i] = f'        // FIXME: Constructor {class_name} requires proper parameters'
                    lines[i+1:i+1] = ['        // ' + line.strip()]
            fixed_code = '\n'.join(lines)
    
    return fixed_code

def fix_invalid_constructor_declarations(code: str, error_message=None) -> str:
    """
    修复无效的构造函数声明错误
    
    主要处理 "invalid method declaration; return type required" 错误
    这通常由于构造函数名与类名不匹配或缺少 public 修饰符导致
    """
    if not error_message:
        return code
        
    import re
    
    lines = code.split('\n')
    fixed_lines = []
    current_class = None
    error_line_numbers = []
    
    # 提取错误行号
    error_str = str(error_message)
    line_number_matches = re.findall(r':\[(\d+),\d+\]', error_str)
    if line_number_matches:
        error_line_numbers = [int(num) - 1 for num in line_number_matches]  # 转为0索引
    
    for i, line in enumerate(lines):
        # 检测类声明
        class_match = re.search(r'(?:public\s+|private\s+|protected\s+)?(?:static\s+)?class\s+(\w+)\s*\{', line)
        if class_match:
            current_class = class_match.group(1)
            fixed_lines.append(line)
            continue
            
        # 如果这一行在错误行号中或看起来像有问题的构造函数
        if ((i in error_line_numbers or 
             error_line_numbers == [] and _looks_like_problematic_constructor(line)) and 
            current_class):
            
            fixed_line = _fix_problematic_constructor_line(line, current_class)
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)

def _looks_like_problematic_constructor(line: str) -> bool:
    """检测是否是有问题的构造函数声明"""
    stripped = line.strip()
    if not stripped or stripped.startswith('//'):
        return False
        
    # 匹配可能有问题的构造函数模式
    import re
    problematic_patterns = [
        r'\s*(\w+)\s*\([^)]*\)\s*\{',  # 缺少 public 的构造函数
        r'\s*public\s+(\w+)\s*\([^)]*\)\s*\{',  # 可能名称不匹配的构造函数
    ]
    
    for pattern in problematic_patterns:
        match = re.match(pattern, stripped)
        if match and match.group(1)[0].isupper():
            return True
    
    return False

def _fix_problematic_constructor_line(line: str, current_class: str) -> str:
    """修复有问题的构造函数行"""
    import re
    
    # 提取缩进和剩余内容
    match = re.match(r'(\s*)(?:public\s+|private\s+|protected\s+)?(\w+)(\s*\([^)]*\)\s*\{.*)', line)
    if not match:
        return line
    
    indent = match.group(1)
    constructor_name = match.group(2)
    params_and_rest = match.group(3)
    
    # 修复构造函数名为当前类名，并确保有 public 修饰符
    if constructor_name[0].isupper():  # 只处理看起来像构造函数的
        return f"{indent}public {current_class}{params_and_rest}"
    
    return line

def fix_resource_management_errors(code: str, error_message=None) -> str:
    """
    修复资源管理错误
    
    Args:
        code: 源代码
        error_message: 错误信息
        
    Returns:
        修复后的代码
    """
    if not error_message:
        return code
    
    fixed_code = code
    error_str = str(error_message)
    
    # 修复try-with-resources语法错误
    if "try-with-resources not applicable" in error_str:
        # 简化策略：将try-with-resources转换为传统try-catch
        # 查找并替换try-with-resources语句（支持多行）
        try_resource_pattern = r'try\s*\((.*?)\)\s*\{'
        
        def replace_try_resources(match):
            resource_decl = match.group(1).strip()
            # 将资源声明移到try外面
            return f'{resource_decl};\n        try {{'
        
        if re.search(try_resource_pattern, fixed_code, re.MULTILINE | re.DOTALL):
            fixed_code = re.sub(try_resource_pattern, replace_try_resources, fixed_code, flags=re.MULTILINE | re.DOTALL)
            # 添加提示注释（在合适的位置）
            if '// TODO:' not in fixed_code:
                # 在最后一个}之前添加注释
                lines = fixed_code.split('\n')
                for i in range(len(lines)-1, -1, -1):
                    if '}' in lines[i] and 'class' not in lines[i]:
                        lines.insert(i, '        // TODO: Add proper resource cleanup in finally block')
                        break
                fixed_code = '\n'.join(lines)
    
    return fixed_code
