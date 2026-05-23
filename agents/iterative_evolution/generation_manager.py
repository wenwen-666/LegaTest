"""
世代管理模块
负责测试选择、重命名、清理和世代间转换
"""

import os
import shutil
import re
import json
from typing import Dict, List, Tuple, Optional

try:
    from .utils import ensure_dir, copy_file, load_json
except ImportError:
    from utils import ensure_dir, copy_file, load_json

class GenerationManager:
    """世代管理器，负责测试选择、重命名和清理"""
    
    def __init__(self, base_dir: str, project_name: str, core_instance=None):
        self.base_dir = base_dir
        self.project_name = project_name
        self.project_dir = os.path.join(base_dir, "dataset", project_name)
        self.evolution_dir = os.path.join(base_dir, "evolution_process", project_name)
        self.historical_best_dir = os.path.join(self.evolution_dir, "historical_best")
        self.core_instance = core_instance  # 添加core实例引用用于适应度记录
        
        # 创建必要的目录
        ensure_dir(self.evolution_dir)
        ensure_dir(self.historical_best_dir)
    
    def select_and_rename_next_generation(self, target_class: str, current_gen: int, 
                                        diversity_calculator) -> bool:
        """原子性代数转换：选择当代最优测试并完成代数转换
        
        修复版本：确保代数转换的原子性
        1. 验证当前代完整性（所有中间文件都已生成报告）
        2. 收集所有候选测试（基础测试 + 交叉 + 变异）
        3. 按适应度排序，选择前10个，删除淘汰测试
        4. 重命名选中测试为 {target_class}TestV1.java - {target_class}TestV10.java
        5. 重命名对应的测试报告
        6. 清理所有残留的中间文件（crossover和mutation）
        7. 复制重命名后的测试到evolution_process/GenN/
        8. 准备下一代目录结构
        """
        print(f"开始原子性第{current_gen}代转换...")
        
        # 步骤1: 验证当前代完整性
        if not self._verify_generation_completeness(target_class, current_gen):
            print(f"错误: 第{current_gen}代不完整，无法进行转换")
            return False
        
        try:
            # 2. 收集所有候选测试的报告
            
            # 获取当前代的所有测试报告，但只保留有对应源文件的测试（强制不使用缓存）
            print(f"🔍 调试: 尝试获取第{current_gen}代测试报告...")
            all_current_reports = diversity_calculator.get_test_reports(current_gen, use_cache=False)
            
            if not all_current_reports:
                print(f"错误: 无法获取第{current_gen}代测试报告")
                return False
            
            # 直接从当前代测试报告中提取目标类的交叉变异测试
            new_tests = {}

            for test_name, report in all_current_reports.items():
                # 检查是否是目标类的交叉或变异测试
                if (f"{target_class}Test_Crossover_Gen{current_gen}" in test_name or
                    f"{target_class}Test_Mutation_Gen{current_gen}" in test_name):

                    # 验证测试文件是否存在
                    test_file = self._find_test_source_file(test_name)
                    if test_file and os.path.exists(test_file):
                        new_tests[test_name] = report
                        print(f"收集目标类新测试: {test_name}")
                    else:
                        print(f"跳过不存在的测试文件: {test_name}")
                else:
                    # 跳过其他类的测试（这是正常的）
                    pass
            
            # 收集前一代的目标类基础测试（TestV1-TestV10）
            prev_gen_all_tests = {}
            if current_gen > 1:
                prev_reports = diversity_calculator.get_test_reports(current_gen - 1)
                if prev_reports:
                    for test_name, report in prev_reports.items():
                        # 检查是否是目标类的基础测试（TestV格式）
                        if (test_name.startswith(f"{target_class}TestV") and
                            re.match(rf'{re.escape(target_class)}TestV\d+$', test_name)):

                            # 验证测试文件是否存在
                            test_file = self._find_test_source_file(test_name)
                            if test_file and os.path.exists(test_file):
                                prev_gen_all_tests[test_name] = report
                                print(f"收集前一代基础测试: {test_name}")
            else:
                # 第一代，从maven目录收集当前的基础测试
                print(f"第1代，从maven目录收集当前基础测试...")
                maven_tests = self._get_current_maven_tests_for_target_class(target_class)
                if maven_tests:
                    for test_name, report in maven_tests.items():
                        prev_gen_all_tests[test_name] = report
                        print(f"收集当前基础测试: {test_name}")
            
            # 合并所有候选测试：前一代所有个体 + 当前代新生成测试
            all_candidates = {}
            all_candidates.update(prev_gen_all_tests)  # 前一代所有个体
            all_candidates.update(new_tests)           # 当前代新生成测试
            
            print(f"从第{current_gen-1}代收集所有个体: {len(prev_gen_all_tests)} 个")
            print(f"从第{current_gen}代收集新测试: {len(new_tests)} 个")
            print(f"总候选测试: {len(all_candidates)} 个")
            
            if not all_candidates:
                print(f"错误: 无法获取第{current_gen}代测试报告")
                return False
            
            # 候选测试已经在上面过滤了目标类，这里直接使用
            target_candidates = all_candidates
            
            print(f"找到{len(target_candidates)}个候选测试")
            
            # 2. 按适应度排序，选择测试（如果超过10个才选择前10个，否则保留所有）
            sorted_tests = sorted(target_candidates.items(), 
                                key=lambda x: (x[1]["fitness"], x[1]["metrics"]["line_coverage"], x[1]["metrics"]["branch_coverage"]), 
                                reverse=True)
            
            # 灵活选择：如果超过10个才选择前10个，否则保留所有
            if len(sorted_tests) > 10:
                selected_tests = sorted_tests[:10]
                eliminated_tests = sorted_tests[10:]
                print(f"选中前10个测试（共{len(sorted_tests)}个候选）:")
            else:
                selected_tests = sorted_tests
                eliminated_tests = []
                print(f"保留所有{len(selected_tests)}个测试:")
            
            for i, (test_name, report) in enumerate(selected_tests, 1):
                fitness = report["fitness"]
                mutation_status = ""
                if report.get("mutation_applied", False):
                    mutation_type = report.get("mutation_type", "unknown")
                    if mutation_type == "crossover_mutation":
                        mutation_status = " [已变异]"
                    elif mutation_type == "elite_mutation":
                        mutation_status = " [精英变异]"
                    else:
                        mutation_status = " [已变异]"
                print(f"  {i}. {test_name} (适应度: {fitness:.4f}){mutation_status}")
            
            if eliminated_tests:
                print(f"淘汰{len(eliminated_tests)}个测试:")
                for test_name, report in eliminated_tests:
                    fitness = report["fitness"]
                    print(f"  - {test_name} (适应度: {fitness:.4f})")
            
            # 3. 直接清理淘汰的测试文件和报告
            eliminated_test_names = [test_name for test_name, _ in eliminated_tests]
            self._cleanup_eliminated_tests(eliminated_test_names, current_gen)
            
            # 4. 重命名选中的测试为标准格式（TestV1-TestV10）
            print(f"\n=== 重命名选中测试为标准格式 ===")
            rename_success = self._rename_and_overwrite_maven_tests(target_class, selected_tests, current_gen)
            if not rename_success:
                print(f"警告: 重命名过程失败，但继续演化")
                return False
            
            # 5. 重命名对应的测试报告
            print(f"\n=== 重命名测试报告 ===")
            self._safe_rename_test_reports(target_class, selected_tests, current_gen)
            
            # 6. 保存本代最优个体到historical_best（使用重命名后的名称）
            if selected_tests:
                # 第一个就是最优的，现在已经被重命名为TestV1
                best_original_name = selected_tests[0][0]  # 原始名称
                best_new_name = f"{target_class}TestV1"  # 重命名后的名称
                best_fitness = selected_tests[0][1]["fitness"]
                self._save_best_test_to_historical(best_new_name, current_gen, best_fitness)
            
            # 5. 清理所有残留的中间文件，确保环境干净
            print(f"\n=== 清理残留的中间文件 ===")
            cleanup_success = self._cleanup_remaining_intermediate_files(target_class, current_gen)
            if not cleanup_success:
                print(f"警告: 中间文件清理不完整，但继续演化")
            
            # 6. 复制重命名后的测试到evolution_process
            self._copy_renamed_tests_to_evolution_process(target_class, selected_tests, current_gen)
            
            # 7. 准备下一代目录结构
            next_gen_ready = self._ensure_next_generation_ready(target_class, current_gen + 1)
            if not next_gen_ready:
                print(f"警告: 第{current_gen + 1}代目录准备失败")
            
            print(f"第{current_gen}代原子性转换完成！")
            return True
            
        except Exception as e:
            print(f"选择下一代测试失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _find_test_source_file(self, test_class: str, exclude_gen: int = None) -> Optional[str]:
        """查找测试类源文件"""
        # 对于基础测试，应该从evolution_process的对应代数中查找原始内容
        # 而不是从可能被污染的maven目录查找
        if self._is_base_test(test_class):
            # 基础测试从evolution_process目录查找，从最新代数开始查找
            evolution_dir = os.path.join(self.base_dir, "evolution_process", self.project_name)
            for gen in range(100, 0, -1):  # 从最新代数开始查找
                if exclude_gen and gen == exclude_gen:
                    continue  # 跳过指定的代数
                gen_dir = os.path.join(evolution_dir, f"Gen{gen}")
                if os.path.exists(gen_dir):
                    for root, _, files in os.walk(gen_dir):
                        for file in files:
                            if file == f"{test_class}.java":
                                return os.path.join(root, file)
        
        # 对于非基础测试（交叉、变异测试），在maven目录中查找
        if not self._is_base_test(test_class):
            test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
            for root, _, files in os.walk(test_src_dir):
                for file in files:
                    if file == f"{test_class}.java":
                        return os.path.join(root, file)
        
        # 如果以上都没找到，最后尝试在evolution_process目录中查找（兜底）
        evolution_dir = os.path.join(self.base_dir, "evolution_process", self.project_name)
        for gen in range(100, 0, -1):  # 从最新代数开始查找
            gen_dir = os.path.join(evolution_dir, f"Gen{gen}")
            if os.path.exists(gen_dir):
                for root, _, files in os.walk(gen_dir):
                    for file in files:
                        if file == f"{test_class}.java":
                            return os.path.join(root, file)
        
        return None

    def _get_current_maven_tests_for_target_class(self, target_class: str) -> Dict[str, Dict]:
        """从maven目录获取指定目标类的当前基础测试"""
        maven_tests = {}
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")

        if not os.path.exists(test_src_dir):
            return maven_tests

        for root, _, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    test_name = file.replace(".java", "")
                    # 检查是否是目标类的基础测试
                    if (test_name.startswith(f"{target_class}TestV") and
                        re.match(rf'{re.escape(target_class)}TestV\d+$', test_name)):

                        # 这里需要生成简单的报告结构，因为maven测试可能还没有覆盖率报告
                        maven_tests[test_name] = {
                            "fitness": 0.5,  # 默认适应度
                            "metrics": {
                                "line_coverage": 50.0,
                                "branch_coverage": 50.0,
                                "method_coverage": 50.0
                            }
                        }

        return maven_tests

    def _is_base_test(self, test_name: str) -> bool:
        """判断是否为基础测试（TestV1-TestV10格式）"""
        return bool(re.match(r'.*TestV\d+$', test_name))
    
    def _extract_target_class_from_test_name(self, test_name: str) -> str:
        """从测试类名中提取目标类名"""
        # 处理TestV格式 (例如: FormSetFactoryTestV1 -> FormSetFactory)
        if "TestV" in test_name:
            match = re.match(r"(.+?)TestV\d+$", test_name)
            if match:
                return match.group(1)
        
        # 处理交叉测试格式 (例如: FormSetFactoryTest_Crossover_Gen2_1x2 -> FormSetFactory)
        if "Test_Crossover_Gen" in test_name:
            return test_name.split("Test_Crossover_Gen")[0]
        
        # 处理变异测试格式 (例如: FormSetFactoryTest_Mutation_Gen2_V1 -> FormSetFactory)
        if "Test_Mutation_Gen" in test_name:
            return test_name.split("Test_Mutation_Gen")[0]
        
        # 其他格式处理 (例如: FormSetFactoryTest -> FormSetFactory)
        if test_name.endswith("Test"):
            return test_name[:-4]
        
        # 默认处理：移除Test字符串
        return test_name.replace("Test", "")
    
    def _cleanup_eliminated_tests(self, eliminated_test_names: List[str], current_gen: int):
        """清理淘汰的测试文件和报告"""
        print(f"清理淘汰的测试文件和报告...")
        
        for test_name in eliminated_test_names:
            print(f"  - 删除淘汰测试: {test_name}")
            
            # 删除maven目录中的测试文件（包括基础测试）
            # 淘汰的测试必须被删除，否则会与重命名的测试冲突
            test_file = self._find_test_source_file(test_name)
            if test_file and os.path.exists(test_file):
                try:
                    os.remove(test_file)
                    print(f"    删除测试文件: {test_file}")
                except Exception as e:
                    print(f"    删除测试文件失败: {e}")
            else:
                print(f"    未找到测试文件: {test_name}")
            
            # 删除测试报告
            report_dir = os.path.join(self.base_dir, "test_reports", self.project_name, 
                                    f"Gen{current_gen}", test_name)
            if os.path.exists(report_dir):
                try:
                    shutil.rmtree(report_dir)
                    print(f"    删除测试报告: {report_dir}")
                except Exception as e:
                    print(f"    删除测试报告失败: {e}")
    
    def _rename_and_overwrite_maven_tests(self, target_class: str, selected_tests: List[Tuple[str, Dict]], current_gen: int) -> bool:
        """重命名选中的测试为标准格式并覆盖maven目录"""
        print(f"重命名并覆盖maven目录...")
        
        try:
            # 找到目标类的包路径（使用多种回退策略）
            package_path = self._find_target_package_path(target_class)
            if package_path is None:
                print(f"错误: 无法找到 {target_class} 的包路径")
                return False
            
            test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
            target_package_dir = os.path.join(test_src_dir, package_path.replace(".", os.sep))
            
            # 步骤1: 重命名并覆盖选中的测试文件
            for i, (old_test_name, report) in enumerate(selected_tests, 1):
                new_test_name = f"{target_class}TestV{i}"
                
                # 找到原始文件（排除当前代数，避免找到未完成的文件）
                old_test_file = self._find_test_source_file(old_test_name, exclude_gen=current_gen)
                if not old_test_file:
                    print(f"警告: 未找到测试文件 {old_test_name}")
                    continue
                
                # 目标文件路径
                new_test_file = os.path.join(target_package_dir, f"{new_test_name}.java")
                
                # 复制并修改类名
                success = self._copy_and_rename_test_file(old_test_file, new_test_file, new_test_name)
                if success:
                    print(f"  {old_test_name} → {new_test_name}")
                else:
                    print(f"  错误: 重命名失败 {old_test_name}")
                    return False
            
            # 不需要重命名报告，保持原始名称
            
            print(f"成功重命名{len(selected_tests)}个测试文件")
            return True
            
        except Exception as e:
            print(f"重命名测试文件失败: {e}")
            return False
    
    def _find_target_package_path(self, target_class: str) -> Optional[str]:
        """查找目标类的包路径，使用多种回退策略"""
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 策略1: 搜索现有的TestV1文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file == f"{target_class}TestV1.java":
                    rel_path = os.path.relpath(root, test_src_dir)
                    if rel_path == ".":
                        return ""  # 默认包
                    else:
                        return rel_path.replace(os.sep, ".")
        
        # 策略2: 搜索任意包含目标类名的测试文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.startswith(f"{target_class}Test") and file.endswith(".java"):
                    rel_path = os.path.relpath(root, test_src_dir)
                    if rel_path == ".":
                        return ""  # 默认包
                    else:
                        return rel_path.replace(os.sep, ".")
        
        # 策略3: 从源码目录查找目标类
        src_dir = os.path.join(self.project_dir, "src", "main", "java")
        if os.path.exists(src_dir):
            for root, dirs, files in os.walk(src_dir):
                for file in files:
                    if file == f"{target_class}.java":
                        rel_path = os.path.relpath(root, src_dir)
                        if rel_path == ".":
                            return ""  # 默认包
                        else:
                            return rel_path.replace(os.sep, ".")
        
        return ""
    
    def restore_generation_integrity(self, target_class: str, gen_num: int):
        """恢复指定代数目录的完整性，确保有完整的V1-V10测试"""
        print(f"检查并恢复Gen{gen_num}目录的完整性...")
        
        target_gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        ensure_dir(target_gen_dir)
        
        # 查找maven目录中的所有目标类测试
        maven_tests = []
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, _, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    test_name = file.replace(".java", "")
                    extracted_class = self._extract_target_class_from_test_name(test_name)
                    if extracted_class == target_class and self._is_base_test(test_name):
                        maven_tests.append((test_name, os.path.join(root, file)))
        
        # 检查目标代数目录中缺失的测试
        package_path = self._find_target_package_path(target_class)
        if package_path:
            target_package_dir = os.path.join(target_gen_dir, package_path.replace(".", os.sep))
            ensure_dir(target_package_dir)
            
            restored_count = 0
            for test_name, maven_file in maven_tests:
                target_file = os.path.join(target_package_dir, f"{test_name}.java")
                
                if not os.path.exists(target_file):
                    try:
                        copy_file(maven_file, target_file)
                        print(f"  恢复Gen{gen_num}文件: {test_name}")
                        restored_count += 1
                    except Exception as e:
                        print(f"  恢复Gen{gen_num}文件失败 {test_name}: {e}")
                        
            if restored_count > 0:
                print(f"成功恢复{restored_count}个Gen{gen_num}文件")
            else:
                print(f"Gen{gen_num}目录完整，无需恢复")
    
    def _copy_and_rename_test_file(self, src_file: str, dst_file: str, new_class_name: str) -> bool:
        """复制并重命名测试文件中的类名"""
        try:
            # 确保目标目录存在
            ensure_dir(os.path.dirname(dst_file))
            
            # 读取源文件
            with open(src_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 修改类名
            content = self._fix_class_name_in_content(content, new_class_name)
            
            # 写入目标文件
            with open(dst_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return True
            
        except Exception as e:
            print(f"复制和重命名测试文件失败: {e}")
            return False
    
    def _fix_class_name_in_content(self, content: str, new_class_name: str) -> str:
        """安全修正代码中的类名 - 只修改与外部文件名相关的内容"""
        
        # 首先提取原始类名
        original_class_name = self._extract_original_class_name(content)
        if not original_class_name:
            print(f"    警告: 无法提取原始类名，跳过内容修改")
            return content
        
        print(f"    检测到原始类名: {original_class_name}")
        print(f"    新类名: {new_class_name}")
        
        # 只有当外部文件名和内部类名一致时才进行修改
        if original_class_name == new_class_name:
            print(f"    类名已匹配，无需修改内容")
            return content
        
        # 全面替换：将所有出现的原类名替换为新类名，确保可以编译
        # 使用单词边界确保只替换完整的类名，不会误替换包含该字符串的其他内容
        
        replacement_count = 0
        
        # 使用单词边界 \b 确保只替换完整的类名
        # 这样 "ZipFileTestV2" 会被替换，但 "MyZipFileTestV2Custom" 不会被替换
        word_boundary_pattern = rf'\b{re.escape(original_class_name)}\b'
        
        # 计算替换次数
        matches = re.findall(word_boundary_pattern, content)
        replacement_count = len(matches)
        
        if replacement_count > 0:
            # 执行替换
            content = re.sub(word_boundary_pattern, new_class_name, content)
            print(f"    已将所有 {original_class_name} 替换为 {new_class_name} (共{replacement_count}处)")
            print(f"    包括: 类声明、构造函数、以及所有其他引用")
        else:
            print(f"    未找到需要替换的 {original_class_name} 引用")
        
        return content
    
    def _extract_original_class_name(self, content: str) -> str:
        """从代码内容中提取原始类名（public或package-private）"""
        # 先尝试public class
        public_class_pattern = r'public\s+class\s+(\w+)\s*\{'
        match = re.search(public_class_pattern, content)
        if match:
            return match.group(1)
        
        # 再尝试package-private class
        package_class_pattern = r'(^|\n)class\s+(\w+)\s*\{'
        match = re.search(package_class_pattern, content, re.MULTILINE)
        if match:
            return match.group(2)
        
        return None
    
    def _fix_inner_class_constructors(self, content: str, main_class_name: str) -> str:
        """修复内部类构造函数名，确保与实际的内部类名匹配"""
        import re
        
        lines = content.split('\n')
        fixed_lines = []
        
        # 先找到所有内部类的定义和它们的实际类名
        class_mapping = {}
        current_class = None
        
        for i, line in enumerate(lines):
            # 查找内部类定义
            class_match = re.search(r'(\s+)(private\s+|public\s+|protected\s+)?static\s+class\s+(\w+)(\s*\{)', line)
            if class_match:
                current_class = class_match.group(3)
                class_mapping[i] = current_class
                continue
            
            # 查找构造函数
            if current_class:
                constructor_match = re.search(r'(\s+)(public\s+|private\s+|protected\s+)*\s*(\w+)\s*\(([^)]*)\)', line)
                if constructor_match:
                    constructor_name = constructor_match.group(3)
                    # 如果构造函数名不匹配当前内部类名，需要修复
                    if constructor_name != current_class:
                        whitespace = constructor_match.group(1)
                        visibility = constructor_match.group(2) or ''
                        params = constructor_match.group(4)
                        fixed_line = f"{whitespace}{visibility}{current_class}({params})"
                        fixed_lines.append(fixed_line)
                        print(f"    修复构造函数: {constructor_name} -> {current_class} (行 {i+1})")
                        continue
                
                # 检查是否是类的结束
                if line.strip() == '}':
                    # 简单启发式：如果这个}前面有其他内容，可能是类结束
                    current_class = None
        
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    def _fix_duplicate_inner_classes(self, content: str, main_class_name: str) -> str:
        """解决重复的内部类名冲突并修复对应的构造函数"""
        import re
        
        lines = content.split('\n')
        fixed_lines = []
        class_counter = 1
        seen_classes = set()
        class_rename_map = {}  # 存储类名重命名映射
        
        # 第一遍：重命名冲突的内部类
        for i, line in enumerate(lines):
            # 查找静态内部类定义
            class_match = re.search(r'(\s+)(private\s+|public\s+|protected\s+)?static\s+class\s+(\w+)(\s*[\{\s])', line)
            
            if class_match:
                prefix = class_match.group(1)
                visibility = class_match.group(2) or ''
                class_name = class_match.group(3)
                suffix = class_match.group(4)
                
                # 如果类名与主类相同或已经存在，生成新名称
                if (class_name == main_class_name or 
                    class_name in seen_classes):
                    
                    new_name = f"{main_class_name}Helper{class_counter}"
                    class_counter += 1
                    class_rename_map[class_name] = new_name
                    
                    modified_line = f"{prefix}{visibility}static class {new_name}{suffix}"
                    print(f"    重命名内部类: {class_name} -> {new_name}")
                else:
                    new_name = class_name
                    modified_line = line
                
                seen_classes.add(new_name)
                fixed_lines.append(modified_line)
            else:
                fixed_lines.append(line)
        
        # 第二遍：修复构造函数名以匹配重命名后的类名
        if class_rename_map:
            final_lines = []
            current_class = None
            
            for i, line in enumerate(fixed_lines):
                # 跟踪当前所在的内部类
                class_match = re.search(r'static\s+class\s+(\w+)', line)
                if class_match:
                    current_class = class_match.group(1)
                    final_lines.append(line)
                    continue
                
                # 如果在内部类中，检查构造函数
                if current_class:
                    # 查找构造函数
                    constructor_match = re.search(r'(\s+)(public\s+|private\s+|protected\s+)*\s*(\w+)\s*\(([^)]*)\)', line)
                    if constructor_match:
                        constructor_name = constructor_match.group(3)
                        # 如果构造函数名在重命名映射中，需要更新
                        if constructor_name in class_rename_map:
                            whitespace = constructor_match.group(1)
                            visibility = constructor_match.group(2) or ''
                            params = constructor_match.group(4)
                            new_constructor_name = class_rename_map[constructor_name]
                            fixed_line = f"{whitespace}{visibility}{new_constructor_name}({params})"
                            final_lines.append(fixed_line)
                            print(f"    修复构造函数: {constructor_name} -> {new_constructor_name} (行 {i+1})")
                            continue
                    
                    # 检查是否是类的结束
                    if line.strip() == '}':
                        current_class = None
                
                final_lines.append(line)
            
            return '\n'.join(final_lines)
        
        return '\n'.join(fixed_lines)
    
    def _rename_test_reports(self, old_test_name: str, new_test_name: str, target_gen: int):
        """重命名测试报告目录并更新内部XML文件内容以匹配新的测试名称"""
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        
        # 目标代数目录
        target_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen}")
        ensure_dir(target_gen_dir)
        
        # 首先尝试在目标代数中查找报告
        old_report_dir = os.path.join(target_gen_dir, old_test_name)
        new_report_dir = os.path.join(target_gen_dir, new_test_name)
        
        # 如果目标代数中没有找到，且是基础测试，则从前一代复制
        if not os.path.exists(old_report_dir) and self._is_base_test(old_test_name) and target_gen > 1:
            prev_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen-1}")
            prev_old_report_dir = os.path.join(prev_gen_dir, old_test_name)
            
            if os.path.exists(prev_old_report_dir):
                print(f"    从前一代复制基础测试报告: Gen{target_gen-1}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                try:
                    # 复制整个报告目录到目标代数
                    shutil.copytree(prev_old_report_dir, new_report_dir)
                    
                    # 更新内部XML文件的测试类名引用
                    self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                    
                    print(f"    成功复制并重命名测试报告: Gen{target_gen}/{new_test_name}")
                    return
                    
                except Exception as e:
                    print(f"    复制测试报告失败 {old_test_name}: {e}")
                    return
        
        # 如果在目标代数中找到了，则直接重命名
        if os.path.exists(old_report_dir) and not os.path.exists(new_report_dir):
            try:
                # 移动目录（因为是在同一代数内）
                shutil.move(old_report_dir, new_report_dir)
                print(f"    重命名测试报告目录: Gen{target_gen}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                
                # 更新内部XML文件的测试类名引用
                self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                
            except Exception as e:
                print(f"    重命名测试报告失败 {old_test_name}: {e}")
        elif os.path.exists(new_report_dir):
            print(f"    目标报告已存在，强制覆盖: {new_test_name}")
            try:
                # 删除已存在的目标报告目录
                shutil.rmtree(new_report_dir)
                print(f"    删除已存在的目标报告: Gen{target_gen}/{new_test_name}")
                
                # 如果源报告存在，则重命名
                if os.path.exists(old_report_dir):
                    shutil.move(old_report_dir, new_report_dir)
                    print(f"    重命名测试报告目录: Gen{target_gen}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                    # 更新内部XML文件的测试类名引用
                    self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                else:
                    # 如果源报告不存在且是基础测试，从前一代复制
                    if self._is_base_test(old_test_name) and target_gen > 1:
                        prev_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen-1}")
                        prev_old_report_dir = os.path.join(prev_gen_dir, old_test_name)
                        
                        if os.path.exists(prev_old_report_dir):
                            print(f"    从前一代复制基础测试报告: Gen{target_gen-1}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                            try:
                                # 复制整个报告目录到目标代数
                                shutil.copytree(prev_old_report_dir, new_report_dir)
                                
                                # 更新内部XML文件的测试类名引用
                                self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                                
                                print(f"    成功复制并重命名测试报告: Gen{target_gen}/{new_test_name}")
                                
                            except Exception as e:
                                print(f"    复制测试报告失败 {old_test_name}: {e}")
                        else:
                            print(f"    警告: 前一代也没有找到报告: {old_test_name}")
                    else:
                        print(f"    警告: 源报告目录不存在: {old_test_name}")
                    
            except Exception as e:
                print(f"    强制覆盖报告失败 {old_test_name} → {new_test_name}: {e}")
        else:
            print(f"    未找到源报告目录: {old_test_name}")
    
    def _safe_rename_test_reports(self, target_class: str, selected_tests: List[Tuple[str, Dict]], target_gen: int):
        """安全地重命名测试报告，避免循环依赖"""
        print(f"安全重命名测试报告到Gen{target_gen}...")
        
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        target_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen}")
        ensure_dir(target_gen_dir)
        
        # 第一步：创建重命名映射
        rename_map = {}
        for i, (old_test_name, report) in enumerate(selected_tests, 1):
            new_test_name = f"{target_class}TestV{i}"
            rename_map[old_test_name] = new_test_name
        
        print(f"  重命名映射: {rename_map}")
        
        # 第二步：使用临时名称避免循环依赖
        temp_moves = []
        import time
        timestamp = int(time.time())
        
        for old_test_name, new_test_name in rename_map.items():
            old_report_dir = os.path.join(target_gen_dir, old_test_name)
            
            # 先检查源报告是否存在，不存在则尝试从前一代复制
            if not os.path.exists(old_report_dir) and self._is_base_test(old_test_name) and target_gen > 1:
                self._copy_base_test_report_from_prev_gen(old_test_name, new_test_name, target_gen)
            
            # 如果名称相同，不需要重命名，但要确保报告存在
            if old_test_name == new_test_name:
                if os.path.exists(old_report_dir):
                    print(f"    保持不变: {old_test_name}")
                else:
                    print(f"    警告: {old_test_name} 报告不存在，已尝试复制")
                continue
            
            new_report_dir = os.path.join(target_gen_dir, new_test_name)
            temp_name = f"{new_test_name}_TEMP_{timestamp}"
            temp_report_dir = os.path.join(target_gen_dir, temp_name)
            
            # 如果源报告存在，先移动到临时位置
            if os.path.exists(old_report_dir):
                try:
                    shutil.move(old_report_dir, temp_report_dir)
                    temp_moves.append((temp_name, new_test_name, old_test_name))
                    print(f"    临时移动: {old_test_name} → {temp_name}")
                except Exception as e:
                    print(f"    临时移动失败 {old_test_name}: {e}")
            else:
                print(f"    警告: 未找到源报告目录 {old_test_name}")
        
        # 第三步：从临时位置移动到最终位置
        for temp_name, new_test_name, old_test_name in temp_moves:
            temp_report_dir = os.path.join(target_gen_dir, temp_name)
            new_report_dir = os.path.join(target_gen_dir, new_test_name)
            
            try:
                # 如果目标已存在，删除它
                if os.path.exists(new_report_dir):
                    shutil.rmtree(new_report_dir)
                    print(f"    删除现有目标: {new_test_name}")
                
                # 移动到最终位置
                shutil.move(temp_report_dir, new_report_dir)
                print(f"    最终移动: {temp_name} → {new_test_name}")
                
                # 更新报告内容中的测试类名
                self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                
            except Exception as e:
                print(f"    最终移动失败 {temp_name} → {new_test_name}: {e}")
        
        print(f"完成安全重命名测试报告")
    
    def _copy_base_test_report_from_prev_gen(self, old_test_name: str, new_test_name: str, target_gen: int):
        """从前一代复制基础测试报告"""
        if target_gen <= 1:
            return
        
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        prev_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen-1}")
        target_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen}")
        
        prev_report_dir = os.path.join(prev_gen_dir, old_test_name)
        target_report_dir = os.path.join(target_gen_dir, new_test_name)
        
        if os.path.exists(prev_report_dir) and not os.path.exists(target_report_dir):
            try:
                shutil.copytree(prev_report_dir, target_report_dir)
                print(f"    从前一代复制并重命名: Gen{target_gen-1}/{old_test_name} → Gen{target_gen}/{new_test_name}")
            except Exception as e:
                print(f"    从前一代复制失败 {old_test_name} → {new_test_name}: {e}")
    
    def _copy_renamed_test_reports_to_target_gen(self, target_class: str, selected_tests: List[Tuple[str, Dict]], current_gen: int, next_gen: int):
        """将重命名后的测试报告复制到目标代数目录"""
        print(f"复制重命名后的测试报告到Gen{next_gen}...")
        
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        current_gen_dir = os.path.join(reports_base_dir, f"Gen{current_gen}")
        next_gen_dir = os.path.join(reports_base_dir, f"Gen{next_gen}")
        
        # 确保目标代数目录存在
        if not os.path.exists(next_gen_dir):
            os.makedirs(next_gen_dir)
            print(f"  创建目标代数目录: {next_gen_dir}")
        
        # 复制每个重命名后的测试报告
        for i, (original_name, report) in enumerate(selected_tests):
            new_name = f"{target_class}TestV{i+1}"
            
            # 源报告目录（重命名后的）
            source_report_dir = os.path.join(current_gen_dir, new_name)
            
            # 目标报告目录
            target_report_dir = os.path.join(next_gen_dir, new_name)
            
            if os.path.exists(source_report_dir):
                try:
                    # 如果目标已存在，先删除
                    if os.path.exists(target_report_dir):
                        shutil.rmtree(target_report_dir)
                    
                    # 复制报告目录
                    shutil.copytree(source_report_dir, target_report_dir)
                    print(f"  复制报告: {new_name} → Gen{next_gen}/{new_name}")
                except Exception as e:
                    print(f"  复制报告失败 {new_name}: {e}")
            else:
                print(f"  警告: 源报告目录不存在: {source_report_dir}")
    
    def _ensure_base_test_reports_copied(self, target_class: str, selected_tests: List[Tuple[str, Dict]], current_gen: int):
        """确保所有基础测试报告都被正确复制到当前代"""
        print(f"确保基础测试报告被复制到Gen{current_gen}...")
        
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        current_gen_dir = os.path.join(reports_base_dir, f"Gen{current_gen}")
        ensure_dir(current_gen_dir)
        
        # 导入配置常量
        from .core import TESTS_PER_GENERATION
        
        # 检查V1-V10的所有基础测试
        for i in range(1, TESTS_PER_GENERATION + 1):
            test_name = f"{target_class}TestV{i}"
            current_report_dir = os.path.join(current_gen_dir, test_name)
            
            # 如果当前代没有这个测试报告
            if not os.path.exists(current_report_dir):
                # 尝试从前一代复制
                if current_gen > 1:
                    prev_gen_dir = os.path.join(reports_base_dir, f"Gen{current_gen-1}")
                    prev_report_dir = os.path.join(prev_gen_dir, test_name)
                    
                    if os.path.exists(prev_report_dir):
                        print(f"  复制缺失的基础测试报告: Gen{current_gen-1}/{test_name} → Gen{current_gen}/{test_name}")
                        try:
                            shutil.copytree(prev_report_dir, current_report_dir)
                        except Exception as e:
                            print(f"  复制失败 {test_name}: {e}")
    
    def _update_report_xml_content(self, report_dir: str, old_test_name: str, new_test_name: str):
        """更新测试报告目录中XML文件的测试类名引用"""
        # 更新Surefire XML报告
        surefire_dir = os.path.join(report_dir, "surefire")
        if os.path.exists(surefire_dir):
            for file_name in os.listdir(surefire_dir):
                if file_name.endswith('.xml') or file_name.endswith('.txt'):
                    file_path = os.path.join(surefire_dir, file_name)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # 替换XML中的测试类名引用
                        content = content.replace(old_test_name, new_test_name)
                        
                        # 替换文件名中的测试类名（如果需要）
                        new_file_name = file_name.replace(old_test_name, new_test_name)
                        new_file_path = os.path.join(surefire_dir, new_file_name)
                        
                        with open(new_file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        # 如果文件名发生了变化，删除旧文件
                        if new_file_name != file_name:
                            os.remove(file_path)
                            
                        print(f"      更新Surefire报告: {file_name} → {new_file_name}")
                        
                    except Exception as e:
                        print(f"      更新Surefire报告失败 {file_path}: {e}")
        
        # 更新JaCoCo XML报告
        jacoco_dir = os.path.join(report_dir, "jacoco")
        if os.path.exists(jacoco_dir):
            jacoco_xml = os.path.join(jacoco_dir, "jacoco.xml")
            if os.path.exists(jacoco_xml):
                try:
                    with open(jacoco_xml, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 替换XML中的测试类名引用（更精确的替换）
                    content = re.sub(
                        rf'(<class name=")[^"]*{re.escape(old_test_name)}([^"]*")',
                        rf'\1{new_test_name}\2',
                        content
                    )
                    
                    with open(jacoco_xml, 'w', encoding='utf-8') as f:
                        f.write(content)
                        
                    print(f"      更新JaCoCo报告: jacoco.xml")
                    
                except Exception as e:
                    print(f"      更新JaCoCo报告失败 {jacoco_xml}: {e}")
        
        # 更新coverage_report.json
        coverage_json = os.path.join(report_dir, "coverage_report.json")
        if os.path.exists(coverage_json):
            try:
                with open(coverage_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 更新JSON中的测试类名引用
                if 'test_class' in data:
                    data['test_class'] = new_test_name
                
                with open(coverage_json, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
                print(f"      更新覆盖率报告: coverage_report.json")
                
            except Exception as e:
                print(f"      更新覆盖率报告失败 {coverage_json}: {e}")
    
    def _copy_selected_to_evolution_process_no_rename(self, target_class: str, selected_tests: List[Tuple[str, Dict]], gen_num: int):
        """复制选中的测试到evolution_process目录（不重命名）"""
        gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        ensure_dir(gen_dir)
        
        # 复制选中的测试文件，保持原始名称
        for test_name, report in selected_tests:
            # 查找测试文件
            test_file = self._find_test_source_file(test_name)
            if not test_file or not os.path.exists(test_file):
                print(f"  警告: 未找到测试文件 {test_name}")
                continue
            
            # 从maven目录复制到evolution_process，保持原始名称和包结构
            package_path = self._find_target_package_path(target_class)
            if package_path:
                dst_file = os.path.join(gen_dir, package_path.replace(".", os.sep), f"{test_name}.java")
                ensure_dir(os.path.dirname(dst_file))
                copy_file(test_file, dst_file)
                print(f"  复制到evolution_process: {test_name}")
            else:
                # 如果找不到包路径，直接复制到gen_dir根目录
                dst_file = os.path.join(gen_dir, f"{test_name}.java")
                copy_file(test_file, dst_file)
                print(f"  复制到evolution_process (默认位置): {test_name}")
    
    def _save_best_test_to_historical(self, test_name: str, gen_num: int, fitness: float):
        """保存最优测试到历史记录，包括测试文件和对应的测试报告"""
        gen_best_dir = os.path.join(self.historical_best_dir, f"Gen{gen_num}")
        ensure_dir(gen_best_dir)
        
        # 提取目标类名并查找包路径
        target_class = self._extract_target_class_from_test_name(test_name)
        package_path = self._find_target_package_path(target_class)
        
        success_count = 0
        
        # 1. 复制测试源文件（直接查找，不依赖包路径）
        test_file = self._find_test_source_file(test_name)
        if test_file and os.path.exists(test_file):
            dst_file = os.path.join(gen_best_dir, f"{test_name}.java")
            copy_file(test_file, dst_file)
            print(f"保存最优测试 {test_name} (适应度: {fitness:.4f}) 到历史记录: {dst_file}")
            success_count += 1
        else:
            print(f"警告: 未找到测试文件 {test_name}")
        
        # 2. 复制测试报告
        self._copy_test_report_to_historical(test_name, gen_num, gen_best_dir)
        
        if success_count > 0:
            print(f"✅ 最优测试 {test_name} 及其报告已保存到 Gen{gen_num} 历史记录")
    
    def _copy_test_report_to_historical(self, test_name: str, gen_num: int, gen_best_dir: str):
        """复制测试报告到历史记录目录"""
        # 源报告目录路径
        test_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
        src_report_dir = os.path.join(test_reports_dir, test_name)
        
        # 目标报告目录路径  
        dst_report_dir = os.path.join(gen_best_dir, "test_reports", test_name)
        
        if os.path.exists(src_report_dir):
            try:
                # 确保目标目录存在
                ensure_dir(os.path.dirname(dst_report_dir))
                
                # 复制整个报告目录
                if os.path.exists(dst_report_dir):
                    shutil.rmtree(dst_report_dir)
                shutil.copytree(src_report_dir, dst_report_dir)
                
                print(f"  - 测试报告已复制: {test_name}")
                
            except Exception as e:
                print(f"  - 复制测试报告失败 {test_name}: {e}")
        else:
            print(f"  - 警告: 测试报告不存在 {src_report_dir}")
    
    def _cleanup_crossover_and_mutation_tests(self, target_class: str):
        """清理所有交叉和变异测试文件"""
        print(f"清理所有{target_class}类的交叉和变异测试文件...")
        
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 删除文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    file_path = os.path.join(root, file)
                    file_name = file.replace(".java", "")
                    
                    # 检查是否为交叉或变异测试文件
                    if (file_name.startswith(f"{target_class}Test_Crossover_") or 
                        file_name.startswith(f"{target_class}Test_Mutation_")):
                        try:
                            os.remove(file_path)
                            print(f"  删除文件: {file_name}.java")
                        except Exception as e:
                            print(f"  删除文件失败 {file_name}.java: {e}")
        
        # 删除对应的测试报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        for gen_dir in os.listdir(reports_dir):
            gen_path = os.path.join(reports_dir, gen_dir)
            if os.path.isdir(gen_path) and gen_dir.startswith("Gen"):
                for report_dir in os.listdir(gen_path):
                    if (report_dir.startswith(f"{target_class}Test_Crossover_") or 
                        report_dir.startswith(f"{target_class}Test_Mutation_")):
                        report_path = os.path.join(gen_path, report_dir)
                        try:
                            shutil.rmtree(report_path)
                            print(f"  删除测试报告: {gen_dir}/{report_dir}")
                        except Exception as e:
                            print(f"  删除测试报告失败 {gen_dir}/{report_dir}: {e}")
    
    def _verify_generation_completeness(self, target_class: str, current_gen: int) -> bool:
        """验证当前代是否完整：所有中间文件都有对应的测试报告"""
        print(f"验证第{current_gen}代完整性...")
        
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
        
        # 收集所有交叉和变异测试文件
        test_files = []
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    file_name = file.replace(".java", "")
                    # 只验证交叉和变异测试的报告，不验证基础测试V1-V10
                    # 因为基础测试V1-V10是选择的结果，不是当前代的输入
                    if (file_name.startswith(f"{target_class}Test_Crossover_Gen{current_gen}_") or 
                        file_name.startswith(f"{target_class}Test_Mutation_Gen{current_gen}_")):
                        test_files.append(file_name)
        
        # 如果没有交叉和变异测试，说明这是第一代或者没有生成新测试，这是正常情况
        if len(test_files) == 0:
            print(f"第{current_gen}代没有交叉和变异测试，这是正常情况（可能是第一代或生成失败）")
            return True
        
        # 检查是否所有测试文件都有完整的覆盖率报告
        if not os.path.exists(reports_dir):
            print(f"错误: 第{current_gen}代测试报告目录不存在: {reports_dir}")
            return False
        
        missing_reports = []
        incomplete_reports = []
        
        for test_name in test_files:
            report_dir = os.path.join(reports_dir, test_name)
            report_file = os.path.join(report_dir, "coverage_report.json")
            
            if not os.path.exists(report_dir):
                missing_reports.append(test_name)
                continue
                
            # 检查是否有完整的coverage_report.json
            if not os.path.exists(report_file):
                # 如果没有coverage_report.json但有jacoco.xml，尝试生成报告
                jacoco_file = os.path.join(report_dir, "jacoco", "jacoco.xml")
                if os.path.exists(jacoco_file):
                    print(f"  尝试为 {test_name} 生成缺失的覆盖率报告...")
                    try:
                        # 调用coverage_analyzer生成报告
                        from ..coverage_analyzer import CoverageAnalyzer
                        coverage_analyzer = CoverageAnalyzer(self.base_dir, self.project_name)
                        report = coverage_analyzer.analyze_test_coverage(test_name, current_gen, use_cache=False)
                        if report:
                            print(f"    ✓ 成功生成覆盖率报告: {test_name}")
                        else:
                            incomplete_reports.append(test_name)
                    except Exception as e:
                        print(f"    ✗ 生成覆盖率报告失败: {test_name}, 错误: {e}")
                        incomplete_reports.append(test_name)
                else:
                    incomplete_reports.append(test_name)
        
        if missing_reports:
            print(f"错误: 以下测试完全缺少报告目录: {missing_reports}")
            
        if incomplete_reports:
            print(f"警告: 以下测试缺少完整覆盖率报告: {incomplete_reports}")
            # 不将不完整报告视为错误，允许继续处理
            print(f"将继续处理有效的测试报告...")
        
        # 只要不是所有测试都缺少报告就允许继续
        total_tests = len(test_files)
        valid_tests = total_tests - len(missing_reports)
        
        if valid_tests == 0:
            print(f"错误: 所有测试都缺少报告")
            return False
        
        print(f"第{current_gen}代完整性验证通过，共{len(test_files)}个测试")
        return True
    
    def _create_generation_transaction(self, target_class: str, current_gen: int) -> dict:
        """创建代数转换事务，记录所有需要操作的文件"""
        print(f"创建第{current_gen}代转换事务...")
        
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        transaction = {
            'target_class': target_class,
            'current_gen': current_gen,
            'crossover_files': [],
            'mutation_files': [],
            'testv_files': [],
            'backup_created': False
        }
        
        # 收集所有需要处理的文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    file_path = os.path.join(root, file)
                    file_name = file.replace(".java", "")
                    
                    if file_name.startswith(f"{target_class}Test_Crossover_Gen{current_gen}_"):
                        transaction['crossover_files'].append(file_path)
                    elif file_name.startswith(f"{target_class}Test_Mutation_Gen{current_gen}_"):
                        transaction['mutation_files'].append(file_path)
                    elif file_name.startswith(f"{target_class}TestV") and file_name.endswith("TestV1"):
                        # 收集所有已重命名的TestV*文件
                        base_name = file_name.replace("TestV1", "")
                        for i in range(1, 11):  # TestV1-TestV10
                            testv_file = os.path.join(root, f"{base_name}TestV{i}.java")
                            if os.path.exists(testv_file):
                                transaction['testv_files'].append(testv_file)
        
        print(f"事务包含: {len(transaction['crossover_files'])}个交叉文件, "
              f"{len(transaction['mutation_files'])}个变异文件, "
              f"{len(transaction['testv_files'])}个TestV文件")
        
        return transaction
    
    def _atomic_cleanup_generation_safe(self, target_class: str, current_gen: int, selected_test_names: List[str]) -> bool:
        """安全清理当前代的中间文件（排除选中的测试）"""
        print(f"安全清理第{current_gen}代中间文件（保留选中测试）...")
        
        success = True
        deleted_files = []
        selected_set = set(selected_test_names)
        
        try:
            # 清理maven目录中的交叉和变异文件（但不删除选中的）
            test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
            for root, dirs, files in os.walk(test_src_dir):
                for file in files:
                    if file.endswith(".java"):
                        file_path = os.path.join(root, file)
                        file_name = file.replace(".java", "")
                        
                        # 检查是否为当前代的交叉和变异文件
                        if (file_name.startswith(f"{target_class}Test_Crossover_Gen{current_gen}_") or 
                            file_name.startswith(f"{target_class}Test_Mutation_Gen{current_gen}_")):
                            
                            # 只有不在选中列表中的才删除
                            if file_name not in selected_set:
                                try:
                                    os.remove(file_path)
                                    deleted_files.append(file_name)
                                    print(f"  删除淘汰的中间文件: {file_name}.java")
                                except Exception as e:
                                    print(f"  删除文件失败 {file_name}.java: {e}")
                                    success = False
                            else:
                                print(f"  保留选中的测试: {file_name}.java")
            
            # 清理测试报告中的中间文件报告（但不删除选中的）
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
            if os.path.exists(reports_dir):
                for report_dir in os.listdir(reports_dir):
                    if (report_dir.startswith(f"{target_class}Test_Crossover_Gen{current_gen}_") or 
                        report_dir.startswith(f"{target_class}Test_Mutation_Gen{current_gen}_")):
                        
                        # 只有不在选中列表中的才删除
                        if report_dir not in selected_set:
                            report_path = os.path.join(reports_dir, report_dir)
                            try:
                                shutil.rmtree(report_path)
                                print(f"  删除淘汰的中间报告: Gen{current_gen}/{report_dir}")
                            except Exception as e:
                                print(f"  删除中间报告失败 Gen{current_gen}/{report_dir}: {e}")
                                success = False
                        else:
                            print(f"  保留选中测试的报告: {report_dir}")
            
            print(f"安全清理完成，删除了{len(deleted_files)}个淘汰的中间文件，保留了{len(selected_set)}个选中测试")
            return success
            
        except Exception as e:
            print(f"安全清理失败: {e}")
            return False
    
    def _ensure_next_generation_ready(self, target_class: str, next_gen: int) -> bool:
        """确保下一代的目录结构准备就绪"""
        print(f"准备第{next_gen}代目录结构...")
        
        try:
            # 创建下一代测试报告目录
            next_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{next_gen}")
            ensure_dir(next_reports_dir)
            
            # 创建下一代evolution_process目录
            next_evolution_dir = os.path.join(self.evolution_dir, f"Gen{next_gen}")
            ensure_dir(next_evolution_dir)
            
            print(f"第{next_gen}代目录结构准备完成")
            return True
            
        except Exception as e:
            print(f"准备下一代目录失败: {e}")
            return False
    
    def _copy_renamed_tests_to_evolution_process(self, target_class: str, selected_tests: List[Tuple[str, Dict]], gen_num: int):
        """复制重命名后的测试到evolution_process目录"""
        gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        ensure_dir(gen_dir)
        
        print(f"复制重命名后的测试到evolution_process...")
        
        # 复制重命名后的测试文件（现在应该是TestV1-TestV10格式）
        for i, (original_test_name, report) in enumerate(selected_tests, 1):
            new_test_name = f"{target_class}TestV{i}"
            
            # 查找重命名后的测试文件（在maven目录中）
            package_path = self._find_target_package_path(target_class)
            if package_path:
                test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
                test_file = os.path.join(test_src_dir, package_path.replace(".", os.sep), f"{new_test_name}.java")
            else:
                # 如果找不到包路径，在整个测试目录中查找（排除当前代数）
                test_file = self._find_test_source_file(new_test_name, exclude_gen=gen_num)
            
            if test_file and os.path.exists(test_file):
                # 目标文件路径
                if package_path:
                    dst_file = os.path.join(gen_dir, package_path.replace(".", os.sep), f"{new_test_name}.java")
                else:
                    dst_file = os.path.join(gen_dir, f"{new_test_name}.java")
                
                ensure_dir(os.path.dirname(dst_file))
                
                # 检查是否是同一个文件，避免same file错误
                try:
                    if os.path.exists(dst_file) and os.path.samefile(test_file, dst_file):
                        print(f"  跳过同名文件: {new_test_name}")
                        continue
                except OSError:
                    # 如果samefile检查失败，继续尝试复制
                    pass
                
                try:
                    copy_file(test_file, dst_file)
                    print(f"  复制到evolution_process: {new_test_name}")
                except Exception as e:
                    print(f"  复制失败 {new_test_name}: {e}")
            else:
                print(f"  警告: 未找到重命名后的测试文件 {new_test_name}")
        
        print(f"完成复制到 evolution_process/Gen{gen_num}/")
    
    def _cleanup_remaining_intermediate_files(self, target_class: str, current_gen: int) -> bool:
        """清理本类本代的残留中间文件（crossover和mutation），确保环境干净

        在重命名完成后，清理本类本代的残留crossover和mutation文件：
        - 选中的已经重命名为TestV1-V10
        - 淘汰的已经在前面步骤中删除
        - 但可能还有一些残留的中间文件需要清理
        - 🔥 修复：只清理当前类当前代的中间文件，不影响其他类的进化
        """
        print(f"开始清理 {target_class} 第{current_gen}代的残留中间文件...")
        
        success = True
        cleaned_files = 0
        cleaned_reports = 0
        
        try:
            # 1. 清理maven目录中的本类本代crossover和mutation文件
            test_src_dir = os.path.join(self.project_dir, "src", "test", "java")

            if os.path.exists(test_src_dir):
                for root, dirs, files in os.walk(test_src_dir):
                    for file in files:
                        if file.endswith(".java"):
                            file_path = os.path.join(root, file)
                            file_name = file.replace(".java", "")

                            # 🔥 修复：只清理本类本代的crossover或mutation文件
                            if (f"{target_class}Test_Crossover_Gen{current_gen}" in file_name or
                                f"{target_class}Test_Mutation_Gen{current_gen}" in file_name):
                                try:
                                    os.remove(file_path)
                                    print(f"  删除残留中间文件: {file_name}")
                                    cleaned_files += 1
                                except Exception as e:
                                    print(f"  删除中间文件失败 {file_name}: {e}")
                                    success = False

            # 2. 清理测试报告中的本类本代crossover和mutation报告
            test_reports_gen_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")

            if os.path.exists(test_reports_gen_dir):
                # 只处理当前代的报告目录
                for report_dir in os.listdir(test_reports_gen_dir):
                    if (f"{target_class}Test_Crossover_Gen{current_gen}" in report_dir or
                        f"{target_class}Test_Mutation_Gen{current_gen}" in report_dir):
                        report_path = os.path.join(test_reports_gen_dir, report_dir)
                        try:
                            if os.path.isdir(report_path):
                                import shutil
                                shutil.rmtree(report_path)
                                print(f"  删除残留测试报告: Gen{current_gen}/{report_dir}")
                                cleaned_reports += 1
                        except Exception as e:
                            print(f"  删除中间报告失败 {report_dir}: {e}")
                            success = False
            
            if cleaned_files == 0 and cleaned_reports == 0:
                print(f"  没有发现需要清理的残留中间文件")
            else:
                print(f"  成功清理 {cleaned_files} 个中间文件和 {cleaned_reports} 个中间报告")
                print(f"  现在环境已清理干净，只保留标准的TestV1-V10文件")
            
            return success
            
        except Exception as e:
            print(f"清理残留中间文件时发生错误: {e}")
            return False
