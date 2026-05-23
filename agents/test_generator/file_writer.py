"""
文件写入模块

负责将LLM生成的测试代码写入到Maven项目结构中
"""
import os
import re
import logging
from typing import Dict, Any, Optional, List, Tuple

# 导入本地模块
from . import prompt_builder
from . import maven_analyzer
from .config import config
from . import llm_interface
# 使用test_repair模块的maven_parser，确保统一的错误解析逻辑
import sys
import os
# 添加当前agents目录到sys.path，这样可以导入其他agents子模块
current_agents_dir = os.path.dirname(os.path.dirname(__file__))
if current_agents_dir not in sys.path:
    sys.path.insert(0, current_agents_dir)

from test_repair.maven_parser import run_and_parse_test
from .statistics import global_stats_collector

# 配置日志
logger = logging.getLogger(__name__)

class TestFileWriter:
    """测试文件写入器"""
    
    def __init__(self):
        self.maven_analyzer = maven_analyzer.MavenProjectAnalyzer()
        self.prompt_builder = prompt_builder.PromptBuilder()
        
    def _mark_buggy_line(self, test_code: str, marks: List[Tuple[int, str]]) -> str:
        """
        在测试代码中标记错误行
        
        Args:
            test_code: 原始测试代码
            marks: 错误标记列表，每项为 (行号, 错误信息)
        
        Returns:
            标记了错误的代码
        """
        lines = test_code.splitlines(keepends=False)
        
        # 为每行添加行号
        lines_with_numbers = [(i+1, line) for i, line in enumerate(lines)]
        
        # 添加错误标记
        insert_records = []
        for mark_line, mark_msg in marks:
            for line_num, _ in lines_with_numbers:
                if mark_line == line_num:
                    insert_records.append((line_num, mark_msg))
                    break
        
        # 按行号降序插入错误标记
        for line_num, mark_msg in sorted(insert_records, key=lambda x: x[0], reverse=True):
            lines_with_numbers.insert(line_num - 1, (-1, mark_msg))
        
        # 移除行号
        return "\n".join([line for _, line in lines_with_numbers])
        
    def generate_test_suites(self, cls_info: Dict[str, Any], suite_count: int = 10, java_version: str = '8') -> List[str]:
        """
        为指定的类生成多个测试套件
        
        Args:
            cls_info: 类信息字典
            suite_count: 要生成的测试套件数量（默认10个）
            java_version: Java版本
        
        Returns:
            生成的测试文件路径列表
        """
        class_name = cls_info.get('className', 'Unknown')
        logger.info(f"为类 {class_name} 生成 {suite_count} 个测试套件")
        
        generated_files = []
        failed_count = 0
        retry_count = 0
        max_retries = 2  # 每个套件最多重试次数
        
        # 获取Maven依赖
        try:
            maven_deps = self.maven_analyzer.analyze_project_structure(cls_info.get('project_path', ''))
            cls_info['java_version'] = java_version
            cls_info['maven_dependencies'] = maven_deps
        except Exception as e:
            logger.warning(f"获取Maven依赖时出错: {e}，使用空依赖列表")
            maven_deps = []
        
        # 获取配置的测试重点策略
        focus_approaches = config.get_focus_approaches()
        
        # 循环生成指定数量的测试套件
        logger.info(f"开始生成 {suite_count} 个测试套件...")
        for suite_index in range(1, suite_count ):
            logger.info(f"正在生成第 {suite_index}/{suite_count} 个测试套件...")
            try:
                final_path = self.generate_for_class(
            cls_info, 
            suite_index=suite_index,
            java_version=java_version,
            maven_dependencies=maven_deps
        )
        
                if final_path:
                    generated_files.append(final_path)
                    logger.info(f"测试套件 {suite_index}/{suite_count} 生成成功: {final_path}")
                else:
                    failed_count += 1
                    logger.warning(f"测试套件 {suite_index}/{suite_count} 生成失败")
                    
                    # 尝试重试
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.info(f"尝试重新生成测试套件 {suite_index}，重试次数: {retry_count}")
                        suite_index -= 1  # 重新尝试当前套件
                    else:
                        retry_count = 0  # 重置重试计数器，进入下一个套件
            
            except Exception as e:
                failed_count += 1
                logger.error(f"生成测试套件 {suite_index} 时出错: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        if failed_count > 0:
            logger.warning(f"共有 {failed_count}/{suite_count} 个测试套件生成失败")
        
        logger.info(f"完成生成，共生成了 {len(generated_files)}/{suite_count} 个测试套件")
        return generated_files

    def _add_license_header(self, test_code: str, package_name: str) -> str:
        """
        添加Apache License头部到测试代码
        
        Args:
            test_code: 原始测试代码
            package_name: 包名
            
        Returns:
            添加了License头部的代码
        """
        # 获取License头，如果配置中不存在则使用默认值
        from .config import config
        apache_license = getattr(config, 'LICENSE_HEADER', """/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */""")
                
        # 检查是否已经包含Apache License
        if "Licensed to the Apache Software Foundation" not in test_code:
            # 如果已有package语句，确保License在package前面
            if 'package ' in test_code:
                package_pos = test_code.find('package ')
                test_code = test_code[:package_pos] + apache_license + "\n\n" + test_code[package_pos:]
            else:
                # 否则直接添加在文件开头
                test_code = apache_license + "\n\n" + test_code
            logger.info("已添加Apache License头部")
            
        return test_code

    def generate_for_class(self, cls_info: Dict[str, Any], suite_index: int = 0, 
                          java_version: str = '8', maven_dependencies: List[str] = None) -> str:
        """
        为指定的类生成测试文件
    
        Args:
            cls_info: 类信息字典
            suite_index: 测试套件索引（用于生成多个测试套件）
            java_version: Java版本
            maven_dependencies: Maven依赖列表
    
        Returns:
            生成的测试文件路径（字符串），失败时返回空字符串
        """
        # 1. 提取必要的信息
        class_name = cls_info.get('className', '')
        package_name = cls_info.get('package', '')
        project_path = cls_info.get('project_path', os.getcwd())
        
        if not class_name or not package_name:
            logger.error("类信息缺少必要的字段：className 或 package")
            return ""
            
        # 2. 构建临时和最终的测试类名
        if suite_index > 0:
            temp_class_name = f"{class_name}TestV{suite_index}Temp"
            final_class_name = f"{class_name}TestV{suite_index}"
        else:
            temp_class_name = f"{class_name}TestTemp"
            final_class_name = f"{class_name}Test"
            
        # 更新类信息，包含预期的类名
        cls_info['expectedClassName'] = final_class_name
        cls_info['suite_index'] = suite_index
        cls_info['temp_class_name'] = temp_class_name
        cls_info['final_class_name'] = final_class_name
            
        # 3. 获取项目结构配置
        test_dir = cls_info.get('testDir', 'src/test/java')
        
        # 4. 构建测试文件路径
        package_path = package_name.replace('.', '/')
        temp_file_name = f"{temp_class_name}.java"
        final_file_name = f"{final_class_name}.java"
        temp_file_path = f"{test_dir}/{package_path}/{temp_file_name}"
        final_file_path = f"{test_dir}/{package_path}/{final_file_name}"
        
        # 检查最终文件是否已经存在，如果存在则跳过生成
        final_file_path_full = os.path.join(project_path, final_file_path)
        if os.path.exists(final_file_path_full):
            logger.info(f"测试文件已存在，跳过生成: {final_file_path}")
            return final_file_path
        
        # 确保目标目录存在
        test_dir_full = os.path.join(project_path, test_dir, package_path)
        os.makedirs(test_dir_full, exist_ok=True)
                
        # 5. 构建提示词并生成测试代码
        try:
            # 构建提示词
            prompt = self.prompt_builder.build_test_generation_prompt(
                cls_info, 
                suite_index=suite_index,
                java_version=java_version,
                maven_dependencies=maven_dependencies
            )
                    
            # 调用LLM生成测试代码
            cls_info['call_type'] = 'generation'
            llm_response = llm_interface.generate_test_code(prompt, cls_info)
            
            # 将LLM响应写入统计文件
            response_info = []
            response_info.append(f"\n{'=' * 100}")
            response_info.append(f"LLM完整响应 (类: {class_name}, 套件: {suite_index})")
            response_info.append(f"{'=' * 100}")
            response_info.append(llm_response)
            response_info.append(f"{'=' * 100}\n")
            global_stats_collector._write_to_stats_file("\n".join(response_info) + "\n")
            
            # 提取Java代码
            test_code = llm_interface.extract_java_code(llm_response, cls_info)
            
            # 将提取的代码写入统计文件
            code_info = []
            code_info.append(f"\n{'#' * 100}")
            code_info.append(f"提取的Java代码 (类: {class_name}, 套件: {suite_index})")
            code_info.append(f"{'#' * 100}")
            code_info.append(test_code)
            code_info.append(f"{'#' * 100}\n")
            global_stats_collector._write_to_stats_file("\n".join(code_info) + "\n")
            
            # 修复可能存在的下划线格式类名问题
            test_code = self._fix_class_name_underscore_format(test_code, temp_class_name)
            
            # 如果提取失败但LLM响应不为空，尝试直接使用LLM响应
            if (not test_code or len(test_code.strip()) < 100) and len(llm_response) > 200:
                logger.warning(f"从LLM响应中提取代码失败，尝试直接使用LLM响应")
                # 确保响应中包含测试相关关键词
                if "@Test" in llm_response or "public class" in llm_response or "class" in llm_response:
                    # 尝试最基本的处理：确保有包声明
                    if not llm_response.strip().startswith("package"):
                        test_code = f"package {package_name};\n\n{llm_response}"
                    else:
                        test_code = llm_response

            # 检查提取的代码是否为空
            if not test_code or len(test_code.strip()) < 50:  # 放宽最小长度要求
                logger.error(f"提取的测试代码为空或过短，无法写入文件")
                return ""
            
            # 添加Apache License头部
            test_code = self._add_license_header(test_code, package_name)
            
            # 确保测试类名与文件名一致
            # 尝试查找类定义 - 更新正则表达式以匹配有或无public修饰符的类定义
            class_pattern = r'(?:public\s+)?class\s+([A-Za-z][A-Za-z0-9_]+)(\s+extends|\s+implements|\s*\{)'
            class_match = re.search(class_pattern, test_code)
            
            if class_match:
                # 找到了类定义，替换类名
                current_class_name = class_match.group(1)
                logger.info(f"找到类名: {current_class_name}，替换为: {temp_class_name}")
                
                # 替换类定义，保留原有的修饰符（如果有）
                if "public class" in test_code:
                    test_code = re.sub(
                        r'public\s+class\s+' + re.escape(current_class_name) + r'(\s+extends|\s+implements|\s*\{)',
                        f'public class {temp_class_name}\\1',
                        test_code
                    )
                else:
                    test_code = re.sub(
                        r'class\s+' + re.escape(current_class_name) + r'(\s+extends|\s+implements|\s*\{)',
                        f'class {temp_class_name}\\1',
                        test_code
                    )
                
                # 替换构造函数
                test_code = re.sub(
                    r'(\s+)' + re.escape(current_class_name) + r'(\s*\()',
                    f'\\1{temp_class_name}\\2',
                    test_code
                )
            else:
                # 没找到类定义，直接使用预期的类名进行替换
                logger.info(f"没有找到类定义，直接尝试替换预期的类名为: {temp_class_name}")
                
                # 简单尝试替换可能的类名
                test_code = re.sub(
                    r'(?:public\s+)?class\s+([A-Za-z][A-Za-z0-9_]+)',
                    f'class {temp_class_name}',
                    test_code
                )
            
            # 写入临时测试文件
            import time
            file_write_start = time.time()
            
            temp_test_full_path = os.path.join(project_path, temp_file_path)
            
            # 确保临时文件目录存在
            temp_dir = os.path.dirname(temp_test_full_path)
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir, exist_ok=True)
                logger.info(f"创建临时文件目录: {temp_dir}")

            # 写入临时文件
            with open(temp_test_full_path, 'w', encoding='utf-8') as f:
                f.write(test_code)
            logger.info(f"创建临时测试文件: {temp_test_full_path}")
            
            file_write_duration = time.time() - file_write_start
            global_stats_collector.record_file_write_time(file_write_duration)
            
            # 检查类名和文件名一致性 - 修改正则表达式以匹配有或无public修饰符的类
            class_match = re.search(r'(?:public\s+)?class\s+([A-Za-z0-9_]+)', test_code)
            if class_match and class_match.group(1) != temp_class_name:
                actual_class_name = class_match.group(1)
                logger.warning(f"文件名与类名不匹配: 文件名应为{actual_class_name}.java，当前临时文件名为{temp_class_name}.java")
                
                # 根据是否有public修饰符进行替换
                if "public class " + actual_class_name in test_code:
                    test_code = test_code.replace(f"public class {actual_class_name}", f"public class {temp_class_name}")
                else:
                    test_code = test_code.replace(f"class {actual_class_name}", f"class {temp_class_name}")
                
                # 重新写入修正后的代码
                with open(temp_test_full_path, 'w', encoding='utf-8') as f:
                    f.write(test_code)
                logger.info(f"已更新类名为: {temp_class_name}")
            
            # 运行临时测试，验证其是否成功
            logger.info(f"验证临时测试文件: {temp_test_full_path}")
            
            # 使用maven_parser运行并解析测试
            maven_start = time.time()
            output, success = run_and_parse_test(project_path, temp_test_full_path)
            maven_duration = time.time() - maven_start
            global_stats_collector.record_maven_compile_time(maven_duration)
            
            # 测试成功，直接重命名临时文件为最终文件
            if success:
                logger.info("临时测试验证成功，直接使用")
                
                # 将临时文件内容替换类名后写入最终文件
                with open(temp_test_full_path, 'r', encoding='utf-8') as f:
                    test_content = f.read()
                    
                # 替换类名 - 考虑是否有public修饰符
                if suite_index > 0:
                    if "public class " + temp_class_name in test_content:
                        test_content = test_content.replace(f"public class {temp_class_name}", f"public class {final_class_name}")
                    else:
                        test_content = test_content.replace(f"class {temp_class_name}", f"class {final_class_name}")
                else:
                    if "public class " + temp_class_name in test_content:
                        test_content = test_content.replace(f"public class {temp_class_name}", f"public class {final_class_name}")
                    else:
                        test_content = test_content.replace(f"class {temp_class_name}", f"class {final_class_name}")
                
                # 写入最终文件
                final_file_path_full = os.path.join(project_path, final_file_path)
                with open(final_file_path_full, 'w', encoding='utf-8') as f:
                    f.write(test_content)
                
                logger.info(f"创建最终文件: {final_file_path}")
                    
                # 删除临时文件
                try:
                    os.remove(temp_test_full_path)
                    logger.info(f"删除临时文件: {temp_test_full_path}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {e}")
                
                return final_file_path
            else:
                # 如果测试失败，使用rule_fixer进行修复
                logger.info("临时测试失败，使用rule_fixer进行修复")
                
                # 已经有输出和错误分析结果，直接传递给rule_fixer，避免重复执行Maven测试
                cls_info_with_output = cls_info.copy()
                cls_info_with_output['maven_output'] = output
                cls_info_with_output['maven_success'] = False
                
                # 记录Maven编译错误的摘要，使用test_repair模块的解析器确保一致性
                from test_repair.maven_parser import MavenOutputParser
                parser = MavenOutputParser()
                maven_output = parser.parse(output)
                error_prompt = maven_output.get_error_prompt()
                
                # 记录有价值的错误信息，这对于后续的规则修复和LLM修复至关重要
                if error_prompt:
                    logger.info("Maven错误摘要 (用于规则匹配和LLM修复):")
                    # 完整显示错误信息，因为这对修复非常重要
                    for line in error_prompt.splitlines():
                        logger.info(f"  {line}")
                
                # 直接传递已解析的错误信息，避免重复执行Maven测试
                cls_info_with_output['maven_parsed_output'] = maven_output
                cls_info_with_output['parsed_error_prompt'] = error_prompt
                
                # 传递统计收集器以获得准确的LLM调用统计
                cls_info_with_output['stats_collector'] = global_stats_collector
                
                # 使用独立的test_repair模块进行修复（没有回退机制）
                try:
                    # 导入test_repair模块的修复客户端
                    import sys
                    
                    # 添加agents目录到sys.path
                    agents_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                    if agents_dir not in sys.path:
                        sys.path.insert(0, agents_dir)
                    
                    from test_repair import TestRepairClient
                    
                    # 创建修复客户端并调用修复方法
                    repair_client = TestRepairClient()
                    final_path, repair_stats = repair_client.repair_test_file(temp_file_path, cls_info_with_output)
                    logger.info("使用test_repair模块进行修复")
                    
                    # 将修复统计信息合并到全局统计中
                    if repair_stats:
                        global_stats_collector.merge_repair_stats(repair_stats)
                    
                    if final_path:
                        logger.info(f"test_repair修复成功，生成最终文件: {final_path}")
                    else:
                        logger.warning("test_repair修复失败，测试文件已被删除")
                    
                except ImportError as e:
                    logger.error(f"无法导入test_repair模块: {e}")
                    logger.error("test_repair模块是必需的，无法继续修复")
                    final_path = ""
                except Exception as e:
                    logger.error(f"使用test_repair模块修复时发生异常: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    final_path = ""
                
                # final_path可能为空（修复失败并删除了测试文件）或非空（修复成功）
                return final_path or ""
        except Exception as e:
            logger.error(f"生成测试代码时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ""

    def _fix_class_name_underscore_format(self, test_code: str, temp_class_name: str) -> str:
        """
        修复可能存在的下划线格式类名问题（Test_V1 → TestV1）
    
    Args:
            test_code: 测试代码
            temp_class_name: 预期的临时类名
    
    Returns:
            修复后的代码
        """
        # 尝试查找可能的带下划线格式的类名
        base_name = re.sub(r'TestV\d+Temp$', '', temp_class_name)
        
        # 匹配几种常见的错误格式
        patterns = [
            rf'(?:public\s+)?class\s+({base_name}Test_V\d+(?:Temp)?)',  # SedolCheckDigitTest_V1
            rf'(?:public\s+)?class\s+({base_name}_TestV\d+(?:Temp)?)',  # SedolCheckDigit_TestV1
            rf'(?:public\s+)?class\s+({base_name}_Test_V\d+(?:Temp)?)'  # SedolCheckDigit_Test_V1
        ]
        
        wrong_class_name = None
        
        # 检查所有可能的错误格式
        for pattern in patterns:
            match = re.search(pattern, test_code)
            if match:
                wrong_class_name = match.group(1)
                logger.warning(f"检测到带下划线的类名格式: {wrong_class_name}，需要改为: {temp_class_name}")
                
                # 替换类定义
                if "public class " + wrong_class_name in test_code:
                    test_code = test_code.replace(f"public class {wrong_class_name}", f"public class {temp_class_name}")
                else:
                    test_code = test_code.replace(f"class {wrong_class_name}", f"class {temp_class_name}")
                
                # 替换构造函数
                constructor_pattern = rf'(\s+){wrong_class_name}(\s*\()'
                test_code = re.sub(constructor_pattern, f'\\1{temp_class_name}\\2', test_code)
                
                logger.info(f"已修复下划线格式类名问题: {wrong_class_name} → {temp_class_name}")
                break
        
        # 特殊处理，再次检查是否有任何公共类与文件名不匹配
        class_match = re.search(r'public\s+class\s+([A-Za-z0-9_]+)', test_code)
        if class_match and class_match.group(1) != temp_class_name:
            actual_class_name = class_match.group(1)
            logger.warning(f"发现public类名与文件名不匹配: {actual_class_name} ≠ {temp_class_name}")
            
            # 直接替换
            test_code = test_code.replace(f"public class {actual_class_name}", f"public class {temp_class_name}")
            
            # 替换构造函数
            constructor_pattern = rf'(\s+){actual_class_name}(\s*\()'
            test_code = re.sub(constructor_pattern, f'\\1{temp_class_name}\\2', test_code)
            
            logger.info(f"已修复类名不匹配问题: {actual_class_name} → {temp_class_name}")
            
        return test_code

# 创建全局文件写入器实例
file_writer = TestFileWriter()

def generate_for_class(cls_info: Dict[str, Any], project_path: str, suite_index: int = 0) -> bool:
    """
    为指定的类生成测试文件
    
    Args:
        cls_info: 类信息字典
        project_path: 项目路径
        suite_index: 测试套件索引，用于选择不同的测试重点
    
    Returns:
        如果测试生成成功，则返回True
    """
    # 添加类型检查
    if not isinstance(cls_info, dict):
        logger.error(f"cls_info不是字典类型，而是 {type(cls_info)}")
        return False
        
    # 确保project_path是字符串类型
    if not isinstance(project_path, str):
        logger.error(f"project_path必须是字符串，而不是 {type(project_path)}")
        if project_path is None:
            logger.error("project_path为None，无法生成测试")
            return False
        try:
            # 尝试将project_path转换为字符串
            project_path = str(project_path)
            logger.warning(f"已将project_path转换为字符串: {project_path}")
        except Exception as e:
            logger.error(f"转换project_path为字符串时出错: {e}")
            return False
    
    # 验证项目路径是否存在且包含pom.xml
    if not os.path.exists(project_path):
        logger.error(f"项目路径不存在: {project_path}")
        return False
    if not os.path.exists(os.path.join(project_path, "pom.xml")):
        logger.error(f"项目路径中未找到pom.xml: {project_path}")
        return False
    
    # 获取类名
    class_name = cls_info.get('className', cls_info.get('class_name', ''))
    if not class_name:
        logger.error("类名为空，无法生成测试")
        return False
    
    # 检查测试文件是否已经存在
    package_name = cls_info.get('package', '')
    test_dir = cls_info.get('testDir', 'src/test/java')
    package_path = package_name.replace('.', '/')
    
    if suite_index > 0:
        final_class_name = f"{class_name}TestV{suite_index}"
    else:
        final_class_name = f"{class_name}Test"
        
    final_file_name = f"{final_class_name}.java"
    final_file_path = f"{test_dir}/{package_path}/{final_file_name}"
    final_file_path_full = os.path.join(project_path, final_file_path)
    
    if os.path.exists(final_file_path_full):
        logger.info(f"测试文件已存在，跳过生成: {final_file_path}")
        return True
    
    # 开始统计收集
    test_stats = global_stats_collector.start_test_generation(
        test_file_path=final_file_path_full,
        class_name=class_name,
        suite_index=suite_index
    )
    
    try:
        # 直接从config获取test_focus
        focus_approaches = config.get_focus_approaches()
        if len(focus_approaches) > 0:
            # 使用循环索引确保即使suite_index超出范围也能获取到有效的测试重点
            focus_index = (suite_index - 1) % len(focus_approaches)
            cls_info['test_focus'] = focus_approaches[focus_index]
            logger.info(f"为套件{suite_index}使用测试重点索引: {focus_index}")
        else:
            # 如果配置中没有测试重点（极少数情况），使用默认值
            cls_info['test_focus'] = "Generate a test suite following JUnit 5 best practices."
            logger.warning("配置中没有测试重点，使用默认值")
        
        # 在终端显示简化信息，详细信息写入文件
        logger.info(f"开始生成 {class_name} Suite {suite_index}")
        
        # 将测试重点信息写入统计文件
        focus_info = []
        focus_info.append(f"\n{'#' * 80}")
        focus_info.append(f"为类 {class_name} 生成测试套件 {suite_index}")
        focus_info.append(f"测试重点: {cls_info['test_focus']}")
        focus_info.append(f"{'#' * 80}\n")
        global_stats_collector._write_to_stats_file("\n".join(focus_info) + "\n")
            
        # 确保suite_index在类信息中
        cls_info['suite_index'] = suite_index  # suite_index已经从1开始
        
        # 添加项目路径到类信息
        cls_info['project_path'] = project_path
        
        # 使用全局文件写入器实例生成测试
        logger.info(f"为类 {class_name} 生成测试套件 {suite_index}")
        final_path = file_writer.generate_for_class(cls_info, suite_index=suite_index)
        success = bool(final_path)
        
        # 完成统计收集
        completed_stats = global_stats_collector.finish_test_generation(success)
        if completed_stats:
            global_stats_collector.print_test_summary(completed_stats)
        
        return success
    except Exception as e:
        logger.error(f"生成测试时出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 标记为失败并完成统计
        global_stats_collector.finish_test_generation(False)
        return False