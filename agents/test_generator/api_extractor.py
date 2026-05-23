"""
API提取器模块

该模块负责分析源代码，补充JSON配置文件中缺失的信息，特别是：
1. 推断类的设计意图和职责
2. 提取类的详细描述
3. 确保main_template.txt模板中的所有变量都能被填充

主要功能：
- 检查JSON信息完整性
- 从源码提取补充信息
- 推断类的意图和设计模式
"""

from typing import Dict, Any, List, Optional
import re
import os
import logging
from pathlib import Path
import json

# 配置日志
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 定义main_template.txt需要的变量列表
TEMPLATE_REQUIRED_VARS = [
    "class_name", "package", "java_version", "imports", 
    "class_description", "methods_section", 
    "method_dependencies", "fields_section", "extends_reference", "implements_reference", "instantiation_reference", 
    "generic_parameter", "class_reference", "variable_info", "constructor_signature", "init_usages"
]

def enhance_class_info(cls_info: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    """
    增强类信息，补充main_template.txt需要的变量
    
    Args:
        cls_info: 原始类信息
        project_path: 项目路径
        
    Returns:
        增强后的类信息
    """
    # 复制输入数据，避免修改原始数据
    enhanced_info = cls_info.copy()
    
    # 检查哪些模板变量缺失
    missing_vars = check_template_vars_completeness(enhanced_info)
    
    if missing_vars:
        logger.info(f"缺失模板变量: {', '.join(missing_vars)}")
        
        # 尝试从源代码文件中提取信息
        source_file = find_source_file(enhanced_info, project_path)
        if source_file:
            try:
                with open(source_file, 'r', encoding='utf-8') as f:
                    source_code = f.read()
                    enhanced_info['source_code'] = source_code
                    
                    # 从源码提取缺失的信息
                    enhanced_info = extract_missing_info(enhanced_info, source_code, missing_vars)
            except Exception as e:
                logger.error(f"读取源代码文件时出错: {e}")
    
    # 提取类的描述 - 这个字段很重要，一定要提供
    if 'description' not in enhanced_info or not enhanced_info['description']:
        enhanced_info['description'] = extract_class_description(enhanced_info)
    
    # 主动调用相关函数补充缺失字段
    from agents.test_generator.json_extractor import (
        format_methods_section,
        extract_fields_info,
        extract_method_dependencies,
        extract_extends_info,
        extract_implements_info,
        extract_instantiates_info,
        extract_generic_params_info,
        extract_references_info
    )
    
    # 格式化方法部分
    if 'methods_section' not in enhanced_info:
        try:
            enhanced_info['methods_section'] = format_methods_section(enhanced_info)
            logger.info(f"已生成methods_section")
        except Exception as e:
            logger.error(f"生成methods_section时出错: {e}")
            enhanced_info['methods_section'] = "方法部分格式化错误"
    
    # 格式化字段部分
    if 'fields_section' not in enhanced_info:
        try:
            enhanced_info['fields_section'] = extract_fields_info(enhanced_info)
            logger.info(f"已生成fields_section")
        except Exception as e:
            logger.error(f"生成fields_section时出错: {e}")
            enhanced_info['fields_section'] = "字段部分格式化错误"
    
    # 提取方法依赖关系
    if 'method_dependencies' not in enhanced_info:
        try:
            enhanced_info['method_dependencies'] = extract_method_dependencies(enhanced_info)
            logger.info(f"已生成method_dependencies")
        except Exception as e:
            logger.error(f"生成method_dependencies时出错: {e}")
            enhanced_info['method_dependencies'] = "方法依赖提取错误"
    
    # 提取其他依赖关系
    if 'extends' not in enhanced_info:
        enhanced_info['extends'] = extract_extends_info(enhanced_info)
    if 'implements' not in enhanced_info:
        enhanced_info['implements'] = extract_implements_info(enhanced_info)
    if 'instantiates' not in enhanced_info:
        enhanced_info['instantiates'] = extract_instantiates_info(enhanced_info)
    if 'generic_params' not in enhanced_info:
        enhanced_info['generic_params'] = extract_generic_params_info(enhanced_info)
    if 'references' not in enhanced_info:
        enhanced_info['references'] = extract_references_info(enhanced_info)
    
    # 确保生成template所需的所有变量
    template_vars = get_template_vars(enhanced_info, project_path)
    enhanced_info.update(template_vars)
    
    # 添加字段的同义词（确保同时有蛇形命名和驼峰命名的字段）
    field_synonyms = {
        'class_name': 'className',
        'methods_section': 'methodsSection',
        'fields_section': 'fieldsSection',
        'dependencies_section': 'dependenciesSection',
        'class_description': 'classDescription',
        'method_dependencies': 'methodDependencies'
    }
    
    for original, synonym in field_synonyms.items():
        if original in enhanced_info and synonym not in enhanced_info:
            enhanced_info[synonym] = enhanced_info[original]
        elif synonym in enhanced_info and original not in enhanced_info:
            enhanced_info[original] = enhanced_info[synonym]
    
    return enhanced_info

def check_template_vars_completeness(cls_info: Dict[str, Any]) -> List[str]:
    """
    检查类信息是否包含填充模板所需的所有变量
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        缺失变量的列表
    """
    missing_vars = []
    
    # 检查基本信息 - 支持驼峰命名和蛇形命名的混合使用
    if 'class_name' not in cls_info and 'className' not in cls_info:
        missing_vars.append('class_name')
    
    if 'package' not in cls_info:
        missing_vars.append('package')
        
    # 检查方法信息
    if ('methods' not in cls_info and 'Methods' not in cls_info) or not (cls_info.get('methods', cls_info.get('Methods', []))):
        missing_vars.append('methods')
    
    if 'methods_section' not in cls_info and 'methodsSection' not in cls_info:
        missing_vars.append('methods_section')
    
    # 检查字段信息
    if ('fields' not in cls_info and 'Fields' not in cls_info) or not (cls_info.get('fields', cls_info.get('Fields', []))):
        missing_vars.append('fields')
    
    if 'fields_section' not in cls_info and 'fieldsSection' not in cls_info:
        missing_vars.append('fields_section')
    
    # 检查依赖信息
    if 'dependencies' not in cls_info and 'Dependencies' not in cls_info:
        missing_vars.append('dependencies')
        
    # 检查描述信息
    if 'description' not in cls_info and 'javadoc' not in cls_info:
        missing_vars.append('description')
    
    # 检查方法依赖
    if 'method_dependencies' not in cls_info and 'methodDependencies' not in cls_info:
        missing_vars.append('method_dependencies')
        
    return missing_vars

def find_source_file(cls_info: Dict[str, Any], project_path: str) -> Optional[str]:
    """
    查找类的源文件
    
    Args:
        cls_info: 类信息字典
        project_path: 项目根目录路径
        
    Returns:
        源文件路径，未找到则返回None
    """
    class_name = cls_info.get('class_name', cls_info.get('className', ''))
    package_path = cls_info.get('package', '').replace('.', '/')
    
    if not class_name or not package_path:
        return None
    
    possible_paths = [
        os.path.join(project_path, 'src', 'main', 'java', package_path, f"{class_name}.java"),
        os.path.join(project_path, 'src', 'java', package_path, f"{class_name}.java"),
        os.path.join(project_path, package_path, f"{class_name}.java")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
            
    return None

def extract_missing_info(cls_info: Dict[str, Any], source_code: str, missing_vars: List[str]) -> Dict[str, Any]:
    """
    从源代码中提取缺失的信息
    
    Args:
        cls_info: 类信息字典
        source_code: 源代码
        missing_vars: 缺失的变量列表
        
    Returns:
        更新后的类信息
    """
    enhanced_info = cls_info.copy()
    class_name = enhanced_info.get('class_name', enhanced_info.get('className', ''))
    
    # 提取字段信息
    if 'fields' in missing_vars:
        fields = extract_fields_from_source(source_code)
        if fields:
            logger.info(f"从源码提取了 {len(fields)} 个字段")
            enhanced_info['fields'] = fields
    
    # 提取方法信息
    if 'methods' in missing_vars:
        methods = extract_methods_from_source(source_code)
        if methods:
            logger.info(f"从源码提取了 {len(methods)} 个方法")
            enhanced_info['methods'] = [m.get('name', '') for m in methods]
            enhanced_info['method_details'] = methods
    
    # 提取JavaDoc
    if 'description' in missing_vars:
        javadoc = extract_javadoc_from_source(source_code, class_name)
        if javadoc:
            enhanced_info['javadoc'] = javadoc
            if 'description' in javadoc:
                enhanced_info['description'] = javadoc['description']
    
    # 提取依赖关系
    if 'dependencies' in missing_vars:
        dependencies = extract_dependencies_from_source(source_code, class_name)
        if dependencies:
            enhanced_info['dependencies'] = dependencies
    
    # 提取导入信息
    if 'imports' in missing_vars:
        imports = extract_imports_from_source(source_code)
        if imports:
            enhanced_info['imports'] = imports
    
    return enhanced_info

def extract_fields_from_source(source_code: str) -> List[Dict]:
    """
    从源代码中提取真正的类字段信息（不包括方法内的局部变量）
    
    Args:
        source_code: 源代码
    
    Returns:
        字段信息列表
    """
    fields = []
    
    try:
        # 首先找到类的定义
        class_pattern = r'(public|private|protected)?\s*class\s+\w+[^{]*\{(.*)\}$'
        class_match = re.search(class_pattern, source_code, re.DOTALL)
        
        if not class_match:
            return fields
        
        class_body = class_match.group(2)
        
        # 移除所有方法体，只保留类级别的声明
        # 找到所有方法并移除它们的方法体
        method_pattern = r'((?:public|private|protected|static|final|synchronized|\s)+(?:[\w<>\[\]\.,\s]+\s+)?(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w\.,\s]+)?\s*)\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        
        # 移除方法体，保留方法签名
        clean_class_body = re.sub(method_pattern, r'\1;', class_body, flags=re.DOTALL)
        
        # 现在在清理后的类体中查找字段 - 更精确的模式
        # 匹配类级别的字段声明，必须以修饰符开头且在行首
        field_pattern = r'\n\s*((?:private|protected|public|static|final|transient|\s)+)\s+([\w<>\[\]]+(?:\s*<[^>]+>)?(?:\[\])*)\s+(\w+)\s*(?:=\s*[^;]+)?;'
        
        for match in re.finditer(field_pattern, clean_class_body):
            full_match = match.group(0)
            modifiers_str = match.group(1).strip()
            field_type = match.group(2).strip()
            field_name = match.group(3)
            
            # 更严格的过滤条件
            # 跳过明显不是字段的声明
            if field_name in ['class', 'interface', 'enum', 'if', 'for', 'while', 'return', 'new', 'this', 'super']:
                continue
            
            # 跳过看起来像方法调用或其他语句的内容  
            if '(' in field_type or ')' in field_type or '=' in field_type:
                continue
                
            # 确保字段名是有效的Java标识符
            if not re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', field_name):
                continue
                
            # 确保类型名是有效的
            if not re.match(r'^[a-zA-Z_$][\w<>\[\]\.,\s]*$', field_type):
                continue
            
            # 必须包含访问修饰符或static/final修饰符
            if not any(mod in modifiers_str for mod in ['private', 'protected', 'public', 'static', 'final']):
                continue
            
            # 解析修饰符
            modifiers = []
            if 'private' in modifiers_str:
                modifiers.append('private')
            if 'protected' in modifiers_str:
                modifiers.append('protected')
            if 'public' in modifiers_str:
                modifiers.append('public')
            if 'static' in modifiers_str:
                modifiers.append('static')
            if 'final' in modifiers_str:
                modifiers.append('final')
            
            # 如果没有明确的访问修饰符，默认为package-private (在这里显示为private)
            access_modifiers = [m for m in modifiers if m in ['private', 'protected', 'public']]
            if not access_modifiers:
                modifiers.insert(0, 'private')  # 假设package-private为private
            
            # 获取行号（近似）
            line_no = source_code[:source_code.find(match.group(0))].count('\n') + 1
            
            fields.append({
                'name': field_name,
                'type': field_type,
                'modifiers': modifiers,
                'line': line_no,
                'initialValue': None  # 在这个简化实现中不提取初始值
            })
    
    except Exception as e:
        logger.warning(f"字段提取失败: {e}")
        # 如果复杂解析失败，返回空列表（说明这个类可能没有实例字段）
        return []
    
    return fields

def extract_methods_from_source(source_code: str) -> List[Dict]:
    """
    从源代码中提取方法信息
    
    Args:
        source_code: 源代码文本
    
    Returns:
        方法信息列表
    """
    methods = []
    
    # 匹配Java方法定义的正则表达式
    method_pattern = r'(?:public|protected|private|static|\s+)+(?:[\w<>\[\]\.]+\s+)+(\w+)\s*\([^\)]*\)\s*(?:\{|throws|;)'
    
    # 查找所有匹配
    method_matches = re.finditer(method_pattern, source_code)
    for match in method_matches:
        start_pos = match.start()
        method_name = match.group(1)
        
        # 跳过构造函数和特殊名称
        if method_name == 'class' or method_name == 'if' or method_name == 'while':
            continue
        
        # 获取行号
        line_no = source_code[:start_pos].count('\n') + 1
        
        # 提取方法签名
        line = source_code.split('\n')[line_no-1] if line_no <= len(source_code.split('\n')) else ""
        
        # 计算方法体大小
        method_end = find_method_end(source_code, start_pos)
        method_lines = source_code[start_pos:method_end].count('\n') if method_end > start_pos else 0
        
        # 检查是否为getter/setter
        is_getter = method_name.startswith("get") or method_name.startswith("is") and method_lines < 5
        is_setter = method_name.startswith("set") and method_lines < 5
            
        # 提取参数
        params_match = re.search(r'\((.*)\)', line)
        params = []
        if params_match:
            param_str = params_match.group(1).strip()
            if param_str:
                param_items = param_str.split(',')
                for item in param_items:
                    parts = item.strip().split()
                    if len(parts) >= 2:
                        params.append({
                            'type': ' '.join(parts[:-1]),
                            'name': parts[-1]
                        })
                
                methods.append({
                    'name': method_name,
                    'signature': line.strip(),
                    'line': line_no,
                    'line_count': method_lines,
                    'is_getter': is_getter,
                    'is_setter': is_setter,
                    'is_getter_setter': is_getter or is_setter,
                    'params': params
                })
    
    return methods

def find_method_end(source_code: str, start_pos: int) -> int:
    """
    找到方法体的结束位置
    
    Args:
        source_code: 源代码
        start_pos: 方法开始位置
    
    Returns:
        方法结束位置
    """
    # 找到方法开始的位置，跳过可能的throws子句
    body_start = source_code.find('{', start_pos)
    if body_start < 0:
        return start_pos  # 没有找到方法体
    
    # 跟踪花括号的深度
    depth = 1
    pos = body_start + 1
    
    while pos < len(source_code) and depth > 0:
        if source_code[pos] == '{':
            depth += 1
        elif source_code[pos] == '}':
            depth -= 1
        pos += 1
    
    return pos

def extract_imports_from_source(source_code: str) -> List[str]:
    """
    从源代码中提取导入语句
    
    Args:
        source_code: 源代码
    
    Returns:
        导入语句列表
    """
    imports = []
    import_pattern = r'^import\s+(.*?);'
    
    for line in source_code.split('\n'):
        match = re.match(import_pattern, line)
        if match:
            imports.append(match.group(1))
    
    return imports

def extract_dependencies_from_source(source_code: str, class_name: str) -> List[Dict]:
    """
    从源代码中提取依赖关系
    
    Args:
        source_code: 源代码
        class_name: 类名
    
    Returns:
        依赖关系列表
    """
    dependencies = []
    
    # 提取extends关系
    extends_pattern = rf'class\s+{class_name}\s+extends\s+(\w+)'
    extends_match = re.search(extends_pattern, source_code)
    if extends_match:
        dependencies.append({
            'type': 'extends_reference',
            'name': extends_match.group(1)
        })
    
    # 提取implements关系
    implements_pattern = rf'class\s+{class_name}.*implements\s+([^{{]+)'
    implements_match = re.search(implements_pattern, source_code)
    if implements_match:
        interfaces = implements_match.group(1).split(',')
        for interface in interfaces:
            dependencies.append({
                'type': 'implements_reference',
                'name': interface.strip()
            })
    
    # 提取类实例化
    new_pattern = r'new\s+(\w+)\s*\('
    for match in re.finditer(new_pattern, source_code):
        instantiated_class = match.group(1)
        if instantiated_class != class_name:  # 避免自引用
            dependencies.append({
                'type': 'instantiation_reference',
                'name': instantiated_class
            })
    
    # 提取泛型参数
    generic_pattern = r'<\s*(\w+)(?:\s*,\s*\w+)*\s*>'
    for match in re.finditer(generic_pattern, source_code):
        type_param = match.group(1)
        if type_param not in ['T', 'E', 'K', 'V'] and not type_param.isupper():  # 排除常见的泛型标识符
            dependencies.append({
                'type': 'generic_parameter',
                'name': type_param
            })
    
    return dependencies

def get_template_vars(cls_info: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    """
    获取用于填充main_template.txt模板的所有变量
    
    Args:
        cls_info: 类信息字典
        project_path: 项目路径
    
    Returns:
        模板变量字典
    """
    # 准备模板变量
    template_vars = {}
    
    # 基本信息 - 支持驼峰命名和蛇形命名的混合使用
    class_name = cls_info.get('class_name', cls_info.get('className', 'Unknown'))
    template_vars['class_name'] = class_name
    template_vars['className'] = class_name  # 增加驼峰命名形式
    template_vars['package'] = cls_info.get('package', '')
    template_vars['java_version'] = cls_info.get('java_version', '8')
    
    # 导入
    imports = cls_info.get('imports', [])
    template_vars['imports'] = ', '.join(imports) if isinstance(imports, list) else imports
    
    # 类描述
    template_vars['class_description'] = extract_class_description(cls_info)
    
    # 方法部分
    methods_section = cls_info.get('methods_section', cls_info.get('methodsSection', 'No methods information available.'))
    template_vars['methods_section'] = methods_section
    template_vars['methodsSection'] = methods_section  # 增加驼峰命名形式
    
    # 方法依赖关系
    method_dependencies = cls_info.get('method_dependencies', cls_info.get('methodDependencies', 'No method call information available.'))
    template_vars['method_dependencies'] = method_dependencies
    template_vars['methodDependencies'] = method_dependencies  # 增加驼峰命名形式
    
    # 字段信息
    fields_section = cls_info.get('fields_section', cls_info.get('fieldsSection', 'No fields information available.'))
    template_vars['fields_section'] = fields_section
    template_vars['fieldsSection'] = fields_section  # 增加驼峰命名形式
    
    # 依赖关系 - 修改字段名以匹配模板中的占位符
    template_vars['extends_reference'] = 'None'
    template_vars['implements_reference'] = 'None'
    template_vars['instantiation_reference'] = 'None'
    template_vars['generic_parameter'] = 'None'
    template_vars['class_reference'] = 'None'
    
    # 从dependencies中提取各类依赖
    dependencies = cls_info.get('dependencies', cls_info.get('Dependencies', []))
    extends_list, implements_list, instantiates_list = [], [], []
    generic_params_list, references_list = [], []
    
    for dep in dependencies:
        if isinstance(dep, dict):
            dep_type = dep.get('type', '')
            dep_name = dep.get('name', '')
            
            if dep_type == 'extends_reference':
                extends_list.append(dep_name)
            elif dep_type == 'implements_reference':
                implements_list.append(dep_name)
            elif dep_type == 'instantiation_reference':
                instantiates_list.append(dep_name)
            elif dep_type == 'generic_parameter':
                generic_params_list.append(dep_name)
        else:
                references_list.append(dep_name)
    
    if extends_list:
        template_vars['extends_reference'] = ', '.join(extends_list)
    if implements_list:
        template_vars['implements_reference'] = ', '.join(implements_list)
    if instantiates_list:
        template_vars['instantiation_reference'] = ', '.join(instantiates_list)
    if generic_params_list:
        template_vars['generic_parameter'] = ', '.join(generic_params_list)
    if references_list:
        template_vars['class_reference'] = ', '.join(references_list)
    
    # 变量引用
    variable_info = cls_info.get('variable_info', cls_info.get('variableInfo', 'No variable information available.'))
    template_vars['variable_info'] = variable_info
    template_vars['variableInfo'] = variable_info  # 增加驼峰命名形式
    
    # 构造函数信息
    constructor_info = cls_info.get('constructor_info', cls_info.get('constructorInfo', ''))
    if constructor_info:
        parts = constructor_info.split("类中使用了以下对象初始化:")
        template_vars['constructor_signature'] = parts[0].strip()
        template_vars['init_usages'] = parts[1].strip() if len(parts) > 1 else 'No initialization information.'
    else:
        template_vars['constructor_signature'] = 'No constructor information available.'
        template_vars['init_usages'] = 'No initialization information available.'
    
    return template_vars

def extract_class_name(source_code: str, file_path: str) -> str:
    """
    从源代码中提取类名
    
    Args:
        source_code: 源代码
        file_path: 文件路径(用于回退)
        
    Returns:
        类名
    """
    # 尝试从类定义中提取
    class_pattern = r'(public|private|protected)?\s+(?:abstract|final)?\s+class\s+(\w+)'
    matches = re.search(class_pattern, source_code)
    
    if matches:
        return matches.group(2)
    
    # 回退：从文件名提取
    filename = os.path.basename(file_path)
    if filename.endswith('.java'):
        return filename[:-5]  # 移除.java后缀
        
    return ""
    
def extract_package(source_code: str) -> str:
    """
    从源代码中提取包名
    
    Args:
        source_code: 源代码
        
    Returns:
        包名，未找到则返回空字符串
    """
    package_pattern = r'package\s+([\w\.]+)\s*;'
    matches = re.search(package_pattern, source_code)
    
    if matches:
        return matches.group(1)
        
    return ""  # 返回空字符串而非默认包名  

# ============= 类描述提取相关函数 =============

def extract_class_description(cls_info: Dict[str, Any]) -> str:
    """
    提取类的描述信息
    
    整合类名、JavaDoc、方法名和类结构等多个信息源，
    生成简洁的类描述。
    
    Args:
        cls_info: 类信息字典
    
    Returns:
        格式化的类描述文本，控制在合理长度
    """
    # 首先尝试获取现有描述
    existing_desc = (cls_info.get('description', '') or
                    cls_info.get('Description', '') or
                    cls_info.get('javadoc', {}).get('description', '') or
                    cls_info.get('javadoc', {}).get('summary', '') or
                    cls_info.get('class_description', ''))
    
    # 如果有现有描述，优先使用它
    if existing_desc and isinstance(existing_desc, str) and len(existing_desc.strip()) > 10:
        # 清理描述文本，去除多余空白
        cleaned_desc = ' '.join(existing_desc.strip().split())
        # 如果描述太长，智能截取最有价值的内容
        if len(cleaned_desc) > 200:
            # 优先提取第一句完整描述
            first_sentence = _extract_first_meaningful_sentence(cleaned_desc)
            if first_sentence and len(first_sentence) <= 200:
                cleaned_desc = first_sentence
            else:
                # 智能截取关键部分
                cleaned_desc = _smart_truncate_description(cleaned_desc, 200)
        return cleaned_desc
    
    # 如果没有现有描述，尝试从源代码提取
    source_code = cls_info.get('source_code', '')
    if source_code:
        class_name = cls_info.get('class_name', cls_info.get('className', ''))
        javadoc = extract_javadoc_from_source(source_code, class_name)
        if javadoc and 'description' in javadoc and javadoc['description'].strip():
            cleaned_desc = ' '.join(javadoc['description'].strip().split())
            # 同样应用智能截取
            if len(cleaned_desc) > 200:
                first_sentence = _extract_first_meaningful_sentence(cleaned_desc)
                if first_sentence and len(first_sentence) <= 200:
                    cleaned_desc = first_sentence
                else:
                    cleaned_desc = _smart_truncate_description(cleaned_desc, 200)
            return cleaned_desc
    
    # 如果仍然没有描述，根据类名推断
    class_name = cls_info.get('class_name', cls_info.get('className', ''))
    package = cls_info.get('package', '')
    
    # 基于类名的简单推断
    if class_name:
        if any(suffix in class_name for suffix in ['DTO', 'Bean', 'Model', 'Entity']):
            base_name = ''.join(c for c in class_name if not c.isdigit())
            for suffix in ['DTO', 'Bean', 'Model', 'Entity']:
                base_name = base_name.replace(suffix, '')
            return f"A data class that represents {base_name} information."
        elif 'Service' in class_name:
            base_name = class_name.replace('Service', '')
            return f"A service class that provides {base_name} operations."
        elif 'Controller' in class_name:
            base_name = class_name.replace('Controller', '')
            return f"A controller class that handles {base_name} related requests."
        elif 'Util' in class_name or 'Utils' in class_name:
            base_name = class_name.replace('Util', '').replace('Utils', '')
            return f"A utility class that provides helper functions for {base_name} operations."
        elif 'Factory' in class_name:
            base_name = class_name.replace('Factory', '')
            return f"A factory class that creates {base_name} instances."
        elif 'Manager' in class_name:
            base_name = class_name.replace('Manager', '')
            return f"A manager class that handles {base_name} operations."
        elif 'Handler' in class_name:
            base_name = class_name.replace('Handler', '')
            return f"A handler class that processes {base_name} operations."
    
    # 最后的默认描述
    if package:
        return f"A Java class named {class_name} in the {package} package."
    else:
        return f"A Java class named {class_name}."

def extract_javadoc_from_source(source_code: str, class_name: str) -> Dict:
    """
    从源代码中提取JavaDoc注释
    
    Args:
        source_code: 源代码
        class_name: 类名
        
    Returns:
        JavaDoc信息字典
    """
    javadoc = {}
    
    # 匹配类的JavaDoc注释
    class_pattern = rf'/\*\*([\s\S]*?)\*/\s*(?:public\s+)?class\s+{class_name}'
    class_match = re.search(class_pattern, source_code)
    
    if class_match:
        doc = class_match.group(1)
        
        # 提取描述
        desc_match = re.search(r'[\s\*]*([^@\s].+(?:\n\s*\*\s*[^@].+)*)', doc)
        if desc_match:
            javadoc['description'] = clean_javadoc_text(desc_match.group(1))
        
        # 提取@标签
        for tag in ['@author', '@version', '@since', '@deprecated', '@see']:
            tag_matches = re.findall(rf'{tag}\s+([^\n@]+)', doc)
            if tag_matches:
                key = tag[1:]  # 移除@符号
                javadoc[key] = [clean_javadoc_text(m) for m in tag_matches]
    
    return javadoc

def clean_javadoc_text(text: str) -> str:
    """
    清理JavaDoc文本
    
    Args:
        text: JavaDoc文本
        
    Returns:
        清理后的文本
    """
    # 移除每行开头的*
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # 移除行首的*和空格
        cleaned = re.sub(r'^\s*\*\s*', '', line)
        if cleaned.strip():
            cleaned_lines.append(cleaned.strip())
    
    return ' '.join(cleaned_lines)

def _extract_first_meaningful_sentence(text: str) -> str:
    """提取第一句有意义的描述"""
    # 按句号分割，找到第一句完整的句子
    sentences = text.split('.')
    if sentences and len(sentences[0].strip()) > 10:
        first_sentence = sentences[0].strip()
        # 确保这是一个有意义的句子（包含动词或名词）
        if any(word in first_sentence.lower() for word in ['is', 'are', 'was', 'were', 'has', 'have', 'provides', 'represents', 'implements', 'extends', 'class', 'interface']):
            return first_sentence + '.'
    return ""

def _smart_truncate_description(text: str, max_length: int) -> str:
    """智能截取描述，保留最有价值的信息"""
    if len(text) <= max_length:
        return text
    
    # 尝试在句号处截取
    cutoff_point = text[:max_length].rfind('.')
    if cutoff_point > max_length * 0.6:  # 确保至少保留60%的内容
        return text[:cutoff_point + 1]
    
    # 尝试在逗号处截取
    cutoff_point = text[:max_length].rfind(',')
    if cutoff_point > max_length * 0.6:
        return text[:cutoff_point] + '.'
    
    # 尝试在空格处截取
    cutoff_point = text[:max_length].rfind(' ')
    if cutoff_point > max_length * 0.6:
        return text[:cutoff_point] + '...'
    
    # 最后直接截取
    return text[:max_length - 3] + "..."

# ============= 类描述提取相关函数结束 ============= 