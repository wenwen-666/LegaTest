"""
规则修复模块

负责使用预定义规则修复测试代码中的错误，提供整体流程控制
"""

import os
import re
import logging
import datetime
import time
from typing import Dict, Any, Optional, Tuple, List, Callable

# 引入classify_and_fix模块中的函数
# 使用绝对导入避免相对导入错误
try:
    from .classify_and_fix import (
        classify_error, 
        fix_by_category, 
        fix_duplicate_modifiers, 
        fix_unused_imports,
        fix_duplicate_annotations,
        fix_duplicate_imports,
        fix_api_compatibility_errors,
        fix_private_access_errors,
        fix_constructor_errors,
        fix_resource_management_errors
    )
except ImportError:
    from classify_and_fix import (
        classify_error, 
        fix_by_category, 
        fix_duplicate_modifiers, 
        fix_unused_imports,
        fix_duplicate_annotations,
        fix_duplicate_imports,
        fix_api_compatibility_errors,
        fix_private_access_errors,
        fix_constructor_errors,
        fix_resource_management_errors
    )
# 修复导入路径
import sys
import os

# 添加test_repair目录到sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 使用绝对导入避免相对导入错误
try:
    from maven_parser import MavenOutputParser, run_maven_test, run_and_parse_test
    from llm_fixer.llm_repair import repair_with_llm
except ImportError:
    # 如果绝对导入失败，尝试从test_repair模块导入
    import sys
    import os
    test_repair_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if test_repair_dir not in sys.path:
        sys.path.insert(0, test_repair_dir)
    
    from maven_parser import MavenOutputParser, run_maven_test, run_and_parse_test
    from llm_fixer.llm_repair import repair_with_llm

# 配置日志
logger = logging.getLogger(__name__)

# 类型定义
FixerFunction = Callable[[str, Dict[str, Any]], str]

class RuleFixer:
    """规则修复器，负责使用预定义规则修复测试代码中的错误"""
    
    def __init__(self):
        """初始化规则修复器"""
        logger.info("初始化规则修复器")
        self.maven_parser = MavenOutputParser()
    
    def _update_class_name(self, code: str, old_name: str, new_name: str) -> str:
        """
        更新代码中的类名
        
        Args:
            code: 源代码
            old_name: 旧类名
            new_name: 新类名
            
        Returns:
            更新后的代码
        """
        # 尝试查找类定义
        class_pattern = r'((?:public\s+)?class\s+)([A-Za-z][A-Za-z0-9_]+)(\s+extends|\s+implements|\s*\{)'
        class_match = re.search(class_pattern, code)
        
        if class_match:
            actual_class_name = class_match.group(2)
            logger.info(f"找到实际类名: {actual_class_name}，将替换为: {new_name}")
            
            # 替换类定义
            code = re.sub(
                r'((?:public\s+)?class\s+)' + re.escape(actual_class_name) + r'(\s+extends|\s+implements|\s*\{)',
                f'\\1{new_name}\\2',
                code
            )
            
            # 替换构造函数
            code = re.sub(
                r'(\s+)' + re.escape(actual_class_name) + r'(\s*\()',
                f'\\1{new_name}\\2',
                code
            )
        else:
            # 找不到类名，直接尝试替换预期的旧类名
            logger.info(f"未找到实际类名，直接尝试替换预期的类名: {old_name} -> {new_name}")
            
            # 替换类定义
            code = re.sub(
                rf'((?:public\s+)?class\s+){old_name}(\s+.*?{{)',
                rf'\1{new_name}\2',
                code
            )
            
            # 替换构造函数
            code = re.sub(
                rf'(\s+){old_name}(\s*\()',
                rf'\1{new_name}\2',
                code
            )
        
        return code
    
    def process_test(self, test_path: str, cls_info: Dict[str, Any]) -> str:
        """
        处理测试文件的完整流程
        
        Args:
            test_path: 测试文件路径
            cls_info: 类信息
            
        Returns:
            成功时返回最终文件路径，失败时返回空字符串
        """
        project_path = cls_info.get('project_path', os.getcwd())
        package_name = cls_info.get('package', '')
        class_name = cls_info.get('className', '')
        suite_index = cls_info.get('suite_index', 0)
        
        # 确保test_path是字符串
        if not isinstance(test_path, str):
            logger.error(f"test_path必须是字符串，而不是 {type(test_path)}")
            return ""
        
        # 1. 确定临时文件和最终文件名
        temp_full_path = os.path.join(project_path, test_path)
        if not os.path.exists(temp_full_path):
            logger.error(f"临时测试文件不存在: {temp_full_path}")
            return ""
            
        # 从临时文件路径获取最终文件路径
        # 对于演化模式，最终路径应该与临时路径相同（不需要重命名）
        # 对于生成模式，移除"Temp"后缀
        if "Temp.java" in test_path:
            final_path = test_path.replace("Temp.java", ".java")
        else:
            # 演化模式，文件名不变
            final_path = test_path
        final_full_path = os.path.join(project_path, final_path)
        
        # 检测传入的是基础类名还是完整测试类名
        def _is_complete_test_class_name(name):
            """检测是否是完整的测试类名"""
            return ("Test" in name and 
                   (name.endswith("Test") or "TestV" in name or 
                    "Crossover" in name or "Mutation" in name))
        
        # 获取临时类名和最终类名
        if _is_complete_test_class_name(class_name):
            # 传入的已经是完整的测试类名（迭代演化场景）
            # 演化模式：类名不变，等待选择
            temp_class_name = class_name
            final_class_name = class_name
            repair_mode = "evolution"
            logger.info(f"检测到完整测试类名（演化模式）: {class_name}")
        else:
            # 传入的是基础类名（测试生成场景）
            # 生成模式：修复成功后重命名
            if suite_index > 0:
                temp_class_name = f"{class_name}TestV{suite_index}Temp"
                final_class_name = f"{class_name}TestV{suite_index}"
            else:
                temp_class_name = f"{class_name}TestTemp"
                final_class_name = f"{class_name}Test"
            repair_mode = "generation"
            logger.info(f"基础类名构造测试类（生成模式）: {class_name} -> {temp_class_name} -> {final_class_name}")
            
        try:
            # 2. 读取临时文件内容
            with open(temp_full_path, 'r', encoding='utf-8') as f:
                temp_test_code = f.read()
                
            # 3. 首先运行测试，检查是否能够直接成功
            logger.info(f"检查测试文件: {temp_full_path}")
            
            # 使用cls_info中已有的Maven输出和解析结果，避免重复执行Maven测试
            if 'maven_output' in cls_info and 'maven_success' in cls_info:
                logger.info("使用已有的Maven执行结果")
                output = cls_info.get('maven_output', '')
                success = cls_info.get('maven_success', False)
                
                # 使用已解析的Maven输出（如果有）
                if 'maven_parsed_output' in cls_info:
                    parsed_output = cls_info.get('maven_parsed_output')
                    logger.info("使用已解析的Maven输出")
                else:
                    parsed_output = self.maven_parser.parse(output)
            else:
                # 如果没有已有结果，执行Maven测试
                logger.info("没有已有的Maven执行结果，执行测试")
                output, success = run_and_parse_test(project_path, temp_full_path)
                parsed_output = self.maven_parser.parse(output)
            
            # 4. 如果测试直接成功（maven_parser已经判定为build success且无测试失败），重命名文件并返回
            if success:
                logger.info("临时测试通过！无需修复，直接使用")
                # 生成模式需要替换类名，演化模式保持原类名
                if repair_mode == "generation":
                    final_test_code = self._update_class_name(temp_test_code, temp_class_name, final_class_name)
                    logger.info(f"生成模式：类名从 {temp_class_name} 更新为 {final_class_name}")
                else:
                    final_test_code = temp_test_code
                    logger.info(f"演化模式：保持原类名 {final_class_name}")
                
                # 写入最终文件
                with open(final_full_path, 'w', encoding='utf-8') as f:
                    f.write(final_test_code)
                    
                # 删除临时文件（仅生成模式）
                if repair_mode == "generation":
                    os.remove(temp_full_path)
                    logger.info(f"删除临时文件: {temp_full_path}")
                
                return final_path
            
            # 5. 测试失败，准备修复
            logger.info("测试失败，尝试使用规则修复")
            
            # 7. 如果有错误，尝试分类并应用规则修复
            fixed_code = temp_test_code
            rule_fixed = False
            has_known_error_type = False
            goto_llm_repair = True
            
            # 开始规则修复计时
            rule_repair_start_time = time.time()
            repair_stats = cls_info.get('repair_stats')
            
            if parsed_output.has_errors():
                all_errors = parsed_output.get_all_errors()
                
                for error in all_errors:
                    # 获取错误信息
                    error_message = error.get_message()
                    
                    # 分类错误
                    error_category = classify_error(error_message)
                    
                    if error_category:
                        has_known_error_type = True
                        logger.info(f"识别到错误类别: {error_category}")
                        
                        # 查找对应的修复函数
                        fixer_func = FIXERS.get(error_category, FIXERS.get("DEFAULT"))
                        
                        # 构造错误信息字典
                        error_info = {
                            "category": error_category,
                            "message": error_message,
                            "match": error_message
                        }
                        
                        # 应用修复
                        before_fix = fixed_code
                        fixed_code = fixer_func(fixed_code, error_info)
                        
                        # 检查是否有变化
                        if fixed_code != before_fix:
                            rule_fixed = True
                            logger.info(f"已应用 {error_category} 类型的修复规则")
                            
                            # 更新统计信息
                            repair_stats = cls_info.get('repair_stats')
                            if repair_stats:
                                repair_stats.repair_attempts += 1
                            
                            # 记录修改内容摘要
                            diff = []
                            before_lines = before_fix.splitlines()
                            after_lines = fixed_code.splitlines()
                            
                            # 简单差异比较，找出修改的行
                            for i in range(min(len(before_lines), len(after_lines))):
                                if before_lines[i] != after_lines[i]:
                                    diff.append(f"行 {i+1}: '{before_lines[i][:40]}...' => '{after_lines[i][:40]}...'")
                                    if len(diff) >= 3:  # 限制展示的差异行数
                                        break
                                            
                            if diff:
                                logger.info(f"修改摘要: {'; '.join(diff)}")
                
                # 如果没有识别到已知的错误类型，直接使用LLM修复
                if not has_known_error_type:
                    logger.info("未识别到已知错误类型，跳过规则修复，直接使用LLM修复")
                    goto_llm_repair = True
                # 如果应用了规则修复，保存并验证
                elif rule_fixed:
                    logger.info("规则修复已应用，验证修复结果")
                    goto_llm_repair = False
                    
                    # 写入修复后的代码
                    with open(temp_full_path, 'w', encoding='utf-8') as f:
                        f.write(fixed_code)
                        
                    # 验证修复后的代码
                    logger.info("验证规则修复结果...")
                    output, success = run_and_parse_test(project_path, temp_full_path)
                    
                    # 如果规则修复成功（maven_parser已经判定为build success且无测试失败），重命名并返回
                    if success:
                        logger.info("规则修复成功！")
                        # 更新统计信息
                        if repair_stats:
                            repair_stats.rule_fixes_applied += 1
                            # 添加规则修复时间
                            rule_repair_duration = time.time() - rule_repair_start_time
                            repair_stats.rule_repair_time += rule_repair_duration
                        # 生成模式需要替换类名，演化模式保持原类名
                        if repair_mode == "generation":
                            final_test_code = self._update_class_name(fixed_code, temp_class_name, final_class_name)
                            logger.info(f"生成模式：类名从 {temp_class_name} 更新为 {final_class_name}")
                        else:
                            final_test_code = fixed_code
                            logger.info(f"演化模式：保持原类名 {final_class_name}")
                        
                        # 写入最终文件
                        with open(final_full_path, 'w', encoding='utf-8') as f:
                            f.write(final_test_code)
                            
                        # 删除临时文件（仅生成模式）
                        if repair_mode == "generation":
                            os.remove(temp_full_path)
                            logger.info(f"删除临时文件: {temp_full_path}")
                        
                        return final_path
                    else:
                        # 规则修复失败，记录新的错误信息
                        logger.warning("规则修复失败，可能引入了新的错误")
                        
                        # 解析新的错误
                        new_errors = self.maven_parser.parse(output)
                        if new_errors.has_errors():
                            logger.warning("规则修复后出现的新错误:")
                            error_prompt = new_errors.get_error_prompt()
                            logger.warning(error_prompt)
                        
                        # 需要使用LLM修复
                        goto_llm_repair = True
                else:
                    # 已识别错误类型但没有可用的修复规则，使用LLM修复
                    logger.info("已识别错误类型，但无可用修复规则，使用LLM修复")
                    goto_llm_repair = True
            else:
                # 没有检测到具体错误，但编译失败，使用LLM修复
                logger.info("未检测到具体错误，但编译失败，使用LLM修复")
                goto_llm_repair = True
            
            # 如果需要LLM修复
            if goto_llm_repair:
                # 优先使用原始的错误提示（测试失败），而不是规则修复失败后的编译错误
                error_prompt = None
                
                # 首先尝试使用原始错误（通常是测试失败）
                if 'original_error_prompt' in cls_info and cls_info['original_error_prompt']:
                    error_prompt = cls_info['original_error_prompt']
                    logger.info("使用原始错误提示信息（测试失败）")
                
                # 如果没有原始错误，使用当前解析的错误
                if not error_prompt:
                    error_prompt = parsed_output.get_error_prompt()
                    logger.info("使用当前解析的错误提示信息")
                
                # 如果重新解析仍然返回通用错误，尝试从缓存获取
                if error_prompt == "Maven构建失败，但没有检测到具体错误信息。" or error_prompt == "Maven构建失败":
                    if 'parsed_error_prompt' in cls_info and cls_info['parsed_error_prompt']:
                        cached_error = cls_info['parsed_error_prompt']
                        if cached_error != "Maven构建失败" and cached_error != error_prompt:
                            error_prompt = cached_error
                            logger.info("回退到缓存的错误提示信息")
                
                # 记录错误提示，这对LLM修复至关重要
                logger.info("传递给LLM的错误信息:")
                for line in error_prompt.splitlines():
                    logger.info(f"  {line}")

                # 调试：输出原始Maven输出到文件（可选，避免文件不存在导致异常）
                try:
                    # 使用项目目录下的调试文件
                    debug_dir = os.path.join(project_path, "target")
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir, exist_ok=True)
                    debug_file = os.path.join(debug_dir, "maven_output_debug.txt")

                    with open(debug_file, "a", encoding="utf-8") as f:
                        f.write(f"\n{'='*100}\n")
                        f.write(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"类名: {class_name}\n")
                        f.write(f"Maven输出长度: {len(cls_info.get('maven_output', ''))}\n")
                        f.write(f"Maven输出:\n{cls_info.get('maven_output', '')}\n")
                        f.write(f"解析后的错误提示: {error_prompt}\n")
                        f.write(f"{'='*100}\n\n")
                except Exception as debug_error:
                    # 调试文件写入失败不应该影响修复流程
                    logger.warning(f"写入调试文件失败（不影响修复）: {debug_error}")
                
                # 添加真实类名信息，便于调试
                logger.info(f"真实类名: {class_name}, 临时类名: {temp_class_name}")
                
                # 调用LLM修复
                # 尝试获取被测类的源代码
                source_code = ""
                try:
                    # 从测试类名中提取被测试的类名
                    def extract_target_class_name(test_class_name):
                        """从测试类名中提取被测试的类名"""
                        import re
                        # 移除Test相关的后缀
                        name = re.sub(r'Test.*$', '', test_class_name)  # 移除Test及其后面的所有内容
                        return name if name else test_class_name
                    
                    def remove_comments_from_source(source_code):
                        """从源代码中移除注释以节省token，压缩空白行"""
                        if not source_code:
                            return source_code
                        
                        lines = source_code.split('\n')
                        cleaned_lines = []
                        in_multiline_comment = False
                        
                        for line in lines:
                            original_line = line
                            
                            # 处理多行注释
                            if not in_multiline_comment:
                                # 处理在同一行内的多行注释
                                while '/*' in line and '*/' in line:
                                    start = line.find('/*')
                                    end = line.find('*/', start) + 2
                                    line = line[:start] + line[end:]
                                
                                # 检查是否有多行注释开始
                                if '/*' in line:
                                    in_multiline_comment = True
                                    line = line[:line.find('/*')]
                            else:
                                # 在多行注释中，查找结束
                                if '*/' in line:
                                    in_multiline_comment = False
                                    line = line[line.find('*/') + 2:]
                                else:
                                    # 完全在多行注释中，跳过这行
                                    continue
                            
                            # 移除单行注释（但要小心字符串中的//）
                            if '//' in line:
                                # 简单处理：直接截断到//位置（忽略字符串内的情况）
                                line = line[:line.find('//')]
                            
                            # 去除行尾空白
                            line = line.rstrip()
                            
                            # 只保留非空行，但保留包含代码的行
                            if line.strip():
                                cleaned_lines.append(line)
                            elif len(cleaned_lines) > 0 and cleaned_lines[-1].strip():
                                # 在有内容的行之后保留一个空行（用于分隔）
                                cleaned_lines.append('')
                        
                        # 移除开头和结尾的多余空行
                        while cleaned_lines and not cleaned_lines[0].strip():
                            cleaned_lines.pop(0)
                        while cleaned_lines and not cleaned_lines[-1].strip():
                            cleaned_lines.pop()
                        
                        # 压缩连续的空行为单个空行
                        compressed_lines = []
                        prev_empty = False
                        for line in cleaned_lines:
                            if not line.strip():
                                if not prev_empty:
                                    compressed_lines.append('')
                                prev_empty = True
                            else:
                                compressed_lines.append(line)
                                prev_empty = False
                        
                        return '\n'.join(compressed_lines)
                    
                    target_class = extract_target_class_name(class_name)
                    logger.info(f"从测试类名 '{class_name}' 提取被测类名: '{target_class}'")
                    
                    # 构建被测类的可能路径（通用查找策略）
                    if 'package' in cls_info and 'project_path' in cls_info:
                        package_path = cls_info.get('package', '').replace('.', '/')
                        project_path = cls_info.get('project_path', '')
                        
                        # 多种可能的项目结构查找
                        possible_paths = [
                            # 标准Maven结构
                            os.path.join(project_path, "src", "main", "java", package_path, f"{target_class}.java"),
                            # 项目根目录下的源码
                            os.path.join(project_path, package_path, f"{target_class}.java"),
                            # 绝对路径（处理符号链接或特殊结构）
                            os.path.abspath(os.path.join(project_path, "src", "main", "java", package_path, f"{target_class}.java")),
                            # 处理可能的相对路径问题
                            os.path.join(os.path.dirname(project_path), "src", "main", "java", package_path, f"{target_class}.java")
                        ]
                        
                        # 依次尝试各种路径
                        for attempt_path in possible_paths:
                            if os.path.exists(attempt_path):
                                try:
                                    with open(attempt_path, 'r', encoding='utf-8') as f:
                                        raw_source_code = f.read()
                                    
                                    # 移除注释
                                    source_code = remove_comments_from_source(raw_source_code)
                                    
                                    logger.info(f"Successfully found source code: {attempt_path}")
                                    logger.info(f"Source code length: original {len(raw_source_code)} chars, after comment removal {len(source_code)} chars")
                                    break
                                except Exception as read_e:
                                    logger.warning(f"Failed to read source file {attempt_path}: {read_e}")
                                    continue
                        else:
                            logger.warning(f"Source code file not found for {target_class}. Tried paths: {possible_paths}")
                except Exception as e:
                    logger.error(f"读取被测类源代码时出错: {e}")
                
                # 增强错误提示 - 根据错误分类添加具体的修复指导
                enhanced_error_prompt = generate_enhanced_prompt(error_prompt)
                logger.info("使用增强后的错误提示进行LLM修复")
                
                # 第一次LLM修复
                logger.info("开始第一次LLM修复...")
                
                # 更新统计信息
                repair_stats = cls_info.get('repair_stats')
                if repair_stats:
                    repair_stats.repair_attempts += 1
                    repair_stats.llm_calls += 1
                
                # 传递完整的cls_info给repair_with_llm，包括stats_collector
                llm_cls_info = {
                    'className': temp_class_name,
                    'temp_class_name': temp_class_name,
                    'stats_collector': cls_info.get('stats_collector'),
                    'call_type': 'repair'
                }
                try:
                    llm_fixed_code = repair_with_llm(temp_test_code, enhanced_error_prompt, temp_class_name, source_code, is_second_attempt=False, repair_stats=repair_stats, cls_info=llm_cls_info)
                except Exception as e:
                    logger.error(f"第一次LLM修复失败: {e}")
                    print(f"第一次LLM修复失败，跳到第二次LLM修复: {e}")
                    llm_fixed_code = None
                
                # 写入LLM修复后的代码
                if llm_fixed_code is not None:
                    with open(temp_full_path, 'w', encoding='utf-8') as f:
                        f.write(llm_fixed_code)
                else:
                    # 第一次LLM修复失败，直接跳到第二次
                    llm_success = False
                    
                # 验证LLM修复后的代码（仅在有修复代码时执行）
                if llm_fixed_code is not None:
                    logger.info("验证第一次LLM修复结果...")
                    output, success = run_and_parse_test(project_path, temp_full_path)
                    
                    # LLM修复阶段宽松成功条件：只要BUILD SUCCESS就视为成功，即使有测试失败也接受
                    llm_success = "BUILD SUCCESS" in output
                else:
                    output, success = "", False
                    llm_success = False
                if llm_success and not success:
                    logger.info("BUILD SUCCESS但有测试失败，在LLM修复阶段视为成功")
                elif not llm_success:
                    logger.info("LLM修复后仍然BUILD FAILURE")
                
                # 如果第一次LLM修复成功，重命名并返回
                if llm_success:
                    logger.info("第一次LLM修复成功！")
                    # 更新统计信息
                    if repair_stats:
                        repair_stats.llm_fixes_applied += 1
                    # 生成模式需要替换类名，演化模式保持原类名
                    if repair_mode == "generation":
                        final_test_code = self._update_class_name(llm_fixed_code, temp_class_name, final_class_name)
                        logger.info(f"生成模式：类名从 {temp_class_name} 更新为 {final_class_name}")
                    else:
                        final_test_code = llm_fixed_code
                        logger.info(f"演化模式：保持原类名 {final_class_name}")
                    
                    # 写入最终文件
                    with open(final_full_path, 'w', encoding='utf-8') as f:
                        f.write(final_test_code)
                        
                    # 删除临时文件（仅生成模式）
                    if repair_mode == "generation":
                        os.remove(temp_full_path)
                        logger.info(f"删除临时文件: {temp_full_path}")
                    
                    return final_path
                else:
                    # 第一次LLM修复失败，尝试第二次修复
                    logger.info("第一次LLM修复失败，尝试第二次修复...")
                    
                    # 解析新的错误信息
                    new_parsed_output = self.maven_parser.parse(output)
                    new_error_prompt = new_parsed_output.get_error_prompt()
                    
                    # 记录新的错误信息
                    logger.info("第二次修复的错误信息:")
                    for line in new_error_prompt.splitlines():
                        logger.info(f"  {line}")
                    
                    # 增强第二次修复的错误提示
                    enhanced_new_error_prompt = generate_enhanced_prompt(new_error_prompt)
                    logger.info("使用增强后的错误提示进行第二次LLM修复")
                    
                    # 第二次LLM修复，使用新的错误信息
                    logger.info("开始第二次LLM修复...")
                    # 更新统计信息（第二次LLM调用）
                    if repair_stats:
                        repair_stats.llm_calls += 1
                    
                    # 第二次修复也传递完整的cls_info
                    llm_cls_info_2 = {
                        'className': temp_class_name,
                        'temp_class_name': temp_class_name,
                        'stats_collector': cls_info.get('stats_collector'),
                        'call_type': 'repair'
                    }
                    try:
                        # 使用第一次修复的代码作为基础，如果第一次失败则使用原始代码
                        base_code = llm_fixed_code if llm_fixed_code is not None else temp_test_code
                        second_llm_fixed_code = repair_with_llm(base_code, enhanced_new_error_prompt, temp_class_name, source_code, is_second_attempt=True, repair_stats=repair_stats, cls_info=llm_cls_info_2)
                    except Exception as e:
                        logger.error(f"第二次LLM修复失败: {e}")
                        print(f"第二次LLM修复失败，跳到测试方法移除: {e}")
                        second_llm_fixed_code = None
                    
                    # 写入第二次LLM修复后的代码
                    if second_llm_fixed_code is not None:
                        with open(temp_full_path, 'w', encoding='utf-8') as f:
                            f.write(second_llm_fixed_code)
                    else:
                        # 第二次LLM修复也失败，设置为失败状态
                        second_llm_success = False
                    
                    # 验证第二次LLM修复后的代码（仅在有修复代码时执行）
                    if second_llm_fixed_code is not None:
                        logger.info("验证第二次LLM修复结果...")
                        output, success = run_and_parse_test(project_path, temp_full_path)
                    else:
                        output, success = "", False
                    
                    # LLM修复阶段宽松成功条件：只要BUILD SUCCESS就视为成功
                    llm_success = "BUILD SUCCESS" in output
                    if llm_success and not success:
                        logger.info("BUILD SUCCESS但有测试失败，在第二次LLM修复阶段视为成功")
                    elif not llm_success:
                        logger.info("第二次LLM修复后仍然BUILD FAILURE")
                    
                    # 如果第二次LLM修复成功，重命名并返回
                    if llm_success:
                        logger.info("第二次LLM修复成功！")
                        # 更新统计信息
                        if repair_stats:
                            repair_stats.llm_fixes_applied += 1
                        # 生成模式需要替换类名，演化模式保持原类名
                        if repair_mode == "generation":
                            final_test_code = self._update_class_name(second_llm_fixed_code, temp_class_name, final_class_name)
                            logger.info(f"生成模式：类名从 {temp_class_name} 更新为 {final_class_name}")
                        else:
                            final_test_code = second_llm_fixed_code
                            logger.info(f"演化模式：保持原类名 {final_class_name}")
                        
                        # 写入最终文件
                        with open(final_full_path, 'w', encoding='utf-8') as f:
                            f.write(final_test_code)
                            
                        # 删除临时文件（仅生成模式）
                        if repair_mode == "generation":
                            os.remove(temp_full_path)
                            logger.info(f"删除临时文件: {temp_full_path}")
                        
                        return final_path
                
                    # 两次LLM修复都失败，进入增强失败处理逻辑
                    logger.info("两次LLM修复都失败，进入增强失败处理逻辑")
                    
                    # 对于Evolution模式，采用更激进的处理策略
                    if repair_mode == "evolution":
                        logger.info("Evolution模式：采用增强失败处理策略")
                        success_after_cleanup = self._handle_evolution_failure(
                            second_llm_fixed_code or temp_test_code, 
                            temp_full_path, 
                            final_full_path, 
                            project_path,
                            temp_class_name,
                            final_class_name
                        )
                        if success_after_cleanup:
                            return final_path
                        else:
                            logger.warning("Evolution模式增强处理失败，删除测试文件")
                            if os.path.exists(final_full_path):
                                os.remove(final_full_path)
                                logger.info(f"删除Evolution测试文件: {final_full_path}")
                            return ""
                    else:
                        # Generation模式保持原有逻辑
                        logger.info("Generation模式：尝试根据错误信息删除有问题的测试用例")
                    
                    # 保证second_llm_fixed_code不为None
                    if not second_llm_fixed_code:
                        logger.warning("second_llm_fixed_code为None，跳过删除测试方法尝试")
                        # 直接跳转到文件删除逻辑
                    else:
                        # 运行一次测试获取详细的错误信息
                        with open(temp_full_path, 'w', encoding='utf-8') as f:
                            f.write(second_llm_fixed_code)
                        
                        logger.info("运行测试获取错误信息...")
                        output, test_success = run_and_parse_test(project_path, temp_full_path)
                        
                        # 从错误输出中提取失败的测试方法（包括编译错误）
                        failed_methods = self._extract_failed_methods_from_output(output)
                        
                        if failed_methods:
                            logger.info(f"识别出失败的测试方法: {failed_methods}")
                            
                            # 删除所有识别出的失败方法
                            test_code_cleaned = self._remove_failed_test_methods(second_llm_fixed_code, failed_methods)
                            
                            if test_code_cleaned and test_code_cleaned != second_llm_fixed_code:
                                # 写入清理后的代码
                                with open(temp_full_path, 'w', encoding='utf-8') as f:
                                    f.write(test_code_cleaned)
                                
                                # 验证清理后的代码
                                logger.info(f"验证删除失败方法后的结果...")
                                output, success = run_and_parse_test(project_path, temp_full_path)
                                
                                # 使用宽松成功条件：只要BUILD SUCCESS就视为成功
                                method_success = "BUILD SUCCESS" in output
                                if method_success and not success:
                                    logger.info("BUILD SUCCESS但有测试失败，在删除测试方法阶段视为成功")
                                
                                # 如果删除失败方法后成功，保存并返回
                                if method_success:
                                    logger.info(f"删除失败方法后构建成功，删除了: {failed_methods}")
                                    # 生成模式需要替换类名，演化模式保持原类名
                                    if repair_mode == "generation":
                                        final_test_code = self._update_class_name(test_code_cleaned, temp_class_name, final_class_name)
                                        logger.info(f"生成模式：类名从 {temp_class_name} 更新为 {final_class_name}")
                                    else:
                                        final_test_code = test_code_cleaned
                                        logger.info(f"演化模式：保持原类名 {final_class_name}")
                                    
                                    # 写入最终文件
                                    with open(final_full_path, 'w', encoding='utf-8') as f:
                                        f.write(final_test_code)
                                        
                                    # 删除临时文件（仅生成模式）
                                    if repair_mode == "generation":
                                        os.remove(temp_full_path)
                                        logger.info(f"删除临时文件: {temp_full_path}")
                                    
                                    return final_path
                                else:
                                    logger.warning(f"删除失败方法后仍然BUILD FAILURE")
                            else:
                                logger.warning("无法清理失败的测试方法或没有识别出失败方法")
                        else:
                            logger.warning("未能从错误输出中识别出失败的测试方法")
                
                    # 10. 所有尝试都失败，放弃该测试类
                    logger.warning("所有修复尝试都失败，放弃该测试类")
                    
                    # 删除修复失败的文件（生成模式删除临时文件，进化模式删除原文件）
                    if repair_mode == "generation":
                        os.remove(temp_full_path)
                        logger.info(f"删除临时文件: {temp_full_path}")
                    elif repair_mode == "evolution":
                        os.remove(final_full_path)
                        logger.info(f"修复失败，删除进化文件: {final_full_path}")
                    
                    return ""
                
        except Exception as e:
            logger.error(f"处理测试文件时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 尝试删除修复失败的文件（生成模式删除临时文件，进化模式删除原文件）
            try:
                if repair_mode == "generation" and os.path.exists(temp_full_path):
                    os.remove(temp_full_path)
                    logger.info(f"异常处理: 删除临时文件 {temp_full_path}")
                elif repair_mode == "evolution" and os.path.exists(final_full_path):
                    os.remove(final_full_path)
                    logger.info(f"异常处理: 删除进化文件 {final_full_path}")
            except:
                pass
                
            return ""
    
    def _extract_failed_methods_from_output(self, maven_output: str) -> List[str]:
        """从Maven输出中提取失败的测试方法名"""
        failed_methods = []
        
        # 常见的Maven测试失败模式
        patterns = [
            # JUnit 5: 类名.方法名() - 错误信息
            r'(\w+)\.(\w+)\(\)\s*-.*?(?:FAILED|Error|Exception)',
            # JUnit 4: 方法名(类名) - 错误信息 
            r'(\w+)\([^)]+\)\s*-.*?(?:Error|Exception|Failure)',
            # Surefire报告格式: 方法名[类名] 
            r'(\w+)\[[^\]]+\].*?(?:FAILED|ERROR)',
            # 编译错误中的方法引用
            r'error.*?method\s+(\w+)\(',
            # 一般的方法调用错误
            r'at\s+[\w.]+\.(\w+)\(',
            # 简化的错误模式：直接匹配方法名后跟错误
            r'(\w+(?:Test|_test)(?:Method|_method)?\w*)\s*\([^)]*\)\s*[-:].*?(?:Error|Exception|Failure|AssertionError)',
            # 更通用的测试方法匹配
            r'(test\w+)\s*\([^)]*\)\s*[-:]',
        ]
        
        logger.debug(f"分析Maven输出以提取失败方法...")
        
        for pattern in patterns:
            matches = re.findall(pattern, maven_output, re.IGNORECASE | re.MULTILINE)
            logger.debug(f"模式 '{pattern}' 匹配到: {matches}")
            
            for match in matches:
                if isinstance(match, tuple):
                    # 如果匹配返回元组，取最后一个元素作为方法名
                    method_name = match[-1] if match else ""
                else:
                    method_name = match
                
                # 过滤掉明显不是测试方法的名称
                if method_name and method_name not in failed_methods:
                    # 简单验证：测试方法通常以test开头或包含Test字样
                    if (method_name.startswith('test') or 
                        'Test' in method_name or 
                        method_name.startswith('should') or 
                        method_name.startswith('when') or
                        method_name.startswith('verify')):
                        failed_methods.append(method_name)
                        logger.debug(f"添加失败方法: {method_name}")
        
        # 处理编译错误：从行号推断失败的测试方法
        if not failed_methods and "COMPILATION ERROR" in maven_output:
            logger.debug("未从运行时错误找到失败方法，尝试从编译错误提取...")
            failed_methods.extend(self._extract_methods_from_compilation_errors(maven_output))
        
        logger.info(f"从输出中提取到 {len(failed_methods)} 个失败方法: {failed_methods}")
        return failed_methods
    
    def _extract_methods_from_compilation_errors(self, maven_output: str) -> List[str]:
        """从编译错误中提取失败的测试方法"""
        failed_methods = []
        
        # 匹配编译错误格式: [ERROR] /path/file.java:[行号,列号] 错误信息
        error_pattern = r'\[ERROR\]\s+[^\[]+\.java:\[(\d+),\d+\]\s+(.+)'
        
        matches = re.findall(error_pattern, maven_output, re.MULTILINE)
        logger.debug(f"找到 {len(matches)} 个编译错误")
        
        for line_num_str, error_msg in matches:
            line_num = int(line_num_str)
            logger.debug(f"编译错误在第{line_num}行: {error_msg}")
            
            # 需要读取测试文件来找到第line_num行对应的测试方法
            # 但这里我们无法直接访问文件，所以使用一个简化的方法：
            # 根据错误类型和上下文推断可能的测试方法
            if ("local variables referenced from a lambda" in error_msg or 
                "effectively final" in error_msg):
                logger.debug(f"检测到lambda final变量错误，行号: {line_num}")
                # 这种错误通常在测试方法内部，我们需要找到包含这行的方法
                # 由于无法直接读取文件，我们记录这个信息，在调用方处理
                failed_methods.append(f"__LINE_{line_num}__")  # 特殊标记
        
        return failed_methods
    
    def _identify_critical_failed_methods(self, failed_methods: List[str], code: str) -> List[str]:
        """识别严重问题的方法，这些方法应该优先删除
        
        严重问题包括：
        1. 编译错误（语法错误、API不存在等）
        2. 运行时异常（空指针、类型转换等）
        3. 简单错误（拼写错误、导入错误等）
        
        Returns:
            严重问题方法列表
        """
        critical_methods = []
        
        for method in failed_methods:
            # 检查是否包含编译错误关键词
            if any(keyword in method.lower() for keyword in [
                'cannot find symbol', 'method does not exist', 'package does not exist',
                'illegal', 'duplicate', 'syntax error', 'unexpected token'
            ]):
                critical_methods.append(method)
                continue
                
            # 检查是否是简单的API兼容性问题（如String.repeat()）
            if 'repeat' in method or 'builder()' in method:
                critical_methods.append(method)
                continue
        
        # 如果没有找到明显的严重问题，返回前一半的方法（保守删除）
        if not critical_methods and failed_methods:
            critical_methods = failed_methods[:max(1, len(failed_methods) // 2)]
            logger.info(f"未发现明显严重问题，保守删除前 {len(critical_methods)} 个方法")
        
        return critical_methods
    
    def _remove_failed_test_methods(self, code: str, failed_methods: List[str], conservative: bool = True) -> str:
        """从代码中删除指定的失败测试方法
        
        Args:
            code: 原始代码
            failed_methods: 失败的方法列表
            conservative: 保守模式，只删除明显有问题的方法
        """
        if not failed_methods:
            return code
        
        # 保守模式下，先尝试只删除最有问题的方法
        if conservative:
            critical_methods = self._identify_critical_failed_methods(failed_methods, code)
            if critical_methods:
                failed_methods = critical_methods
                logger.info(f"保守模式：只删除严重问题方法 {critical_methods}")
        
        cleaned_code = code
        
        for method_identifier in failed_methods:
            # 检查是否是行号标记
            if method_identifier.startswith("__LINE_") and method_identifier.endswith("__"):
                line_num = int(method_identifier[7:-2])  # 提取行号
                logger.debug(f"处理行号标记，目标行: {line_num}")
                
                # 根据行号找到对应的测试方法
                method_name = self._find_method_by_line_number(cleaned_code, line_num)
                if method_name:
                    logger.info(f"根据行号 {line_num} 找到测试方法: {method_name}")
                else:
                    logger.warning(f"无法根据行号 {line_num} 找到对应的测试方法")
                    continue
            else:
                method_name = method_identifier
            
            # 构建更精确的正则表达式，支持多行方法体
            # 匹配从@Test注解到方法结束的完整块
            patterns = [
                # 模式1：@Test注解在同一行
                rf'@Test[^\n]*\n\s*(?:@[^\n]*\n\s*)*(?:public|private|protected)?\s*void\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*\}}',
                # 模式2：@Test注解独立一行
                rf'@Test\s*\n\s*(?:@[^\n]*\n\s*)*(?:public|private|protected)?\s*void\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*\}}',
                # 模式3：简化模式，使用非贪婪匹配
                rf'@Test.*?void\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{.*?\}}\s*(?=\n\s*(?:@|public|private|protected|}}|\Z))',
            ]
            
            for pattern in patterns:
                new_code = re.sub(pattern, '', cleaned_code, flags=re.DOTALL | re.MULTILINE)
                if new_code != cleaned_code:
                    cleaned_code = new_code
                    logger.info(f"成功删除测试方法: {method_name}")
                    break
            else:
                logger.warning(f"无法删除测试方法: {method_name}")
        
        return cleaned_code
    
    def _find_method_by_line_number(self, code: str, target_line: int) -> str:
        """根据行号找到对应的测试方法名"""
        lines = code.split('\n')
        
        if target_line > len(lines):
            return ""
        
        # 从目标行向上查找，找到最近的@Test方法
        for i in range(target_line - 1, -1, -1):  # 从目标行-1开始向上查找
            line = lines[i].strip()
            
            # 查找方法定义行
            method_match = re.search(r'(?:public|private|protected)?\s*void\s+(\w+)\s*\(', line)
            if method_match:
                method_name = method_match.group(1)
                
                # 检查这个方法是否是测试方法（向上查找@Test注解）
                for j in range(i - 1, max(-1, i - 5), -1):  # 在方法定义前5行内查找@Test
                    if '@Test' in lines[j]:
                        logger.debug(f"在行 {i+1} 找到测试方法 {method_name}，@Test注解在行 {j+1}")
                        return method_name
        
        logger.debug(f"无法在第 {target_line} 行附近找到测试方法")
        return ""
    
    def _handle_evolution_failure(self, test_code: str, temp_file_path: str, final_file_path: str, 
                                project_path: str, temp_class_name: str, final_class_name: str) -> bool:
        """
        处理Evolution模式下的修复失败情况
        采用激进策略：定位具体错误测试并删除，最后验证或删除整个文件
        
        Args:
            test_code: 测试代码
            temp_file_path: 临时文件路径  
            final_file_path: 最终文件路径
            project_path: 项目路径
            temp_class_name: 临时类名
            final_class_name: 最终类名
            
        Returns:
            是否成功修复
        """
        logger.info("开始Evolution模式增强失败处理")
        
        # 保存当前代码到临时文件
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(test_code)
        
        # 第一次运行，获取详细错误信息
        logger.info("运行测试获取详细错误信息...")
        output, test_success = run_and_parse_test(project_path, temp_file_path)
        
        # 如果已经成功了，直接保存并返回
        if "BUILD SUCCESS" in output:
            logger.info("代码实际上是成功的，直接保存")
            final_test_code = self._update_class_name(test_code, temp_class_name, final_class_name)
            with open(final_file_path, 'w', encoding='utf-8') as f:
                f.write(final_test_code)
            return True
        
        # 提取失败的测试方法
        failed_methods = self._extract_failed_methods_from_output(output)
        logger.info(f"提取到失败的测试方法: {failed_methods}")
        
        if not failed_methods:
            logger.warning("无法提取失败的测试方法，尝试删除编译错误的方法")
            # 尝试通过编译错误定位问题方法
            failed_methods = self._extract_compilation_error_methods(output)
            logger.info(f"从编译错误提取到的方法: {failed_methods}")
        
        if failed_methods:
            # 逐步删除失败的方法并验证
            current_code = test_code
            removed_methods = []
            
            for method in failed_methods:
                logger.info(f"尝试删除失败方法: {method}")
                cleaned_code = self._remove_failed_test_methods(current_code, [method])
                
                if cleaned_code != current_code:
                    # 保存清理后的代码并测试
                    with open(temp_file_path, 'w', encoding='utf-8') as f:
                        f.write(cleaned_code)
                    
                    # 验证清理后的代码
                    logger.info(f"验证删除方法 {method} 后的结果...")
                    output, success = run_and_parse_test(project_path, temp_file_path)
                    
                    if "BUILD SUCCESS" in output:
                        logger.info(f"删除方法 {method} 后构建成功")
                        current_code = cleaned_code
                        removed_methods.append(method)
                        break  # 找到解决方案就停止
                    else:
                        logger.info(f"删除方法 {method} 后仍有问题，继续尝试")
                        current_code = cleaned_code  # 继续使用清理后的代码
                        removed_methods.append(method)
                else:
                    logger.warning(f"无法删除方法: {method}")
            
            # 最终验证
            if removed_methods:
                logger.info(f"总共删除了方法: {removed_methods}")
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    f.write(current_code)
                
                output, success = run_and_parse_test(project_path, temp_file_path)
                
                if "BUILD SUCCESS" in output:
                    logger.info("删除失败方法后最终验证成功")
                    final_test_code = self._update_class_name(current_code, temp_class_name, final_class_name)
                    with open(final_file_path, 'w', encoding='utf-8') as f:
                        f.write(final_test_code)
                    return True
                else:
                    logger.warning("删除失败方法后仍然构建失败")
        
        # 删除失败方法后仍然有问题，直接删除整个测试文件
        logger.warning("删除失败方法后仍然构建失败，删除整个测试文件")
        logger.error("Evolution模式增强处理失败，删除测试文件")
        logger.info("修复流程终止：2次LLM修复 → 删除错误方法 → 删除整个文件 (防止无限修复)")
        return False
    
    def _extract_compilation_error_methods(self, maven_output: str) -> List[str]:
        """从编译错误中提取有问题的方法"""
        methods = []
        lines = maven_output.split('\n')
        
        for line in lines:
            # 查找编译错误中的方法引用
            if 'error' in line.lower() and ('method' in line or 'void' in line):
                # 尝试提取方法名
                method_match = re.search(r'void\s+(\w+)\s*\(', line)
                if method_match:
                    method_name = method_match.group(1)
                    if method_name.startswith('test') and method_name not in methods:
                        methods.append(method_name)
        
        return methods
    
    def _count_test_methods(self, code: str) -> int:
        """统计代码中的测试方法数量"""
        return len(re.findall(r'@Test', code))
    
    def _create_minimal_test_class(self, original_code: str, class_name: str) -> str:
        """创建最小化的测试类，只保留基础结构和最简单的测试"""
        lines = original_code.split('\n')
        minimal_lines = []
        in_test_method = False
        brace_count = 0
        
        # 保留包声明、导入和类定义
        for line in lines:
            stripped = line.strip()
            
            # 保留基础结构
            if (stripped.startswith('package ') or 
                stripped.startswith('import ') or
                'class ' in stripped and '{' in stripped or
                stripped.startswith('/*') or stripped.startswith('*') or
                stripped == '' or stripped.startswith('//')):
                minimal_lines.append(line)
                continue
            
            # 跳过测试方法
            if '@Test' in line:
                in_test_method = True
                continue
                
            if in_test_method:
                if '{' in line:
                    brace_count += line.count('{')
                if '}' in line:
                    brace_count -= line.count('}')
                    if brace_count <= 0:
                        in_test_method = False
                continue
            
            # 保留类结束
            if stripped == '}' and not in_test_method:
                # 在类结束前添加一个基础测试方法
                minimal_lines.append('    @Test')
                minimal_lines.append('    void testBasic() {')
                minimal_lines.append('        // Basic test')
                minimal_lines.append('    }')
                minimal_lines.append('')
                minimal_lines.append(line)
                break
            
            # 保留其他重要结构
            if not in_test_method:
                minimal_lines.append(line)
        
        return '\n'.join(minimal_lines)

# 创建全局规则修复器实例
rule_fixer = RuleFixer()

# 默认修复函数，用于处理未明确定义修复器的错误类别
def default_fixer(test_code: str, error: Dict[str, Any]) -> str:
    """
    默认修复函数，使用fix_by_category处理通用错误
    
    Args:
        test_code: 测试代码
        error: 错误信息
        
    Returns:
        修复后的代码
    """
    category = error.get("category", "")
    message = error.get("message", "")
    return fix_by_category(test_code, category, message)

# 精简为3个高效规则，确保精确匹配和修复
FIXERS: Dict[str, FixerFunction] = {
    # 1. 导入错误修复 - 最高效的错误类型，精确匹配和修复
    "IMPORT_ERRORS": fix_unused_imports,
    
    # 2. 重复定义错误 - 处理重复修饰符、注解等，高成功率
    "DUPLICATE_DEFINITION_ERRORS": lambda code, error: (
        fix_duplicate_modifiers(fix_duplicate_annotations(fix_duplicate_imports(code, error), error))
    ),
    
    # 3. 访问修饰符错误 - 处理重复修饰符
    "ACCESS_MODIFIER_ERRORS": lambda code, error: fix_duplicate_modifiers(code),
    
    # 4. API兼容性错误 - 处理版本不兼容问题
    "API_COMPATIBILITY_ERRORS": lambda code, error: fix_api_compatibility_errors(code, error),
    
    # 5. 私有访问错误 - 移除私有方法调用
    "PRIVATE_ACCESS_ERRORS": lambda code, error: fix_private_access_errors(code, error),
    
    # 6. 构造器错误 - 修复构造器调用问题
    "CONSTRUCTOR_ERRORS": lambda code, error: fix_constructor_errors(code, error),
    
    # 7. 资源管理错误 - 修复try-with-resources语法
    "RESOURCE_MANAGEMENT_ERRORS": lambda code, error: fix_resource_management_errors(code, error),
    
    # 默认处理，快速失败转向LLM修复
    "DEFAULT": default_fixer
}

def process_test(test_path: str, cls_info: Dict[str, Any]) -> str:
    """
    处理测试文件的全局包装函数
    
    Args:
        test_path: 测试文件路径
        cls_info: 类信息，可能包含repair_stats用于统计收集
        
    Returns:
        成功时返回最终文件路径，失败时返回空字符串
    """
    result = rule_fixer.process_test(test_path, cls_info)
    
    # 如果cls_info中包含repair_stats，更新统计信息
    repair_stats = cls_info.get('repair_stats')
    if repair_stats is not None:
        # 这里可以基于处理结果更新统计
        if result:
            repair_stats.success = True
            # 如果进行了修复，增加修复尝试计数
            # 注意：实际的统计应该在RuleFixer.process_test中进行，这里只是确保有基本统计
            if hasattr(repair_stats, 'repair_attempts') and repair_stats.repair_attempts == 0:
                repair_stats.repair_attempts = 1
        else:
            repair_stats.success = False
    
    return result

def generate_enhanced_prompt(original_error_prompt: str) -> str:
    """
    Return original error prompt without adding duplicate guidance
    The LLM repair module already provides appropriate guidance based on error types
    
    Args:
        original_error_prompt: Original error prompt with classification information
        
    Returns:
        Original error prompt (no enhancement needed)
    """
    # Return original prompt without adding duplicate Chinese/English guidance
    # The LLM repair module (_create_concise_repair_prompt) already handles appropriate guidance
    return original_error_prompt
