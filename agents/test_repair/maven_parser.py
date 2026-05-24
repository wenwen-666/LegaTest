"""
Maven输出解析模块

负责解析Maven命令的输出，提取编译和测试错误信息，并执行Maven测试
"""
import re
import logging
import os
import subprocess
import time
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

def run_maven_test(project_dir: str, test_class: str, profile: str = None) -> tuple[str, bool]:
    """
    在指定项目目录执行特定的测试类
    
    Args:
        project_dir: Maven项目目录(包含pom.xml的目录)
        test_class: 要执行的测试类名
        profile: 可选，Maven profile名称
        
    Returns:
        (输出结果, 是否成功)
    """
    try:
        # 处理项目路径
        project_dir = os.path.abspath(project_dir)
        logger.info(f"使用项目路径: {project_dir}")
        
        # 确保项目目录存在且包含pom.xml
        if not os.path.exists(project_dir):
            logger.error(f"项目路径不存在: {project_dir}")
            return f"项目路径不存在: {project_dir}", False
            
        pom_path = os.path.join(project_dir, "pom.xml")
        if not os.path.exists(pom_path):
            logger.error(f"pom.xml不存在: {pom_path}")
            return f"pom.xml不存在: {pom_path}", False
        
        # 切换到项目目录
        original_dir = os.getcwd()
        os.chdir(project_dir)
        
        # 构建Maven命令
        cmd_str = f'mvn clean test "-Dtest={test_class}"'
        if profile:
            cmd_str += f' "-P{profile}"'
        
        logger.info(f"执行命令: {cmd_str} (在目录: {project_dir})")
        print(f"执行命令: {cmd_str}")
        start_time = time.time()
        
        # 设置环境变量，确保Maven使用UTF-8编码
        env = os.environ.copy()
        env['JAVA_TOOL_OPTIONS'] = '-Dfile.encoding=UTF-8'
        
        # 使用subprocess.run直接执行命令，允许输出直接显示在终端
        # 这样可以确保输出与终端执行一致
        try:
            # 方法1：直接使用subprocess.run，实时显示输出
            # 但同时也需要捕获输出用于后续处理
            import tempfile
            with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as stdout_file, \
                 tempfile.TemporaryFile(mode='w+', encoding='utf-8') as stderr_file:
                
                # 创建进程，同时输出到终端和临时文件
                process = subprocess.Popen(
                    cmd_str,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    bufsize=1,  # 行缓冲
                    universal_newlines=True,  # 文本模式
                    encoding='utf-8',  # UTF-8编码
                    errors='replace'  # 替换无法解码的字符
                )
                
                # 实时读取并显示输出
                all_output = []
                for line in iter(process.stdout.readline, ''):
                    print(line, end='')  # 实时打印到终端
                    all_output.append(line)
                    stdout_file.write(line)
                
                # 读取错误输出
                for line in iter(process.stderr.readline, ''):
                    print(line, end='')  # 实时打印到终端
                    all_output.append(line)
                    stderr_file.write(line)
                
                # 等待进程完成
                process.stdout.close()
                process.stderr.close()
                return_code = process.wait()
                
                # 重置文件指针并读取所有输出
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout_content = stdout_file.read()
                stderr_content = stderr_file.read()
                
                # 合并输出
                output = ''.join(all_output)
                
        except Exception as e:
            logger.error(f"执行命令时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            output = f"执行命令时出错: {e}"
            return_code = 1
        
        # 恢复原始目录
        os.chdir(original_dir)
        
        # 修改构建成功的判断逻辑
        # 只有在输出中包含"BUILD SUCCESS"且没有测试失败时才视为成功
        success = "BUILD SUCCESS" in output
        
        # 检查是否有测试失败
        if success and any(x in output for x in ["Tests run:", "Failures:", "Errors:"]):
            # 如果有测试运行信息，检查是否有失败或错误
            test_failure_pattern = r'Tests run: \d+, Failures: ([1-9]\d*), Errors: (\d+)'
            test_error_pattern = r'Tests run: \d+, Failures: (\d+), Errors: ([1-9]\d*)'
            
            failure_match = re.search(test_failure_pattern, output)
            error_match = re.search(test_error_pattern, output)
            
            if failure_match or error_match:
                # 有测试失败或错误，视为构建失败
                success = False
                logger.info("BUILD SUCCESS但存在测试失败或错误，视为失败")
        
        # 记录命令输出，便于调试
        logger.debug(f"Maven命令输出 (前500字符): {output[:500]}")
        if not success:
            logger.info(f"Maven命令失败，返回码: {return_code}")
            # 不再重复记录错误信息，这些信息在命令执行时已经输出到终端
        
        execution_time = time.time() - start_time
        logger.info(f"命令执行完成，耗时 {execution_time:.2f}秒, 状态: {'成功' if success else '失败'}")
        
        return output, success
    except subprocess.TimeoutExpired:
        logger.error("命令执行超时")
        return "命令执行超时", False
    except Exception as e:
        logger.error(f"执行命令失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return str(e), False

class ErrorInfo:
    """Maven错误信息"""
    
    def __init__(self, error_line: str, message: str = ""):
        self.error_line = error_line
        self.message = message
        self.file_path = self._extract_path()
        self.line_num, self.col_num = self._extract_line_col()
        self.category, self.details = self._classify_error()
    
    def _extract_path(self) -> Optional[str]:
        """获取错误文件路径"""
        # 英文格式
        match = re.search(r'\[ERROR\]\s+(.*?\.java):', self.error_line)
        if match:
            return match.group(1)
            
        # 中文格式 - 通常包含完整路径
        match = re.search(r'\[ERROR\]\s+(.*?\.java)', self.error_line)
        return match.group(1) if match else None
    
    def _classify_error(self) -> Tuple[str, List[str]]:
        """分类错误类型并提取关键信息"""
        error_text = self.error_line + " " + (self.message or "")
        
        # 定义错误模式和分类
        error_patterns = {
            'missing_method': [
                r'cannot find symbol.*method (\w+)',
                r'method (\w+) in class .+ cannot be applied',
                r'does not override abstract method (\w+)\(',
                r'method does not override or implement a method from a supertype',
            ],
            'missing_constructor': [
                r'constructor (\w+) in class .+ cannot be applied to given types',
                r'no suitable constructor found for (\w+)',
            ],
            'missing_class_or_package': [
                r'symbol:\s+class\s+(\w+)',  # From combined symbol details (more specific)
                r'cannot find symbol.*class (\w+)',  # Fallback for uncombined errors
                r'cannot find symbol.*variable (\w+)',
                r'package (.+) does not exist',
            ],
            'api_compatibility': [
                r'cannot find symbol.*variable (\w+) in (\w+)',
                r'cannot find symbol.*method (\w+)',
                r'(\w+)\.repeat\(',
                r'(\w+)\.builder\(\)',
                r'withAllowDuplicateHeaderNames',
            ],
            'access_violation': [
                r'(\w+) has private access',
                r'(\w+) has protected access',
                r'(\w+)\([^)]*\) has private access',
                r'(\w+)\([^)]*\) has protected access',
                r'(\w+) is not public',
            ],
            'duplicate_definition': [
                r'duplicate class: (\w+)',
                r'(\w+) is already defined',
                r'method (.+) is already defined',
                r'duplicate (.+)',
            ],
            'interface_implementation': [
                r'is not abstract and does not override abstract method (\w+)',
                r'(\w+) is not abstract and does not override abstract method',
            ],
            'type_mismatch': [
                r'incompatible types: (.+) cannot be converted to (.+)',
                r'required: (.+), found: (.+)',
                r'cannot infer type arguments for (.+)',
                r'cannot infer type-variable\(s\) (.+)',
                r'try-with-resources not applicable to variable type',
                r'(.+) cannot be converted to java\.lang\.AutoCloseable',
            ],
            'test_failure': [
                r'expected: <(.+)> but was: <(.+)>',
                r'Expected (.+) to be thrown, but (.+) was thrown',
                r'Expected (.+) to be thrown, but nothing was thrown',
                r'Unexpected exception thrown: (.+)',
                r'Unexpected exception type thrown.*expected: <(.+)> but was: <(.+)>',
                r'(.+) ==> expected: <(.+)> but was: <(.+)>',
                r'Time elapsed: .* <<< FAILURE!',
            ],
            'syntax_error': [
                r"'\(' or '\[' expected",
                r'not a statement',
                r"'try' without 'catch', 'finally' or resource declarations",
                r'resource specification not allowed here',
                r'unreported exception (.+); must be caught or declared to be thrown',
                r'expected (.+)',
                r'illegal (.+)',
                r'unexpected (.+)',
            ],
            'compilation_error': [
                r'COMPILATION ERROR',
                r'exception (.+) is never thrown in body of corresponding try statement',
                r'cannot find symbol',
                r'package (.+) does not exist',
                r'(.+)\.java:\[\d+,\d+\]',  # Java文件编译错误格式
                r'Failed to execute goal .+maven-compiler-plugin.+ Compilation failure',
                r'try-with-resources not applicable',
            ]
        }
        
        # 尝试匹配错误模式
        for category, patterns in error_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, error_text, re.IGNORECASE)
                if match:
                    return category, list(match.groups())
        
        # 如果没有匹配到，返回未分类
        return 'unclassified', []
    
    def _extract_line_col(self) -> Tuple[int, int]:
        """获取错误行号和列号"""
        # 英文格式 - 通常是 file.java:123:45
        match = re.search(r'\.java:(\d+)(?::(\d+))?', self.error_line)
        if match:
            line = int(match.group(1))
            col = int(match.group(2)) if match.group(2) else 0
            return line, col
            
        # 中文格式 - 通常是 file.java:[123,45]
        match = re.search(r'\.java:\[(\d+)(?:,(\d+))?\]', self.error_line)
        if match:
            line = int(match.group(1))
            col = int(match.group(2)) if match.group(2) else 0
            return line, col
            
        return 0, 0
    
    def get_path(self) -> Optional[str]:
        """获取错误文件路径"""
        return self.file_path
    
    def get_line_col(self) -> Tuple[int, int]:
        """获取错误行号和列号"""
        return self.line_num, self.col_num
    
    def get_message(self) -> str:
        """获取错误消息"""
        return self.message if self.message else self.error_line
    
    def get_error_context(self) -> Dict[str, Any]:
        """获取包含错误上下文的字典，用于修复"""
        return {
            "error_line": self.error_line,
            "message": self.message,
            "file_path": self.file_path,
            "line_num": self.line_num,
            "col_num": self.col_num,
            "category": self.category,
            "details": self.details
        }
    
    def get_category(self) -> str:
        """获取错误分类"""
        return self.category
    
    def get_details(self) -> List[str]:
        """获取错误详细信息"""
        return self.details
    
    def get_repair_guidance(self) -> str:
        """
        获取针对错误类型的具体修复指导
        """
        category = self.get_category()
        details = self.get_details()
        error_text = self.error_line.lower()
        
        # 针对不同错误类型提供具体指导
        if category == 'type_mismatch':
            if 'cannot be converted to java.lang.autocloseable' in error_text:
                return "该类型未实现AutoCloseable，不能用于try-with-resources；请改用手动close()或选择AutoCloseable替代类型。"
            elif 'autocloseable' in error_text:
                return "该类型不实现AutoCloseable接口，无法用于try-with-resources。建议使用传统的try-finally模式手动管理资源。"
            else:
                from_type = details[0] if details else '源类型'
                to_type = details[1] if len(details) > 1 else '目标类型'
                return f"类型不匹配：{from_type} 无法转换为 {to_type}。检查变量类型声明和赋值兼容性。"
        
        elif category == 'compilation_error':
            if 'try-with-resources not applicable' in error_text:
                return ("try-with-resources语法错误。确保资源类型实现AutoCloseable接口。\n"
                       "如果资源不支持AutoCloseable，使用try-finally替代：\n"
                       "Resource resource = null;\n"
                       "try {\n"
                       "    resource = new Resource();\n"
                       "    // 使用resource\n"
                       "} finally {\n"
                       "    if (resource != null) resource.close();\n"
                       "}")
            elif 'maven-compiler-plugin' in error_text:
                return "Maven编译失败。检查：1) Java版本兼容性，2) pom.xml配置，3) 依赖项版本，4) 源码语法。"
            else:
                return "编译错误：检查语法、导入语句和类型声明。"
        
        elif category == 'syntax_error':
            if "'(' or '[' expected" in error_text:
                return "语法错误：缺少括号或方括号。检查方法调用、数组访问或条件语句的语法。"
            elif 'not a statement' in error_text:
                return "语法错误：表达式不能作为语句。可能是缺少赋值操作符或方法调用语法错误。"
            elif 'try without catch' in error_text:
                return ("try语句缺少catch、finally或资源声明。\n"
                       "修复方案：\n"
                       "1. 添加catch块：try { ... } catch (Exception e) { ... }\n"
                       "2. 添加finally块：try { ... } finally { ... }\n"
                       "3. 使用try-with-resources：try (Resource r = new Resource()) { ... }")
            elif 'resource specification not allowed here' in error_text:
                return "try-with-resources语法错误。资源声明必须在try语句的括号内，且资源类型必须实现AutoCloseable。"
            else:
                detail_text = ' '.join(details) if details else '检查代码结构和语法'
                return f"语法错误：{detail_text}。"
        
        elif category == 'missing_class_or_package':
            missing_item = details[0] if details else '未知类或包'
            return f"找不到类或包：{missing_item}。检查import语句和依赖项配置。"
        
        elif category == 'missing_method':
            method_name = details[0] if details else '未知方法'
            return f"找不到方法：{method_name}。检查方法名、参数类型、访问修饰符和API版本兼容性。"
        
        elif category == 'access_violation':
            member_name = details[0] if details else '未知成员'
            return f"访问权限错误：{member_name} 无法访问。检查访问修饰符或使用public方法/字段。"
        
        elif category == 'test_failure':
            if len(details) >= 2:
                expected, actual = details[0], details[1]
                return f"测试断言失败：期望值 {expected}，实际值 {actual}。检查业务逻辑和测试用例的正确性。"
            else:
                return "测试失败：检查测试逻辑和预期结果设置。"
        
        else:
            return "编译错误：检查导入语句、方法签名和Java版本兼容性。如果是特定API错误，请确认库版本和依赖配置。"

class MavenOutput:
    """Maven输出结果"""
    
    def __init__(self, output: str):
        # 确保输出是有效的字符串
        if output is None:
            logger.warning("Maven输出为None，使用空字符串")
            self.output = ""
        else:
            # 处理可能的编码问题
            try:
                # 不清理ANSI转义序列，只清理真正有问题的字符
                # 保留ANSI转义序列(\x1b)以便正确解析错误信息
                self.output = ''.join(c if c.isprintable() or c in ['\n', '\r', '\t', '\x1b'] else ' ' for c in output)
            except Exception as e:
                logger.warning(f"清理Maven输出时出错: {e}, 使用原始输出")
                self.output = output
                
        self.errors = []  # 错误列表
        
        # 改进构建状态判断逻辑：区分编译失败和测试失败
        if "BUILD SUCCESS" in self.output:
            # 编译成功，检查是否有测试失败
            if any(x in self.output for x in ["Tests run:", "Failures:", "Errors:"]):
                # 检查测试失败或错误
                test_failure_pattern = r'Tests run: \d+, Failures: ([1-9]\d*), Errors: (\d+)'
                test_error_pattern = r'Tests run: \d+, Failures: (\d+), Errors: ([1-9]\d*)'
                
                failure_match = re.search(test_failure_pattern, self.output)
                error_match = re.search(test_error_pattern, self.output)
                
                if failure_match or error_match:
                    self.status = "test_failure"  # 新状态：测试失败
                    logger.info("Build successful but tests failed")
                else:
                    self.status = "success"
            else:
                self.status = "success"
        else:
            self.status = "failure"  # 编译失败
        
        # 解析错误信息
        self._parse_errors()
        
        # 简化日志记录
        logger.debug(f"Maven构建状态: {'成功' if self.status == 'success' else '失败'}")
        logger.debug(f"解析到 {len(self.errors)} 个错误")
    
    def _parse_errors(self):
        """Improved error parsing with deduplication and better context extraction"""
        try:
            lines = self.output.splitlines()
            seen_errors = set()  # For deduplication
            processed_lines = set()  # Track processed line indices
            
            # First pass: collect all relevant information
            for i, line in enumerate(lines):
                clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)
                
                # Collect detailed compilation error information
                if 'cannot find symbol' in clean_line or 'no suitable constructor found' in clean_line or 'cannot infer type arguments' in clean_line or 'cannot be applied to given types' in clean_line:
                    processed_lines.add(i)  # Mark this line as processed
                    
                    # Look for symbol details in next lines
                    symbol_details = ""
                    location_details = ""
                    constructor_details = []
                    
                    for j in range(i+1, min(i+5, len(lines))):  # Check more lines for constructor details
                        next_line = re.sub(r'\x1b\[[0-9;]*m', '', lines[j]).strip()
                        
                        # Stop if we encounter a new error line (starts new error context)
                        if next_line.startswith('[ERROR]') and ('.java:' in next_line):
                            break
                            
                        # Remove [ERROR] prefix to check for symbol/location details
                        clean_next = next_line.replace('[ERROR]', '').strip()
                        
                        if clean_next.startswith('symbol:'):
                            symbol_details = clean_next
                            processed_lines.add(j)  # Mark symbol line as processed
                        elif clean_next.startswith('location:'):
                            location_details = clean_next
                            processed_lines.add(j)  # Mark location line as processed
                        elif ('constructor' in clean_next and 'is not applicable' in clean_next) or \
                             '(actual and formal argument lists differ in length)' in clean_next or \
                             clean_next.startswith('reason:') or \
                             clean_next.startswith('required:') or \
                             clean_next.startswith('found:'):
                            constructor_details.append(clean_next)
                            processed_lines.add(j)  # Mark constructor detail line as processed
                    
                    # Build complete error information (clean_line already has [ERROR] prefix)
                    full_error = clean_line
                    if symbol_details:
                        full_error += f" ({symbol_details})"
                    if location_details:
                        full_error += f" ({location_details})"
                    if constructor_details:
                        # Add constructor details with a summary
                        full_error += f" (Available constructors mismatch: {len(constructor_details)} alternatives checked)"
                    
                    # Deduplicate based on file and line number
                    error_key = self._extract_error_key(full_error)
                    if error_key not in seen_errors:
                        seen_errors.add(error_key)
                        self.errors.append(ErrorInfo(full_error, ""))
                
                # Find [ERROR] lines (skip already processed lines)
                elif '[ERROR]' in clean_line and i not in processed_lines:
                    if any(skip_text in clean_line for skip_text in [
                        "To see the full stack trace", 
                        "Re-run Maven", 
                        "For more information", 
                        "[Help", 
                        "http://cwiki.apache.org"
                    ]):
                        continue
                    
                    # Deduplicate
                    error_key = self._extract_error_key(clean_line)
                    if error_key not in seen_errors:
                        seen_errors.add(error_key)
                        self.errors.append(ErrorInfo(clean_line, ""))
                
                # Find compilation errors (without [ERROR] prefix)
                elif 'error:' in clean_line and '.java:' in clean_line:
                    error_key = self._extract_error_key(clean_line)
                    if error_key not in seen_errors:
                        seen_errors.add(error_key)
                        self.errors.append(ErrorInfo(f"[ERROR] {clean_line}", ""))
                
                # Find test failures
                elif '<<< FAILURE!' in clean_line or '<<< ERROR!' in clean_line:
                    error_key = self._extract_error_key(clean_line)
                    if error_key not in seen_errors:
                        seen_errors.add(error_key)
                        self.errors.append(ErrorInfo(f"[ERROR] {clean_line.strip()}", ""))
            
            # Handle different failure types
            if not self.errors:
                if self.status == "failure":
                    self.errors.append(ErrorInfo(
                        "[ERROR] Maven build failed",
                        "Maven build failed but no specific error information was detected. Please check code syntax, import statements and class names."
                    ))
                elif self.status == "test_failure":
                    # For test failures, extract assertion failures from output
                    self._extract_test_failures(lines)
            
        except Exception as e:
            logger.error(f"Error parsing Maven output: {e}")
            self.errors.append(ErrorInfo(
                "[ERROR] Maven output parsing failed",
                f"Unable to parse Maven output: {str(e)}"
            ))
    
    def _extract_error_key(self, error_line):
        """Extract a unique key for error deduplication based on file path and line number"""
        # Extract file path and line number for deduplication
        match = re.search(r'([^\s]+\.java):\[(\d+),\d+\]', error_line)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
        
        # Fallback: use first 100 characters of cleaned error
        clean_error = re.sub(r'\[ERROR\]\s*', '', error_line).strip()
        return clean_error[:100]
    
    def _extract_test_failures(self, lines):
        """Extract test failure information from Maven output"""
        for i, line in enumerate(lines):
            clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)
            
            # Look for assertion failures with expected/actual values
            if "expected:" in clean_line and "but was:" in clean_line:
                # Extract the test method and assertion details
                test_method = ""
                # Look for test method name in previous lines
                for j in range(max(0, i-10), i):
                    prev_line = re.sub(r'\x1b\[[0-9;]*m', '', lines[j])
                    method_match = re.search(r'(test\w+).*?Time elapsed:', prev_line)
                    if method_match:
                        test_method = method_match.group(1)
                        break
                
                # Create detailed test failure info
                failure_info = clean_line
                if test_method:
                    failure_info = f"{test_method}: {failure_info}"
                
                self.errors.append(ErrorInfo(f"[TEST_FAILURE] {failure_info}", ""))
            
            # Look for test failure summary lines
            elif "<<< FAILURE!" in clean_line and "Time elapsed:" in clean_line:
                method_match = re.search(r'(test\w+).*?Time elapsed:', clean_line)
                if method_match:
                    test_method = method_match.group(1)
                    self.errors.append(ErrorInfo(f"[TEST_FAILURE] {test_method} failed", ""))
    
    def format_errors(self) -> str:
        """Format error information for output"""
        if not self.errors:
            if self.status == "failure":
                return "Maven build failed but no specific error information was detected."
            return "No errors found."
        
        result = "Maven build errors:\n\n"
        
        for i, error in enumerate(self.errors, 1):
            path = error.get_path() or "Unknown file"
            line, col = error.get_line_col()
            result += f"Error {i}:" + "\n"
            result += f"  Location: {path}"
            if line > 0:
                result += f", line {line}"
                if col > 0:
                    result += f", column {col}"
            result += "\n"
            result += f"  Content: {error.error_line}" + "\n"
            if error.message:
                result += f"  Details: {error.message}" + "\n"
            result += "\n"
        
        return result
    
    def get_error_prompt(self) -> str:
        """
        Get optimized error prompt for LLM repair with intelligent analysis and prioritization
        
        Returns:
            Formatted error prompt string optimized for LLM repair
        """
        if not self.errors:
            if self.status == "failure":
                return "COMPILATION_ERROR: Maven build failed but no specific error information was detected."
            elif self.status == "test_failure":
                return "TEST_FAILURE: Tests failed but no specific failure information was detected."
            return "No errors found."
        
        # Different handling for test failures vs compilation errors
        if self.status == "test_failure":
            return self._format_test_failure_prompt()
        else:
            return self._format_compilation_error_prompt()
    
    def _format_test_failure_prompt(self) -> str:
        """Format specific prompt for test failures with assertion details"""
        result = ["TEST_FAILURE:"]
        
        for error in self.errors:
            error_text = self._clean_error_text(error.error_line)
            
            # Extract test method and assertion details
            if "expected:" in error_text and "but was:" in error_text:
                # Extract method name from error context
                method_match = re.search(r'(test\w+)', error_text)
                method_name = method_match.group(1) if method_match else "unknown test method"
                
                # Extract expected vs actual values
                expected_match = re.search(r'expected:\s*<([^>]+)>', error_text)
                actual_match = re.search(r'but was:\s*<([^>]+)>', error_text)
                
                expected = expected_match.group(1) if expected_match else "unknown"
                actual = actual_match.group(1) if actual_match else "unknown"
                
                result.append(f"• {method_name}: expected <{expected}> but was <{actual}>")
            else:
                result.append(f"• {error_text}")
        
        return "\n".join(result)
    
    def _format_compilation_error_prompt(self) -> str:
        """Format detailed prompt for compilation errors with specific error information"""
        # Prioritize errors and get top issues
        prioritized_errors = self._get_prioritized_errors()
        
        if not prioritized_errors:
            return "COMPILATION_ERROR: Maven build failed but no actionable error information was detected."
        
        result = ["COMPILATION_ERROR:"]
        
        # Group errors by type for better organization
        error_groups = self._group_compilation_errors(prioritized_errors)
        
        # Display errors with detailed information
        for group_name, errors in error_groups.items():
            if errors:
                result.append(f"\n{group_name}:")
                for error in errors:
                    error_details = self._extract_detailed_error_info(error)
                    result.append(f"  • {error_details}")
        
        return "\n".join(result)
    
    def _group_compilation_errors(self, errors) -> Dict[str, List]:
        """Group compilation errors by type for better organization"""
        groups = {
            "Missing imports/packages": [],
            "Syntax errors": [],
            "API/method issues": [],
            "Other compilation issues": []
        }
        
        for error in errors:
            category = error.get_category()
            error_text = error.error_line.lower()
            
            if category in ['missing_class_or_package']:
                groups["Missing imports/packages"].append(error)
            elif category in ['syntax_error', 'type_mismatch'] or any(x in error_text for x in ['expected', 'try-with-resources']):
                groups["Syntax errors"].append(error)
            elif category in ['missing_method', 'missing_constructor', 'access_violation', 'api_compatibility']:
                groups["API/method issues"].append(error)
            elif 'cannot find symbol' in error_text and category not in ['missing_method', 'access_violation']:
                # Only put unclassified "cannot find symbol" errors in missing imports
                groups["Missing imports/packages"].append(error)
            else:
                groups["Other compilation issues"].append(error)
        
        return {k: v for k, v in groups.items() if v}
    
    def _extract_detailed_error_info(self, error: 'ErrorInfo') -> str:
        """Extract detailed error information for compilation errors"""
        error_text = error.error_line
        details = error.get_details()
        category = error.get_category()
        
        # Clean the error text
        clean_error = self._clean_error_text(error_text)
        
        # Add location info if available
        file_path = error.get_path()
        line_num, col_num = error.get_line_col()
        location = ""
        if file_path:
            file_name = os.path.basename(file_path) if file_path else "unknown"
            location = f" at {file_name}"
            if line_num > 0:
                location += f":{line_num}"
        
        # Extract specific error details based on category
        if category == 'missing_class_or_package' and details:
            missing_item = details[0]
            return f"Cannot find symbol: '{missing_item}'{location}"
        
        elif category == 'type_mismatch' and 'autocloseable' in clean_error.lower():
            return f"Type does not implement AutoCloseable - cannot use try-with-resources{location}"
        
        elif category == 'syntax_error':
            if 'resource specification not allowed' in clean_error.lower():
                return f"Invalid try-with-resources syntax{location}"
            elif "'(' or '[' expected" in clean_error:
                return f"Missing parentheses or brackets{location}"
            elif 'not a statement' in clean_error:
                return f"Invalid statement syntax{location}"
            else:
                return f"Syntax error: {clean_error[:100]}{location}"
        
        elif category == 'missing_method':
            if 'does not override or implement' in clean_error:
                return f"Invalid @Override annotation - method not in supertype{location}"
            elif details:
                method_name = details[0]
                return f"Cannot find method: '{method_name}'{location}"
            else:
                return f"Method implementation issue{location}"
        
        elif category == 'access_violation' and details:
            member_name = details[0]
            return f"Access violation: '{member_name}' is private/protected{location}"
        
        elif category == 'duplicate_definition' and details:
            duplicate_item = details[0]
            if 'method' in clean_error.lower():
                return f"Duplicate method definition: '{duplicate_item}'{location}"
            else:
                return f"Duplicate definition: '{duplicate_item}'{location}"
        
        elif category == 'interface_implementation':
            if details:
                method_name = details[0]
                return f"Missing abstract method implementation: '{method_name}'{location}"
            else:
                return f"Abstract method not implemented{location}"
        
        else:
            # Generic error format with location - increased limit for better error info
            return f"{clean_error[:300]}{location}"
    
    def _get_prioritized_errors(self) -> List['ErrorInfo']:
        """获取优先级排序的错误列表"""
        if len(self.errors) <= 5:
            return self.errors
        
        # 按重要性分类
        critical_errors = []
        important_errors = []
        other_errors = []
        
        for error in self.errors:
            category = error.get_category()
            error_text = error.error_line.lower()
            
            # 关键错误：类型不匹配、语法错误
            if category in ['type_mismatch', 'syntax_error'] or 'autocloseable' in error_text:
                critical_errors.append(error)
            # 重要错误：缺失类/包、方法问题
            elif category in ['missing_class_or_package', 'missing_method', 'compilation_error']:
                important_errors.append(error)
            else:
                other_errors.append(error)
        
        # 返回优先级排序的错误（智能限制以避免token浪费）
        # 对于missing_method，确保显示所有唯一的方法名
        unique_methods = set()
        filtered_important = []
        for error in important_errors:
            if error.get_category() == 'missing_method':
                if error.details and error.details[0] not in unique_methods:
                    unique_methods.add(error.details[0])
                    filtered_important.append(error)
            else:
                filtered_important.append(error)
        
        # 增加重要错误的限制，确保覆盖所有关键的missing_method
        result = critical_errors[:5] + filtered_important[:15] + other_errors[:3]
        return result[:25]
    
    def _group_errors_with_guidance(self, errors) -> Dict[str, Dict]:
        """将错误分组并提供修复指导"""
        groups = {
            "Critical Issues (需要优先修复)": {"errors": []},
            "Import/Package Issues": {"errors": []},
            "Syntax Issues": {"errors": []},
            "Other Issues": {"errors": []}
        }
        
        for error in errors:
            category = error.get_category()
            error_text = error.error_line.lower()
            
            # 生成错误摘要和指导
            summary = self._generate_error_summary(error)
            guidance = self._generate_concise_guidance(error)
            
            error_info = {
                'summary': summary,
                'guidance': guidance,
                'error': error
            }
            
            # 分组逻辑
            if (category == 'type_mismatch' and 'autocloseable' in error_text) or \
               (category == 'syntax_error' and 'try-with-resources' in error_text):
                groups["Critical Issues (需要优先修复)"]["errors"].append(error_info)
            elif category in ['missing_class_or_package', 'missing_method']:
                groups["Import/Package Issues"]["errors"].append(error_info)
            elif category == 'syntax_error':
                groups["Syntax Issues"]["errors"].append(error_info)
            else:
                groups["Other Issues"]["errors"].append(error_info)
        
        # 只返回非空组
        return {k: v for k, v in groups.items() if v['errors']}
    
    def _generate_error_summary(self, error: 'ErrorInfo') -> str:
        """生成错误摘要"""
        clean_error = self._clean_error_text(error.error_line)
        # 限制长度，突出关键信息
        if 'cannot be converted to java.lang.autocloseable' in clean_error.lower():
            return "类型不支持try-with-resources语法"
        elif 'cannot find symbol' in clean_error.lower() and 'class' in clean_error.lower():
            match = re.search(r'class (\w+)', clean_error, re.IGNORECASE)
            if match:
                return f"缺少类导入: {match.group(1)}"
        elif 'expected' in clean_error.lower():
            return "语法错误: " + clean_error[:60] + ("..." if len(clean_error) > 60 else "")
        
        # 默认摘要
        return clean_error[:80] + ("..." if len(clean_error) > 80 else "")
    
    def _generate_concise_guidance(self, error: 'ErrorInfo') -> str:
        """生成简洁的修复指导"""
        category = error.get_category()
        error_text = error.error_line.lower()
        
        if category == 'type_mismatch' and 'zipfile cannot be converted to java.lang.autocloseable' in error_text:
            return "使用try-finally替代try-with-resources"
        elif category == 'missing_class_or_package':
            details = error.get_details()
            return "检查import语句"
        elif category == 'syntax_error':
            if "'(' or '[' expected" in error_text:
                return "检查括号匹配"
            elif 'try without catch' in error_text:
                return "添加catch或finally块"
            else:
                return "检查语法结构"
        else:
            return "检查代码语法和依赖"
    
    def _clean_error_text(self, error_text):
        """Clean error text by removing prefixes, color codes, and noise"""
        clean_error = error_text
        
        # Remove ANSI color codes
        clean_error = re.sub(r'\x1b\[[0-9;]*m', '', clean_error)
        clean_error = re.sub(r'\[\[.*?m\]', '', clean_error)
        clean_error = re.sub(r'\[.*?m\]', '', clean_error)
        
        # Remove prefixes
        clean_error = clean_error.replace("[ERROR] ", "").replace("[TEST_FAILURE] ", "").strip()
        
        # Remove file path noise for readability
        clean_error = re.sub(r'/[^\s]*/(LegaTest/[^\s]*)', r'\1', clean_error)
        
        return clean_error
    
    def _group_errors_for_display(self, errors):
        """Group errors for optimal display to LLM"""
        groups = {
            "Missing imports/packages": [],
            "Syntax errors": [],
            "API/method issues": [],
            "Other issues": []
        }
        
        for error in errors:
            error_lower = error.lower()
            
            # Group by type for better LLM understanding
            if any(pattern in error_lower for pattern in [
                'cannot find symbol', 'package', 'does not exist', 'import'
            ]):
                groups["Missing imports/packages"].append(error)
            elif any(pattern in error_lower for pattern in [
                'expected', 'illegal', 'unexpected', 'syntax', 'resource specification'
            ]):
                groups["Syntax errors"].append(error)
            elif any(pattern in error_lower for pattern in [
                'method', 'constructor', 'access', 'cannot be applied'
            ]):
                groups["API/method issues"].append(error)
            else:
                groups["Other issues"].append(error)
        
        # Return only non-empty groups
        return {k: v for k, v in groups.items() if v}
    
    def _format_error_for_llm(self, error):
        """Format individual error for optimal LLM comprehension with specific fix guidance"""
        error_lower = error.lower()
        
        # For "cannot find symbol" errors, extract the symbol details
        if 'cannot find symbol' in error:
            symbol_match = re.search(r'symbol:\s*\w+\s+(\w+)', error)
            location_match = re.search(r'location:\s*\w+\s+(\w+)', error)
            
            if symbol_match:
                symbol = symbol_match.group(1)
                location = location_match.group(1) if location_match else "unknown"
                
                return f"Missing symbol '{symbol}' in {location} - likely missing import"
        
        # For package errors
        if 'package' in error and 'does not exist' in error:
            package_match = re.search(r'package (.+) does not exist', error)
            if package_match:
                package = package_match.group(1)
                return f"Package '{package}' not found - remove import or check spelling"
        
        # For try-with-resources errors
        if 'try-with-resources' in error_lower or 'autoCloseable' in error_lower:
            return "Try-with-resources requires AutoCloseable - use manual close() or find AutoCloseable alternative"
        
        # For syntax errors with specific patterns
        if "'try' without 'catch'" in error:
            return "Incomplete try statement - add catch/finally block or fix try-with-resources syntax"
        elif "';' expected" in error:
            return "Missing semicolon - add ';' at end of statement"
        elif "')' expected" in error:
            return "Missing closing parenthesis - check parentheses matching"
        elif "'(' or '[' expected" in error:
            return "Invalid method/array syntax - check method calls and array access"
        elif "not a statement" in error:
            return "Invalid Java syntax - check statement structure"
        elif "illegal start of expression" in error:
            return "Invalid expression syntax - check variable declarations and assignments"
        
        # For other errors, clean up but keep essential info
        formatted = re.sub(r'/[^\s]*\.java:\[\d+,\d+\]', '', error)  # Remove file paths
        formatted = re.sub(r'\s+', ' ', formatted).strip()  # Normalize whitespace
        
        return formatted[:200] + "..." if len(formatted) > 200 else formatted
    
    def _deduplicate_similar_errors(self, errors):
        """Advanced error deduplication with root cause analysis and intelligent merging"""
        if len(errors) <= 1:
            return errors
        
        # Step 1: Group errors by root cause patterns
        error_groups = self._group_errors_by_root_cause(errors)
        
        # Step 2: For each group, pick the most representative error
        unique_errors = []
        for group_key, group_errors in error_groups.items():
            # Pick the most informative error from each group
            representative = self._select_representative_error(group_errors)
            if representative:
                unique_errors.append(representative)
        
        # Step 3: Prioritize fundamental errors
        return self._prioritize_fundamental_errors(unique_errors)
    
    def _group_errors_by_root_cause(self, errors):
        """Group errors by their underlying root cause"""
        error_groups = {}
        
        for error in errors:
            # Identify root cause pattern
            root_cause = self._identify_root_cause(error)
            
            if root_cause not in error_groups:
                error_groups[root_cause] = []
            error_groups[root_cause].append(error)
        
        return error_groups
    
    def _identify_root_cause(self, error):
        """Identify the root cause of an error for grouping"""
        error_lower = error.lower()
        
        # Missing import patterns
        if 'cannot find symbol' in error_lower:
            if 'zipentry' in error_lower:
                return 'missing_import_zipentry'
            elif 'charset' in error_lower:
                return 'missing_import_charset'  
            elif 'standardcharsets' in error_lower:
                return 'missing_import_standardcharsets'
            elif 'paths' in error_lower or 'path' in error_lower:
                return 'missing_import_paths'
            else:
                # Generic missing symbol - group by the symbol name
                symbol_match = re.search(r'symbol:\s*\w+\s+(\w+)', error)
                if symbol_match:
                    return f'missing_symbol_{symbol_match.group(1).lower()}'
                return 'missing_symbol_generic'
        
        # Try-with-resources syntax errors
        if 'resource specification not allowed here' in error_lower:
            return 'try_with_resources_syntax'
        
        # Method access errors  
        if 'has private access' in error_lower or 'has protected access' in error_lower:
            return 'access_violation'
        
        # Package not exist errors
        if 'package' in error_lower and 'does not exist' in error_lower:
            package_match = re.search(r'package (.+) does not exist', error_lower)
            if package_match:
                return f'missing_package_{package_match.group(1).replace(".", "_")}'
            return 'missing_package_generic'
        
        # Syntax errors like missing semicolons, braces etc
        if any(syntax_pattern in error_lower for syntax_pattern in ['expected', 'illegal', 'unexpected']):
            return 'syntax_error'
        
        # Generic grouping by normalized error pattern
        normalized = re.sub(r'/[^\s]*\.java:\[\d+,\d+\]', 'FILE:LINE', error)
        normalized = re.sub(r'\b\w+Test_\w+', 'TestClass', normalized)
        return f'generic_{hash(normalized) % 1000}'
    
    def _select_representative_error(self, group_errors):
        """Select the most representative error from a group"""
        if len(group_errors) == 1:
            return group_errors[0]
        
        # Prefer errors with more context information
        best_error = None
        best_score = -1
        
        for error in group_errors:
            score = 0
            
            # Prefer errors with symbol/location details
            if 'symbol:' in error:
                score += 3
            if 'location:' in error:
                score += 2
            
            # Prefer shorter, cleaner errors (less likely to be cascading)
            if len(error) < 200:
                score += 1
            
            # Prefer errors from main test files (not generated variants)
            if not re.search(r'Test_\w+_\w+', error):  # Not a generated test variant
                score += 2
                
            if score > best_score:
                best_score = score
                best_error = error
        
        return best_error or group_errors[0]
    
    def _prioritize_fundamental_errors(self, errors):
        """Prioritize fundamental errors that need to be fixed first"""
        if len(errors) <= 5:  # If few errors, keep all
            return errors
        
        # Define priority levels
        high_priority = []
        medium_priority = []
        low_priority = []
        
        for error in errors:
            error_lower = error.lower()
            
            # High priority: Missing imports, package issues
            if any(pattern in error_lower for pattern in [
                'missing_import_', 'missing_package_', 'cannot find symbol'
            ]):
                high_priority.append(error)
            
            # Medium priority: Syntax errors, access violations
            elif any(pattern in error_lower for pattern in [
                'try_with_resources', 'syntax_error', 'access_violation'
            ]):
                medium_priority.append(error)
            
            # Low priority: Other errors
            else:
                low_priority.append(error)
        
        # Return prioritized list, limiting total count
        result = high_priority[:8]  # Max 8 high priority
        if len(result) < 10:
            result.extend(medium_priority[:10-len(result)])
        if len(result) < 12:
            result.extend(low_priority[:12-len(result)])
        
        return result
    
    def has_errors(self) -> bool:
        """Whether there are errors"""
        return len(self.errors) > 0
    
    def is_test_failure(self) -> bool:
        """Whether this is a test failure (not compilation error)"""
        return self.status == "test_failure"
    
    def get_all_errors(self) -> List[ErrorInfo]:
        """获取所有错误"""
        return self.errors

class MavenOutputParser:
    """Maven输出解析器"""
    
    def parse(self, output: str) -> MavenOutput:
        """
        解析Maven输出
        
        Args:
            output: Maven命令输出
            
        Returns:
            解析后的Maven输出结果
        """
        logger.info("开始解析Maven输出...")
        maven_output = MavenOutput(output)
        
        # 判断构建状态
        if maven_output.status == "failure":
            logger.info(f"Maven构建失败，发现 {len(maven_output.errors)} 个错误")
            
            # 不再重复输出错误信息，这些信息在Maven命令执行时已经输出过
            if len(maven_output.errors) > 0:
                logger.debug(f"已解析 {len(maven_output.errors)} 个错误")
        else:
            logger.info("Maven构建成功")
            
        return maven_output

def run_and_parse_test(project_path: str, test_file: str) -> Tuple[str, bool]:
    """
    运行Maven测试并解析输出
    
    Args:
        project_path: Maven项目路径
        test_file: 测试文件路径
        
    Returns:
        (命令输出, 是否成功)
    """
    # 获取测试类名
    test_file_name = os.path.basename(test_file)
    test_class_name = os.path.splitext(test_file_name)[0]
    
    # 提取包路径
    package_path = os.path.dirname(os.path.relpath(test_file, os.path.join(project_path, 'src/test/java')))
    package_name = package_path.replace(os.path.sep, '.')
    
    # 构建完整测试类名
    full_test_class = f"{package_name}.{test_class_name}" if package_name else test_class_name
    
    # 运行测试并获取输出
    output, success = run_maven_test(project_path, full_test_class)
    
    return output, success
