"""
JSON提取器模块

该模块负责从项目中提取JSON配置信息，包括：
1. 定位JSON配置文件
2. 从JSON文件中读取类信息
3. 解析JSON数据结构
4. 必要时从源码提取补充信息

主要功能：
- 查找valid_classes.json文件
- 从JSON中提取类信息
- 解析不同格式的JSON数据
- 整合源码分析结果
"""

from typing import Dict, Any, List, Union, Optional, Tuple
import os
import json
import logging
import re
from pathlib import Path

# 从api_extractor导入必要的函数
try:
    from api_extractor import (
        extract_class_description, 
        extract_javadoc_from_source,
        extract_imports_from_source,
        find_source_file,
        extract_fields_from_source,
        extract_methods_from_source,
        extract_dependencies_from_source,
        enhance_class_info,
        check_template_vars_completeness,
        clean_javadoc_text
    )
except ImportError:
    try:
        from .api_extractor import (
            extract_class_description, 
            extract_javadoc_from_source,
            extract_imports_from_source,
            find_source_file,
            extract_fields_from_source,
            extract_methods_from_source,
            extract_dependencies_from_source,
            enhance_class_info,
            check_template_vars_completeness,
            clean_javadoc_text
        )
    except ImportError:
        # 如果无法导入，定义一些简单的替代函数
        def extract_class_description(cls_info):
            return cls_info.get('description', 'No description available')
            
        def extract_javadoc_from_source(source_code, class_name):
            return {}
            
        def extract_imports_from_source(source_code):
            return []
            
        def find_source_file(cls_info, project_path):
            return None
            
        def extract_fields_from_source(source_code):
            return []
            
        def extract_methods_from_source(source_code):
            return []
            
        def extract_dependencies_from_source(source_code, class_name):
            return []
            
        def enhance_class_info(cls_info, project_path):
            return cls_info
            
        def check_template_vars_completeness(cls_info):
            return []
            
        def clean_javadoc_text(text):
            return text

# 导入method_analyzer以进行方法复杂度分析和测试用例数量计算
try:
    # 尝试绝对导入
    import agents.test_generator.method_analyzer as method_analyzer
    
    # 导入需要的函数
    calculate_test_distribution = method_analyzer.calculate_test_distribution
    format_test_distribution = method_analyzer.format_test_distribution
    get_method_complexity_description = method_analyzer.get_method_complexity_description
    prioritize_methods = method_analyzer.prioritize_methods
except ImportError:
    try:
        # 尝试相对导入
        from . import method_analyzer
        
        # 导入需要的函数
        calculate_test_distribution = method_analyzer.calculate_test_distribution
        format_test_distribution = method_analyzer.format_test_distribution
        get_method_complexity_description = method_analyzer.get_method_complexity_description
        prioritize_methods = method_analyzer.prioritize_methods
    except ImportError as e:
        # 如果无法导入，定义一些简单的替代函数
        def calculate_test_distribution(methods):
            return {"total_min": 0, "total_max": 0, "methods": {}}
            
        def format_test_distribution(test_distribution, methods):
            return "无法生成测试分布信息"
            
        def get_method_complexity_description(complexity):
            return "未知复杂度"
            
        def prioritize_methods(methods):
            return methods

# 配置日志
logger = logging.getLogger(__name__)

# 记录导入状态
if 'method_analyzer' in globals():
    logger.info("成功导入method_analyzer模块")
elif hasattr(calculate_test_distribution, '__module__') and calculate_test_distribution.__module__ == 'agents.test_generator.method_analyzer':
    logger.info("成功导入method_analyzer模块（绝对导入）")
elif hasattr(calculate_test_distribution, '__module__') and calculate_test_distribution.__module__ == '__main__':
    logger.info("成功导入method_analyzer模块（相对导入）")
else:
    logger.warning("使用替代的method_analyzer函数")

def find_all_repos() -> List[Tuple[str, str, str]]:
    """
    查找所有包含valid_classes.json的项目
    
    Returns:
        项目列表，每个项目为(项目名, 项目路径, json文件路径)的元组
    """
    # 默认在当前目录的上级目录的dataset文件夹中查找
    dataset_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")
    if not os.path.exists(dataset_root):
        # 尝试在当前目录下查找dataset文件夹
        dataset_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
        if not os.path.exists(dataset_root):
            # 最后尝试在当前工作目录下查找
            dataset_root = os.path.join(os.getcwd(), "dataset")
            
    logger.info(f"在 {dataset_root} 中查找项目...")
    
    repos = []
    if not os.path.exists(dataset_root):
        logger.warning(f"找不到dataset目录: {dataset_root}")
        return repos
    
    # 遍历dataset目录下的所有文件夹
    for project_name in os.listdir(dataset_root):
        project_path = os.path.join(dataset_root, project_name)
        if not os.path.isdir(project_path):
            continue
            
        # 使用find_json_config查找valid_classes.json文件
        json_path = find_json_config(project_path)
        if json_path:
            repos.append((project_name, project_path, json_path))
            
    logger.info(f"找到 {len(repos)} 个项目")
    return repos


def find_json_config(project_path: str, json_path: Optional[str] = None) -> Optional[str]:
    """
    查找valid_classes.json配置文件
    
    Args:
        project_path: 项目根目录路径
        json_path: 可选的指定JSON文件路径
        
    Returns:
        找到的JSON文件路径，未找到则返回None
    """
    if json_path and os.path.exists(json_path):
        return json_path
        
    # 尝试多种可能的路径
    possible_paths = [
        os.path.join(os.path.dirname(project_path), "valid_classes.json"),
        os.path.join(project_path, "valid_classes.json"),
        os.path.join(project_path, "dataset", "valid_classes.json"),
        os.path.join(os.path.dirname(project_path), "dataset", "valid_classes.json")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"找到valid_classes.json文件: {path}")
            return path
            
    return None

def extract_valid_classes(project_path: str, json_path: str) -> List[Dict[str, Any]]:
    """
    从valid_classes.json文件中提取有效类信息
    
    Args:
        project_path: 项目根目录路径
        json_path: JSON文件路径
        
    Returns:
        有效类列表
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_content = f.read()
            
        # 解析JSON
        try:
            valid_classes_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return []
        
        # 提取类列表
        valid_classes = extract_classes_from_json(valid_classes_data)
        
        # 处理方法优先级
        for cls_info in valid_classes:
            if isinstance(cls_info, dict):
                # 确保获取正确的方法列表，兼容不同格式
                methods = cls_info.get('methods', [])
                if methods:
                    try:
                        cls_info['methods'] = prioritize_methods(methods)
                    except Exception as e:
                        class_name = cls_info.get('class_name', cls_info.get('className', '未知'))
                        logger.warning(f"处理类 {class_name} 的方法时出错: {e}")
                    
        return valid_classes
        
    except Exception as e:
        logger.error(f"读取或处理valid_classes.json时出错: {e}")
        return []

def extract_classes_from_json(data: Union[List, Dict]) -> List[Dict[str, Any]]:
    """
    从JSON数据中提取类信息
    
    Args:
        data: JSON解析后的数据
        
    Returns:
        类信息列表
    """
    valid_classes = []
    
    if isinstance(data, list):
        valid_classes = [cls for cls in data if isinstance(cls, dict)]
    elif isinstance(data, dict):
        if "classes" in data:
            valid_classes = [cls for cls in data["classes"] if isinstance(cls, dict)]
        else:
            valid_classes = [data]
    elif isinstance(data, str):
        try:
            second_parse = json.loads(data)
            if isinstance(second_parse, list):
                valid_classes = [cls for cls in second_parse if isinstance(cls, dict)]
            elif isinstance(second_parse, dict):
                if "classes" in second_parse:
                    valid_classes = [cls for cls in second_parse["classes"] if isinstance(cls, dict)]
                else:
                    valid_classes = [second_parse]
        except:
            logger.error("无法解析JSON内容为有效的类信息")
            return []
    
    return valid_classes

def extract_class_from_json(json_path: str, class_name: str) -> Optional[Dict[str, Any]]:
    """
    从JSON文件中提取目标类的信息
    
    Args:
        json_path: JSON文件路径
        class_name: 目标类名
        
    Returns:
        类信息字典，未找到则返回None
    """
    try:
        logger.info(f"从JSON文件 {json_path} 中查找类 {class_name}")
        with open(json_path, 'r', encoding='utf-8') as f:
            all_classes_data = json.load(f)
            
        # 从不同格式中查找类
        if isinstance(all_classes_data, list):
            logger.info(f"JSON数据是列表格式，包含 {len(all_classes_data)} 个类")
            for cls in all_classes_data:
                if not isinstance(cls, dict):
                    continue
                
                # 检查类名是否匹配
                cls_name = cls.get('className', cls.get('class_name', ''))
                if cls_name == class_name:
                    logger.info(f"在JSON中找到类 {class_name}")
                    
                    # 确保方法信息完整
                    _enhance_method_info(cls)
                    return cls
                
                # 通过路径匹配
                if 'path' in cls:
                    path = cls.get('path', '')
                    normalized_path = path.replace('\\\\', '/')
                    if f"/{class_name}.java" in normalized_path or f"\\{class_name}.java" in path:
                        logger.info(f"通过路径 {path} 匹配到类 {class_name}")
                        
                        # 确保方法信息完整
                        _enhance_method_info(cls)
                        return cls
            
            # 如果遍历完所有类还没有找到匹配，返回None
            logger.warning(f"在JSON列表中找不到类 {class_name}")
            
        elif isinstance(all_classes_data, dict):
            logger.info("JSON数据是字典格式")
            if "classes" in all_classes_data:
                classes = all_classes_data["classes"]
                logger.info(f"字典中包含classes字段，有 {len(classes)} 个类")
                for cls in classes:
                    if not isinstance(cls, dict):
                        continue
                    
                    # 检查类名是否匹配
                    cls_name = cls.get('className', cls.get('class_name', ''))
                    if cls_name == class_name:
                        logger.info(f"在JSON中找到类 {class_name}")
                        
                        # 确保方法信息完整
                        _enhance_method_info(cls)
                        return cls
                    
                    # 通过路径匹配
                    if 'path' in cls:
                        path = cls.get('path', '')
                        normalized_path = path.replace('\\\\', '/')
                        if f"/{class_name}.java" in normalized_path or f"\\{class_name}.java" in path:
                            logger.info(f"通过路径 {path} 匹配到类 {class_name}")
                            
                            # 确保方法信息完整
                            _enhance_method_info(cls)
                            return cls
                
                # 如果遍历完所有类还没有找到匹配，返回None
                logger.warning(f"在JSON字典的classes字段中找不到类 {class_name}")
                
            elif all_classes_data.get('className') == class_name or all_classes_data.get('class_name') == class_name:
                logger.info(f"JSON本身就是类 {class_name} 的信息")
                
                # 确保方法信息完整
                _enhance_method_info(all_classes_data)
                return all_classes_data
            else:
                logger.warning(f"JSON字典不包含类 {class_name}")
        else:
            logger.error(f"JSON格式不正确，无法查找类 {class_name}")
        
        # 如果没有找到匹配，返回None
        logger.error(f"在JSON中找不到类 {class_name}")
        return None
                
    except Exception as e:
        logger.error(f"读取类 {class_name} 信息时出错: {e}")
        return None

def _enhance_method_info(cls_info: Dict[str, Any]) -> None:
    """
    增强类信息中的方法数据，确保methods字段中的方法含有必要的可见性信息
    
    Args:
        cls_info: 类信息字典
    """
    if not isinstance(cls_info, dict):
        return
    
    methods = cls_info.get('methods', [])
    
    # 如果methods为空，无需处理
    if not methods:
        return
        
    # 仅处理没有可见性信息的方法
    for i, method in enumerate(methods):
        if isinstance(method, str) and not any(method.strip().startswith(vis) for vis in ["public", "protected", "private", "package-private"]):
            # 默认为public，除非方法名明显是私有的（以_开头）
            visibility = "private" if method.strip().split('(')[0].endswith('_') or method.strip().split('(')[0].startswith('_') else "public"
            
            # 使用method_details中的信息（如果存在）
            method_details = cls_info.get('method_details', [])
            if method_details:
                method_name = method.split('(')[0].strip()
                for detail in method_details:
                    if isinstance(detail, dict) and detail.get('name') == method_name:
                        visibility = detail.get('visibility', visibility)
                        break
            
            # 更新方法字符串，添加可见性信息
            methods[i] = f"{visibility} {method}"

def extract_comprehensive_class_info(cls_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    从类信息中提取全面的信息，并按照指定格式组织
    
    Args:
        cls_info: 原始类信息字典
        
    Returns:
        格式化后的全面类信息
    """
    # 首先使用api_extractor.enhance_class_info增强类信息
    # 注意这里假设项目路径为"."，因为我们只需要从类信息本身提取更多信息
    enhanced_info = enhance_class_info(cls_info, ".")
    
    # 添加JSON提取器特有的字段
    result = enhanced_info.copy()
    
    # 字段映射转换：处理field_refs -> fields的转换
    if 'field_refs' in cls_info and 'fields' not in cls_info:
        field_refs = cls_info.get('field_refs', [])
        # 将field_refs转换为fields格式
        fields = []
        for field_ref in field_refs:
            field = {
                'name': field_ref.get('name', ''),
                'type': field_ref.get('type', ''),
                'modifiers': ['static'] if field_ref.get('is_static', False) else []
            }
            fields.append(field)
        result['fields'] = fields
    
    # 格式化方法部分
    if 'methods_section' not in result:
        result['methods_section'] = format_methods_section(cls_info)
    
    # 格式化字段部分
    if 'fields_section' not in result:
        result['fields_section'] = extract_fields_info(cls_info)
    
    # 提取方法依赖关系
    if 'method_dependencies' not in result:
        result['method_dependencies'] = extract_method_dependencies(cls_info)
    
    # 提取描述信息
    if 'description' not in result and 'class_description' not in result:
        result['description'] = extract_class_description(cls_info)
        result['class_description'] = result['description']  # 确保与模板中的占位符一致
    
    # 补充其他可能缺少的字段
    field_mappings = {
        'dependencies_section': lambda: extract_dependencies_info(cls_info) if 'dependencies' in cls_info else "",
        'variable_info': lambda: extract_variable_info(cls_info),
        'constructor_info': lambda: extract_constructor_info(cls_info),
        # 修改字段名以匹配模板中的占位符
        'extends_reference': lambda: extract_extends_info(cls_info),
        'implements_reference': lambda: extract_implements_info(cls_info),
        'instantiation_reference': lambda: extract_instantiates_info(cls_info),
        'generic_parameter': lambda: extract_generic_params_info(cls_info),
        'class_reference': lambda: extract_references_info(cls_info)
    }
    
    # 只添加缺失的字段
    for field_name, field_func in field_mappings.items():
        if field_name not in result:
            result[field_name] = field_func()
    
    # 计算测试分布
    methods = cls_info.get('methods', [])
    source_code = cls_info.get('source_code', '')
    
    try:
        if methods:
            test_distribution = calculate_test_distribution(methods)
            if test_distribution:
                result['test_distribution'] = test_distribution
    except Exception as e:
        logger.error(f"生成测试分布信息时出错: {e}")
    
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
        if original in result and synonym not in result:
            result[synonym] = result[original]
        elif synonym in result and original not in result:
            result[original] = result[synonym]
    
    return result

def extract_extends_info(cls_info: Dict[str, Any]) -> str:
    """提取继承信息"""
    dependencies = cls_info.get('dependencies', [])
    extends_list = []
    
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get('type') == 'extends_reference':
            extends_list.append(dep.get('name', ''))
    
    return ', '.join(extends_list) if extends_list else 'None'

def extract_implements_info(cls_info: Dict[str, Any]) -> str:
    """提取接口实现信息"""
    dependencies = cls_info.get('dependencies', [])
    implements_list = []
    
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get('type') == 'implements_reference':
            implements_list.append(dep.get('name', ''))
    
    return ', '.join(implements_list) if implements_list else 'None'

def extract_instantiates_info(cls_info: Dict[str, Any]) -> str:
    """提取实例化信息"""
    dependencies = cls_info.get('dependencies', [])
    instantiates_list = []
    
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get('type') == 'instantiation_reference':
            instantiates_list.append(dep.get('name', ''))
    
    return ', '.join(instantiates_list) if instantiates_list else 'None'

def extract_generic_params_info(cls_info: Dict[str, Any]) -> str:
    """提取泛型参数信息"""
    dependencies = cls_info.get('dependencies', [])
    generic_params_list = []
    
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get('type') == 'generic_parameter':
            generic_params_list.append(dep.get('name', ''))
    
    return ', '.join(generic_params_list) if generic_params_list else 'None'

def extract_references_info(cls_info: Dict[str, Any]) -> str:
    """提取引用信息"""
    dependencies = cls_info.get('dependencies', [])
    references_list = []
    
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get('type') == 'class_reference':
            references_list.append(dep.get('name', ''))
    
    return ', '.join(references_list) if references_list else 'None'

def format_methods_section(cls_info: Dict[str, Any]) -> str:
    """
    格式化方法部分，按优先级排序，并添加测试用例建议
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化后的方法部分
    """
    # 添加类型检查
    if not isinstance(cls_info, dict):
        logger.error(f"cls_info不是字典类型，而是 {type(cls_info)}")
        return "错误: 无法格式化方法部分，传入的不是字典"
    
    # 直接使用methods字段，valid_classes.json中已经包含了足够的信息
    methods = cls_info.get('methods', [])
    
    # 如果没有methods，无法格式化
    if not methods:
        return ""
    
    # 确保methods是列表
    if not isinstance(methods, list):
        if isinstance(methods, str):
            methods = [methods]
        else:
            logger.warning(f"methods不是列表类型，而是 {type(methods)}")
            return ""
    
    # 使用method_analyzer模块中的功能进行处理
    try:
        # 方法优先级排序
        prioritized_methods = prioritize_methods(methods)
        
        # 计算测试分布 - 不再传递source_code参数
        test_distribution = calculate_test_distribution(prioritized_methods)
        
        # 格式化测试分布
        return format_test_distribution(test_distribution, prioritized_methods)
    except Exception as e:
        logger.warning(f"格式化方法部分时出错: {e}")
        import traceback
        traceback.print_exc()
        return "无法生成方法测试分布信息"

def extract_method_dependencies(cls_info: Dict[str, Any]) -> str:
    """
    提取方法调用层次结构
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化的方法调用层次结构，使用 "caller → method" 格式
        忽略无法确定调用者的方法调用
    """
    # 添加类型检查
    if not isinstance(cls_info, dict):
        logger.error(f"cls_info不是字典类型，而是 {type(cls_info)}")
        return "错误: 无法提取方法依赖，传入的不是字典"
    
    method_calls = cls_info.get('method_calls', [])
    if not method_calls:
        return "未检测到方法调用关系"
    
    # 确保method_calls是列表
    if not isinstance(method_calls, list):
        logger.warning(f"method_calls不是列表类型，而是 {type(method_calls)}")
        return "方法调用数据格式错误"
    
    # 直接构建调用格式列表
    call_list = []
    
    # 从method_calls中提取调用关系
    for call in method_calls:
        if not isinstance(call, dict):
            continue
            
        # 获取被调用方法
        method = call.get('method', '')
        if not method:
            continue
            
        # 获取调用者
        caller = call.get('caller', '<unknown>')
        
        # 忽略无法确定调用者的方法调用
        if caller == '<unknown>':
            continue
            
        # 获取对象
        obj = call.get('object', '')
        
        # 构建方法调用全名
        method_full = f"{obj}.{method}" if obj else method
        
        # 获取参数列表
        args = call.get('arguments', [])
        args_str = ', '.join([str(arg) for arg in args])
        
        # 构建完整方法调用，包括参数
        if args_str:
            method_call = f"{method_full}({args_str})"
        else:
            method_call = f"{method_full}()"
            
        # 使用called_full如果存在
        if 'called_full' in call:
            called_full = call.get('called_full')
            if args_str:
                method_call = f"{called_full}({args_str})"
            else:
                method_call = f"{called_full}()"
        
        # 添加到调用列表
        call_entry = f"{caller} → {method_call}"
        call_list.append(call_entry)
    
    # 按照调用者分组
    call_by_caller = {}
    for entry in call_list:
        caller = entry.split(' → ')[0]
        if caller not in call_by_caller:
            call_by_caller[caller] = []
        call_by_caller[caller].append(entry)
    
    # 按分组组织输出
    sections = []
    
    # 先处理特殊调用者（除了<unknown>）
    special_callers = ['<static_initializer>', '<field_initializer>']
    for caller in special_callers:
        if caller in call_by_caller:
            sections.extend(call_by_caller[caller])
            del call_by_caller[caller]
    
    # 然后处理普通方法调用者
    for caller, calls in sorted(call_by_caller.items()):
        sections.extend(calls)
    
    # 如果没有调用关系，返回提示信息
    if not sections:
        return "未检测到方法调用关系"
    
    return "\n".join(sections)

def extract_fields_info(cls_info: Dict[str, Any]) -> str:
    """
    提取真正的类字段信息（区分类字段和方法内局部变量）
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化的类字段信息，只包含真正的类级别字段
    """
    # 首先尝试使用field_refs（已过滤的字段信息）
    field_refs = cls_info.get('field_refs', [])
    
    # 如果field_refs为空，尝试从源码提取真正的字段
    if not field_refs:
        source_code = cls_info.get('code', '')
        if source_code:
            try:
                from .api_extractor import extract_fields_from_source
                field_refs = extract_fields_from_source(source_code)
            except ImportError:
                from api_extractor import extract_fields_from_source
                field_refs = extract_fields_from_source(source_code)
    
    # 如果仍然没有字段信息，尝试从variable_refs中过滤出真正的类字段
    if not field_refs:
        variable_refs = cls_info.get('variable_refs', [])
        # 过滤掉明显的方法参数和局部变量
        field_refs = []
        for var in variable_refs:
            # 跳过方法参数
            if var.get('is_parameter', False):
                continue
            # 跳过循环变量
            if var.get('is_loop_var', False) or var.get('is_foreach_var', False):
                continue
            # 跳过资源变量
            if var.get('is_resource', False):
                continue
            # 跳过明显的局部变量名称
            var_name = var.get('name', '')
            if var_name in ['def', 'size', 'trs', 'preds', 'i', 'j', 'k', 'index', 'count', 'result', 'temp', 'tmp']:
                continue
            # 跳过明显在方法内声明的变量（通过行号或上下文判断）
            context = var.get('context', '')
            if any(pattern in context.lower() for pattern in ['final ', 'for (', 'while (', 'if (', 'catch (', '= new ', 'return ']):
                continue
            field_refs.append(var)
    
    if not field_refs:
        return "该类没有实例字段"
    
    lines = []
    for field in field_refs:
        field_name = field.get('name', '')
        field_type = field.get('type', '')
        
        # 处理修饰符信息
        modifiers = field.get('modifiers', [])
        is_static = False
        visibility = 'private'  # 默认
        
        if isinstance(modifiers, list):
            for mod in modifiers:
                if mod in ['private', 'protected', 'public']:
                    visibility = mod
                elif mod == 'static':
                    is_static = True
        elif isinstance(modifiers, str):
            if 'static' in modifiers:
                is_static = True
            for vis in ['public', 'protected', 'private']:
                if vis in modifiers:
                    visibility = vis
                    break
        
        # 检查是否有其他方式获取可见性信息
        if 'access_modifier' in field:
            visibility = field.get('access_modifier', visibility)
        if 'is_static' in field:
            is_static = field.get('is_static', is_static)
        if 'visibility' in field:
            visibility = field.get('visibility', visibility)
        
        # 构建修饰符字符串
        modifier_parts = []
        modifier_parts.append(visibility)
        if is_static:
            modifier_parts.append('static')
        
        modifiers_str = ' '.join(modifier_parts)
        lines.append(f"{modifiers_str} {field_type} {field_name}")
    
    return "\n".join(lines)

def extract_dependencies_info(cls_info: Dict[str, Any]) -> str:
    """
    提取依赖关系信息
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化的依赖信息
    """
    # 添加类型检查
    if not isinstance(cls_info, dict):
        logger.error(f"cls_info不是字典类型，而是 {type(cls_info)}")
        return "错误: 无法提取依赖，传入的不是字典"
    
    # 确保能获取到dependencies字段
    dependencies = cls_info.get('dependencies', [])
    if not dependencies:
        return "未找到依赖关系信息"
    
    # 确保dependencies是列表
    if not isinstance(dependencies, list):
        logger.warning(f"dependencies不是列表类型，而是 {type(dependencies)}")
        return "依赖关系格式错误"
    
    # 按依赖类型分类
    dep_by_type = {
        "extends_reference": [],
        "implements_reference": [],
        "instantiation_reference": [],
        "generic_parameter": [],
        "class_reference": [],
        "import": []
    }
    
    # 遍历所有依赖
    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
            
        # 获取依赖类型和名称
        dep_type = dep.get('type', '')
        dep_name = dep.get('name', '')
        context = dep.get('context', '')
        
        # 如果没有类型或名称，跳过
        if not dep_name:
            continue
            
        # 根据类型分类
        if dep_type in dep_by_type:
            entry = f"{dep_name}"
            if context:
                # 提取上下文中的相关代码片段
                context_summary = re.sub(r'\s+', ' ', context).strip()[:100]
                if len(context) > 100:
                    context_summary += "..."
                # 只在详细模式下添加上下文
                # entry += f"：：{context_summary}"
            
            dep_by_type[dep_type].append(entry)
    
    # 格式化输出
    lines = []
    
    # 添加继承信息
    if dep_by_type["extends_reference"]:
        lines.append(f"- Extends: {', '.join(dep_by_type['extends_reference'])}")
        
    # 添加接口实现信息
    if dep_by_type["implements_reference"]:
        lines.append(f"- Implements: {', '.join(dep_by_type['implements_reference'])}")
        
    # 添加实例化信息
    if dep_by_type["instantiation_reference"]:
        lines.append(f"- Instantiates: {', '.join(dep_by_type['instantiation_reference'])}")
        
    # 添加泛型参数信息
    if dep_by_type["generic_parameter"]:
        lines.append(f"- Uses as generic parameter: {', '.join(dep_by_type['generic_parameter'])}")
        
    # 添加类引用信息
    if dep_by_type["class_reference"]:
        lines.append(f"- References: {', '.join(dep_by_type['class_reference'])}")
        
    # 添加导入信息
    if dep_by_type["import"]:
        lines.append(f"- Imports: {', '.join(dep_by_type['import'])}")
    
    # 如果没有任何依赖信息，返回一个默认消息
    if not lines:
        return "无依赖关系"
        
    return "\n".join(lines)

def extract_variable_info(cls_info: Dict[str, Any]) -> str:
    """
    提取真正的类字段信息（区分类字段和方法内局部变量）
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化的类字段描述，只包含真正的类级别字段
    """
    # 首先尝试使用field_refs（已过滤的字段信息）
    field_refs = cls_info.get('field_refs', [])
    
    # 如果field_refs为空，尝试从源码提取真正的字段
    if not field_refs:
        source_code = cls_info.get('code', '')
        if source_code:
            try:
                from .api_extractor import extract_fields_from_source
                field_refs = extract_fields_from_source(source_code)
            except ImportError:
                from api_extractor import extract_fields_from_source
                field_refs = extract_fields_from_source(source_code)
    
    # 如果仍然没有字段信息，尝试从variable_refs中过滤出真正的类字段
    if not field_refs:
        variable_refs = cls_info.get('variable_refs', [])
        # 过滤掉明显的方法参数和局部变量
        field_refs = []
        for var in variable_refs:
            # 跳过方法参数
            if var.get('is_parameter', False):
                continue
            # 跳过循环变量
            if var.get('is_loop_var', False) or var.get('is_foreach_var', False):
                continue
            # 跳过资源变量
            if var.get('is_resource', False):
                continue
            # 跳过明显的局部变量名称
            var_name = var.get('name', '')
            if var_name in ['def', 'size', 'trs', 'preds', 'i', 'j', 'k', 'index', 'count', 'result', 'temp', 'tmp']:
                continue
            # 跳过明显在方法内声明的变量（通过行号或上下文判断）
            context = var.get('context', '')
            if any(pattern in context.lower() for pattern in ['final ', 'for (', 'while (', 'if (', 'catch (', '= new ', 'return ']):
                continue
            field_refs.append(var)
    
    if not field_refs:
        return ""
    
    lines = []
    for var in field_refs:
        var_name = var.get('name', '')
        var_type = var.get('type', '')
        
        # 构建变量描述字符串
        var_str = f"{var_name} ({var_type})"
        
        # 检查是否有写操作（对于从field_refs来的数据）
        is_modified = False
        if 'references' in var:
            for ref in var.get('references', []):
                if ref.get('operation', '') == 'write':
                    is_modified = True
                    break
        elif 'uses' in var:  # 对于从api_extractor来的数据
            for use in var.get('uses', []):
                if use.get('operation', '') == 'write':
                    is_modified = True
                    break
        
        # 添加修改标记
        if is_modified:
            var_str += " [This variable is modified]"
            
        # 添加字段特性信息
        modifiers = var.get('modifiers', [])
        if modifiers:
            if isinstance(modifiers, list):
                modifier_str = ' '.join(modifiers)
            else:
                modifier_str = str(modifiers)
            var_str += f" - 字段修饰符: {modifier_str}"
            
        lines.append(var_str)
    
    return "\n".join(lines)

def extract_constructor_info(cls_info: Dict[str, Any]) -> str:
    """
    提取构造函数信息
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化的构造函数信息和对象初始化信息
    """
    constructor_deps = cls_info.get('constructor_deps', [])
    if not constructor_deps:
        return ""
    
    # 提取构造函数定义
    constructor_definitions = []
    for dep in constructor_deps:
        if 'name' in dep:  # 是构造函数定义
            name = dep.get('name', '')
            params = []
            for param in dep.get('parameters', []):
                param_type = param.get('type', '')
                param_name = param.get('name', 'arg')
                params.append(f"{param_type} {param_name}")
            
            param_str = ", ".join(params)
            constructor_definitions.append(f"{name}({param_str}) —— 设置字段值或初始化对象状态。")
    
    # 提取对象初始化
    init_usages = []
    for dep in constructor_deps:
        if 'init_usages' in dep:  # 是实例化信息
            for usage in dep.get('init_usages', []):
                type_name = usage.get('type', '')
                args = []
                for arg in usage.get('arguments', []):
                    arg_value = arg.get('value', '')
                    arg_type = arg.get('type', '')
                    if arg_type and arg_type != 'unknown':
                        args.append(f"{arg_type} {arg_value}")
                    else:
                        args.append(f"unknown {arg_value}")
                
                arg_str = ", ".join(args)
                init_usages.append(f"- {type_name}({arg_str})")
    
    # 组织输出为两部分，方便后续提取
    constructor_part = "\n".join(constructor_definitions) if constructor_definitions else ""
    init_part = "\n".join(init_usages) if init_usages else ""
    
    # 使用特殊分隔符，以便后续拆分
    if constructor_part and init_part:
        return f"{constructor_part}@@SEPARATOR@@{init_part}"
    elif constructor_part:
        return constructor_part
    elif init_part:
        return f"@@SEPARATOR@@{init_part}"
    else:
        return ""

def get_formatted_class_info(cls_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    获取格式化的类信息
    
    Args:
        cls_info: 类信息字典
        
    Returns:
        格式化后的类信息字典
    """
    try:
        # 添加类型检查
        if not isinstance(cls_info, dict):
            logger.error(f"cls_info不是字典类型，而是 {type(cls_info)}")
            if isinstance(cls_info, str):
                return {"error": f"错误: 接收到字符串而非字典 - {cls_info[:100]}..."}
            return {"error": f"错误: 接收到的类信息类型不正确，需要字典而得到 {type(cls_info)}"}
        
        # 创建结果字典
        result = {}
        
        # 添加源代码
        result['code'] = cls_info.get('code', '')
        
        # 类名和包
        result['class_name'] = cls_info.get('className', cls_info.get('class_name', ''))
        result['package'] = cls_info.get('package', '')
        
        # 描述 - 直接调用api_extractor的extract_class_description函数
        result['description'] = extract_class_description(cls_info)
        result['class_description'] = result['description']  # 确保与模板中的占位符一致
        
        # 导入
        imports = cls_info.get('imports', [])
        if imports:
            # 确保imports是列表
            if isinstance(imports, str):
                imports = [imports]
            result['imports'] = imports
        else:
            result['imports'] = []
            
        # 字段
        # 从field_refs或fields中提取字段信息
        fields = []
        if 'fields' in cls_info:
            fields = cls_info['fields']
        elif 'field_refs' in cls_info:
            field_refs = cls_info['field_refs']
            for field_ref in field_refs:
                if isinstance(field_ref, dict):
                    field = {
                        'name': field_ref.get('name', ''),
                        'type': field_ref.get('type', ''),
                        'modifiers': ['static'] if field_ref.get('is_static', False) else [],
                        # 添加是否被修改的标记
                        'is_modified': any(use.get('operation', '') == 'write' for use in field_ref.get('uses', []))
                    }
                    fields.append(field)
        
        if fields:
            result['fields'] = fields
            # 格式化字段文本
            try:
                result['fields_section'] = format_fields_section(fields)
            except Exception as e:
                logger.error(f"格式化字段信息时出错: {e}")
                result['fields_section'] = "字段格式化错误"
        else:
            result['fields'] = []
            result['fields_section'] = ""
            
        # 方法部分
        try:
            methods_section = format_methods_section(cls_info)
            result['methods_section'] = methods_section
        except Exception as e:
            logger.error(f"格式化方法部分时出错: {e}")
            result['methods_section'] = "方法部分格式化错误"
            
        # 方法依赖 - 使用新的箭头格式
        try:
            # 直接使用extract_method_dependencies生成新格式的方法依赖
            method_dependencies = extract_method_dependencies(cls_info)
            result['method_dependencies'] = method_dependencies
            
            # 确保有值，即使是空字符串
            if not method_dependencies:
                result['method_dependencies'] = "未检测到方法调用关系"
        except Exception as e:
            logger.error(f"提取方法依赖时出错: {e}")
            result['method_dependencies'] = "方法依赖提取错误"
        
        # 移除旧的method_call_hierarchy字段，避免格式不一致
        if 'method_call_hierarchy' in result:
            del result['method_call_hierarchy']
                
        # 测试分布
        try:
            methods_info = []
            if "method_details" in cls_info and cls_info["method_details"]:
                method_details = cls_info["method_details"]
                # 添加类型检查
                if isinstance(method_details, list):
                    methods_info = method_details
                else:
                    logger.warning(f"method_details不是列表类型，而是 {type(method_details)}")
            elif "methods" in cls_info:
                # 如果只有方法名列表，简单处理
                method_names = cls_info["methods"]
                # 添加类型检查
                if isinstance(method_names, list):
                    for method_name in method_names:
                        if isinstance(method_name, str):
                            name = method_name
                            if '(' in method_name and ')' in method_name:
                                name = method_name.split('(')[0]
                            methods_info.append({
                                "name": name,
                                "signature": method_name,
                                "is_getter_setter": name.startswith("get") or name.startswith("set") or name.startswith("is")
                            })
                elif isinstance(method_names, str):
                    # 如果是单个方法名字符串，转换为列表处理
                    name = method_names
                    methods_info.append({
                        "name": name,
                        "signature": name,
                        "is_getter_setter": name.startswith("get") or name.startswith("set") or name.startswith("is")
                    })
                else:
                    logger.warning(f"methods不是列表或字符串类型，而是 {type(method_names)}")
            
            # 计算测试分布
            source_code = cls_info.get("source_code", "")
            test_distribution = calculate_test_distribution(methods_info)
            if test_distribution:
                # 添加类型检查
                if isinstance(test_distribution, dict):
                    result['test_distribution'] = test_distribution
                else:
                    logger.warning(f"test_distribution不是字典类型，而是 {type(test_distribution)}")
        except Exception as e:
            logger.error(f"计算测试分布时出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 处理依赖关系
        # 从dependencies字段中提取依赖关系
        dependencies = cls_info.get('dependencies', [])
        if dependencies and isinstance(dependencies, list):
            # 提取不同类型的依赖
            extends_refs = []
            implements_refs = []
            instantiates_refs = []
            generic_params = []
            class_refs = []
            
            for dep in dependencies:
                if isinstance(dep, dict):
                    dep_type = dep.get('type', '')
                    dep_name = dep.get('name', '')
                    
                    if not dep_name:
                        continue
                        
                    if dep_type == 'extends_reference':
                        extends_refs.append(dep_name)
                    elif dep_type == 'implements_reference':
                        implements_refs.append(dep_name)
                    elif dep_type == 'instantiation_reference':
                        instantiates_refs.append(dep_name)
                    elif dep_type == 'generic_parameter':
                        generic_params.append(dep_name)
                    elif dep_type == 'class_reference':
                        class_refs.append(dep_name)
            
            # 设置依赖字段
            result['extends'] = ', '.join(extends_refs) if extends_refs else 'None'
            result['implements'] = ', '.join(implements_refs) if implements_refs else 'None'
            result['instantiates'] = ', '.join(instantiates_refs) if instantiates_refs else 'None'
            result['generic_params'] = ', '.join(generic_params) if generic_params else 'None'
            result['references'] = ', '.join(class_refs) if class_refs else 'None'
            
            # 生成依赖部分
            try:
                dependencies_section = extract_dependencies_info(cls_info)
                result['dependencies_section'] = dependencies_section
            except Exception as e:
                logger.error(f"提取依赖关系时出错: {e}")
                result['dependencies_section'] = "依赖关系提取错误"
        else:
            # 设置默认值
            result['extends'] = 'None'
            result['implements'] = 'None'
            result['instantiates'] = 'None'
            result['generic_params'] = 'None'
            result['references'] = 'None'
            result['dependencies_section'] = "未找到依赖关系信息"
        
        # 添加其他必要的字段 - 修改字段名以匹配模板中的占位符
        result['extends_reference'] = result.get('extends', 'None')
        result['implements_reference'] = result.get('implements', 'None')
        result['instantiation_reference'] = result.get('instantiates', 'None')
        result['generic_parameter'] = result.get('generic_params', 'None')
        result['class_reference'] = result.get('references', 'None')
        result['variable_info'] = extract_variable_info(cls_info)
        result['constructor_info'] = extract_constructor_info(cls_info)
        
        # 处理构造函数信息
        constructor_info = result.get('constructor_info', '')
        if constructor_info and "@@SEPARATOR@@" in constructor_info:
            parts = constructor_info.split("@@SEPARATOR@@")
            result['constructor_signature'] = parts[0].strip()
            result['init_usages'] = parts[1].strip() if len(parts) > 1 else "未检测到对象初始化信息"
        else:
            result['constructor_signature'] = constructor_info
            result['init_usages'] = "未检测到对象初始化信息"
        
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
            if original in result and synonym not in result:
                result[synonym] = result[original]
            elif synonym in result and original not in result:
                result[original] = result[synonym]
        
        return result
    except Exception as e:
        logger.error(f"获取格式化类信息时出错: {e}")
        import traceback
        traceback.print_exc()
        return {
            "class_name": cls_info.get('className', cls_info.get('class_name', '')),
            "error": str(e)
        }

def get_formatted_class_info_from_path(project_path: str, class_name: str, json_path: Optional[str] = None) -> Dict[str, Any]:
    """
    从项目路径、类名和JSON路径获取格式化的类信息
    
    Args:
        project_path: 项目路径
        class_name: 类名
        json_path: JSON文件路径（可选）
        
    Returns:
        格式化后的类信息字典
    """
    result = {}
    
    try:
        # 1. 查找JSON配置文件（如果未提供）
        if not json_path:
            json_path = find_json_config(project_path)
            if not json_path:
                logger.error(f"无法找到valid_classes.json文件，项目路径: {project_path}")
                return {"error": "无法找到valid_classes.json文件"}
        
        # 2. 从JSON中提取类信息
        cls_info = extract_class_from_json(json_path, class_name)
        if not cls_info:
            logger.error(f"在JSON中找不到类 {class_name}，JSON路径: {json_path}")
            return {"error": f"在JSON中找不到类 {class_name}"}
        
        # 确保类信息包含正确的类名
        actual_class_name = cls_info.get('className', cls_info.get('class_name', ''))
        if actual_class_name and actual_class_name != class_name:
            logger.warning(f"找到的类名 {actual_class_name} 与请求的类名 {class_name} 不匹配")
            # 如果找到的类名与请求的不匹配，仍然使用找到的类名，但记录警告
        
        # 3. 使用api_extractor.enhance_class_info增强类信息
        enhanced_info = enhance_class_info(cls_info, project_path)
            
        # 4. 获取格式化的类信息
        result = get_formatted_class_info(enhanced_info)
        
        # 5. 确保结果是字典类型
        if not isinstance(result, dict):
            result = {"formatted_info": result}
            
    except Exception as e:
        logger.error(f"获取格式化类信息时出错: {e}")
        result = {"error": str(e)}
    
    return result

def format_class_info_for_prompt(cls_info: Dict[str, str]) -> str:
    """
    将类信息格式化为提示词
    
    Args:
        cls_info: 格式化后的类信息字典
        
    Returns:
        格式化的提示词
    """
    # 获取方法调用关系，确保总是有内容
    method_dependencies = cls_info.get('method_dependencies', '')
    if not method_dependencies:
        method_dependencies = "未检测到方法调用关系"
    
    sections = [
        f"Class name: {cls_info.get('class_name', '')}",
        f"Package: {cls_info.get('package', '')}",
        f"Imports: {', '.join(cls_info.get('imports', []))}" if cls_info.get('imports') else "Imports: []",
        
        "\n## METHODS SECTION",
        cls_info.get('methods_section', ''),
        
        "\n## METHOD CALL HIERARCHY",
        "下面展示了方法调用关系，格式为 \"caller → method()\":",
        method_dependencies,
        
        "\n## FIELD USAGE",
        cls_info.get('fields_section', ''),
        
        "\n## DEPENDENCIES",
        cls_info.get('dependencies_section', ''),
        
        "\n## VARIABLE DESCRIPTIONS",
        cls_info.get('variable_info', ''),
        
        "\n## CONSTRUCTORS",
        cls_info.get('constructor_info', ''),
        
        "\n## SOURCE CODE",
        cls_info.get('code', '')
    ]
    
    return "\n".join(sections)

def format_fields_section(fields: List[Dict[str, Any]]) -> str:
    """
    格式化字段部分
    
    Args:
        fields: 字段列表
        
    Returns:
        格式化后的字段部分，格式为"访问修饰符 字段类型 字段名称"
    """
    if not fields:
        return ""
        
    formatted_fields = []
    
    for field in fields:
        if isinstance(field, dict):
            # 提取字段属性，使用空字符串作为默认值
            name = field.get('name', '')
            type_name = field.get('type', '')
            visibility = field.get('visibility', 'private')
            
            # 处理修饰符
            modifiers = field.get('modifiers', [])
            modifiers_str = ' '.join(modifiers) if modifiers else ''
            
            # 构建字段描述字符串
            parts = []
            if visibility:
                parts.append(visibility)
            if modifiers_str:
                parts.append(modifiers_str)
            if type_name:
                parts.append(type_name)
            if name:
                parts.append(name)
                
            field_str = ' '.join(parts)
            formatted_fields.append(field_str)
        elif isinstance(field, str):
            # 如果字段是字符串格式，直接添加
            formatted_fields.append(field)
    
    return "\n".join(formatted_fields)

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
                signature = method.get("signature", "")
                signature_with_visibility = method.get("signature_with_visibility", "")
                visibility = method.get("visibility", "")
                return_type = method.get("return_type", "void")
                
                # 提取参数
                params = method.get("parameters", method.get("params", method.get("param_names", [])))
                params_str = ""
                if params:
                    if isinstance(params, list):
                        if all(isinstance(p, dict) for p in params):
                            params_str = ", ".join([f"{p.get('type', 'Object')} {p.get('name', 'arg')}" for p in params])
                        else:
                            params_str = ", ".join([str(p) for p in params])
                    else:
                        params_str = str(params)
                
                # 构建完整的方法签名
                if signature_with_visibility:
                    method_signature = signature_with_visibility
                else:
                    # 如果没有带可见性的签名，手动构建一个
                    visibility_str = visibility + " " if visibility else ""
                    return_type_str = return_type + " " if return_type else ""
                    method_signature = f"{visibility_str}{return_type_str}{method_name}({params_str})"
                
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
                    method_signature = method_str  # 使用整个字符串作为签名
                    method_name = method_signature.split('(')[0].split()[-1] if '(' in method_signature else method_signature.split()[-1]
                else:
                    # 不包含可见性信息，默认为公开方法
                    method_name = method_str.split('(')[0] if '(' in method_str else method_str
                    visibility = "public"  # 默认为公开
                    method_signature = f"{visibility} {method_str}"
            
            # 从测试分布中获取方法信息
            method_info = None
            if isinstance(test_distribution, dict) and "methods" in test_distribution:
                methods_dict = test_distribution["methods"]
                if isinstance(methods_dict, dict):
                    # 尝试通过名称或签名查找
                    method_info = methods_dict.get(method_name, None)
                    if method_info is None and 'signature' in locals():
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
            
            # 添加非公开方法标记
            is_public = visibility.lower() == "public"
            if is_public:
                public_methods.append((i, method_entry))
            else:
                non_public_note = " (非公开，需通过公开方法间接测试)"
                non_public_methods.append((i, f"{method_entry}{non_public_note}"))
            
        except Exception as e:
            # 如果处理单个方法失败，继续处理其他方法
            method_name_val = "方法" + str(i)
            if 'method_name' in locals():
                method_name_val = method_name
            lines.append(f"{i}. {method_name_val} (处理错误: {str(e)})")
            continue
    
    # 先添加公开方法
    for i, entry in public_methods:
        lines.append(f"{i}. {entry}")
    
    # 如果有非公开方法，添加分隔标题
    if non_public_methods:
        lines.append("\n【非公开方法（仅供参考，不要直接测试）】:")
        for i, entry in non_public_methods:
            lines.append(f"{i-len(public_methods)}. {entry}")
    
    # 添加总测试用例数量信息
    if isinstance(test_distribution, dict) and "total_min" in test_distribution and "total_max" in test_distribution:
        total_min = test_distribution["total_min"]
        total_max = test_distribution["total_max"]
        lines.append(f"\n总计需要提供 {total_min}-{total_max} 个测试用例")
    
    return "\n".join(lines)

# 如果直接运行这个模块，提供一个简单的命令行接口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python json_extractor.py <project_path> <class_name> [json_path]")
        sys.exit(1)
    
    project_path = sys.argv[1]
    class_name = sys.argv[2]
    json_path = sys.argv[3] if len(sys.argv) > 3 else None
    
    cls_info = get_formatted_class_info_from_path(project_path, class_name, json_path)
    if isinstance(cls_info, dict) and "error" in cls_info:
        print(f"Error: {cls_info['error']}")
    else:
        print(cls_info)
