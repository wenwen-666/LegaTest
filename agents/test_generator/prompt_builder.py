"""
提示词构建模块，负责生成高质量的提示词

该模块使用main_template.txt模板创建完整的测试生成提示词
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# 配置日志
logger = logging.getLogger(__name__)

# 导入config
try:
    from config import config
except ImportError:
    try:
        from .config import config
    except ImportError:
        # 创建一个简单的配置对象
        class SimpleConfig:
            def get_prompt_config(self):
                return {
                    "language": "en"
                }
            
            def get_test_config(self):
                return {
                    "min_test_methods": 5,
                    "min_code_length": 100,
                    "suites_per_class": 10
                }
                
            def get_paths(self):
                return {
                    "prompt_dir": Path(os.path.dirname(__file__)) / "prompts"
                }
                
            def get_focus_approaches(self):
                # 与config.py中保持一致的测试重点列表
                return [
                    "Focus on NORMAL INPUTS and BASIC FUNCTIONALITY verification.",
                    "Focus on EDGE CASES and BOUNDARY CONDITIONS testing.",
                    "Focus on EXCEPTION HANDLING and ERROR SCENARIOS.",
                    "Focus on ISOLATED and MOCKED DEPENDENCIES to verify the class behavior independently of external systems.",
                    "Focus on DATA TRANSFORMATION and STATE CHANGES caused by method calls.",
                    "Create an INNOVATIVE test suite with valid, compilable, and meaningful edge or rare scenarios.",
                    "Design a BALANCED test suite that combines creativity with standard testing practices.",
                    "Focus on COMPREHENSIVE CODE COVERAGE including methods, branches, and conditions while following JUnit 5 best practices.",
                    "Generate a test suite WITHOUT ANY SPECIFIC FOCUS. Use your best judgment and test design intuition.",
                    "Use the GIVEN PROMPT DETAILS to generate a COMPLETE and STRUCTURED test suite without assuming extra behavior."
                ]
            
        config = SimpleConfig()
        logger.warning("使用简化配置")

class PromptBuilder:
    """提示词构建器类，负责整合模板生成完整提示词"""
    
    def __init__(self):
        """初始化提示词构建器"""
        # 从config加载配置
        self.prompt_config = config.get_prompt_config()
        self.test_config = config.get_test_config()
        self.paths = config.get_paths()
        self.focus_approaches = config.get_focus_approaches()
        
        # 模板目录
        self.template_dir = self.paths.get("prompt_dir", Path(os.path.dirname(__file__)) / "prompts")
        
        # 加载主模板
        self.main_template = self._load_template("main_template.txt")
        if not self.main_template:
            logger.warning("无法加载main_template.txt，使用默认模板")
            self.main_template = self._get_default_template()
        
        # 加载通用测试规则
        self.common_rules = self._load_template("common_rules.txt") or """
- Generate at least 1 test for each public method
- Test both normal paths and edge cases
- Test exception handling for methods that throw exceptions
- Use JUnit 5 annotations correctly
- Follow standard naming conventions
"""
        
    def build_test_generation_prompt(self, cls_info: Dict[str, Any], suite_index: int = 0, 
                                 java_version: str = "8", maven_dependencies: List[str] = None) -> str:
        """
        构建测试生成提示词
        
        Args:
            cls_info: 类信息字典
            suite_index: 测试套件索引，用于选择不同的测试重点
            java_version: Java版本
            maven_dependencies: Maven依赖列表
            
        Returns:
            完整的测试生成提示词
        """
        # 预处理类信息
        self._preprocess_class_info(cls_info)
        
        # 使用cls_info中已设置的test_focus
        test_focus = cls_info.get('test_focus', '')
            
        # 如果cls_info中没有test_focus（这不应该发生，因为应该在file_writer.py中已设置）
        if not test_focus:
            logger.warning(f"cls_info中没有test_focus，这是意外情况")
            # 使用默认值
            test_focus = "Generate comprehensive tests following JUnit 5 best practices."
        
        # 准备变量字典
        format_vars = {
            "class_name": cls_info.get('className', cls_info.get('class_name', 'Unknown')),
            "package": cls_info.get('package', ''),
            "java_version": java_version,
            "class_description": cls_info.get('class_description', cls_info.get('description', '')),
            "imports": cls_info.get('imports', ''),
            "methods_section": cls_info.get('methods_section', ''),
            "method_dependencies": cls_info.get('method_dependencies', ''),
            "fields_section": cls_info.get('fields_section', ''),
            "extends_reference": cls_info.get('extends', 'None'),
            "implements_reference": cls_info.get('implements', 'None'),
            "instantiation_reference": cls_info.get('instantiates', 'None'),
            "generic_parameter": cls_info.get('generic_params', 'None'),
            "class_reference": cls_info.get('references', 'None'),
            "variable_info": cls_info.get('variable_info', ''),
            "constructor_signature": cls_info.get('constructor_signature', ''),
            "init_usages": cls_info.get('init_usages', ''),
            "test focus": test_focus,
            "common_rules": self.common_rules.strip(),
            "suite_index": suite_index + 1,
            "code": cls_info.get('code', ''),
            "maven_deps": ", ".join(maven_dependencies if maven_dependencies else [])
        }
        
        # 为每个空值提供默认值
        for key, value in format_vars.items():
            if not value:
                if key in ['extends_reference', 'implements_reference', 'instantiation_reference', 'generic_parameter', 'class_reference']:
                    format_vars[key] = 'None'
                else:
                    format_vars[key] = f'未提供{key}信息'
        
        # 使用Python格式化字符串填充模板
        try:
            filled_template = self.main_template.format(**format_vars)
        except Exception as e:
            logger.error(f"填充模板出错: {e}")
            # 如果格式化出错，使用简化格式
            filled_template = f"""# TEST GENERATION PROMPT
Class: {format_vars['class_name']}
Package: {format_vars['package']}
Test focus: {format_vars['test focus']}

Please generate a JUnit 5 test class for this class."""
            
        return filled_template
        
    def _load_template(self, template_name: str) -> Optional[str]:
        """加载模板文件"""
        template_path = self.template_dir / template_name
        
        try:
            if os.path.exists(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # 尝试使用相对路径
                alt_path = Path(os.path.dirname(os.path.abspath(__file__))) / "prompts" / template_name
                if os.path.exists(alt_path):
                    with open(alt_path, 'r', encoding='utf-8') as f:
                        return f.read()
                
                logger.warning(f"模板文件不存在: {template_name}")
                return None
        except Exception as e:
            logger.error(f"加载模板文件出错: {e}")
            return None
            
    def _get_default_template(self) -> str:
        """获取默认的主模板"""
        return """# TEST GENERATION PROMPT

## CLASS INFORMATION
Class name: {class_name}
Package: {package}
Java version: {java_version}
Imports: {imports}
Class description:{class_description}

## METHODS SECTION
{methods_section}

## METHOD CALL HIERARCHY
下面展示了方法调用关系，每行表示一个调用（格式："caller → method_name(parameters)"）：
{method_dependencies}

## FIELD USAGE
以下是类中字段的信息（格式：访问修饰符 字段类型 字段名称）：
{fields_section}

## DEPENDENCIES
类的依赖关系：
Extends: {extends_reference}
Implements: {implements_reference}
Instantiates: {instantiation_reference}
Generic parameters: {generic_parameter}
References: {class_reference}

## VARIABLE INFORMATION
以下是类中使用的变量（格式：变量名 (类型) 【如有写操作则显示"该变量会被修改"】）：
{variable_info}

## CONSTRUCTOR DEPS & INIT USAGES
构造函数信息和初始化的对象：
Constructor signature: {constructor_signature}
Initialized objects: {init_usages}

## Test focus
{test focus}

## TEST GUIDELINES
{common_rules}

## OUTPUT INSTRUCTIONS
Generate a complete JUnit 5 test class that follows all guidelines above."""
            
    def _preprocess_class_info(self, cls_info: Dict[str, Any]) -> None:
        """预处理类信息，如移除不必要的内容"""
        # 处理方法依赖关系，移除所有caller为unknown的方法调用
        if 'method_dependencies' in cls_info:
            method_deps = cls_info['method_dependencies']
            if method_deps:
                # 按行分割方法依赖信息
                deps_lines = method_deps.split('\n')
                # 只保留非"unknown →"开头的行
                valid_deps = [line for line in deps_lines if not line.strip().startswith('unknown →')]
                # 更新方法依赖信息，只包含有明确调用者的方法调用
                if valid_deps:
                    cls_info['method_dependencies'] = '\n'.join(valid_deps)
                else:
                    cls_info['method_dependencies'] = "无明确的方法调用层次信息"
        
        # 处理导入信息
        imports = cls_info.get("imports", [])
        if isinstance(imports, list):
            cls_info["imports"] = ", ".join(imports)
        elif not isinstance(imports, str):
            cls_info["imports"] = str(imports)
        
        # 处理构造函数信息
        constructor_info = cls_info.get("constructor_info", cls_info.get("constructorInfo", ""))
        if constructor_info and "类中使用了以下对象初始化:" in constructor_info:
            # 尝试提取构造函数签名和初始化使用情况
            constructor_parts = constructor_info.split("类中使用了以下对象初始化:")
            cls_info["constructor_signature"] = constructor_parts[0].strip()
            cls_info["init_usages"] = constructor_parts[1].strip() if len(constructor_parts) > 1 else "No initialization information."
        
        # 增强方法信息以强调可见性
        if 'methods_section' in cls_info and cls_info['methods_section']:
            methods_section = cls_info['methods_section']
            # 检查methods_section是否是字符串
            if isinstance(methods_section, str):
                # 添加关于方法可见性的明确指导
                enhanced_methods = "方法列表（按照优先级排序）：\n"
                
                # 提取单独的方法行
                method_lines = methods_section.split('\n')
                
                # 收集公开方法和非公开方法
                public_methods = []
                non_public_methods = []
                
                for line in method_lines:
                    if line.strip() and not line.startswith("方法列表"):
                        # 检查是否是以序号开头的方法行
                        if re.match(r'^\d+\.', line.strip()):
                            # 判断是否为公开方法
                            if "public" in line.lower() or "公开" in line:
                                public_methods.append(line)
                            else:
                                non_public_methods.append(line + " (非公开，需通过公开方法间接测试)")
        
                # 重建方法部分，优先展示公开方法
                if public_methods:
                    enhanced_methods += "【公开方法（可直接测试）】:\n"
                    enhanced_methods += "\n".join(public_methods) + "\n"
                
                if non_public_methods:
                    enhanced_methods += "\n【非公开方法（仅供参考，不要直接测试）】:\n"
                    enhanced_methods += "\n".join(non_public_methods) + "\n"
                    # 添加警告信息
                    enhanced_methods += "\n警告：非公开方法仅供参考，不要在测试中直接调用这些方法。这些方法应该通过公开方法间接测试。\n"
                    enhanced_methods += "❌ 错误做法: 直接调用 object.privateMethod()\n"
                    enhanced_methods += "✅ 正确做法: 调用公开方法 object.publicMethod()，该方法内部会调用privateMethod()\n"
                
                if not (public_methods or non_public_methods):
                    # 如果没有解析出方法，保留原始内容
                    enhanced_methods = methods_section
                
                # 用增强版方法部分替换原来的
                cls_info['methods_section'] = enhanced_methods
        
        # 添加可见性分类指导
        if 'fields_section' in cls_info and cls_info['fields_section']:
            fields_section = cls_info['fields_section']
            if isinstance(fields_section, str) and fields_section.strip():
                # 添加字段可见性指南
                cls_info['fields_section'] = fields_section + "\n\n注意: 测试时只能直接访问public字段，private/protected字段必须通过公开方法间接测试"
        
    def _select_test_focus(self, suite_index: int) -> str:
        """
        根据套件索引选择测试重点
        
        Args:
            suite_index: 测试套件索引
            
        Returns:
            测试重点策略
        """
        # 从配置中获取测试重点策略
        focus_approaches = config.get_focus_approaches()
            
        # 根据索引选择测试重点
        if suite_index < len(focus_approaches):
            focus = focus_approaches[suite_index]
            logger.debug(f"选择测试重点: {focus}")
            return focus
        else:
            # 默认使用创新策略
            default_focus = "Create an innovative test suite with your own creative approaches."
            logger.debug(f"使用默认测试重点: {default_focus}")
            return default_focus

# 创建全局提示词构建器实例
prompt_builder = PromptBuilder()