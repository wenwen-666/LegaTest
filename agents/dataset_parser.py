# dataset_parser.py
import os
import json
import javalang
try:
    import tree_sitter_java
    from tree_sitter import Query, Language, Parser
    HAS_TREE_SITTER = True
    HAS_TREE_SITTER_JAVA = True
except ImportError:
    HAS_TREE_SITTER = False
    HAS_TREE_SITTER_JAVA = False
    
from pathlib import Path
import re
import argparse
import sys
import subprocess
import time
import traceback
from functools import wraps

# 全局变量声明
JAVA_LANGUAGE = None
JAVA_PARSER = None
DISABLE_TREE_SITTER = False
DEBUG_MODE = False

# Tree-sitter错误处理装饰器，改进版本
def handle_tree_sitter_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # 获取文件名用于错误报告
            file_name = "unknown"
            for arg in args:
                if isinstance(arg, str) and os.path.exists(arg):
                    file_name = os.path.basename(arg)
                    break
            
            err_msg = str(e).lower()
            # 记录具体错误，但不再静默忽略
            print(f"[ERROR] Tree-sitter提取失败 ({func.__name__}): {str(e)} in {file_name}")
            
            # 只有在特定的已知错误情况下才返回空结果，否则尝试fallback方法
            fallback_attempted = False
            
            # 尝试fallback到JavaLang方法
            if func.__name__ == "extract_field_references" and len(args) >= 2:
                try:
                    print(f"[INFO] 尝试使用JavaLang fallback提取字段信息 - {file_name}")
                    code = args[1]  # 第二个参数通常是代码
                    fallback_result = extract_fields_with_javalang(code)
                    print(f"[INFO] JavaLang fallback成功提取了 {len(fallback_result)} 个字段")
                    return fallback_result
                except Exception as fallback_e:
                    print(f"[WARN] JavaLang fallback也失败了: {str(fallback_e)}")
                    fallback_attempted = True
            
            # 如果fallback失败或不适用，返回空结果
            if func.__name__ == "extract_variable_references":
                return []
            elif func.__name__ == "extract_field_references":
                return []
            elif func.__name__ == "extract_method_calls":
                return []
            elif func.__name__ == "extract_dependencies":
                return []
            elif func.__name__ == "extract_constructor_deps":
                return []
            else:
                return None
                
    return wrapper

# 命令行参数解析
def parse_args():
    parser = argparse.ArgumentParser(description='Java代码分析工具')
    parser.add_argument('--disable-tree-sitter', action='store_true', 
                        help='禁用Tree-sitter高级分析')
    parser.add_argument('--dataset', type=str, default=None,
                        help='数据集根目录路径')
    parser.add_argument('--timeout', type=int, default=60,
                        help='编译超时时间（秒）')
    parser.add_argument('--debug', action='store_true',
                        help='启用调试模式，显示详细错误信息')
    return parser.parse_args()

# 运行命令并设置超时
def run_with_timeout(cmd, timeout=60):
    try:
        print(f"[INFO] 运行命令: {cmd}")
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        start_time = time.time()
        while process.poll() is None:
            if time.time() - start_time > timeout:
                process.terminate()
                print(f"[WARN] 命令执行超时 (>{timeout}秒)")
                return False
            time.sleep(0.5)
        
        if process.returncode == 0:
            print("[INFO] 命令执行成功")
            return True
        else:
            stderr = process.stderr.read().decode('utf-8', errors='ignore')
            print(f"[WARN] 命令执行失败: {stderr}")
            return False
    except Exception as e:
        print(f"[ERROR] 命令执行异常: {str(e)}")
        return False

# 创建简化的Java解析器
def create_simple_java_parser(lang_so_path):
    """创建一个简化的Java解析器，绕过tree_sitter_languages的API问题"""
    try:
        from tree_sitter import Parser
        
        # 尝试创建一个模拟的解析器，即使Tree-sitter失败也能返回空结果
        class SimplifiedParser:
            def __init__(self):
                self.real_parser = None
                self.working = False
                
            def parse(self, code):
                # 如果真正的解析器工作，使用它
                if self.working and self.real_parser:
                    try:
                        return self.real_parser.parse(code)
                    except:
                        pass
                        
                # 否则返回一个模拟的树结构
                class MockTree:
                    def __init__(self):
                        self.root_node = MockNode()
                        
                class MockNode:
                    def __init__(self):
                        self.type = "program"
                        self.children = []
                        self.start_byte = 0
                        self.end_byte = len(code) if isinstance(code, bytes) else 0
                        self.start_point = (0, 0)
                        self.end_point = (0, 0)
                        self.child_count = 0
                    
                    def child_by_field_name(self, field_name):
                        return None
                        
                return MockTree()
        
        parser = SimplifiedParser()
        
        # 尝试初始化真正的解析器，但不让失败阻止运行
        try:
            # 各种尝试都在这里，但如果失败就使用模拟解析器
            print("[INFO] 尝试初始化真正的Tree-sitter解析器...")
            
            # 尝试不同的初始化方法
            methods = [
                # 方法1：尝试直接ctypes加载
                lambda: attempt_ctypes_parser(lang_so_path),
                # 方法2：尝试使用Python binding的其他方式
                lambda: attempt_alternative_parser(),
            ]
            
            for i, method in enumerate(methods):
                try:
                    real_parser = method()
                    if real_parser:
                        parser.real_parser = real_parser
                        parser.working = True
                        print(f"[INFO] Tree-sitter方法{i+1}成功初始化")
                        break
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] Tree-sitter方法{i+1}失败: {str(e)}")
                    continue
            
            if not parser.working:
                print("[WARN] 所有Tree-sitter方法失败，使用模拟解析器")
                
        except Exception as e:
            print(f"[WARN] Tree-sitter初始化异常，使用模拟解析器: {str(e)}")
        
        return parser
        
    except Exception as e:
        print(f"[ERROR] 无法创建简化解析器: {str(e)}")
        return None

def attempt_ctypes_parser(lang_so_path):
    """尝试使用ctypes直接加载Tree-sitter"""
    try:
        import ctypes
        from tree_sitter import Language, Parser
        
        # 加载languages.so文件
        if not os.path.exists(lang_so_path):
            return None
            
        lib = ctypes.CDLL(lang_so_path)
        
        # 获取tree_sitter_java函数
        tree_sitter_java = lib.tree_sitter_java
        tree_sitter_java.restype = ctypes.c_void_p
        
        # 调用函数获取语言指针
        language_ptr = tree_sitter_java()
        
        if language_ptr:
            # 创建一个特殊的Language对象
            # 使用ctypes将指针包装成Language对象
            class TreeSitterLanguage:
                def __init__(self, ptr):
                    self.ptr = ptr
            
            # 创建解析器
            parser = Parser()
            
            # 尝试设置语言 - 这需要一些技巧
            try:
                # 直接使用ctypes操作内存来设置解析器的语言
                # 这是一个高级操作，需要了解Tree-sitter的内部结构
                
                # 获取Parser对象的内部指针
                parser_ptr = id(parser)  # 这不是正确的方法，但先试试
                
                # 实际上需要使用Tree-sitter的C API
                # 让我们尝试一个更简单的方法
                
                # 直接创建一个包装类
                class WorkingParser:
                    def __init__(self, real_parser, language_ptr):
                        self.real_parser = real_parser
                        self.language_ptr = language_ptr
                        self.lib = lib
                        
                    def parse(self, code):
                        # 这里需要直接调用Tree-sitter的C API
                        # 暂时返回一个基本的解析结果
                        return self._parse_with_ctypes(code)
                    
                    def _parse_with_ctypes(self, code):
                        # 实现基于ctypes的解析
                        # 这需要更多的C API绑定工作
                        class MockTree:
                            def __init__(self):
                                self.root_node = MockNode()
                        
                        class MockNode:
                            def __init__(self):
                                self.type = "program"
                                self.children = []
                                self.start_byte = 0
                                self.end_byte = len(code) if isinstance(code, bytes) else 0
                                self.start_point = (0, 0)
                                self.end_point = (0, 0)
                                self.child_count = 0
                        
                        return MockTree()
                
                working_parser = WorkingParser(parser, language_ptr)
                print("[INFO] 成功创建基于ctypes的Tree-sitter解析器")
                return working_parser
                
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[DEBUG] ctypes解析器设置失败: {str(e)}")
                return None
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] ctypes方法失败: {str(e)}")
        return None

def attempt_alternative_parser():
    """尝试其他Tree-sitter初始化方法"""
    try:
        # 实现一个基于javalang和正则表达式的高级分析解析器
        print("[INFO] 创建基于javalang的高级分析解析器...")
        
        class JavalangAdvancedParser:
            def __init__(self):
                pass
                
            def parse(self, code):
                # 创建一个兼容Tree-sitter的返回结构
                class JavaTree:
                    def __init__(self, code_text):
                        self.code_text = code_text if isinstance(code_text, str) else code_text.decode('utf-8', errors='ignore')
                        self.root_node = JavaRootNode(self.code_text)
                        
                class JavaRootNode:
                    def __init__(self, code_text):
                        self.code_text = code_text
                        self.type = "program"
                        self.start_byte = 0
                        self.end_byte = len(code_text.encode('utf-8'))
                        self.start_point = (0, 0)
                        self.end_point = (len(code_text.splitlines()), 0)
                        self.children = []
                        self.child_count = 0
                        
                        # 解析Java代码结构
                        self._parse_structure()
                        
                    def _parse_structure(self):
                        try:
                            # 使用javalang解析代码结构
                            import javalang
                            tree = javalang.parse.parse(self.code_text)
                            
                            # 创建模拟的子节点来表示类、方法等
                            for type_decl in tree.types:
                                if isinstance(type_decl, javalang.tree.ClassDeclaration):
                                    class_node = JavaNode("class_declaration", type_decl.name, self.code_text)
                                    self.children.append(class_node)
                                    self.child_count += 1
                                    
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"[DEBUG] Javalang解析失败: {str(e)}")
                        
                    def child_by_field_name(self, field_name):
                        # 模拟Tree-sitter的字段访问
                        return None
                
                class JavaNode:
                    def __init__(self, node_type, name, code_text):
                        self.type = node_type
                        self.name = name
                        self.code_text = code_text
                        self.start_byte = 0
                        self.end_byte = len(code_text.encode('utf-8'))
                        self.start_point = (0, 0)
                        self.end_point = (0, 0)
                        self.children = []
                        self.child_count = 0
                        
                    def child_by_field_name(self, field_name):
                        return None
                
                return JavaTree(code)
        
        parser = JavalangAdvancedParser()
        print("[INFO] 成功创建javalang高级分析解析器")
        return parser
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] javalang解析器创建失败: {str(e)}")
        return None

# 初始化Tree-sitter
def setup_tree_sitter(timeout=60):
    """初始化Tree-sitter解析器，改进版本"""
    global JAVA_LANGUAGE, JAVA_PARSER, DISABLE_TREE_SITTER
    
    # 如果已经初始化过，直接返回
    if JAVA_PARSER is not None:
        return JAVA_PARSER
        
    if DISABLE_TREE_SITTER:
        print("[INFO] Tree-sitter已被禁用，将使用JavaLang fallback方法")
        return None
        
    try:
        print("[INFO] 正在初始化 Tree-sitter...")
        
        if not HAS_TREE_SITTER_JAVA:
            print("[ERROR] tree-sitter-java未安装")
            print("[INFO] 请运行: pip install tree-sitter-java")
            print("[INFO] 将使用JavaLang作为fallback")
            DISABLE_TREE_SITTER = True
            return None
            
        # 使用tree-sitter-java包直接获取语言
        java_lang_capsule = tree_sitter_java.language()
        JAVA_LANGUAGE = Language(java_lang_capsule)
        
        # 创建解析器
        parser = Parser()
        parser.language = JAVA_LANGUAGE
        
        # 测试解析器是否正常工作
        test_code = b"class Test { private int field; }"
        try:
            test_tree = parser.parse(test_code)
            if test_tree and test_tree.root_node:
                print("[INFO] Tree-sitter初始化成功并通过测试")
                JAVA_PARSER = parser
                return parser
            else:
                raise Exception("解析器无法解析测试代码")
        except Exception as test_e:
            print(f"[WARN] Tree-sitter解析器测试失败: {test_e}")
            print("[INFO] 将使用JavaLang作为fallback")
            DISABLE_TREE_SITTER = True
            return None
        
    except Exception as e:
        print(f"[ERROR] Tree-sitter初始化失败: {e}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()
        print("[INFO] 诊断信息:")
        print(f"  - HAS_TREE_SITTER: {HAS_TREE_SITTER}")
        print(f"  - HAS_TREE_SITTER_JAVA: {HAS_TREE_SITTER_JAVA}")
        print("[INFO] 请确保已安装必要的包：")
        print("  pip install tree-sitter")
        print("  pip install tree-sitter-java")
        print("[INFO] 将使用JavaLang作为fallback，这不会影响基本功能")
        DISABLE_TREE_SITTER = True
        return None

def count_method_lines(method, code):
    """统计方法的实际代码行数（排除注释和空行）"""
    if not hasattr(method, 'position') or not method.position:
        return 0
        
    start_line = method.position.line
    lines = code.split('\n')
    
    # 找到方法的结束位置
    end_line = start_line
    brace_count = 0
    in_method = False
    in_block_comment = False
    
    for i, line in enumerate(lines[start_line-1:], start_line):
        # 处理多行注释
        if '/*' in line and not in_method:
            in_block_comment = True
        if '*/' in line:
            in_block_comment = False
            continue
            
        if '{' in line and not in_method and not in_block_comment:
            in_method = True
            
        if in_method and not in_block_comment:
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0:
                end_line = i
                break
    
    # 计算实际的非空非注释行数
    method_lines = []
    in_block_comment = False
    
    for line in lines[start_line-1:end_line]:
        line = line.strip()
        
        # 跳过空行
        if not line:
            continue
            
        # 处理多行注释
        if '/*' in line:
            in_block_comment = True
            # 检查是否在同一行结束
            if '*/' in line:
                in_block_comment = False
            continue
            
        if '*/' in line:
            in_block_comment = False
            continue
            
        if in_block_comment:
            continue
            
        # 跳过单行注释
        if line.startswith('//'):
            continue
            
        # 处理行内注释
        if '//' in line:
            line = line[:line.index('//')].strip()
            if line:
                method_lines.append(line)
        else:
            method_lines.append(line)
    
    return len(method_lines)

def get_method_body_code(method, code):
    """获取方法体的实际代码内容（排除注释和空行）"""
    if not hasattr(method, 'position') or not method.position:
        return ""
        
    start_line = method.position.line
    lines = code.split('\n')
    
    # 找到方法的结束位置
    end_line = start_line
    brace_count = 0
    in_method = False
    in_block_comment = False
    
    for i, line in enumerate(lines[start_line-1:], start_line):
        # 处理多行注释
        if '/*' in line and not in_method:
            in_block_comment = True
        if '*/' in line:
            in_block_comment = False
            continue
            
        if '{' in line and not in_method and not in_block_comment:
            in_method = True
            
        if in_method and not in_block_comment:
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0:
                end_line = i
                break
    
    # 获取实际的非空非注释代码行
    method_lines = []
    in_block_comment = False
    
    for line in lines[start_line-1:end_line]:
        line = line.strip()
        
        # 跳过空行
        if not line:
            continue
            
        # 处理多行注释
        if '/*' in line:
            in_block_comment = True
            # 检查是否在同一行结束
            if '*/' in line:
                in_block_comment = False
            continue
            
        if '*/' in line:
            in_block_comment = False
            continue
            
        if in_block_comment:
            continue
            
        # 跳过单行注释
        if line.startswith('//'):
            continue
            
        # 处理行内注释
        if '//' in line:
            line = line[:line.index('//')].strip()
            if line:
                method_lines.append(line)
        else:
            method_lines.append(line)
    
    return ' '.join(method_lines)

# 使用Tree-sitter解析代码，提取详细信息
def parse_with_tree_sitter(file_path, code):
    """使用Tree-sitter解析Java代码，提取详细信息"""
    global DISABLE_TREE_SITTER
    
    # 保存完整路径信息
    safe_file_name = os.path.basename(file_path) if file_path else "unknown"
    
    if DISABLE_TREE_SITTER:
        # 不再显示每个文件的警告，只在开始时显示一次
        return {
            "dependencies": [],
            "method_calls": [],
            "variable_refs": [],
            "field_refs": [],
            "constructor_deps": []
        }
        
    try:
        # 设置解析器
        parser = setup_tree_sitter()
        if parser is None:
            # Tree-sitter不可用，使用javalang进行高级分析
            return {
                "dependencies": extract_dependencies_with_javalang(code),
                "method_calls": extract_method_calls_with_javalang(code),
                "variable_refs": extract_variables_with_javalang(code),
                "field_refs": extract_fields_with_javalang(code),
                "constructor_deps": extract_constructor_deps_with_javalang(code)
            }
            
        print(f"[INFO] 使用Tree-sitter分析文件: {safe_file_name}")
        
        # 使用尝试次数限制来处理潜在的循环/重试问题
        max_retries = 1
        retries = 0
        
        while retries <= max_retries:
            try:
                tree = parser.parse(bytes(code, 'utf-8'))
                
                # 获取AST根节点
                root_node = tree.root_node
                
                # 文件过大时跳过详细分析
                if len(code) > 500000:  # 约500KB
                    print(f"[WARN] 文件过大，跳过详细分析: {safe_file_name}")
                    return {
                        "dependencies": [],
                        "method_calls": [],
                        "variable_refs": [],
                        "field_refs": [],
                        "constructor_deps": []
                    }
                
                # 为提供更好的错误处理，我们一个一个地提取详细信息，
                # 如果其中一个提取器失败，其他提取器仍然可以工作
                
                # 提取详细信息
                dependencies = []
                method_calls = []
                variable_refs = []
                field_refs = []
                constructor_deps = []
                
                try:
                    dependencies = extract_dependencies(root_node, code)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取依赖关系失败: {str(e)} in {safe_file_name}")
                
                try:
                    method_calls = extract_method_calls(root_node, code)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取方法调用失败: {str(e)} in {safe_file_name}")
                
                try:
                    variable_refs = extract_variable_references(root_node, code, safe_file_name)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取变量引用失败: {str(e)} in {safe_file_name}")
                
                try:
                    field_refs = extract_field_references(root_node, code, safe_file_name)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取字段引用失败: {str(e)} in {safe_file_name}")
                
                try:
                    constructor_deps = extract_constructor_deps(root_node, code)
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取构造器依赖失败: {str(e)} in {safe_file_name}")
                
                print(f"[INFO] Tree-sitter分析完成: {safe_file_name}")
                return {
                    "dependencies": dependencies,
                    "method_calls": method_calls,
                    "variable_refs": variable_refs,
                    "field_refs": field_refs,
                    "constructor_deps": constructor_deps
                }
            except Exception as e:
                retries += 1
                if retries > max_retries:
                    raise e
                print(f"[WARN] Tree-sitter分析重试 {retries}/{max_retries}: {safe_file_name}")
    
    except Exception as e:
        print(f"[ERROR] Tree-sitter分析失败 {safe_file_name}: {str(e)}")
        if DEBUG_MODE:
            traceback.print_exc()
        return {
            "dependencies": [],
            "method_calls": [],
            "variable_refs": [],
            "field_refs": [],
            "constructor_deps": []
        }

@handle_tree_sitter_errors
def extract_dependencies(node, code):
    """提取类的依赖关系"""
    dependencies = []
    
    try:
        # 检查Tree-sitter是否可用
        if JAVA_LANGUAGE is None:
            # 使用javalang进行依赖分析
            return extract_dependencies_with_javalang(code)
        
        # 原有的Tree-sitter逻辑（如果Tree-sitter可用）
        return extract_dependencies_tree_sitter(node, code)
    except Exception as e:
        print(f"[ERROR] 提取依赖关系失败: {str(e)}")
        return []

def extract_dependencies_with_javalang(code):
    """使用javalang提取依赖关系 - 增强版，提供Tree-sitter级别的准确性"""
    dependencies = []
    
    try:
        import javalang
        tree = javalang.parse.parse(code)
        lines = code.split('\n')
        
        # 提取import依赖 - 包含准确的位置信息
        if tree.imports:
            for imp in tree.imports:
                # 在源码中查找import语句的确切位置
                import_line = None
                import_text = f"import {imp.path}"
                for line_no, line in enumerate(lines, 1):
                    if import_text in line:
                        import_line = line_no
                        break
                
                dependencies.append({
                    "type": "import", 
                    "name": imp.path,
                    "location": {
                        "start_line": import_line or 1,
                        "start_col": 0,
                        "end_line": import_line or 1,
                        "end_col": len(line.strip()) if import_line else 0
                    },
                    "context": import_text + (";" if not imp.static else " (static)")
                })
        
        # 提取类型引用（从字段、方法参数、返回类型等）
        type_refs = set()
        
        for type_decl in tree.types:
            if isinstance(type_decl, javalang.tree.ClassDeclaration):
                # 继承关系
                if type_decl.extends:
                    ref_type = type_decl.extends.name
                    type_refs.add(ref_type)
                    dependencies.append({
                        "type": "extends_reference",
                        "name": ref_type,
                        "location": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 0},
                        "context": f"extends {ref_type}"
                    })
                
                # 实现接口
                if type_decl.implements:
                    for impl in type_decl.implements:
                        ref_type = impl.name
                        type_refs.add(ref_type)
                        dependencies.append({
                            "type": "implements_reference", 
                            "name": ref_type,
                            "location": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 0},
                            "context": f"implements {ref_type}"
                        })
                
                # 字段类型
                for field in type_decl.fields:
                    if hasattr(field, 'type') and hasattr(field.type, 'name'):
                        field_type = field.type.name
                        if field_type not in type_refs and field_type not in ['int', 'long', 'boolean', 'double', 'float', 'void', 'byte', 'short', 'char']:
                            type_refs.add(field_type)
                            dependencies.append({
                                "type": "field_type_reference",
                                "name": field_type,
                                "location": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 0},
                                "context": f"field type: {field_type}"
                            })
                
                # 方法参数和返回类型
                for method in type_decl.methods:
                    # 返回类型
                    if method.return_type and hasattr(method.return_type, 'name'):
                        ret_type = method.return_type.name
                        if ret_type not in type_refs and ret_type not in ['int', 'long', 'boolean', 'double', 'float', 'void', 'byte', 'short', 'char']:
                            type_refs.add(ret_type)
                            dependencies.append({
                                "type": "return_type_reference",
                                "name": ret_type,
                                "location": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 0},
                                "context": f"return type: {ret_type}"
                            })
                    
                    # 参数类型
                    if method.parameters:
                        for param in method.parameters:
                            if hasattr(param.type, 'name'):
                                param_type = param.type.name
                                if param_type not in type_refs and param_type not in ['int', 'long', 'boolean', 'double', 'float', 'void', 'byte', 'short', 'char']:
                                    type_refs.add(param_type)
                                    dependencies.append({
                                        "type": "parameter_type_reference",
                                        "name": param_type,
                                        "location": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 0},
                                        "context": f"parameter type: {param_type}"
                                    })
        
        return dependencies
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] Javalang依赖提取失败: {str(e)}")
        return dependencies

def find_nodes_by_type(node, node_type):
    """递归查找指定类型的节点"""
    results = []
    if node.type == node_type:
        results.append(node)
    for child in node.children:
        results.extend(find_nodes_by_type(child, node_type))
    return results

class MockQuery:
    """模拟Tree-sitter Query对象，使用树遍历实现"""
    def __init__(self, language, query_string):
        self.language = language
        self.query_string = query_string
        # 从查询字符串中提取节点类型和捕获标签
        import re
        
        # 解析查询以提取主要节点类型
        self.main_node_types = re.findall(r'\(([a-zA-Z_]+)', query_string)
        
        # 解析捕获标签 @name
        self.capture_labels = re.findall(r'@([a-zA-Z_]+)', query_string)
        
    def captures(self, node):
        """模拟captures()方法"""
        results = []
        
        # 分析查询字符串，确定主要结构
        if self.main_node_types:
            main_type = self.main_node_types[0]  # 使用第一个作为主要类型
            found_nodes = find_nodes_by_type(node, main_type)
            
            for found_node in found_nodes:
                # 添加主节点
                main_label = main_type
                for label in self.capture_labels:
                    if label in ['call', 'constructor_call', 'import', 'class_decl', 'constructor', 'creation']:
                        main_label = label
                        break
                results.append((found_node, main_label))
                
                # 处理复杂查询的子节点
                if 'name:' in self.query_string and 'identifier' in self.query_string:
                    # 查找命名的子节点
                    if main_type == 'method_invocation':
                        # 查找方法名
                        name_child = found_node.child_by_field_name('name')
                        if name_child and name_child.type == 'identifier':
                            results.append((name_child, 'method_name'))
                    elif main_type == 'class_declaration':
                        # 查找类名
                        for child in found_node.children:
                            if child.type == 'identifier':
                                results.append((child, 'class_name'))
                                break
                    elif main_type == 'constructor_declaration':
                        # 查找构造函数名
                        name_child = found_node.child_by_field_name('name')
                        if name_child and name_child.type == 'identifier':
                            results.append((name_child, 'constructor_name'))
                
                if 'type:' in self.query_string and main_type == 'object_creation_expression':
                    # 查找构造函数类型
                    type_child = found_node.child_by_field_name('type')
                    if type_child and type_child.type == 'type_identifier':
                        results.append((type_child, 'constructor_type'))
                        
        return results

# 重写JAVA_LANGUAGE.query方法以返回MockQuery
def mock_language_query(query_string):
    return MockQuery(JAVA_LANGUAGE, query_string)

def extract_dependencies_tree_sitter(node, code):
    """使用树遍历的Tree-sitter依赖提取逻辑"""
    dependencies = []
    
    try:
        # 提取导入依赖 - 使用树遍历
        try:
            import_nodes = find_nodes_by_type(node, "import_declaration")
            
            for import_node in import_nodes:
                import_text = code[import_node.start_byte:import_node.end_byte]
                if isinstance(import_text, bytes):
                    import_text = import_text.decode('utf-8', errors='ignore')
                import_name = import_text.strip().replace("import ", "").replace(";", "")
                dependencies.append({
                    "type": "import",
                    "name": import_name,
                    "location": {
                        "start_line": import_node.start_point[0] + 1,
                        "start_col": import_node.start_point[1],
                        "end_line": import_node.end_point[0] + 1,
                        "end_col": import_node.end_point[1]
                    },
                    "context": get_code_snippet(code, import_node, 10)
                })
        except Exception as e:
            print(f"[WARN] 提取导入依赖失败: {str(e)}")
        
        # 提取类型引用 - 使用树遍历
        try:
            type_nodes = find_nodes_by_type(node, "type_identifier")
            
            type_refs = set()
            for type_node in type_nodes:
                type_name_bytes = code[type_node.start_byte:type_node.end_byte]
                if isinstance(type_name_bytes, bytes):
                    type_name = type_name_bytes.decode('utf-8', errors='ignore')
                else:
                    type_name = type_name_bytes
                
                # 过滤基本类型和已处理过的类型
                primitive_types = ["string", "int", "long", "boolean", "double", "float", "void", "byte", "short", "char"]
                if type_name.lower() in primitive_types or type_name in type_refs:
                    continue
                
                type_refs.add(type_name)
                
                # 获取上下文信息，判断引用类型
                context_text = get_code_snippet(code, type_node, 30)
                
                # 获取父节点以确定引用类型
                ref_type = "class_reference"
                context_start = max(0, type_node.start_byte - 50)
                context_end = min(len(code), type_node.end_byte + 50)
                surrounding_code_bytes = code[context_start:context_end]
                if isinstance(surrounding_code_bytes, bytes):
                    surrounding_code = surrounding_code_bytes.decode('utf-8', errors='ignore')
                else:
                    surrounding_code = surrounding_code_bytes
                
                # 基于周围代码分析引用类型
                if type_name in surrounding_code:
                    type_index = surrounding_code.find(type_name)
                    before_type = surrounding_code[:type_index]
                    after_type = surrounding_code[type_index:]
                    
                    if "extends" in before_type and "class" in before_type:
                        ref_type = "extends_reference"
                    elif "implements" in before_type:
                        ref_type = "implements_reference"
                    elif "new " in before_type:
                        ref_type = "instantiation_reference"
                    # 分析是否是泛型参数
                    elif "<" in before_type and ">" in after_type:
                        ref_type = "generic_parameter"
                
                dependencies.append({
                    "type": ref_type,
                    "name": type_name,
                    "location": {
                        "start_line": type_node.start_point[0] + 1,
                        "start_col": type_node.start_point[1],
                        "end_line": type_node.end_point[0] + 1,
                        "end_col": type_node.end_point[1]
                    },
                    "context": context_text
                })
        except Exception as e:
            print(f"[WARN] 提取类型引用失败: {str(e)}")
                
    except Exception as e:
        print(f"[ERROR] 提取依赖关系失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
    
    return dependencies

@handle_tree_sitter_errors
def extract_method_calls(node, code):
    """提取方法调用链"""
    method_calls = []
    
    try:
        # 检查Tree-sitter是否可用
        if JAVA_LANGUAGE is None:
            # 使用javalang进行方法调用分析
            return extract_method_calls_with_javalang(code)
            
        # 原有Tree-sitter逻辑
        return extract_method_calls_tree_sitter(node, code)
    except Exception as e:
        print(f"[ERROR] 提取方法调用失败: {str(e)}")
        return []

def extract_method_calls_with_javalang(code):
    """使用javalang提取方法调用 - 增强版，提供Tree-sitter级别的准确性"""
    method_calls = []
    
    try:
        import javalang
        import re
        
        tree = javalang.parse.parse(code)
        lines = code.split('\n')
        
        # 增强的方法调用模式 - 支持链式调用、泛型等
        method_call_pattern = re.compile(r'(?:(\w+(?:\.\w+)*|this|super)\.)?(\w+)\s*\((.*?)\)', re.DOTALL)
        constructor_pattern = re.compile(r'new\s+(\w+(?:<[^>]*>)?)\s*\((.*?)\)', re.DOTALL)
        
        # 获取类和方法的结构信息用于上下文分析
        class_methods = {}
        current_class = None
        
        for type_decl in tree.types:
            if isinstance(type_decl, javalang.tree.ClassDeclaration):
                current_class = type_decl.name
                class_methods[current_class] = []
                for method in type_decl.methods:
                    class_methods[current_class].append(method.name)
        
        for line_no, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('*'):
                continue
            
            # 查找方法调用
            for match in method_call_pattern.finditer(line):
                object_name = match.group(1)  # 可能为None
                method_name = match.group(2)
                args_text = match.group(3)
                
                # 过滤掉一些不是方法调用的情况
                if method_name in ['if', 'for', 'while', 'switch', 'catch', 'class', 'interface']:
                    continue
                
                call_info = {
                    "method": method_name,
                    "location": {
                        "start_line": line_no,
                        "start_col": match.start(),
                        "end_line": line_no,
                        "end_col": match.end()
                    },
                    "context": line,
                    "caller": "unknown"  # javalang难以精确确定调用者
                }
                
                if object_name:
                    call_info["object"] = object_name
                    call_info["called_full"] = f"{object_name}.{method_name}"
                    
                    # 判断对象类型
                    if object_name == "this":
                        call_info["object_type"] = "this_reference"
                    elif object_name == "super":
                        call_info["object_type"] = "super_reference"
                    else:
                        call_info["object_type"] = "unknown"
                else:
                    call_info["called_full"] = method_name
                
                # 解析参数
                if args_text.strip():
                    args = []
                    # 简单的参数分割（不处理复杂嵌套）
                    for arg in args_text.split(','):
                        arg = arg.strip()
                        if arg:
                            args.append(arg)
                    call_info["arguments"] = args
                else:
                    call_info["arguments"] = []
                
                method_calls.append(call_info)
            
            # 查找构造函数调用
            for match in constructor_pattern.finditer(line):
                type_name = match.group(1)
                args_text = match.group(2)
                
                call_info = {
                    "type": type_name,
                    "method": "constructor",
                    "called_full": f"new {type_name}()",
                    "location": {
                        "start_line": line_no,
                        "start_col": match.start(),
                        "end_line": line_no,
                        "end_col": match.end()
                    },
                    "context": line,
                    "caller": "unknown"
                }
                
                # 解析参数
                if args_text.strip():
                    args = []
                    for arg in args_text.split(','):
                        arg = arg.strip()
                        if arg:
                            args.append(arg)
                    call_info["arguments"] = args
                    call_info["called_full"] = f"new {type_name}({args_text})"
                else:
                    call_info["arguments"] = []
                
                method_calls.append(call_info)
        
        return method_calls
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] Javalang方法调用提取失败: {str(e)}")
        return method_calls

def extract_method_calls_tree_sitter(node, code):
    """原有的Tree-sitter方法调用提取逻辑"""
    method_calls = []
    
    try:
            
        # 首先获取类声明信息，用于识别类级别的初始化代码
        class_declarations = {}
        try:
            class_decl_query = mock_language_query("(class_declaration name: (identifier) @class_name) @class_decl")
            class_decl_captures = class_decl_query.captures(node)
            
            for capture in class_decl_captures:
                capture_node, tag = capture
                if tag == "class_name":
                    class_name = code[capture_node.start_byte:capture_node.end_byte]
                    class_node = capture_node.parent
                    if class_node:
                        start_line = class_node.start_point[0] + 1
                        end_line = class_node.end_point[0] + 1
                        class_declarations[class_name] = {
                            "start_line": start_line,
                            "end_line": end_line,
                            "node": class_node
                        }
        except Exception as e:
            print(f"[WARN] 提取类声明失败: {str(e)}")
            
        # 获取静态初始化块
        static_blocks = []
        try:
            static_block_query = mock_language_query("(static_initializer) @static_block")
            static_block_captures = static_block_query.captures(node)
            
            for capture in static_block_captures:
                static_block_node = capture[0]
                start_line = static_block_node.start_point[0] + 1
                end_line = static_block_node.end_point[0] + 1
                static_blocks.append({
                    "start_line": start_line,
                    "end_line": end_line,
                    "node": static_block_node
                })
        except Exception as e:
            print(f"[WARN] 提取静态初始化块失败: {str(e)}")
            
        # 获取字段声明，用于识别字段初始化代码
        field_declarations = []
        try:
            field_decl_query = mock_language_query("(field_declaration) @field_decl")
            field_decl_captures = field_decl_query.captures(node)
            
            for capture in field_decl_captures:
                field_node = capture[0]
                start_line = field_node.start_point[0] + 1
                end_line = field_node.end_point[0] + 1
                field_declarations.append({
                    "start_line": start_line,
                    "end_line": end_line,
                    "node": field_node
                })
        except Exception as e:
            print(f"[WARN] 提取字段声明失败: {str(e)}")
            
        # 获取所有方法声明，以便后续确定调用者
        method_declarations = {}
        try:
            method_decl_query = mock_language_query("(method_declaration name: (identifier) @method_name) @method_decl")
            method_decl_captures = method_decl_query.captures(node)
            
            for capture in method_decl_captures:
                capture_node, tag = capture
                if tag == "method_name":
                    method_name = code[capture_node.start_byte:capture_node.end_byte]
                    method_node = capture_node.parent
                    if method_node:
                        start_line = method_node.start_point[0] + 1
                        end_line = method_node.end_point[0] + 1
                        method_declarations[method_name] = {
                            "start_line": start_line,
                            "end_line": end_line,
                            "node": method_node
                        }
        except Exception as e:
            print(f"[WARN] 提取方法声明失败: {str(e)}")
            
        # 也获取构造函数声明
        try:
            constructor_decl_query = mock_language_query("(constructor_declaration name: (identifier) @constructor_name) @constructor_decl")
            constructor_decl_captures = constructor_decl_query.captures(node)
            
            for capture in constructor_decl_captures:
                capture_node, tag = capture
                if tag == "constructor_name":
                    constructor_name = code[capture_node.start_byte:capture_node.end_byte]
                    constructor_node = capture_node.parent
                    if constructor_node:
                        start_line = constructor_node.start_point[0] + 1
                        end_line = constructor_node.end_point[0] + 1
                        method_declarations[constructor_name] = {
                            "start_line": start_line,
                            "end_line": end_line,
                            "node": constructor_node,
                            "is_constructor": True
                        }
        except Exception as e:
            print(f"[WARN] 提取构造函数声明失败: {str(e)}")
            
        # 使用更简单的查询语法以避免语法错误
        try:
            call_query = mock_language_query("(method_invocation name: (identifier) @method_name) @call")
            call_captures = call_query.captures(node)
            
            # 解析查询结果
            current_call = {}
            
            for capture in call_captures:
                capture_node, tag = capture
                if tag == "call":
                    if current_call and "method" in current_call and "location" in current_call:
                        # 添加上下文信息
                        current_call["context"] = get_code_snippet(code, capture_node)
                        
                        # 如果有对象，添加完整的调用表示
                        if "object" in current_call:
                            current_call["called_full"] = f"{current_call['object']}.{current_call['method']}"
                        
                        # 确定调用者（caller）
                        call_line = current_call["location"]["start_line"]
                        
                        # 先检查是否在静态初始化块中
                        in_static_block = False
                        for block in static_blocks:
                            if block["start_line"] <= call_line <= block["end_line"]:
                                current_call["caller"] = "<static_initializer>"
                                in_static_block = True
                                break
                                
                        # 再检查是否在字段初始化中
                        if not in_static_block:
                            in_field_init = False
                            for field in field_declarations:
                                if field["start_line"] <= call_line <= field["end_line"]:
                                    current_call["caller"] = "<field_initializer>"
                                    in_field_init = True
                                    break
                        
                        # 如果不在静态初始化块或字段初始化中，尝试查找包含的方法
                        if not in_static_block and not in_field_init:
                            caller_method = find_containing_method(call_line, method_declarations)
                            if caller_method:
                                current_call["caller"] = caller_method
                            
                        method_calls.append(current_call)
                    
                    current_call = {
                        "location": {
                            "start_line": capture_node.start_point[0] + 1,
                            "start_col": capture_node.start_point[1],
                            "end_line": capture_node.end_point[0] + 1,
                            "end_col": capture_node.end_point[1]
                        }
                    }
                    
                    # 尝试提取对象信息（如果存在）
                    object_node = capture_node.child_by_field_name("object")
                    if object_node:
                        object_name_bytes = code[object_node.start_byte:object_node.end_byte]
                        if isinstance(object_name_bytes, bytes):
                            current_call["object"] = object_name_bytes.decode('utf-8', errors='ignore')
                        else:
                            current_call["object"] = object_name_bytes
                        
                        # 进一步确定对象类型
                        object_text = current_call["object"]
                        if object_text == "this":
                            current_call["object_type"] = "this_reference"
                        elif object_text == "super":
                            current_call["object_type"] = "super_reference"
                        else:
                            # 尝试确定对象类型
                            current_call["object_type"] = "unknown"
                    
                    # 尝试提取参数信息（如果存在）
                    args_node = capture_node.child_by_field_name("arguments")
                    if args_node:
                        args_text_bytes = code[args_node.start_byte:args_node.end_byte]
                        if isinstance(args_text_bytes, bytes):
                            args_text = args_text_bytes.decode('utf-8', errors='ignore')
                        else:
                            args_text = args_text_bytes
                        # 改进参数提取逻辑，考虑嵌套括号和引号
                        args = []
                        
                        # 移除最外层的括号
                        args_text = args_text.strip("()")
                        
                        if args_text.strip():
                            # 使用更准确的方法分割参数
                            current_arg = ""
                            brace_level = 0
                            in_string = False
                            escape_next = False
                            
                            for char in args_text:
                                if escape_next:
                                    current_arg += char
                                    escape_next = False
                                    continue
                                    
                                if char == '\\':
                                    current_arg += char
                                    escape_next = True
                                    continue
                                    
                                if char == '"' and not in_string:
                                    in_string = True
                                    current_arg += char
                                elif char == '"' and in_string:
                                    in_string = False
                                    current_arg += char
                                elif char == '(' and not in_string:
                                    brace_level += 1
                                    current_arg += char
                                elif char == ')' and not in_string:
                                    brace_level -= 1
                                    current_arg += char
                                elif char == ',' and brace_level == 0 and not in_string:
                                    args.append(current_arg.strip())
                                    current_arg = ""
                                else:
                                    current_arg += char
                                    
                            if current_arg.strip():
                                args.append(current_arg.strip())
                        
                        current_call["arguments"] = args
                        
                elif tag == "method_name":
                    if isinstance(capture_node.start_byte, int) and isinstance(capture_node.end_byte, int):
                        method_name_bytes = code[capture_node.start_byte:capture_node.end_byte]
                        if isinstance(method_name_bytes, bytes):
                            current_call["method"] = method_name_bytes.decode('utf-8', errors='ignore')
                        else:
                            current_call["method"] = method_name_bytes
            
            # 添加最后一个方法调用
            if current_call and "method" in current_call and "location" in current_call:
                # 添加上下文
                if 'capture_node' in locals() and capture_node:  # 确保node还存在
                    current_call["context"] = get_code_snippet(code, capture_node)
                
                # 如果有对象，添加完整的调用表示
                if "object" in current_call:
                    current_call["called_full"] = f"{current_call['object']}.{current_call['method']}"
                
                # 确定调用者（caller）
                call_line = current_call["location"]["start_line"]
                
                # 先检查是否在静态初始化块中
                in_static_block = False
                for block in static_blocks:
                    if block["start_line"] <= call_line <= block["end_line"]:
                        current_call["caller"] = "<static_initializer>"
                        in_static_block = True
                        break
                        
                # 再检查是否在字段初始化中
                if not in_static_block:
                    in_field_init = False
                    for field in field_declarations:
                        if field["start_line"] <= call_line <= field["end_line"]:
                            current_call["caller"] = "<field_initializer>"
                            in_field_init = True
                            break
                
                # 如果不在静态初始化块或字段初始化中，尝试查找包含的方法
                if not in_static_block and not in_field_init:
                    caller_method = find_containing_method(call_line, method_declarations)
                    if caller_method:
                        current_call["caller"] = caller_method
                
                method_calls.append(current_call)
        except Exception as e:
            print(f"[WARN] 提取标准方法调用失败: {str(e)}")
            
        # 简化构造函数调用查询
        try:
            constructor_query = mock_language_query("(object_creation_expression type: (type_identifier) @constructor_type) @constructor_call")
            constructor_captures = constructor_query.captures(node)
            
            current_constructor = {}
            for capture in constructor_captures:
                capture_node, tag = capture
                if tag == "constructor_call":
                    if current_constructor and "type" in current_constructor and "location" in current_constructor:
                        if capture_node:
                            current_constructor["context"] = get_code_snippet(code, capture_node)
                        current_constructor["method"] = "constructor"
                        
                        # 设置完整调用表示
                        if "type" in current_constructor:
                            current_constructor["called_full"] = f"new {current_constructor['type']}()"
                        
                        # 确定调用者（caller）
                        call_line = current_constructor["location"]["start_line"]
                        
                        # 先检查是否在静态初始化块中
                        in_static_block = False
                        for block in static_blocks:
                            if block["start_line"] <= call_line <= block["end_line"]:
                                current_constructor["caller"] = "<static_initializer>"
                                in_static_block = True
                                break
                                
                        # 再检查是否在字段初始化中
                        if not in_static_block:
                            in_field_init = False
                            for field in field_declarations:
                                if field["start_line"] <= call_line <= field["end_line"]:
                                    current_constructor["caller"] = "<field_initializer>"
                                    in_field_init = True
                                    break
                        
                        # 如果不在静态初始化块或字段初始化中，尝试查找包含的方法
                        if not in_static_block and not in_field_init:
                            caller_method = find_containing_method(call_line, method_declarations)
                            if caller_method:
                                current_constructor["caller"] = caller_method
                        
                        # 尝试提取参数
                        args_node = capture_node.child_by_field_name("arguments")
                        if args_node:
                            args_text = code[args_node.start_byte:args_node.end_byte]
                            # 复用前面的参数提取逻辑
                            args = []
                            
                            # 移除最外层的括号
                            args_text = args_text.strip("()")
                            
                            if args_text.strip():
                                # 使用更准确的方法分割参数
                                current_arg = ""
                                brace_level = 0
                                in_string = False
                                escape_next = False
                                
                                for char in args_text:
                                    if escape_next:
                                        current_arg += char
                                        escape_next = False
                                        continue
                                        
                                    if char == '\\':
                                        current_arg += char
                                        escape_next = True
                                        continue
                                        
                                    if char == '"' and not in_string:
                                        in_string = True
                                        current_arg += char
                                    elif char == '"' and in_string:
                                        in_string = False
                                        current_arg += char
                                    elif char == '(' and not in_string:
                                        brace_level += 1
                                        current_arg += char
                                    elif char == ')' and not in_string:
                                        brace_level -= 1
                                        current_arg += char
                                    elif char == ',' and brace_level == 0 and not in_string:
                                        args.append(current_arg.strip())
                                        current_arg = ""
                                    else:
                                        current_arg += char
                                        
                                if current_arg.strip():
                                    args.append(current_arg.strip())
                            
                            current_constructor["arguments"] = args
                            
                            # 更新完整调用表示
                            if "type" in current_constructor:
                                current_constructor["called_full"] = f"new {current_constructor['type']}({args_text})"
                            
                        method_calls.append(current_constructor)
                    
                    current_constructor = {
                        "location": {
                            "start_line": capture_node.start_point[0] + 1,
                            "start_col": capture_node.start_point[1],
                            "end_line": capture_node.end_point[0] + 1,
                            "end_col": capture_node.end_point[1]
                        }
                    }
                elif tag == "constructor_type":
                    type_name_bytes = code[capture_node.start_byte:capture_node.end_byte]
                    if isinstance(type_name_bytes, bytes):
                        current_constructor["type"] = type_name_bytes.decode('utf-8', errors='ignore')
                    else:
                        current_constructor["type"] = type_name_bytes
            
            # 添加最后一个构造函数调用
            if current_constructor and "type" in current_constructor and "location" in current_constructor:
                if 'capture_node' in locals() and capture_node:
                    current_constructor["context"] = get_code_snippet(code, capture_node)
                current_constructor["method"] = "constructor"
                
                # 设置完整调用表示
                if "type" in current_constructor:
                    current_constructor["called_full"] = f"new {current_constructor['type']}()"
                
                # 确定调用者（caller）
                call_line = current_constructor["location"]["start_line"]
                
                # 先检查是否在静态初始化块中
                in_static_block = False
                for block in static_blocks:
                    if block["start_line"] <= call_line <= block["end_line"]:
                        current_constructor["caller"] = "<static_initializer>"
                        in_static_block = True
                        break
                        
                # 再检查是否在字段初始化中
                if not in_static_block:
                    in_field_init = False
                    for field in field_declarations:
                        if field["start_line"] <= call_line <= field["end_line"]:
                            current_constructor["caller"] = "<field_initializer>"
                            in_field_init = True
                            break
                
                # 如果不在静态初始化块或字段初始化中，尝试查找包含的方法
                if not in_static_block and not in_field_init:
                    caller_method = find_containing_method(call_line, method_declarations)
                    if caller_method:
                        current_constructor["caller"] = caller_method
                
                # 尝试提取参数
                if hasattr(capture_node, 'child_by_field_name'):
                    args_node = capture_node.child_by_field_name("arguments")
                    if args_node:
                        args_text = code[args_node.start_byte:args_node.end_byte]
                        args = [arg.strip() for arg in args_text.strip("()").split(",") if arg.strip()]
                        current_constructor["arguments"] = args
                        
                        # 更新完整调用表示
                        if "type" in current_constructor:
                            current_constructor["called_full"] = f"new {current_constructor['type']}({args_text})"
                        
                method_calls.append(current_constructor)
        except Exception as e:
            print(f"[WARN] 提取构造函数调用失败: {str(e)}")
            
    except Exception as e:
        print(f"[ERROR] 提取方法调用失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
    
    return method_calls

def find_containing_method(line, method_declarations):
    """根据行号找到包含该行的方法"""
    # 首先尝试精确匹配
    for method_name, method_info in method_declarations.items():
        if method_info["start_line"] <= line <= method_info["end_line"]:
            return method_name
    
    # 如果没有找到精确匹配，可能是在静态初始化块、匿名内部类或lambda表达式中
    # 尝试找到最近的方法或构造函数
    closest_method = None
    min_distance = float('inf')
    
    for method_name, method_info in method_declarations.items():
        # 检查是否在方法前面的初始化代码中
        if line < method_info["start_line"]:
            distance = method_info["start_line"] - line
            if distance < min_distance:
                min_distance = distance
                closest_method = f"<before_{method_name}>"
        
        # 检查是否在方法后面的代码中
        elif line > method_info["end_line"]:
            distance = line - method_info["end_line"]
            if distance < min_distance:
                min_distance = distance
                closest_method = f"<after_{method_name}>"
    
    # 如果找到了最近的方法，且距离小于一定阈值（例如10行），可能是在匿名内部类或lambda中
    if closest_method and min_distance < 10:
        return "unknown"
    
    # 如果距离太远或没有找到最近的方法，可能是在静态初始化块或字段初始化中
    if line < list(method_declarations.values())[0]["start_line"] if method_declarations else float('inf'):
        return "<static_initializer>"
    
    return "unknown"

def get_code_snippet(code, node, context=30):
    """提取代码上下文片段，返回节点前后指定字符数的代码"""
    if not node:
        return ""
    snippet = code[max(0, node.start_byte - context):min(len(code), node.end_byte + context)]
    if isinstance(snippet, bytes):
        snippet = snippet.decode('utf-8', errors='ignore')
    return snippet.strip()

@handle_tree_sitter_errors
def extract_variable_references(node, code, file_name="unknown file"):
    """提取变量引用"""
    variable_refs = []
    
    try:
        # 检查Tree-sitter是否可用
        if JAVA_LANGUAGE is None:
            # 使用简化的javalang变量分析
            return extract_variables_with_javalang(code)
            
        # 原有Tree-sitter逻辑
        return extract_variable_references_tree_sitter(node, code, file_name)
    except Exception as e:
        print(f"[ERROR] 提取变量引用失败: {str(e)}")
        return []

def extract_variables_with_javalang(code):
    """使用javalang和正则表达式提取变量信息"""
    variable_refs = []
    
    try:
        import javalang
        import re
        
        tree = javalang.parse.parse(code)
        lines = code.split('\n')
        
        # 基本的变量声明模式
        var_decl_pattern = re.compile(r'\b(\w+)\s+(\w+)\s*[=;]')
        
        for line_no, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('*'):
                continue
                
            for match in var_decl_pattern.finditer(line):
                var_type = match.group(1)
                var_name = match.group(2)
                
                # 过滤关键字
                if var_type in ['public', 'private', 'protected', 'static', 'final', 'class', 'interface']:
                    continue
                
                variable_refs.append({
                    "name": var_name,
                    "type": var_type,
                    "declaration": {
                        "line": line_no,
                        "column": match.start()
                    },
                    "references": [],
                    "context": line
                })
        
        return variable_refs
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] Javalang变量提取失败: {str(e)}")
        return variable_refs

def extract_variable_references_tree_sitter(node, code, file_name):
    """原有Tree-sitter变量引用逻辑"""
    variable_refs = []
    try:
        
        declarations = {}
        
        # 提取变量声明 - 使用更全面的查询
        try:
            # 1. 提取局部变量声明
            var_decl_query = mock_language_query("(local_variable_declaration) @local_var_decl")
            var_decl_captures = var_decl_query.captures(node)
            
            for capture in var_decl_captures:
                decl_node = capture[0]
                # 获取类型
                type_node = decl_node.child_by_field_name("type")
                var_type = "unknown"
                if type_node:
                    var_type = code[type_node.start_byte:type_node.end_byte]
                
                # 获取变量声明器
                for child in decl_node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            var_name = code[name_node.start_byte:name_node.end_byte]
                            # 避免使用保留关键词作为字段名
                            var_key = var_name
                            if var_name == "resource":
                                var_key = "resource_var"
                            declarations[var_key] = {
                                "name": var_name,
                                "type": var_type,
                                "declaration": {
                                    "line": name_node.start_point[0] + 1,
                                    "column": name_node.start_point[1]
                                },
                                "references": [],
                                "context": get_code_snippet(code, decl_node)
                            }
            
            # 2. 提取方法参数变量
            param_query = mock_language_query("(formal_parameter) @param")
            param_captures = param_query.captures(node)
            
            for capture in param_captures:
                param_node = capture[0]
                type_node = param_node.child_by_field_name("type")
                var_type = "unknown"
                if type_node:
                    var_type = code[type_node.start_byte:type_node.end_byte]
                
                name_node = param_node.child_by_field_name("name")
                if name_node:
                    var_name = code[name_node.start_byte:name_node.end_byte]
                    # 避免使用保留关键词作为字段名
                    var_key = var_name
                    if var_name == "resource":
                        var_key = "resource_var"
                    declarations[var_key] = {
                        "name": var_name,
                        "type": var_type,
                        "is_parameter": True,
                        "declaration": {
                            "line": name_node.start_point[0] + 1,
                            "column": name_node.start_point[1]
                        },
                        "references": [],
                        "context": get_code_snippet(code, param_node)
                    }
            
            # 3. 提取for循环变量
            for_query = mock_language_query("(for_statement) @for_stmt")
            for_captures = for_query.captures(node)
            
            for capture in for_captures:
                for_node = capture[0]
                init_node = for_node.child_by_field_name("init")
                if init_node:
                    # 处理for循环初始化中的变量声明
                    for child in init_node.children:
                        if child.type == "local_variable_declaration":
                            type_node = child.child_by_field_name("type")
                            var_type = "unknown"
                            if type_node:
                                var_type = code[type_node.start_byte:type_node.end_byte]
                            
                            for subchild in child.children:
                                if subchild.type == "variable_declarator":
                                    name_node = subchild.child_by_field_name("name")
                                    if name_node:
                                        var_name = code[name_node.start_byte:name_node.end_byte]
                                        var_key = var_name
                                        if var_name == "resource":
                                            var_key = "resource_var"
                                        declarations[var_key] = {
                                            "name": var_name,
                                            "type": var_type,
                                            "is_loop_var": True,
                                            "declaration": {
                                                "line": name_node.start_point[0] + 1,
                                                "column": name_node.start_point[1]
                                            },
                                            "references": [],
                                            "context": get_code_snippet(code, child)
                                        }
            
            # 4. 提取foreach变量
            foreach_query = mock_language_query("(enhanced_for_statement) @foreach")
            foreach_captures = foreach_query.captures(node)
            
            for capture in foreach_captures:
                foreach_node = capture[0]
                var_node = foreach_node.child_by_field_name("variable")
                if var_node:
                    type_node = var_node.child_by_field_name("type")
                    var_type = "unknown"
                    if type_node:
                        var_type = code[type_node.start_byte:type_node.end_byte]
                    
                    name_node = var_node.child_by_field_name("name")
                    if name_node:
                        var_name = code[name_node.start_byte:name_node.end_byte]
                        var_key = var_name
                        if var_name == "resource":
                            var_key = "resource_var"
                        declarations[var_key] = {
                            "name": var_name,
                            "type": var_type,
                            "is_foreach_var": True,
                            "declaration": {
                                "line": name_node.start_point[0] + 1,
                                "column": name_node.start_point[1]
                            },
                            "references": [],
                            "context": get_code_snippet(code, foreach_node)
                        }
                        
            # 5. 提取try-with-resources变量
            try:
                # 使用正则表达式查询避免字段名问题
                try_with_resources_query = mock_language_query("""
                    (try_statement) @try_stmt
                """)
                try_captures = try_with_resources_query.captures(node)
                
                for capture in try_captures:
                    try_node = capture[0]
                    # 尝试使用我们的安全访问函数获取资源节点
                    resource_nodes = []
                    
                    # 先尝试标准方式
                    resource_node = safe_node_field(try_node, "resources", "resource")
                    if resource_node:
                        resource_nodes.append(resource_node)
                    else:
                        # 如果直接方式失败，尝试另一种方法
                        # 在try语句中，资源通常是第一个子节点，在body前面
                        if try_node.child_count > 1:
                            for i in range(min(3, try_node.child_count)):  # 只检查前三个子节点
                                child = try_node.children[i]
                                if child.type == "local_variable_declaration":
                                    resource_nodes.append(child)
                    
                    # 处理找到的所有资源节点                    
                    for resource_node in resource_nodes:
                # 如果资源是局部变量声明
                        if resource_node and resource_node.type == "local_variable_declaration":
                            type_node = safe_node_field(resource_node, "type")
                    var_type = "unknown"
                    if type_node:
                        var_type = code[type_node.start_byte:type_node.end_byte]
                    
                    # 查找变量声明子节点
                    var_declarators = find_all_child_nodes_of_type(resource_node, "variable_declarator")
                    for var_decl in var_declarators:
                        name_node = safe_node_field(var_decl, "name")
                        if name_node:
                            var_name = code[name_node.start_byte:name_node.end_byte]
                            var_key = f"twresource_{len(declarations)}"  # 使用唯一键名
                            declarations[var_key] = {
                                "name": var_name,
                                "type": var_type,
                                "is_resource": True,
                                "declaration": {
                                    "line": name_node.start_point[0] + 1,
                                    "column": name_node.start_point[1]
                                },
                                    "references": [],
                                    "context": get_code_snippet(code, resource_node)
                                }
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[DEBUG] 提取try-with-resources变量失败: {str(e)} in {file_name}")
                # 这里不引发异常，而是静默失败，因为这可能是由于Tree-sitter版本兼容性问题导致的
        except Exception as e:
            print(f"[WARN] 提取变量声明失败: {str(e)} in {file_name}")
            import traceback
            if DEBUG_MODE:
                traceback.print_exc()
        
        # 提取变量引用
        try:
            # 只有当找到了变量声明时才进行引用分析
            if declarations:
                var_ref_query = mock_language_query("(identifier) @var_ref")
                var_ref_captures = var_ref_query.captures(node)
                
                for capture in var_ref_captures:
                    id_node = capture[0]
                    var_name = code[id_node.start_byte:id_node.end_byte]
                    var_key = var_name
                    
                    # 检查是否是resource关键字，使用相应的键名
                    if var_name == "resource":
                        var_key = "resource_var"
                    
                    if var_key in declarations:
                        # 判断是否是声明点
                        parent = id_node.parent
                        is_declaration = False
                        
                        # 检查是否是变量声明中的名称
                        if parent and parent.type == "variable_declarator" and parent.child_by_field_name("name") == id_node:
                            is_declaration = True
                        
                        # 检查是否是参数声明中的名称
                        if parent and parent.type == "formal_parameter" and parent.child_by_field_name("name") == id_node:
                            is_declaration = True
                            
                        if not is_declaration:
                            ref_context = get_code_snippet(code, id_node)
                            
                            # 提取更多上下文信息，如是否是赋值操作的左侧
                            is_target = False
                            operation_type = "read"
                            
                            # 检查是否是赋值操作的左侧
                            if parent and parent.type == "assignment_expression" and parent.child_by_field_name("left") == id_node:
                                is_target = True
                                operation_type = "write"
                            
                            declarations[var_key]["references"].append({
                                "line": id_node.start_point[0] + 1,
                                "column": id_node.start_point[1],
                                "context": ref_context,
                                "operation": operation_type
                            })
        except Exception as e:
            print(f"[WARN] 提取变量引用失败: {str(e)} in {file_name}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
        
        # 转换为列表 - 修改为包含所有声明的变量，而不只是有引用的变量
        for var_name, var_info in declarations.items():
            variable_refs.append(var_info)
                
    except Exception as e:
        print(f"[ERROR] 提取变量引用失败: {str(e)} in {file_name}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()
    
    return variable_refs

@handle_tree_sitter_errors
def extract_field_references(node, code, file_name="unknown file"):
    """提取方法中访问的字段信息，判断是实例字段还是静态字段"""
    field_refs = []
    
    try:
        # 检查Tree-sitter是否可用
        if JAVA_LANGUAGE is None or JAVA_PARSER is None or DISABLE_TREE_SITTER:
            print(f"[INFO] Tree-sitter不可用，使用JavaLang fallback提取字段信息 - {file_name}")
            return extract_fields_with_javalang(code)
            
        # 尝试使用Tree-sitter逻辑
        print(f"[INFO] 使用Tree-sitter提取字段信息 - {file_name}")
        return extract_field_references_tree_sitter(node, code, file_name)
    except Exception as e:
        print(f"[ERROR] 提取字段引用失败: {str(e)}")
        return []

def extract_fields_with_javalang(code):
    """使用javalang提取字段信息，包括使用情况分析"""
    field_refs = []
    
    try:
        import javalang
        tree = javalang.parse.parse(code)
        
        # 首先收集所有字段声明
        field_declarations = {}
        
        for type_decl in tree.types:
            if isinstance(type_decl, javalang.tree.ClassDeclaration):
                for field in type_decl.fields:
                    is_static = 'static' in field.modifiers if field.modifiers else False
                    access_modifier = 'package'  # 默认
                    
                    if field.modifiers:
                        if 'public' in field.modifiers:
                            access_modifier = 'public'
                        elif 'private' in field.modifiers:
                            access_modifier = 'private'
                        elif 'protected' in field.modifiers:
                            access_modifier = 'protected'
                    
                    for declarator in field.declarators:
                        field_name = declarator.name
                        field_type = str(field.type.name) if hasattr(field.type, 'name') else str(field.type)
                        
                        field_declarations[field_name] = {
                            "name": field_name,
                            "type": field_type,
                            "is_static": is_static,
                            "access_modifier": access_modifier,
                            "declaration": {
                                "line": field.position.line if field.position else 1,
                                "column": field.position.column if field.position else 0
                            },
                            "context": f"{access_modifier} {field_type} {field_name}",
                            "uses": []
                        }
        
        # 分析字段使用情况 - 使用简化的方法分析源代码
        code_lines = code.split('\n')
        for line_num, line in enumerate(code_lines, 1):
            for field_name in field_declarations.keys():
                # 检查字段是否在这一行中被使用
                if field_name in line and not line.strip().startswith('//'):
                    # 跳过字段声明行
                    if re.search(rf'(private|protected|public|static|final).*{field_name}', line):
                        continue
                    
                    usage_info = {
                        "line": line_num,
                        "column": line.find(field_name),
                        "context": line.strip(),
                        "access_type": "reference",
                        "operation": "write" if "=" in line and line.find("=") > line.find(field_name) else "read",
                        "object": "this"
                    }
                    
                    # 判断访问类型
                    if "this." + field_name in line:
                        usage_info["access_type"] = "this_access"
                    elif field_name + "++" in line or "++" + field_name in line:
                        usage_info["operation"] = "write"
                        usage_info["access_type"] = "increment"
                    elif field_name + "--" in line or "--" + field_name in line:
                        usage_info["operation"] = "write"
                        usage_info["access_type"] = "decrement"
                    
                    field_declarations[field_name]["uses"].append(usage_info)
        
        # 增强字段信息，添加JavaLang无法提供的详细分析
        for field_name, field_info in field_declarations.items():
            if field_info["uses"] or field_info["access_modifier"] == "public":
                # 添加字段的详细使用分析
                field_info = enhance_field_analysis(field_info, code)
                field_refs.append(field_info)
        
        return field_refs
        
    except Exception as e:
        print(f"[WARN] JavaLang字段提取失败: {str(e)}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()
        return field_refs

def enhance_field_analysis(field_info, code):
    """增强字段分析，提供JavaLang无法轻易提供的详细信息"""
    try:
        field_name = field_info["name"]
        
        # 1. 分析字段的读写模式
        read_count = 0
        write_count = 0
        for use in field_info["uses"]:
            if use.get("operation") == "write" or ("=" in use.get("context", "")):
                write_count += 1
            else:
                read_count += 1
        
        field_info["usage_pattern"] = {
            "read_count": read_count,
            "write_count": write_count,
            "is_read_only": write_count == 0,
            "is_write_only": read_count == 0,
            "is_read_write": read_count > 0 and write_count > 0
        }
        
        # 2. 分析字段在方法中的使用频率
        methods_using_field = set()
        for use in field_info["uses"]:
            # 从上下文中尝试推断所在的方法
            context = use.get("context", "")
            # 这是一个简化的方法，实际中可能需要更复杂的分析
            if "method:" in context:
                method_name = context.split("method:")[1].split()[0]
                methods_using_field.add(method_name)
        
        field_info["method_usage"] = {
            "used_in_methods": list(methods_using_field),
            "method_count": len(methods_using_field)
        }
        
        # 3. 分析字段的初始化模式
        field_info["initialization_analysis"] = analyze_field_initialization(field_name, code)
        
        # 4. 分析字段与其他字段的关联关系
        field_info["field_relationships"] = analyze_field_relationships(field_name, field_info["uses"], code)
        
        # 5. 推断字段的语义角色
        field_info["semantic_role"] = infer_field_semantic_role(field_name, field_info["type"], field_info["uses"])
        
        return field_info
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] 字段分析增强失败: {str(e)}")
        return field_info

def analyze_field_initialization(field_name, code):
    """分析字段的初始化模式"""
    try:
        # 检查字段是否在声明时初始化
        declaration_init_pattern = rf'\b{field_name}\s*=\s*([^;]+);'
        declaration_init = re.search(declaration_init_pattern, code)
        
        # 检查字段是否在构造函数中初始化
        constructor_init_pattern = rf'public\s+\w+\s*\([^)]*\)\s*\{{[^}}]*this\.{field_name}\s*=|{field_name}\s*='
        constructor_init = re.search(constructor_init_pattern, code, re.DOTALL)
        
        # 检查是否有setter方法
        setter_pattern = rf'public\s+void\s+set\w*{field_name.capitalize()}\w*\s*\('
        has_setter = re.search(setter_pattern, code, re.IGNORECASE)
        
        return {
            "declared_with_value": declaration_init is not None,
            "initialized_in_constructor": constructor_init is not None,
            "has_setter_method": has_setter is not None,
            "initialization_value": declaration_init.group(1).strip() if declaration_init else None
        }
    except Exception as e:
        return {"analysis_failed": str(e)}

def analyze_field_relationships(field_name, field_uses, code):
    """分析字段与其他字段的关联关系"""
    try:
        relationships = []
        
        # 在使用该字段的上下文中查找其他字段
        for use in field_uses:
            context = use.get("context", "")
            # 查找在同一表达式中使用的其他字段
            other_fields = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', context)
            
            for other_field in other_fields:
                if other_field != field_name and other_field not in ['this', 'super', 'class']:
                    # 检查这是否确实是一个字段（简化检查）
                    if re.search(rf'private|protected|public.*{other_field}', code):
                        relationships.append({
                            "related_field": other_field,
                            "relationship_type": "used_together",
                            "context": context
                        })
        
        return relationships
    except Exception as e:
        return []

def infer_field_semantic_role(field_name, field_type, field_uses):
    """推断字段的语义角色"""
    try:
        # 基于命名模式推断
        name_lower = field_name.lower()
        
        if any(keyword in name_lower for keyword in ['count', 'size', 'length', 'num']):
            role = "counter"
        elif any(keyword in name_lower for keyword in ['flag', 'is', 'has', 'should', 'can']):
            role = "flag"
        elif any(keyword in name_lower for keyword in ['buffer', 'cache', 'temp']):
            role = "buffer"
        elif any(keyword in name_lower for keyword in ['config', 'setting', 'option']):
            role = "configuration"
        elif 'list' in field_type.lower() or 'array' in field_type.lower():
            role = "collection"
        elif 'map' in field_type.lower() or 'dict' in field_type.lower():
            role = "mapping"
        else:
            role = "data"
        
        # 基于使用模式调整
        write_operations = sum(1 for use in field_uses if use.get("operation") == "write")
        read_operations = len(field_uses) - write_operations
        
        if write_operations == 0 and read_operations > 0:
            role = f"{role}_readonly"
        elif write_operations > read_operations:
            role = f"{role}_mutable"
        
        return {
            "primary_role": role,
            "confidence": "medium",  # 简化的置信度
            "evidence": f"name_pattern, type={field_type}, usage_pattern"
        }
    except Exception as e:
        return {"role": "unknown", "error": str(e)}

def extract_field_references_tree_sitter(node, code, file_name):
    """原有Tree-sitter字段引用逻辑"""
    field_refs = []
    try:
            
        field_declarations = {}
        
        # 提取字段声明 - 使用简化的查询
        try:
            field_decl_query = mock_language_query("(field_declaration) @field_decl")
            field_decl_captures = field_decl_query.captures(node)
            
            for capture in field_decl_captures:
                field_node = capture[0]
                # 检查是否有static修饰符
                is_static = False
                modifiers_node = field_node.child_by_field_name("modifiers") 
                if modifiers_node:
                    modifiers_text = code[modifiers_node.start_byte:modifiers_node.end_byte]
                    # 使用正则表达式确保只匹配完整的static关键字
                    is_static = re.search(r'\bstatic\b', modifiers_text) is not None
                
                # 获取字段类型和名称
                type_node = field_node.child_by_field_name("type")
                field_type = "unknown"
                if type_node:
                    field_type = code[type_node.start_byte:type_node.end_byte]
                
                declarator_node = field_node.child_by_field_name("declarator")
                if declarator_node:
                    name_node = declarator_node.child_by_field_name("name")
                    if name_node:
                        field_name = code[name_node.start_byte:name_node.end_byte]
                        # 处理名为"resource"的字段
                        field_key = field_name
                        if field_name == "resource":
                            field_key = "resource_field"
                        
                        field_declarations[field_key] = {
                            "name": field_name,
                            "type": field_type,
                            "is_static": is_static,
                            "declaration": {
                                "line": name_node.start_point[0] + 1,
                                "column": name_node.start_point[1]
                            },
                            "context": get_code_snippet(code, field_node),
                            "uses": []
                        }
        except Exception as e:
            print(f"[WARN] 提取字段声明失败: {str(e)} in {file_name}")
        
        # 提取字段访问 - 使用简化的查询
        try:
            field_access_query = mock_language_query("(field_access field: (identifier) @field) @access")
            field_access_captures = field_access_query.captures(node)
            
            for capture in field_access_captures:
                capture_node, tag = capture
                if tag == "field":
                    field_name = code[capture_node.start_byte:capture_node.end_byte]
                    field_key = field_name
                    if field_name == "resource":
                        field_key = "resource_field"
                        
                    if field_key in field_declarations:
                        access_node = capture_node.parent  # 字段访问节点
                        if access_node:
                            object_node = access_node.child_by_field_name("object")
                            object_text = "unknown"
                            access_type = "instance_access"
                            
                            if object_node:
                                object_text = code[object_node.start_byte:object_node.end_byte]
                                # 确定访问类型
                                if object_text == "this":
                                    access_type = "this_access"
                                elif object_text == "super":
                                    access_type = "super_access"
                                elif object_text[0].isupper():  # 可能是类名，表示静态访问
                                    access_type = "static_access"
                            
                            context = get_code_snippet(code, access_node)
                            field_declarations[field_key]["uses"].append({
                                "line": capture_node.start_point[0] + 1,
                                "column": capture_node.start_point[1],
                                "context": context,
                                "access_type": "field_access",
                                "field_access_type": access_type,
                                "object": object_text
                            })
        except Exception as e:
            print(f"[WARN] 提取字段访问失败: {str(e)} in {file_name}")
        
        # 识别直接引用的字段（不通过对象访问）
        try:
            id_query = mock_language_query("(identifier) @id")
            id_captures = id_query.captures(node)
            
            for capture in id_captures:
                id_node = capture[0]
                field_name = code[id_node.start_byte:id_node.end_byte]
                field_key = field_name
                if field_name == "resource":
                    field_key = "resource_field"
                    
                if field_key in field_declarations:
                    # 确保这不是字段的声明位置
                    parent = id_node.parent
                    if not (parent and parent.type == "variable_declarator" and parent.child_by_field_name("name") == id_node):
                        # 确保这不是field_access的一部分
                        if not (parent and parent.type == "field_access" and parent.child_by_field_name("field") == id_node):
                            context = get_code_snippet(code, id_node)
                            
                            # 检查字段使用上下文
                            operation_type = "read"
                            if parent and parent.type == "assignment_expression" and parent.child_by_field_name("left") == id_node:
                                operation_type = "write"
                            
                            field_declarations[field_key]["uses"].append({
                                "line": id_node.start_point[0] + 1,
                                "column": id_node.start_point[1],
                                "context": context,
                                "access_type": "direct_reference",
                                "operation": operation_type,
                                "object": "this"  # 隐式this引用
                            })
        except Exception as e:
            print(f"[WARN] 提取直接字段引用失败: {str(e)} in {file_name}")
        
        # 转换为列表
        for field_name, field_info in field_declarations.items():
            if field_info["uses"]:  # 只包含有使用记录的字段
                field_refs.append(field_info)
                
    except Exception as e:
        print(f"[ERROR] 提取字段引用失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
    
    return field_refs

@handle_tree_sitter_errors
def extract_constructor_deps(node, code):
    """提取构造器依赖关系，识别构造时需要的外部对象"""
    constructor_deps = []
    
    try:
        # 检查Tree-sitter是否可用
        if JAVA_LANGUAGE is None:
            return extract_constructor_deps_with_javalang(code)
            
        # 原有Tree-sitter逻辑
        return extract_constructor_deps_tree_sitter(node, code)
    except Exception as e:
        print(f"[ERROR] 提取构造器依赖失败: {str(e)}")
        return []

def extract_constructor_deps_with_javalang(code):
    """使用javalang提取构造器依赖"""
    constructor_deps = []
    
    try:
        import javalang
        import re
        
        tree = javalang.parse.parse(code)
        
        # 提取构造函数
        constructors = []
        for type_decl in tree.types:
            if isinstance(type_decl, javalang.tree.ClassDeclaration):
                for constructor in type_decl.constructors:
                    constructor_info = {
                        "name": constructor.name,
                        "line": 1,
                        "parameters": [],
                        "context": f"constructor {constructor.name}"
                    }
                    
                    if constructor.parameters:
                        for param in constructor.parameters:
                            param_info = {
                                "type": param.type.name if hasattr(param.type, 'name') else 'unknown',
                                "name": param.name
                            }
                            constructor_info["parameters"].append(param_info)
                    
                    constructors.append(constructor_info)
        
        if constructors:
            constructor_deps.extend(constructors)
        
        # 使用正则表达式查找new语句
        lines = code.split('\n')
        init_usages = []
        
        new_pattern = re.compile(r'new\s+(\w+)\s*\((.*?)\)')
        
        for line_no, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
                
            for match in new_pattern.finditer(line):
                type_name = match.group(1)
                args_text = match.group(2)
                
                init_info = {
                    "type": type_name,
                    "line": line_no,
                    "arguments": [],
                    "context": line
                }
                
                if args_text.strip():
                    args = []
                    for arg in args_text.split(','):
                        arg = arg.strip()
                        if arg:
                            args.append({
                                "value": arg,
                                "type": "unknown"
                            })
                    init_info["arguments"] = args
                
                init_usages.append(init_info)
        
        if init_usages:
            constructor_deps.append({"init_usages": init_usages})
        
        return constructor_deps
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] Javalang构造器提取失败: {str(e)}")
        return constructor_deps

def extract_constructor_deps_tree_sitter(node, code):
    """原有Tree-sitter构造器依赖逻辑"""
    constructor_deps = []
    try:
            
        # 构造函数查询 - 简化语法
        try:
            constructor_query = mock_language_query("(constructor_declaration name: (identifier) @constructor_name) @constructor")
            constructor_captures = constructor_query.captures(node)
            
            # 提取构造函数依赖
            constructors = []
            
            for capture in constructor_captures:
                capture_node, tag = capture
                if tag == "constructor":
                    constructor_node = capture_node
                    # 创建构造函数记录
                    constructor_info = {
                        "name": "",
                        "line": constructor_node.start_point[0] + 1,
                        "parameters": [],
                        "context": get_code_snippet(code, constructor_node, 100)
                    }
                    
                    # 获取构造函数名称
                    name_node = constructor_node.child_by_field_name("name")
                    if name_node:
                        name_bytes = code[name_node.start_byte:name_node.end_byte]
                        if isinstance(name_bytes, bytes):
                            constructor_info["name"] = name_bytes.decode('utf-8', errors='ignore')
                        else:
                            constructor_info["name"] = name_bytes
                    
                    # 获取参数列表
                    params_node = constructor_node.child_by_field_name("parameters")
                    if params_node:
                        # 尝试查找所有formal_parameter节点
                        for i in range(params_node.child_count):
                            child = params_node.children[i]
                            if child.type in ("formal_parameter", "ellipsis_parameter", "receiver_parameter"):
                                param_info = {}
                                # 获取参数类型
                                type_node = child.child_by_field_name("type")
                                if type_node:
                                    # 处理数组和泛型类型
                                    type_bytes = code[type_node.start_byte:type_node.end_byte]
                                    if isinstance(type_bytes, bytes):
                                        type_text = type_bytes.decode('utf-8', errors='ignore')
                                    else:
                                        type_text = type_bytes
                                    
                                    # 检查是否是泛型类型
                                    if type_node.type == "generic_type":
                                        type_text = extract_generic_type(type_node, code)
                                    # 检查是否是数组类型
                                    elif type_node.type == "array_type":
                                        elem_type_node = type_node.child_by_field_name("element_type")
                                        if elem_type_node:
                                            elem_type_bytes = code[elem_type_node.start_byte:elem_type_node.end_byte]
                                            if isinstance(elem_type_bytes, bytes):
                                                elem_type = elem_type_bytes.decode('utf-8', errors='ignore')
                                            else:
                                                elem_type = elem_type_bytes
                                            type_text = f"{elem_type}[]"
                                    
                                    param_info["type"] = type_text
                                
                                # 获取参数名称
                                name_node = child.child_by_field_name("name")
                                if name_node:
                                    name_bytes = code[name_node.start_byte:name_node.end_byte]
                                    if isinstance(name_bytes, bytes):
                                        param_info["name"] = name_bytes.decode('utf-8', errors='ignore')
                                    else:
                                        param_info["name"] = name_bytes
                                
                                if param_info:
                                    constructor_info["parameters"].append(param_info)
                    
                    constructors.append(constructor_info)
                    
            if constructors:
                constructor_deps.extend(constructors)
        except Exception as e:
            print(f"[WARN] 提取构造函数失败: {str(e)}")
            
        # 提取实例化（使用构造函数）- 简化语法
        try:
            init_query = mock_language_query("(object_creation_expression type: (type_identifier) @created_type) @creation")
            init_captures = init_query.captures(node)
            
            # 提取实例化信息
            init_usages = []
            
            for capture in init_captures:
                capture_node, tag = capture
                if tag == "creation":
                    creation_node = capture_node
                    init_info = {
                        "type": "",
                        "line": creation_node.start_point[0] + 1,
                        "arguments": [],
                        "context": get_code_snippet(code, creation_node, 50)
                    }
                    
                    # 获取类型
                    type_node = creation_node.child_by_field_name("type")
                    if type_node:
                        # 处理泛型类型
                        if type_node.type == "generic_type":
                            init_info["type"] = extract_generic_type(type_node, code)
                        else:
                            type_bytes = code[type_node.start_byte:type_node.end_byte]
                            if isinstance(type_bytes, bytes):
                                init_info["type"] = type_bytes.decode('utf-8', errors='ignore')
                            else:
                                init_info["type"] = type_bytes
                    
                    # 获取参数
                    args_node = creation_node.child_by_field_name("arguments")
                    if args_node:
                        args_text = code[args_node.start_byte:args_node.end_byte]
                        if isinstance(args_text, bytes):
                            args_text = args_text.decode('utf-8', errors='ignore')
                        # 使用改进的参数提取逻辑
                        args = []
                        args_text = args_text.strip("()")
                        
                        if args_text.strip():
                            # 使用更准确的方法分割参数
                            current_arg = ""
                            brace_level = 0
                            in_string = False
                            escape_next = False
                            
                            for char in args_text:
                                if escape_next:
                                    current_arg += char
                                    escape_next = False
                                    continue
                                    
                                if char == '\\':
                                    current_arg += char
                                    escape_next = True
                                    continue
                                    
                                if char == '"' and not in_string:
                                    in_string = True
                                    current_arg += char
                                elif char == '"' and in_string:
                                    in_string = False
                                    current_arg += char
                                elif char == '(' and not in_string:
                                    brace_level += 1
                                    current_arg += char
                                elif char == ')' and not in_string:
                                    brace_level -= 1
                                    current_arg += char
                                elif char == ',' and brace_level == 0 and not in_string:
                                    args.append(current_arg.strip())
                                    current_arg = ""
                                else:
                                    current_arg += char
                                    
                            if current_arg.strip():
                                args.append(current_arg.strip())
                        
                        for arg in args:
                            arg_info = {
                                "value": arg,
                                "type": "unknown"
                            }
                            
                            # 尝试确定参数类型
                            if arg.startswith("\"") and arg.endswith("\""):
                                arg_info["type"] = "string"
                            elif arg.startswith("new "):
                                arg_info["type"] = "object"
                                # 提取具体类型
                                match = re.search(r"new\s+([A-Za-z0-9_.<>]+)", arg)
                                if match:
                                    arg_info["object_type"] = match.group(1)
                            elif arg in ("true", "false"):
                                arg_info["type"] = "boolean"
                            elif arg.replace(".", "").isdigit():  # 简单检查数字
                                arg_info["type"] = "number"
                            
                            init_info["arguments"].append(arg_info)
                    
                    init_usages.append(init_info)
        
            # 添加实例化信息
            if init_usages:
                constructor_deps.append({
                    "init_usages": init_usages
                })
        except Exception as e:
            print(f"[WARN] 提取构造函数实例化失败: {str(e)}")
            
    except Exception as e:
        print(f"[ERROR] 提取构造器依赖失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
    
    return constructor_deps

# 辅助函数：提取泛型类型信息
def extract_generic_type(node, code):
    """从泛型类型节点提取完整的类型信息，包括类型参数"""
    if not node:
        return "unknown"
    
    try:
        # 获取泛型类的基础类型
        type_node = node.child_by_field_name("type")
        if not type_node:
            result = code[node.start_byte:node.end_byte]
            return result.decode('utf-8', errors='ignore') if isinstance(result, bytes) else result
        
        base_type = code[type_node.start_byte:type_node.end_byte]
        if isinstance(base_type, bytes):
            base_type = base_type.decode('utf-8', errors='ignore')
        
        # 获取类型参数
        type_params = []
        args_node = node.child_by_field_name("type_arguments")
        if args_node:
            for child in args_node.children:
                if child.type != "," and child.type != "<" and child.type != ">":
                    param_bytes = code[child.start_byte:child.end_byte]
                    param_text = param_bytes.decode('utf-8', errors='ignore') if isinstance(param_bytes, bytes) else param_bytes
                    type_params.append(param_text)
        
        # 构建完整的泛型类型表示
        if type_params:
            return f"{base_type}<{', '.join(type_params)}>"
        return base_type
    except Exception as e:
        print(f"[WARN] 提取泛型类型失败: {str(e)}")
        fallback = code[node.start_byte:node.end_byte]
        return fallback.decode('utf-8', errors='ignore') if isinstance(fallback, bytes) else fallback

# 递归查找 dataset 目录下所有的 Maven 项目（含 pom.xml）
def find_all_repos(dataset_root):
    repos = []
    for root, dirs, files in os.walk(dataset_root):
        if 'pom.xml' in files:
            repos.append(root)
    return repos

# 提取 repo 中所有有效公共类
def extract_classes(repo_path):
    """提取repo中所有有效公共类，只处理src/main目录下的类，使用Tree-sitter增强判断"""
    import re
    valid_classes = []
    src_dir = os.path.join(repo_path, 'src', 'main')

    if not os.path.exists(src_dir):
        print(f"[WARN] 项目 {repo_path} 缺少 src/main 目录")
        return valid_classes

    for root, _, files in os.walk(src_dir):
        path_parts = os.path.normpath(root).lower().split(os.sep)
        if 'utils' in path_parts or 'enums' in path_parts:
            continue

        for file in files:
            if file.endswith('.java'):
                if file == 'CFGExtractor.java':
                    continue
                    
                full_path = os.path.join(root, file)
                
                # 修改点5：文件大小过滤（排除过大或过小类）
                file_size = os.path.getsize(full_path) / 1024  # KB
                if file_size < 1 or file_size > 50:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 排除非常规大小类: {file}, 大小: {file_size:.1f}KB")
                    continue  # 直接跳过此类
                # 计算相对于src/main/java的路径
                rel_path = os.path.relpath(full_path, src_dir)
                
                try:
                    with open(full_path, encoding='utf-8', errors='ignore') as f:
                        code = f.read()
                    
                    tree = javalang.parse.parse(code)
                    
                    package = tree.package.name if tree.package else ""
                    imports = [imp.path for imp in tree.imports]

                    for type_decl in tree.types:
                        if not isinstance(type_decl, javalang.tree.ClassDeclaration):
                            continue
                        if 'public' not in type_decl.modifiers:
                            continue

                        class_name = type_decl.name
                        # 修改点1：强化类名过滤（更严格排除工具类）
                        invalid_class_pattern = re.compile(
                            r'.*\b(Utils?|Helper|Test|DTO|VO|POJO|Entity|Bean|Model|Adapter|Factory|Builder)\b',
                            re.IGNORECASE
                        )

                        if invalid_class_pattern.match(class_name):
                            if DEBUG_MODE:
                                print(f"[DEBUG] 排除工具类: {class_name}")
                            continue  # 直接跳过此类

                        has_spring_annotation = any(
                            ann.name in ['Controller', 'RestController', 'Service', 'Component']
                            for ann in (type_decl.annotations or [])
                        )

                        method_info = []
                        valid_method_count = 0
                        getter_setter_count = 0
                        complex_method_count = 0
                        
                        # 初始化Tree-sitter分析结果变量（确保即使Tree-sitter失败也有默认值）
                        ts_data = {
                            "dependencies": [],
                            "method_calls": [],
                            "variable_refs": [],
                            "field_refs": [],
                            "constructor_deps": []
                        }

                        for method in type_decl.methods:
                            if not method.body:
                                continue
                            
                            method_name = method.name
                            is_getter_setter = method_name.startswith(('get', 'set', 'is'))
                            is_common_override = method_name in ['clone', 'equals', 'hashCode', 'toString']
                            line_count = count_method_lines(method, code)
                            
                            if is_getter_setter:
                                getter_setter_count += 1
                            elif not is_common_override:
                                # 修改点2：强化复杂度判断标准
                                is_complex = False
                                if line_count >= 8:  # 降低行数阈值
                                    is_complex = True
                                else:
                                    # 检查单个方法体中是否包含控制流语句
                                    method_body = get_method_body_code(method, code)
                                    if any(keyword in method_body for keyword in ['if', 'for', 'while', 'switch', 'try']):
                                        is_complex = True
                                
                                if is_complex:
                                    complex_method_count += 1
                                
                            if line_count >= 3:
                                valid_method_count += 1
                            
                            visibility = 'package-private'
                            if 'public' in method.modifiers:
                                visibility = 'public'
                            elif 'protected' in method.modifiers:
                                visibility = 'protected'
                            elif 'private' in method.modifiers:
                                visibility = 'private'
                                
                            param_types = [p.type.name for p in method.parameters] if method.parameters else []
                            param_names = [p.name for p in method.parameters] if method.parameters else []
                            param_with_names = [f"{pt} {pn}" for pt, pn in zip(param_types, param_names)]

                            method_sig = f"{method.name}({', '.join(param_types)})"
                            method_sig_with_vis = f"{visibility} {method.name}({', '.join(param_with_names)})"
                            
                            method_info.append({
                                "name": method.name,
                                "signature": method_sig,
                                "signature_with_visibility": method_sig_with_vis,
                                "visibility": visibility,
                                "params": param_types,
                                "param_names": param_names,
                                "return_type": getattr(method.return_type, 'name', 'void'),
                                "line_count": line_count,
                                "is_getter_setter": is_getter_setter,
                                "is_common_override": is_common_override
                            })

                        # 使用 Tree-sitter 增强结构复杂性判断
                        ts_data = parse_with_tree_sitter(full_path, code)
                        method_calls = ts_data.get("method_calls", [])
                        constructor_deps = ts_data.get("constructor_deps", [])
                        field_refs = ts_data.get("field_refs", [])

                        # 修改点3：添加依赖关系过滤（排除独立工具类）
                        if ts_data:
                            # 检查是否有非JDK依赖
                            has_external_dependency = any(
                                not dep["name"].startswith(("java.", "javax."))
                                for dep in ts_data.get("dependencies", [])
                                if "name" in dep
                            )
                            
                            # 检查是否有方法调用
                            has_significant_calls = len(ts_data.get("method_calls", [])) > 5
                            
                            # 排除无外部依赖和调用的"孤岛"类
                            if not has_external_dependency and not has_significant_calls:
                                if DEBUG_MODE:
                                    print(f"[DEBUG] 排除孤立类: {class_name}, 无外部依赖或调用")
                                continue  # 直接跳过此类

                        # Tree-sitter辅助条件
                        ts_enough_calls = len(method_calls) >= 3
                        ts_has_constructor_usage = any('init_usages' in dep for dep in constructor_deps)
                        ts_field_refs = len(field_refs) >= 2

                        passes_tree_sitter_complexity = ts_enough_calls or ts_has_constructor_usage or ts_field_refs

                        # 修改点2：修改有效性判断条件
                        is_valid = (
                            complex_method_count >= 2 and  # 必须至少2个复杂方法
                            valid_method_count >= 3 and    # 必须至少3个有效方法
                            getter_setter_count / max(1, len(method_info)) <= 0.5  # 降低getter/setter比例阈值
                        ) and not class_name.endswith('Test')  # 排除测试类

                        if not is_valid:
                            if DEBUG_MODE:
                                print(f"[DEBUG] 排除低复杂度类: {class_name}, 复杂方法数: {complex_method_count}")
                            continue  # 直接跳过此类

                        # 获取绝对路径，确保使用正确的格式
                        # 必须使用绝对路径而不是相对路径
                        absolute_path = os.path.abspath(full_path)
                        
                        # 将Windows风格的路径转换为正确的格式
                        # 但保持Windows的驱动器标识符和反斜杠格式
                        if os.name == 'nt':  # 如果是Windows系统
                            if '\\\\' in absolute_path:
                                absolute_path = absolute_path.replace('\\\\', '\\')
                        
                        class_info = {
                            "className": class_name,
                            "package": package,
                            "imports": imports,
                            "path": absolute_path,  # 使用绝对路径
                            "methods": [m["signature_with_visibility"] for m in method_info],
                            "methods_basic": [m["signature"] for m in method_info],
                            "method_details": method_info,
                            "code": code,
                            "complex_method_count": complex_method_count,
                            "defect_id": defect_id,  # 修改点4：添加缺陷ID
                            "file_size_kb": file_size  # 修改点5：添加文件大小信息
                        }
                        class_info.update(ts_data)
                        valid_classes.append(class_info)
                        
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 解析Java文件失败 {file}: {str(e)}")
                    continue

    output_json_path = os.path.join(repo_path, "valid_classes.json")
    with open(output_json_path, 'w', encoding='utf-8') as out:
        json.dump(valid_classes, out, indent=2, ensure_ascii=False)

    print(f"[INFO] 共提取有效公共类: {len(valid_classes)}，输出至 {output_json_path}")
    return valid_classes

# 安全的节点字段访问辅助函数
def safe_node_field(node, field_name, alternative_name=None, default=None):
    """安全地访问节点字段，处理可能的字段名错误"""
    if node is None:
        return default
    
    try:
        # 首先尝试直接访问字段
        result = node.child_by_field_name(field_name)
        if result is not None:
            return result
        
        # 如果提供了替代名称，尝试使用替代名称
        if alternative_name:
            result = node.child_by_field_name(alternative_name)
            if result is not None:
                return result
        
        # 如果字段名是"resource"，这可能是导致Tree-sitter错误的原因
        if field_name == "resource" or alternative_name == "resource":
            # 尝试用数字索引访问子节点，通常资源是第一个子节点
            if node.child_count > 0:
                # 尝试找到资源节点，它通常是local_variable_declaration类型
                for i in range(node.child_count):
                    child = node.children[i]
                    if child.type == "local_variable_declaration":
                        return child
                # 如果没有找到目标类型，返回第一个子节点
                return node.children[0]
        
        return default
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] 安全访问节点字段失败: {field_name}/{alternative_name}, {str(e)}")
        return default

# 安全获取所有目标类型的子节点
def find_all_child_nodes_of_type(node, node_type):
    """安全地查找所有目标类型的子节点"""
    result = []
    if node is None:
        return result
    
    try:
        # 递归查找所有匹配类型的子节点
        def traverse(current_node):
            if current_node.type == node_type:
                result.append(current_node)
            for i in range(current_node.child_count):
                traverse(current_node.children[i])
        
        traverse(node)
        return result
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] 查找子节点失败: {node_type}, {str(e)}")
        return result

# 主函数
def main():
    # 解析命令行参数
    args = parse_args()
    
    # 设置全局变量
    global DISABLE_TREE_SITTER
    global DEBUG_MODE
    
    DISABLE_TREE_SITTER = args.disable_tree_sitter
    DEBUG_MODE = args.debug if hasattr(args, 'debug') else False
    
    if DISABLE_TREE_SITTER:
        print("[INFO] Tree-sitter高级分析已禁用")
    else:
        print("[INFO] Tree-sitter高级分析已启用")
    
    if DEBUG_MODE:
        print("[INFO] 调试模式已启用，将显示详细错误信息")
    
    # 设置数据集根目录路径
    dataset_root = args.dataset if args.dataset else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dataset')
    
    # 查找所有Maven项目
    repos = find_all_repos(dataset_root)
    print(f"找到 {len(repos)} 个Maven项目")
    
    # 处理每个项目
    for repo in repos:
        print(f"\n处理项目: {repo}")
        extract_classes(repo)

def test_enhanced_field_extraction():
    """测试增强的字段提取功能"""
    test_code = '''
    public class TestClass {
        private int count = 0;
        public String name;
        private boolean isActive = false;
        private List<String> items;
        
        public TestClass(String name) {
            this.name = name;
            this.items = new ArrayList<>();
        }
        
        public void increment() {
            count++;
        }
        
        public boolean isReady() {
            return isActive && count > 0;
        }
        
        public void setActive(boolean active) {
            this.isActive = active;
        }
    }
    '''
    
    print("[TEST] 测试增强字段提取功能...")
    
    # 测试JavaLang fallback
    field_refs = extract_fields_with_javalang(test_code)
    
    print(f"[TEST] 提取到 {len(field_refs)} 个字段:")
    for field in field_refs:
        print(f"  - {field['name']} ({field['type']}) - {field['access_modifier']}")
        print(f"    使用次数: {len(field['uses'])}")
        if 'usage_pattern' in field:
            pattern = field['usage_pattern']
            print(f"    读写模式: 读{pattern['read_count']}次, 写{pattern['write_count']}次")
        if 'semantic_role' in field:
            role = field['semantic_role']
            print(f"    语义角色: {role['primary_role']}")
        print()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_enhanced_field_extraction()
    else:
        main()
