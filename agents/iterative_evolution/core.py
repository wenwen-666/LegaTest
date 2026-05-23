"""
核心类和主要流程模块
"""

import os
import shutil
import subprocess
import sys
import re
import json
import glob
from typing import Dict, List, Tuple, Optional

try:
    from .utils import ensure_dir, copy_file, load_json
    from .clients import LLMClient
    from .evaluation import DiversityCalculator
    from .operators import CrossoverOperator, MutationOperator
    from .test_executor import TestExecutor
    from .coverage_analyzer import CoverageAnalyzer
    from .intelligent_test_optimizer import IntelligentTestOptimizer
    from .generation_manager import GenerationManager
    from .unified_manager import get_unified_manager
except ImportError:
    from utils import ensure_dir, copy_file, load_json
    from clients import LLMClient
    from evaluation import DiversityCalculator
    from operators import CrossoverOperator, MutationOperator
    from test_executor import TestExecutor
    from coverage_analyzer import CoverageAnalyzer
    from intelligent_test_optimizer import IntelligentTestOptimizer
    from generation_manager import GenerationManager
    from unified_manager import get_unified_manager
# 导入常量
from .constants import (
    MAX_GENERATIONS, FITNESS_THRESHOLD, CONVERGENCE_THRESHOLD, 
    CONVERGENCE_GENERATIONS, LINE_COVERAGE_TARGET, ENABLE_CROSSOVER_MUTATION,
    BRANCH_COVERAGE_TARGET, TESTS_PER_GENERATION
)

class EvolutionaryTesting:
    def __init__(self, base_dir: str, project_name: str, target_class: str = None):
        """初始化演化测试框架
        
        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
            target_class: 指定单个被测类（可选，如果不指定则处理所有被测类）
        """
        self.base_dir = base_dir
        self.project_name = project_name
        self.target_class = target_class
        self.dataset_dir = os.path.join(base_dir, "dataset")
        self.project_dir = os.path.join(self.dataset_dir, project_name)
        self.evolution_dir = os.path.join(base_dir, "evolution_process", project_name)
        self.historical_best_dir = os.path.join(self.evolution_dir, "historical_best")
        
        # 创建必要的目录
        ensure_dir(self.evolution_dir)
        ensure_dir(self.historical_best_dir)
        
        # 记录历史适应度值
        self.historical_fitness = []
        
        # 为每个类维护单独的适应度历史记录
        self.class_fitness_history = {}  # {target_class: [fitness_values]}
        
        # 类状态管理
        self.class_status_file = os.path.join(self.evolution_dir, "class_status.json")
        self.class_states = {}  # {target_class: {"status": "active/terminated", "last_generation": int, "fitness_history": [], ...}}
        
        # 初始化组件
        self.llm_client = LLMClient(base_dir)
        self.diversity_calculator = DiversityCalculator(base_dir, project_name)
        self.crossover_operator = CrossoverOperator(base_dir, project_name, self.llm_client)
        self.mutation_operator = MutationOperator(base_dir, project_name, self.llm_client)
        self.test_executor = TestExecutor(base_dir, project_name)
        self.coverage_analyzer = CoverageAnalyzer(base_dir, project_name)
        self.generation_manager = GenerationManager(base_dir, project_name, core_instance=self)
        self.unified_manager = get_unified_manager(base_dir, project_name)
        # 演化状态锁 - 确保同时只有一个演化过程在运行
        self.evolution_in_progress = False
        self.current_evolution_class = None

        # 强制覆盖模式
        self.force_overwrite = False
    
    def run_evolution(self, end_gen: int = None):
        """运行演化优化过程 - 按被测类分别演化

        Args:
            end_gen: 结束代数，如果未指定则使用 MAX_GENERATIONS
        """
        # 设置实际使用的结束代数
        actual_end_gen = end_gen if end_gen is not None else MAX_GENERATIONS

        print(f"开始对项目 {self.project_name} 进行演化优化...")
        print(f"最大迭代次数: {MAX_GENERATIONS}")
        print(f"目标结束代数: {actual_end_gen}")
        # 移除终止条件相关的输出信息
        
        # 清空覆盖率缓存
        self.coverage_analyzer.clear_cache()
        
        # 检测完整的现有进度并决定从哪一代开始
        current_gen = self.detect_complete_latest_generation()
        if current_gen > 1:
            print(f"检测到完整进度，从第{current_gen+1}代继续演化")
            # 恢复现有的演化测试到项目目录
            self.restore_evolved_tests(current_gen)
            current_gen += 1  # 继续下一代
        elif current_gen == 1:
            print("检测到第1代完整，从第2代开始演化")
            # 恢复现有的演化测试到项目目录
            self.restore_evolved_tests(1)
            current_gen = 2
        else:
            print("未检测到完整进度，从第1代开始演化")
            # 从test_generator结果初始化第一代
            if not self.initialize_first_generation_from_test_generator():
                print("错误: 无法从test_generator结果初始化第一代")
                return
            current_gen = 2  # 从第二代开始迭代优化
        
        # 检查当前代的test_reports目录结构
        self.organize_test_reports_for_generation(current_gen)
        
        # 检查当前代的完成状态并决定从哪个步骤继续
        resume_info = self.detect_generation_progress(current_gen)
        if resume_info['should_resume']:
            print(f"检测到第{current_gen}代部分完成，从{resume_info['next_step']}步骤继续...")
            if resume_info['next_step'] == 'select_next_generation':
                # 已有所有测试的报告，直接进行代际选择
                self.handle_generation_selection_resume(current_gen)
                return
            elif resume_info['next_step'] == 'run_existing_tests':
                # 有现有测试但缺少报告，需要运行测试
                self.handle_existing_tests_resume(current_gen, resume_info['existing_tests'])
                return
            elif resume_info['next_step'] == 'crossover_mutation_step':
                # 有交叉测试和报告，需要执行交叉后变异步骤
                self.handle_crossover_mutation_resume(current_gen, resume_info['crossover_tests'])
                return
            elif resume_info['next_step'] == 'continue_crossover':
                print("检测到continue_crossover状态，但将跳过以使用正常的单类演化流程...")
        
        # 获取基础代的测试报告并按被测类分组
        # 如果是继续演化，使用前一代的报告；如果是第1代，使用第1代的报告
        base_gen = max(1, current_gen - 1) if current_gen > 1 else current_gen
        test_reports = self.diversity_calculator.get_test_reports(base_gen)
        if not test_reports:
            print(f"错误: 无法获取第{base_gen}代测试报告")
            return
        
        grouped_tests = self.group_tests_by_target_class(test_reports)
        
        # 获取测试目录中实际存在的被测类（这是权威来源）
        discovered_classes = self.discover_testv_classes()
        if discovered_classes:
            print(f"测试目录中发现的被测类: {discovered_classes}")
            
            # 检查是否有被测类在当前代测试报告中缺失
            missing_classes = set(discovered_classes) - set(grouped_tests.keys())
            if missing_classes:
                print(f"检测到 {len(missing_classes)} 个被测类在第{base_gen}代报告中缺失: {missing_classes}")
                print(f"这些类需要继续进行第{current_gen}代的演化，使用前一代数据作为基础...")
                
                # 从前一代获取这些缺失类的测试作为演化基础
                for prev_gen in range(base_gen - 1, 0, -1):
                    if missing_classes:
                        prev_reports = self.diversity_calculator.get_test_reports(prev_gen)
                        if prev_reports:
                            prev_grouped = self.group_tests_by_target_class(prev_reports)
                            for missing_class in list(missing_classes):
                                if missing_class in prev_grouped:
                                    # 使用前一代数据作为演化基础
                                    grouped_tests[missing_class] = prev_grouped[missing_class]
                                    missing_classes.remove(missing_class)
                                    print(f"  使用第{prev_gen}代数据作为 {missing_class} 的演化基础")
                    else:
                        break
                
                if missing_classes:
                    print(f"警告: 找不到前一代数据的被测类: {missing_classes}")
                    print(f"这些类将跳过第{current_gen}代演化")
        
        # 如果指定了target_class，只处理该被测类
        if self.target_class:
            # 尝试精确匹配
            if self.target_class in grouped_tests:
                grouped_tests = {self.target_class: grouped_tests[self.target_class]}
                print(f"指定测试被测类: {self.target_class}")
            else:
                # 尝试模糊匹配（支持不带版本号的类名）
                import re
                matched_classes = []
                for cls in grouped_tests.keys():
                    # 移除版本号后比较
                    base_cls = re.sub(r'V\d+$', '', cls)
                    if base_cls == self.target_class or cls.startswith(self.target_class):
                        matched_classes.append(cls)
                
                if matched_classes:
                    # 使用第一个匹配的类
                    selected_class = matched_classes[0]
                    grouped_tests = {selected_class: grouped_tests[selected_class]}
                    print(f"指定测试被测类: {self.target_class} -> 匹配到: {selected_class}")
                else:
                    print(f"错误: 找不到被测类 {self.target_class}")
                    print(f"可用的被测类: {list(grouped_tests.keys())}")
                    return
        
        active_target_classes = set(grouped_tests.keys())
        
        print(f"发现 {len(active_target_classes)} 个被测类:")
        for target_class in active_target_classes:
            test_count = len(grouped_tests[target_class])
            print(f"  - {target_class}: {test_count} 个测试")
        
        # 初始化终止类集合和类级别适应度历史
        terminated_classes = set()  # 已终止的类
        
        # 加载已保存的类状态并恢复terminated_classes
        self._load_class_states()
        for target_class, state in self.class_states.items():
            if state.get("status") == "terminated":
                terminated_classes.add(target_class)
                print(f"从状态文件恢复：类 {target_class} 在第{state.get('last_generation', 0)}代已终止")
        
        if terminated_classes:
            print(f"恢复了 {len(terminated_classes)} 个已终止类的状态")
        
        # 主演化循环
        while current_gen <= actual_end_gen:
            print(f"\n===== 开始第 {current_gen} 代演化 =====")
            
            # 检查是否只处理单个被测类（当指定了target_class参数时）
            if self.target_class:
                # 单类模式：只处理指定的被测类
                target_class = self.target_class
                print(f"处理指定的被测类: {target_class}")
                
                # 检查该类是否已终止
                if target_class in terminated_classes:
                    print(f"被测类 {target_class} 已在之前代数终止，复制上一代测试报告")
                    self._copy_previous_generation_reports(target_class, current_gen)
                else:
                    # 获取该被测类的当前测试
                    target_tests = self._get_current_maven_tests(target_class)
                    if not target_tests:
                        print(f"警告: 无法从maven目录获取 {target_class} 的测试报告，尝试生成缺失的报告...")
                        # 尝试为maven目录中的测试文件生成报告
                        if self._generate_missing_test_reports(target_class, current_gen):
                            target_tests = self._get_current_maven_tests(target_class)
                            if target_tests:
                                print(f"  ✓ 成功为 {target_class} 生成了 {len(target_tests)} 个测试报告")
                            else:
                                print(f"  ✗ 仍然无法获取 {target_class} 的测试报告")
                                continue  # 跳过这个类，继续处理下一个类
                        else:
                            print(f"  ✗ 无法为 {target_class} 生成测试报告")
                            continue  # 跳过这个类，继续处理下一个类
                    
                    if len(target_tests) < 2:
                        print(f"警告: 被测类 {target_class} 的测试数量不足({len(target_tests)})，无法进行演化")
                        break
                    
                    print(f"找到 {len(target_tests)} 个 {target_class} 类的测试")
                    
                    # 执行一代完整的演化过程
                    success = self.evolve_single_generation(target_class, target_tests, current_gen)
                    if not success:
                        print(f"第{current_gen}代演化失败")
                        break
                    
                    # 演化成功后立即计算并记录适应度
                    self._calculate_and_record_generation_fitness(target_class, current_gen)

                    # 检查是否达到98%覆盖率终止条件
                    final_tests = self._get_final_generation_tests(target_class, current_gen)
                    if self._should_terminate_class_evolution(target_class, final_tests, current_gen):
                        print(f"被测类 {target_class} 在第{current_gen}代达到98%覆盖率终止条件")
                        terminated_classes.add(target_class)
                        self._update_class_state(target_class, current_gen, status="terminated",
                                                termination_reason="high_coverage_achieved")
                        break  # 该类演化终止，结束该类的演化循环
                
                current_gen += 1
            else:
                # 多类模式：处理所有发现的类
                discovered_classes = self.discover_testv_classes()
                
                if not discovered_classes:
                    print("错误: 未发现任何TestV*模式的测试类")
                    break
                
                print(f"发现 {len(discovered_classes)} 个TestV*测试类")
                active_classes = set(discovered_classes) - terminated_classes
                print(f"活跃类: {len(active_classes)} 个")
                print(f"已终止类: {len(terminated_classes)} 个")
                
                # 对每个发现的类按顺序进行当代演化 - 确保严格的单类处理顺序
                # 重要：一个类必须完全处理完成后才能处理下一个类
                print(f"\n🔄 第{current_gen}代：按顺序处理 {len([c for c in discovered_classes if c not in terminated_classes])} 个活跃类")
                
                for idx, target_class in enumerate(sorted(discovered_classes), 1):
                    print(f"\n--- 处理被测类 {idx}/{len(discovered_classes)}: {target_class} ---")
                    print(f"⏳ 确保该类完全处理完成后再处理下一个类")
                    
                    # 检查该类在当前代是否已经完成
                    if self._is_class_completed_in_generation(target_class, current_gen):
                        print(f"被测类 {target_class} 在第{current_gen}代已完成，跳过")
                        continue
                    
                    # 获取该被测类的当前测试
                    target_tests = self._get_current_maven_tests(target_class)
                    if not target_tests:
                        print(f"警告: 无法从maven目录获取 {target_class} 的测试，标记为终止")
                        terminated_classes.add(target_class)
                        self._update_class_state(target_class, current_gen, status="terminated", 
                                                termination_reason="no_tests_found")
                        continue
                    
                    if len(target_tests) < 2:
                        print(f"警告: 被测类 {target_class} 的测试数量不足({len(target_tests)})，标记为终止")
                        terminated_classes.add(target_class)
                        self._update_class_state(target_class, current_gen, status="terminated", 
                                                termination_reason="insufficient_tests")
                        continue
                    
                    print(f"找到 {len(target_tests)} 个 {target_class} 类的测试，开始完整演化处理")
                    print(f"按照用户要求：该类必须完全完成所有演化步骤后才能处理下一个类")
                    
                    # 确保该类的演化过程完全完成，不跳过失败的类
                    max_retries = 5  # 增加重试次数，避免因为临时问题导致终止
                    class_completed = False
                    
                    for retry in range(max_retries):
                        if retry > 0:
                            print(f"被测类 {target_class} 第{current_gen}代演化重试 {retry}/{max_retries}")
                        
                        # 执行该类在当代的演化过程
                        success = self.evolve_single_generation(target_class, target_tests, current_gen)
                        if not success:
                            print(f"被测类 {target_class} 第{current_gen}代演化失败 (尝试 {retry+1}/{max_retries})")
                            if retry == max_retries - 1:
                                print(f"被测类 {target_class} 达到最大重试次数，标记为终止")
                                terminated_classes.add(target_class)
                                self._update_class_state(target_class, current_gen, status="terminated", 
                                                        termination_reason="evolution_failed")
                                class_completed = True  # 标记为已处理完成（虽然失败）
                                break
                            continue
                        
                        # 演化成功后检查该类在当代是否真正完成
                        if not self._is_class_completed_in_generation(target_class, current_gen):
                            print(f"被测类 {target_class} 第{current_gen}代演化过程未完全完成 (尝试 {retry+1}/{max_retries})")
                            if retry == max_retries - 1:
                                print(f"⚠️ 被测类 {target_class} 演化完成检查失败，但不终止演化，继续下一代")
                                class_completed = True  # 标记为已处理完成，继续演化
                                break
                            continue
                        
                        # 演化成功且完成检查通过
                        print(f"✅ 被测类 {target_class} 第{current_gen}代演化完全成功")
                        
                        # 立即计算并记录该类该代的适应度
                        self._calculate_and_record_generation_fitness(target_class, current_gen)

                        # 检查是否达到98%覆盖率终止条件
                        if target_class not in terminated_classes:
                            final_tests = self._get_final_generation_tests(target_class, current_gen)
                            if self._should_terminate_class_evolution(target_class, final_tests, current_gen):
                                print(f"被测类 {target_class} 在第{current_gen}代达到98%覆盖率终止条件")
                                terminated_classes.add(target_class)
                                self._update_class_state(target_class, current_gen, status="terminated",
                                                        termination_reason="high_coverage_achieved")

                        class_completed = True
                        break

                    # 确保类已完成处理（成功或失败都算完成）
                    if not class_completed:
                        print(f"错误: 被测类 {target_class} 处理异常，强制标记为终止")
                        terminated_classes.add(target_class)
                        self._update_class_state(target_class, current_gen, status="terminated",
                                                termination_reason="processing_error")
                    
                    print(f"--- ✅ 被测类 {target_class} 在第{current_gen}代处理完毕，继续下一个类 ---")
                
                # 严格验证所有活跃类是否真正完成当代演化（使用全面的代间同步验证）
                print(f"\n=== 验证第{current_gen}代所有类完整性（代间同步检查）===")
                all_classes_complete = self._verify_generation_completeness_for_all_classes(current_gen, active_classes)
                
                if all_classes_complete:
                    print(f"\n✅ 第{current_gen}代所有活跃类完整完成演化，可以进入第{current_gen+1}代")
                    current_gen += 1
                else:
                    print(f"\n⚠️ 第{current_gen}代有类演化未完成，正在获取详细未完成类列表...")
                    incomplete_classes = self._get_incomplete_classes_in_generation(current_gen, active_classes)
                    
                    if incomplete_classes:
                        print(f"正在自动完成这些类的选择和重命名过程...")
                        
                        # 尝试完成未完成的类
                        completion_success = self._complete_incomplete_classes(incomplete_classes, current_gen)
                        
                        if completion_success:
                            print(f"✅ 已成功完成所有未完成类的演化过程，可以进入第{current_gen+1}代")
                            current_gen += 1
                        else:
                            print(f"❌ 部分类无法自动完成，但继续进入第{current_gen+1}代（允许部分失败）")
                            print(f"  建议手动检查以下内容:")
                            print(f"  1. evolution_process/{self.project_name}/Gen{current_gen}/ 目录结构")
                            print(f"  2. test_reports/{self.project_name}/Gen{current_gen}/ 目录结构")
                            print(f"  3. 中间文件是否需要手动清理")
                            current_gen += 1
                    else:
                        print(f"❌ 代间同步验证失败，但无法检测到具体未完成类，强制进入第{current_gen+1}代")
                        print(f"  请手动检查所有类的完整性")
                        current_gen += 1
        
        print(f"\n演化过程完成，共进行了 {current_gen-1} 代演化")
        
        # 演化完成后的最终优化
        if self.target_class:
            self._handle_final_optimization(self.target_class, current_gen-1)
    
    def detect_complete_latest_generation(self) -> int:
        """检测最新的完整代数

        单类模式：检查指定类的完整性
        多类模式：检查所有活跃类的共同完整代数

        Returns:
            最新完整代数，如果没有完整进度则返回0
        """
        # 先加载类状态
        self._load_class_states()

        if self.target_class:
            # 单类模式：检查指定类的完整性
            for gen in range(MAX_GENERATIONS, 0, -1):
                if self.is_generation_complete(gen, quiet=True):
                    print(f"检测到被测类 {self.target_class} 第{gen}代完整")
                    return gen
            return 0
        else:
            # 多类模式：检查所有类的共同完整代数
            discovered_classes = self.discover_testv_classes()
            if not discovered_classes:
                print("未发现任何TestV*模式的测试类，无法进行断点续传")
                return 0
            
            print(f"断点续传检测：发现 {len(discovered_classes)} 个测试类: {', '.join(discovered_classes)}")
            
            # 找到所有类的共同完整代数
            for gen in range(MAX_GENERATIONS, 0, -1):
                all_classes_complete = True
                
                for target_class in discovered_classes:
                    if not self.is_class_generation_complete(target_class, gen, quiet=True):
                        all_classes_complete = False
                        break
                
                if all_classes_complete:
                    print(f"检测到所有类的第{gen}代都已完整")
                    return gen
                    
            print("未检测到所有类的共同完整代数")
            return 0
    
    def is_class_generation_complete(self, target_class: str, generation: int, quiet: bool = False) -> bool:
        """检查指定类的指定代数是否完整"""
        # 1. 检查evolution_process目录是否有测试文件
        gen_dir = os.path.join(self.evolution_dir, f"Gen{generation}")
        if not os.path.exists(gen_dir):
            if not quiet:
                print(f"类 {target_class} 第{generation}代不完整: 缺少 evolution_process/Gen{generation}")
            return False
        
        # 检查该类的测试文件
        found_test_files = []
        for root, dirs, files in os.walk(gen_dir):
            for file in files:
                if re.match(rf'^{target_class}TestV\d+\.java$', file):
                    found_test_files.append(file)
        
        if len(found_test_files) == 0:
            if not quiet:
                print(f"类 {target_class} 第{generation}代不完整: evolution_process中未找到测试文件")
            return False
        
        # 2. 检查test_reports目录是否有该类的报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}")
        if not os.path.exists(reports_dir):
            if not quiet:
                print(f"类 {target_class} 第{generation}代不完整: 缺少 test_reports/Gen{generation}")
            return False
        
        # 检查该类相关的报告目录
        class_reports_found = False
        for item in os.listdir(reports_dir):
            if target_class in item and os.path.isdir(os.path.join(reports_dir, item)):
                class_reports_found = True
                break
        
        if not class_reports_found:
            if not quiet:
                print(f"类 {target_class} 第{generation}代不完整: 未找到测试报告")
            return False
        
        # 3. 检查Maven目录中是否有未处理的交叉或变异测试
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        if os.path.exists(maven_test_dir):
            for root, dirs, files in os.walk(maven_test_dir):
                for file in files:
                    if (f"{target_class}Test_Crossover_Gen{generation}" in file or 
                        f"{target_class}Test_Mutation_Gen{generation}" in file):
                        if not quiet:
                            print(f"类 {target_class} 第{generation}代不完整: Maven目录中仍有未处理的测试: {file}")
                        return False
        
        return True
    
    def is_generation_complete(self, generation: int, quiet: bool = False) -> bool:
        """检查指定代是否完整"""
        if not self.target_class:
            return False
        
        # 1. 检查evolution_process目录是否有完整的V1-V{TESTS_PER_GENERATION}
        gen_dir = os.path.join(self.evolution_dir, f"Gen{generation}")
        if not os.path.exists(gen_dir):
            if not quiet:
                print(f"第{generation}代不完整: 缺少 evolution_process/Gen{generation}")
            return False
        
        # 检查测试文件，动态判断需要多少个
        found_test_files = []
        for root, dirs, files in os.walk(gen_dir):
            for file in files:
                if re.match(rf'^{self.target_class}TestV\d+\.java$', file):
                    found_test_files.append(file)
        
        # 如果没有找到任何测试文件，代数不完整
        if len(found_test_files) == 0:
            print(f"第{generation}代不完整: evolution_process中未找到任何测试文件")
            return False
        
        # 检查Maven目录中是否有交叉或变异测试，如果有则说明代数未完成
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        for root, dirs, files in os.walk(maven_test_dir):
            for file in files:
                if (f"{self.target_class}Test_Crossover_Gen{generation}" in file or 
                    f"{self.target_class}Test_Mutation_Gen{generation}" in file):
                    if not quiet:
                        print(f"第{generation}代不完整: Maven目录中仍有未处理的交叉/变异测试: {file}")
                    return False
        
        # 2. 检查test_reports目录是否存在对应的报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}")
        if not os.path.exists(reports_dir):
            if not quiet:
                print(f"第{generation}代不完整: 缺少 test_reports/Gen{generation}")
            return False
        
        # 计算有效的测试报告数量（基于实际找到的测试文件）
        valid_reports = 0
        expected_reports = len(found_test_files)
        
        # 从找到的测试文件中提取版本号
        for test_file in found_test_files:
            match = re.match(rf'^{self.target_class}TestV(\d+)\.java$', test_file)
            if match:
                version = match.group(1)
                report_dir = os.path.join(reports_dir, f"{self.target_class}TestV{version}")
                report_file = os.path.join(report_dir, "coverage_report.json")
                if os.path.exists(report_file):
                    valid_reports += 1
        
        if valid_reports < expected_reports:
            if not quiet:
                print(f"第{generation}代不完整: test_reports中只有 {valid_reports} 个有效报告，需要{expected_reports}个")
            return False
        
        # 3. 检查historical_best目录是否有该代最优测试
        historical_dir = os.path.join(self.historical_best_dir, f"Gen{generation}")
        if not os.path.exists(historical_dir):
            if not quiet:
                print(f"第{generation}代不完整: 缺少 historical_best/Gen{generation}")
            return False
        
        # 检查是否有最优测试文件
        has_best_test = False
        try:
            files = os.listdir(historical_dir)
            for file in files:
                if file.endswith('.java'):
                    has_best_test = True
                    break
        except OSError:
            if not quiet:
                print(f"第{generation}代不完整: 无法读取 historical_best/Gen{generation}")
            return False
        
        if not has_best_test:
            if not quiet:
                print(f"第{generation}代不完整: 缺少 historical_best 中的最优测试")
            return False
        
        if not quiet:
            print(f"第{generation}代完整性检查通过")
        return True
    
    def initialize_first_generation_from_test_generator(self) -> bool:
        """从test_generator结果初始化第一代"""
        if self.target_class:
            # 处理单个指定的类
            print(f"从test_generator结果初始化第一代 - 类: {self.target_class}")
            return self._initialize_single_class_from_test_generator(self.target_class)
        else:
            # 自动发现并处理所有TestV*测试类
            print("从test_generator结果初始化第一代 - 自动发现所有TestV*测试类")
            discovered_classes = self.discover_testv_classes()
            
            if not discovered_classes:
                print("错误: 未发现任何TestV*模式的测试类")
                return False
            
            success_count = 0
            for target_class in discovered_classes:
                if self._initialize_single_class_from_test_generator(target_class):
                    success_count += 1
                else:
                    print(f"警告: 无法初始化类 {target_class}")
            
            if success_count == 0:
                print("错误: 所有类初始化都失败")
                return False
            
            print(f"成功初始化了 {success_count}/{len(discovered_classes)} 个类")
            return True
    
    def _initialize_single_class_from_test_generator(self, target_class: str) -> bool:
        """为单个类从test_generator结果初始化第一代"""
        print(f"初始化类: {target_class}")
        
        # 在项目src/test/java目录中查找test_generator生成的TestV1-V{TESTS_PER_GENERATION}
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        test_files = []
        
        # 搜索所有包路径
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                # 匹配 {target_class}TestV{数字}.java 的模式
                if re.match(rf'^{target_class}TestV\d+\.java$', file):
                    full_path = os.path.join(root, file)
                    test_files.append(full_path)
        
        if len(test_files) < 2:
            print(f"警告: 类 {target_class} 只找到 {len(test_files)} 个测试文件，少于最小要求的2个")
            return False
        
        # 排序确保V1, V2, ..., V10的顺序
        test_files.sort(key=lambda x: int(re.search(r'V(\d+)', x).group(1)))
        
        # 创建Gen1目录
        gen1_dir = os.path.join(self.evolution_dir, "Gen1")
        ensure_dir(gen1_dir)
        
        gen1_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, "Gen1")
        ensure_dir(gen1_reports_dir)
        
        historical_gen1_dir = os.path.join(self.historical_best_dir, "Gen1")
        ensure_dir(historical_gen1_dir)
        
        # 复制测试文件到Gen1
        copied_count = 0
        test_names = []
        # 灵活处理：如果测试文件数量少于TESTS_PER_GENERATION，则全部复制
        files_to_copy = test_files[:TESTS_PER_GENERATION] if len(test_files) > TESTS_PER_GENERATION else test_files
        for i, test_file in enumerate(files_to_copy, 1):
            # 目标文件名
            target_name = f"{target_class}TestV{i}"
            target_file = os.path.join(gen1_dir, f"{target_name}.java")
            
            try:
                shutil.copy2(test_file, target_file)
                test_names.append(target_name)
                copied_count += 1
                print(f"复制: {os.path.basename(test_file)} -> {target_name}.java")
            except Exception as e:
                print(f"复制失败: {test_file} - {e}")
        
        if copied_count < 2:
            print(f"错误: 成功复制的测试文件太少 ({copied_count} < 2)")
            return False
        
        # 生成测试报告
        print("生成第一代测试报告...")
        reports_generated = 0
        best_test = None
        best_fitness = -1
        
        for test_name in test_names:
            try:
                # 使用_check_and_generate_test_reports方法自动生成报告
                if self._check_and_generate_test_reports(test_name, 1):
                    # 报告生成成功，现在读取报告
                    test_report_dir = os.path.join(gen1_reports_dir, test_name)
                    report_file = os.path.join(test_report_dir, "coverage_report.json")
                    
                    if os.path.exists(report_file):
                        with open(report_file, 'r', encoding='utf-8') as f:
                            coverage_report = json.load(f)
                        
                        reports_generated += 1
                        
                        # 记录最优测试
                        fitness = coverage_report.get('fitness', 0)
                        if fitness > best_fitness:
                            best_fitness = fitness
                        best_test = test_name
                    
                    print(f"生成报告: {test_name} (适应度: {fitness:.4f})")
                else:
                    print(f"警告: 无法生成 {test_name} 的覆盖率报告")
            except Exception as e:
                print(f"生成报告失败: {test_name} - {e}")
        
        if reports_generated < 2:
            print(f"错误: 成功生成的报告太少 ({reports_generated} < 2)")
            return False
        
        # 复制最优测试到historical_best
        if best_test:
            best_test_file = os.path.join(gen1_dir, f"{best_test}.java")
            historical_file = os.path.join(historical_gen1_dir, f"{best_test}.java")
            
            try:
                shutil.copy2(best_test_file, historical_file)
                print(f"复制最优测试到历史记录: {best_test} (适应度: {best_fitness:.4f})")
            except Exception as e:
                print(f"复制最优测试失败: {e}")
        
        print(f"第一代初始化完成: {copied_count} 个测试, {reports_generated} 个报告")
        return True

    def detect_latest_generation(self) -> int:
        """检测已有的最新代数

        Returns:
            最新代数，如果没有现有进度则返回1
        """
        max_gen = 1

        # 首先检查class_status.json中记录的最高代数
        try:
            status_file = os.path.join(self.evolution_dir, "class_status.json")
            if os.path.exists(status_file):
                with open(status_file, 'r', encoding='utf-8') as f:
                    status_data = json.load(f)
                    for class_name, info in status_data.items():
                        if isinstance(info, dict) and 'last_generation' in info:
                            max_gen = max(max_gen, info['last_generation'])
                print(f"从class_status.json检测到最高代数: {max_gen}")
                return max_gen
        except Exception as e:
            print(f"读取class_status.json失败: {e}")

        # 检查evolution_process目录
        for i in range(1, MAX_GENERATIONS + 1):
            gen_dir = os.path.join(self.evolution_dir, f"Gen{i}")
            if os.path.exists(gen_dir):
                max_gen = max(max_gen, i)
        
        # 检查test_reports目录
        test_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        if os.path.exists(test_reports_dir):
            for i in range(1, MAX_GENERATIONS + 1):
                gen_reports_dir = os.path.join(test_reports_dir, f"Gen{i}")
                if os.path.exists(gen_reports_dir):
                    # 检查是否有测试报告文件
                    has_reports = False
                    for root, dirs, files in os.walk(gen_reports_dir):
                        if "coverage_report.json" in files:
                            has_reports = True
                            break
                    if has_reports:
                        max_gen = max(max_gen, i)
        
        # 从最新代向前检查，找到有完整测试报告的代数
        for gen in range(max_gen, 0, -1):
            if self.has_complete_test_reports(gen):
                if gen == max_gen and self.is_generation_complete(gen):
                    return gen + 1  # 该代已完成，开始下一代
                else:
                    return gen  # 从该代继续
        
        return 1  # 如果没有找到完整报告，从第一代开始
    
    
    def has_complete_test_reports(self, gen_num: int) -> bool:
        """检查指定代数是否有完整的测试报告
        
        Args:
            gen_num: 代数
            
        Returns:
            是否有完整的测试报告
        """
        test_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
        if not os.path.exists(test_reports_dir):
            return False
        
        # 检查是否有足够的测试报告文件
        report_count = 0
        for root, dirs, files in os.walk(test_reports_dir):
            if "coverage_report.json" in files:
                report_count += 1
        
        # 如果有测试报告就认为是有效的
        return report_count > 0
    
    def restore_evolved_tests(self, current_gen: int):
        """恢复已有的演化测试到项目测试目录
        
        Args:
            current_gen: 当前代数
        """
        print("恢复现有演化测试到项目目录...")
        
        project_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 恢复所有已有代的演化测试
        for gen in range(1, current_gen + 1):
            gen_dir = os.path.join(self.evolution_dir, f"Gen{gen}")
            if not os.path.exists(gen_dir):
                continue
            
            # 查找所有交叉和变异生成的测试（只恢复指定target_class的）
            for root, dirs, files in os.walk(gen_dir):
                for file in files:
                    if file.endswith(".java") and ("_Crossover_" in file or "_Mutation_" in file):
                        # 检查是否属于指定的target_class
                        test_class_name = file.replace(".java", "")
                        extracted_target = self._extract_target_class_from_test_name(test_class_name)
                        
                        # 只恢复指定target_class的测试
                        if self.target_class and extracted_target == self.target_class:
                            src_path = os.path.join(root, file)
                            
                            # 计算相对路径
                            rel_path = os.path.relpath(src_path, gen_dir)
                            dst_path = os.path.join(project_test_dir, rel_path)
                            
                            # 确保目标目录存在
                            ensure_dir(os.path.dirname(dst_path))
                            
                            # 复制文件
                            if not os.path.exists(dst_path):
                                copy_file(src_path, dst_path)
                                print(f"恢复演化测试: {rel_path}")
    
    def initialize_first_generation(self):
        """初始化第一代，复制原始测试到evolution_process目录"""
        print("初始化第一代...")
        
        # 创建第一代目录
        gen1_dir = os.path.join(self.evolution_dir, "Gen1")
        ensure_dir(gen1_dir)
        
        # 查找src/test中的所有测试类
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        if not os.path.exists(test_src_dir):
            print(f"警告: 测试源目录 {test_src_dir} 不存在")
            return
        
        # 复制所有测试类（格式为[被测名]TestV几.java）到evolution_process/project/Gen1目录
        test_count = 0
        for root, _, files in os.walk(test_src_dir):
            for file in files:
                # 匹配格式：[被测名]TestV几.java，并且被测类名必须匹配target_class
                if file.endswith(".java") and "TestV" in file:
                    # 提取被测类名
                    test_class_name = file.replace(".java", "")
                    extracted_target = self._extract_target_class_from_test_name(test_class_name)
                    
                    # 只复制指定target_class的测试
                    if self.target_class and extracted_target == self.target_class:
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(src_path, test_src_dir)
                        dst_path = os.path.join(gen1_dir, rel_path)
                        
                        # 创建目标目录
                        ensure_dir(os.path.dirname(dst_path))
                        
                        # 复制文件
                        copy_file(src_path, dst_path)
                        print(f"复制 {src_path} 到 {dst_path}")
                        test_count += 1
        
        if test_count == 0:
            print("警告: 未找到任何测试类")
        else:
            print(f"成功复制 {test_count} 个测试类到第一代目录")
            
            # 生成第一代的测试报告
            print("生成第一代测试报告...")
            self._generate_first_generation_reports()
    
    def _generate_first_generation_reports(self):
        """生成第一代的测试报告"""
        try:
            # 获取已复制的测试类名列表
            test_classes = []
            gen1_dir = os.path.join(self.evolution_dir, "Gen1")
            
            for root, _, files in os.walk(gen1_dir):
                for file in files:
                    if file.endswith(".java") and "TestV" in file:
                        test_class_name = file.replace(".java", "")
                        test_classes.append(test_class_name)
            
            if not test_classes:
                print("警告: 未找到任何测试类")
                return
            
            print(f"开始检查和生成 {len(test_classes)} 个测试类的报告...")
            
            # 检查每个测试类是否有完整的报告，如果没有就生成
            for test_class in test_classes:
                if self._check_and_generate_test_reports(test_class, 1):
                    print(f"  ✓ {test_class} 报告完整")
                else:
                    print(f"  ✗ {test_class} 报告生成失败")
            
            print("第一代测试报告检查完成")
            
        except Exception as e:
            print(f"生成第一代测试报告失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _check_and_generate_test_reports(self, test_class: str, generation: int) -> bool:
        """检查测试报告是否完整，如果不完整则生成"""
        # 构建报告目录路径
        test_report_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}", test_class)
        coverage_report_file = os.path.join(test_report_dir, "coverage_report.json")
        jacoco_xml_file = os.path.join(test_report_dir, "jacoco", "jacoco.xml")
        
        # 检查是否已有完整报告
        if (os.path.exists(test_report_dir) and 
            os.path.exists(coverage_report_file) and 
            os.path.exists(jacoco_xml_file)):
            print(f"    {test_class} 报告已存在，跳过生成")
            return True
        
        print(f"    {test_class} 报告不完整，开始生成...")
        
        # 运行测试并生成基础报告
        success = self.test_executor.run_test_and_generate_reports(test_class, generation)
        if not success:
            print(f"    {test_class} Maven测试失败")
            return False
        
        # 生成覆盖率分析报告
        report = self.coverage_analyzer.analyze_test_coverage(test_class, generation, use_cache=True)
        if not report:
            print(f"    {test_class} 覆盖率分析失败")
            return False
        
        print(f"    {test_class} 报告生成成功")
        return True
    
    def organize_test_reports_for_generation(self, gen_num: int):
        """检查test_reports目录结构"""
        if gen_num == 1:
            # 检查Gen1目录是否已存在
            gen1_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, "Gen1")
            if os.path.exists(gen1_reports_dir):
                print(f"第一代测试报告目录已存在: {gen1_reports_dir}")
            else:
                print(f"警告: 第一代测试报告目录不存在: {gen1_reports_dir}")
                print("请先运行 analyze_test_coverage.py 生成测试报告")
    
    def should_terminate(self, current_gen: int, active_target_classes: set) -> bool:
        """判断是否满足全局终止条件"""
        # 检查是否达到最大代数
        if current_gen > MAX_GENERATIONS:
            print(f"已达到最大代数 {MAX_GENERATIONS}，终止演化")
            return True
        
        # 检查是否所有被测类都已完成演化
        if not active_target_classes:
            print("所有被测类都已达到终止条件，终止演化")
            return True
        
        # 全局终止条件不再包含适应度收敛判断，该判断移到单个类的终止条件中
        return False
    
    def group_tests_by_target_class(self, test_reports: Dict[str, Dict]) -> Dict[str, Dict[str, Dict]]:
        """按被测类分组测试
        
        Args:
            test_reports: 测试报告字典
            
        Returns:
            按被测类分组的测试报告字典，格式为 {被测类名: {测试类名: 测试报告}}
        """
        grouped_tests = {}
        
        for test_class, report in test_reports.items():
            # 总是从测试类名推断正确的target_class，不依赖报告中的值
            import re
            
            target_class = self._extract_target_class_from_test_name(test_class)
            
            if target_class not in grouped_tests:
                grouped_tests[target_class] = {}
            
            grouped_tests[target_class][test_class] = report
        
        return grouped_tests
    
    def discover_testv_classes(self) -> List[str]:
        """自动发现所有TestV*模式的测试类"""
        target_classes = []
        
        # 查找maven目录中的测试文件
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        if not os.path.exists(test_src_dir):
            print(f"警告: 测试目录不存在: {test_src_dir}")
            return target_classes
            
        # 收集所有TestV*文件
        testv_files = []
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java") and "TestV" in file:
                    testv_files.append(file.replace(".java", ""))
        
        # 按基础类名分组
        class_groups = {}
        for test_name in testv_files:
            # 提取基础类名（移除TestV和版本号）
            import re
            match = re.match(r'(.+?)TestV\d+$', test_name)
            if match:
                base_class = match.group(1)
                if base_class not in class_groups:
                    class_groups[base_class] = []
                class_groups[base_class].append(test_name)
        
        # 只保留有多个版本的类
        for base_class, tests in class_groups.items():
            if len(tests) > 1:  # 只要有一个以上的版本就算
                target_classes.append(base_class)
        
        # 排序以确保一致性
        target_classes.sort()
        
        return target_classes
    
    def _get_current_maven_tests(self, target_class: str) -> Dict[str, Dict]:
        """从maven目录获取当前的测试文件及其报告"""
        target_tests = {}
        missing_reports = []
        
        # 查找maven目录中的测试文件
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    test_name = file.replace(".java", "")
                    extracted_class = self._extract_target_class_from_test_name(test_name)
                    
                    # 只保留目标类的测试
                    if extracted_class == target_class:
                        # 尝试从各个代数中获取测试报告
                        report = self._find_test_report_for_maven_test(test_name)
                        if report:
                            target_tests[test_name] = report
                        else:
                            missing_reports.append(test_name)
                            print(f"警告: 未找到 {test_name} 的测试报告")
        
        # 如果没有找到任何报告，但有测试文件，尝试生成报告
        if not target_tests and missing_reports:
            print(f"检测到 {target_class} 类有 {len(missing_reports)} 个测试文件但无报告，尝试生成...")
            # 使用一个临时的代数来生成报告，然后重新获取
            temp_gen = self._get_latest_generation() or 1
            if self._generate_missing_test_reports(target_class, temp_gen):
                # 重新获取测试报告
                for test_name in missing_reports:
                    report = self._find_test_report_for_maven_test(test_name)
                    if report:
                        target_tests[test_name] = report
        
        return target_tests
    
    def _get_latest_generation(self) -> Optional[int]:
        """获取最新的代数"""
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        if not os.path.exists(reports_base_dir):
            return None
            
        max_gen = 0
        for item in os.listdir(reports_base_dir):
            if item.startswith("Gen") and os.path.isdir(os.path.join(reports_base_dir, item)):
                try:
                    gen_num = int(item[3:])  # 移除"Gen"前缀
                    max_gen = max(max_gen, gen_num)
                except ValueError:
                    continue
        return max_gen if max_gen > 0 else None
    
    def _generate_missing_test_reports(self, target_class: str, current_gen: int) -> bool:
        """为maven目录中缺少报告的测试文件生成测试报告"""
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        success_count = 0
        total_count = 0
        
        # 查找maven目录中该类的所有测试文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    test_name = file.replace(".java", "")
                    extracted_class = self._extract_target_class_from_test_name(test_name)
                    
                    # 只处理目标类的测试
                    if extracted_class == target_class:
                        total_count += 1
                        
                        # 检查是否已有测试报告
                        existing_report = self._find_test_report_for_maven_test(test_name)
                        if not existing_report:
                            print(f"    为 {test_name} 生成测试报告...")
                            
                            # 使用当前代数运行测试并生成报告
                            try:
                                success = self.test_executor.run_test_and_generate_reports(test_name, current_gen)
                                if success:
                                    # 生成覆盖率分析报告
                                    report = self.coverage_analyzer.analyze_test_coverage(test_name, current_gen, use_cache=False)
                                    if report:
                                        success_count += 1
                                        print(f"      ✓ 成功生成: {test_name}")
                                    else:
                                        print(f"      ✗ 覆盖率分析失败: {test_name}")
                                else:
                                    print(f"      ✗ 测试运行失败: {test_name}")
                            except Exception as e:
                                print(f"      ✗ 生成报告异常: {test_name}, 错误: {e}")
        
        print(f"    完成报告生成: {success_count}/{total_count} 个测试")
        return success_count > 0
    
    def _find_test_report_for_maven_test(self, test_name: str) -> Optional[Dict]:
        """为maven目录中的测试文件查找对应的测试报告"""
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        
        # 从最新的代数开始查找
        for gen in range(30, 0, -1):
            gen_dir = os.path.join(reports_base_dir, f"Gen{gen}")
            if os.path.exists(gen_dir):
                report_dir = os.path.join(gen_dir, test_name)
                report_file = os.path.join(report_dir, "coverage_report.json")
                
                if os.path.exists(report_file):
                    from .utils import load_json
                    return load_json(report_file)
        
        return None
    
    def _get_final_generation_tests(self, target_class: str, current_gen: int) -> Dict[str, Dict]:
        """获取重命名后的最终测试报告（仅包含TestV1-V10）
        
        这个方法确保只包含演化完成后的最终10个测试，排除所有临时的交叉/变异测试
        """
        final_tests = {}
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
        
        if not os.path.exists(reports_dir):
            print(f"警告: Gen{current_gen}报告目录不存在: {reports_dir}")
            return final_tests
        
        # 只查找标准的TestV1-V10格式的测试
        for i in range(1, 11):
            test_name = f"{target_class}TestV{i}"
            report_path = os.path.join(reports_dir, test_name, "coverage_report.json")
            
            if os.path.exists(report_path):
                from .utils import load_json
                report = load_json(report_path)
                if report:
                    final_tests[test_name] = report
                else:
                    print(f"警告: {test_name} 的报告文件损坏")
            else:
                print(f"警告: 未找到 {test_name} 的报告: {report_path}")
        
        print(f"获取到 {target_class} 第{current_gen}代最终测试: {len(final_tests)} 个")
        return final_tests
    
    def _extract_target_class_from_test_name(self, test_class: str) -> str:
        """从测试类名中提取被测类名"""
        return self.unified_manager.extract_target_class_from_test_name(test_class)
    
    def should_terminate_for_target_class(self, target_class: str, test_reports: Dict[str, Dict], current_gen: int) -> bool:
        """判断某个被测类是否满足终止条件
        
        Args:
            target_class: 被测类名
            test_reports: 该被测类的所有测试报告
            current_gen: 当前代数
            
        Returns:
            是否应该终止该被测类的演化
        """
        # 仅检查是否达到最大代数
        if current_gen > MAX_GENERATIONS:
            print(f"被测类 {target_class} 已达到最大迭代次数 ({MAX_GENERATIONS})，终止该被测类的演化")
            return True
        
        return False
    
    def should_converge_for_target_class(self, target_class: str, test_reports: Dict[str, Dict], current_gen: int) -> bool:
        """判断某个被测类是否达到平均适应度收敛条件
        
        此方法已被禁用 - 不再使用收敛条件终止演化
        
        Args:
            target_class: 被测类名
            test_reports: 该被测类的最终测试报告（选择并重命名后的）
            current_gen: 当前代数
            
        Returns:
            始终返回False，不再检查收敛条件
        """
        # 不再使用收敛条件终止演化
        return False

    def _should_terminate_class_evolution(self, target_class: str, test_reports: Dict[str, Dict], current_gen: int) -> bool:
        """判断某个被测类是否达到98%覆盖率终止条件

        Args:
            target_class: 被测类名
            test_reports: 该被测类的所有测试报告
            current_gen: 当前代数

        Returns:
            是否应该终止该被测类的演化（分支覆盖率和方法覆盖率均达到98%）
        """
        if not test_reports:
            return False

        # 检查是否达到最大代数
        if current_gen > MAX_GENERATIONS:
            print(f"被测类 {target_class} 已达到最大迭代次数 ({MAX_GENERATIONS})，终止该被测类的演化")
            return True

        # 检查所有测试的覆盖率是否有任何一个达到98%阈值
        for test_name, report in test_reports.items():
            metrics = report.get("metrics", {})
            branch_coverage = metrics.get("branch_coverage", 0)
            method_coverage = metrics.get("method_coverage", 0)

            # 如果分支覆盖率和方法覆盖率均达到98%，则终止该类的演化
            if branch_coverage >= 98.0 and method_coverage >= 98.0:
                print(f"被测类 {target_class} 达到98%覆盖率终止条件:")
                print(f"  测试: {test_name}")
                print(f"  分支覆盖率: {branch_coverage:.1f}%")
                print(f"  方法覆盖率: {method_coverage:.1f}%")
                return True

        return False
    
    def _copy_previous_generation_reports(self, target_class: str, current_gen: int):
        """复制已终止类的上一代测试报告到当前代
        
        当某个类在之前的代数已经终止优化时，需要将其最后一代的测试报告
        复制到当前代，以确保每代都有完整的所有类的测试报告。
        
        Args:
            target_class: 被测类名
            current_gen: 当前代数
        """
        # 找到该类最后一次有测试报告的代数
        last_gen_with_reports = current_gen - 1
        source_dir = None
        
        # 向前查找最后一个有效的测试报告目录
        for gen in range(last_gen_with_reports, 0, -1):
            potential_source_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen}")
            if os.path.exists(potential_source_dir):
                # 检查是否有该target_class的测试报告
                class_has_reports = False
                for item in os.listdir(potential_source_dir):
                    if target_class in item:
                        class_has_reports = True
                        break
                
                if class_has_reports:
                    source_dir = potential_source_dir
                    last_gen_with_reports = gen
                    break
        
        if not source_dir:
            print(f"警告: 无法找到被测类 {target_class} 的历史测试报告，无法复制")
            return
        
        # 创建当前代的测试报告目录
        current_gen_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
        ensure_dir(current_gen_dir)
        
        # 复制该target_class相关的所有测试报告目录
        import shutil
        copied_count = 0
        
        for item in os.listdir(source_dir):
            if target_class in item:
                source_path = os.path.join(source_dir, item)
                dest_path = os.path.join(current_gen_dir, item)
                
                if os.path.isdir(source_path):
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path)
                    shutil.copytree(source_path, dest_path)
                    copied_count += 1
                elif os.path.isfile(source_path):
                    shutil.copy2(source_path, dest_path)
                    copied_count += 1
        
        print(f"已从Gen{last_gen_with_reports}复制 {copied_count} 个 {target_class} 相关的测试报告到Gen{current_gen}")
    
    def _save_class_states(self):
        """保存所有类的状态到文件"""
        try:
            import json
            with open(self.class_status_file, 'w', encoding='utf-8') as f:
                json.dump(self.class_states, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"警告: 保存类状态失败: {e}")
    
    def _load_class_states(self):
        """从文件加载所有类的状态，并验证与文件系统一致性"""
        if not os.path.exists(self.class_status_file):
            print("状态文件不存在，将基于文件系统创建")
            self._create_initial_class_states()
            return
        
        try:
            import json
            with open(self.class_status_file, 'r', encoding='utf-8') as f:
                json_states = json.load(f)
                print(f"从状态文件加载了 {len(json_states)} 个类的状态")
                
                # 验证JSON状态与文件系统一致性
                validated_states = self._validate_and_correct_class_states(json_states)
                
                self.class_states = validated_states
                
                # 同时恢复适应度历史到运行时变量
                for target_class, state in self.class_states.items():
                    if 'fitness_history' in state:
                        self.class_fitness_history[target_class] = state['fitness_history']
                        
        except Exception as e:
            print(f"警告: 加载类状态失败: {e}")
            print("将基于文件系统重新创建状态")
            self._create_initial_class_states()
    
    def _validate_and_correct_class_states(self, json_states: dict) -> dict:
        """验证JSON状态与文件系统一致性，以文件系统为准进行修正"""
        print("验证JSON状态与文件系统一致性...")
        
        discovered_classes = self.discover_testv_classes()
        corrected_states = {}
        corrections_made = False
        
        for class_name in discovered_classes:
            # 从文件系统检测真实状态
            real_status = self._detect_class_status_from_filesystem(class_name)
            json_status = json_states.get(class_name, {})
            
            # 比较状态一致性
            if self._status_inconsistent(json_status, real_status):
                print(f"  ⚠️ 类 {class_name} 状态不一致:")
                print(f"    JSON: {json_status}")
                print(f"    文件系统: {real_status}")
                print(f"    以文件系统为准进行修正")
                corrected_states[class_name] = real_status
                corrections_made = True
            else:
                print(f"  ✅ 类 {class_name} 状态一致")
                corrected_states[class_name] = json_status if json_status else real_status
        
        # 如果有修正，保存到文件
        if corrections_made:
            print(f"检测到状态不一致，自动修正并保存")
            self.class_states = corrected_states
            self._save_class_states()
        
        return corrected_states
    
    def _detect_class_status_from_filesystem(self, class_name: str) -> dict:
        """从文件系统检测类的真实状态"""
        # 检查maven目录中的测试文件数量
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        test_files = []
        
        if os.path.exists(maven_test_dir):
            for root, dirs, files in os.walk(maven_test_dir):
                for file in files:
                    if file.endswith(".java") and file.startswith(f"{class_name}TestV"):
                        test_files.append(file)
        
        # 检查最新完整代数
        latest_gen = 0
        for gen in range(1, 11):
            evolution_dir = os.path.join(self.evolution_dir, f"Gen{gen}")
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen}")
            
            has_evolution_files = False
            has_reports = False
            
            # 检查evolution_process
            if os.path.exists(evolution_dir):
                for root, dirs, files in os.walk(evolution_dir):
                    for file in files:
                        if file.endswith(".java") and class_name in file:
                            has_evolution_files = True
                            break
                    if has_evolution_files:
                        break
            
            # 检查test_reports
            if os.path.exists(reports_dir):
                for report_dir in os.listdir(reports_dir):
                    if class_name in report_dir:
                        report_path = os.path.join(reports_dir, report_dir, "coverage_report.json")
                        if os.path.exists(report_path):
                            has_reports = True
                            break
            
            if has_evolution_files and has_reports:
                latest_gen = gen
        
        # 判断状态
        if len(test_files) < 2:
            status = "terminated"
            reason = "insufficient_tests"
        elif len(test_files) > 15:  # 超过正常范围，可能有问题
            status = "active"  # 但需要人工检查
            reason = "abnormal_test_count"
        else:
            status = "active"
            reason = None
        
        return {
            "status": status,
            "last_generation": latest_gen,
            "fitness_history": [],
            "termination_reason": reason
        }
    
    def _status_inconsistent(self, json_status: dict, real_status: dict) -> bool:
        """检查JSON状态与真实状态是否不一致"""
        if not json_status:
            return True
        
        # 比较关键字段
        json_terminated = json_status.get("status") == "terminated"
        real_terminated = real_status.get("status") == "terminated"
        
        if json_terminated != real_terminated:
            return True
            
        # 比较代数（允许1代的误差）
        json_gen = json_status.get("last_generation", 0)
        real_gen = real_status.get("last_generation", 0)
        
        if abs(json_gen - real_gen) > 1:
            return True
            
        return False
    
    def _create_initial_class_states(self):
        """基于文件系统创建初始类状态"""
        print("基于文件系统创建初始类状态...")
        discovered_classes = self.discover_testv_classes()
        
        self.class_states = {}
        for class_name in discovered_classes:
            real_status = self._detect_class_status_from_filesystem(class_name)
            self.class_states[class_name] = real_status
            print(f"  {class_name}: {real_status['status']} (Gen{real_status['last_generation']})")
        
        # 保存到文件
        self._save_class_states()
        print(f"已创建 {len(self.class_states)} 个类的初始状态")
    
    def _update_class_state(self, target_class: str, current_gen: int, avg_fitness: float = None, 
                           status: str = "active", termination_reason: str = None):
        """更新单个类的状态"""
        if target_class not in self.class_states:
            self.class_states[target_class] = {
                "status": "active",
                "last_generation": 0,
                "fitness_history": [],
                "termination_reason": None
            }
        
        state = self.class_states[target_class]
        state["last_generation"] = current_gen
        state["status"] = status
        
        if avg_fitness is not None:
            state["fitness_history"].append(avg_fitness)
            
        if termination_reason:
            state["termination_reason"] = termination_reason
            
        # 保存到文件
        self._save_class_states()
    
    def save_best_tests(self, gen_num: int, test_reports: Dict[str, Dict]):
        """保存当前代最优测试（不再保存次优）"""
        # 按适应度值排序
        sorted_tests = sorted(test_reports.items(), key=lambda x: x[1]["fitness"], reverse=True)
        
        if len(sorted_tests) < 1:
            print("警告: 当前代测试数量不足，无法保存最优测试")
            return
        
        # 创建保存目录
        save_dir = os.path.join(self.historical_best_dir, f"Gen{gen_num}")
        ensure_dir(save_dir)
        
        # 只保存最优测试
        best_test_class, best_report = sorted_tests[0]
        test_file = self._find_test_source_file(best_test_class)
        
        if test_file:
            dst_path = os.path.join(save_dir, os.path.basename(test_file))
            copy_file(test_file, dst_path)
            print(f"保存最优测试 {best_test_class} (适应度: {best_report['fitness']:.4f}) 到 {dst_path}")
        else:
            print(f"警告: 未找到测试文件 {best_test_class}")
        
        # 记录最优适应度值
        best_fitness = best_report["fitness"]
        self.historical_fitness.append(best_fitness)
        print(f"当前代最优适应度值: {best_fitness:.4f}")
    
    def _handle_final_optimization(self, target_class: str, final_gen: int):
        """处理最终优化：让用户决定是否进行最后一步的优化"""
        print(f"\n{'='*60}")
        print(f"🎉 演化完成! 被测类: {target_class}")
        print(f"{'='*60}")
        
        # 获取最终一代的所有测试报告
        final_reports = self.diversity_calculator.get_test_reports(final_gen)
        if not final_reports:
            print(f"错误: 无法获取第{final_gen}代测试报告")
            return
        
        # 过滤出目标类的测试
        target_tests = {}
        for test_name, report in final_reports.items():
            extracted_class = self._extract_target_class_from_test_name(test_name)
            if extracted_class == target_class:
                target_tests[test_name] = report
        
        if not target_tests:
            print(f"错误: 没有找到被测类 {target_class} 的测试")
            return
        
        print(f"📊 当前保留 {len(target_tests)} 个测试（V1-V{len(target_tests)}）")
        
        # 检查并补充缺失的覆盖率报告
        print(f"\n🔍 检查测试报告完整性...")
        incomplete_reports = []
        for test_name, report in target_tests.items():
            if not self._is_report_complete(report):
                incomplete_reports.append(test_name)
        
        if incomplete_reports:
            print(f"⚠️  发现 {len(incomplete_reports)} 个测试缺少完整报告")
            for test_name in incomplete_reports:
                print(f"   - {test_name}")
        else:
            print(f"✅ 所有测试报告都完整")
        
        # 显示当前最优测试的情况
        sorted_tests = sorted(target_tests.items(), key=lambda x: x[1]["fitness"], reverse=True)
        best_test_name, best_report = sorted_tests[0]
        
        print(f"\n🏆 当前最优测试: {best_test_name}")
        print(f"   行覆盖率: {best_report['metrics']['line_coverage']:.2f}%")
        print(f"   分支覆盖率: {best_report['metrics']['branch_coverage']:.2f}%")
        print(f"   方法覆盖率: {best_report['metrics']['method_coverage']:.2f}%")
        print(f"   适应度: {best_report['fitness']:.4f}")
        
        # 询问用户是否进行最终优化
        print(f"\n🔍 最终优化可以做什么：")
        print(f"   1. 渐进式选择最少数量的测试组合")
        print(f"   2. 移除冗余的测试（相同覆盖路径）")
        print(f"   3. 将多个测试合并为一个堆叠文件")
        print(f"   4. 最终只保留一个最优化的测试文件")
        
        while True:
            choice = input(f"\n是否进行最终优化？ (y/n): ").strip().lower()
            if choice in ['y', 'yes', '是']:
                self._perform_final_optimization(target_class, final_gen, target_tests)
                break
            elif choice in ['n', 'no', '不']:
                print(f"\n✅ 跳过最终优化，保持当前 {len(target_tests)} 个测试")
                break
            else:
                print(f"请输入 'y' 或 'n'")
    
    def _perform_final_optimization(self, target_class: str, final_gen: int, target_tests: Dict[str, Dict]):
        """执行最终优化"""
        try:
            # 创建智能测试优化器
            optimizer = IntelligentTestOptimizer(
                str(self.base_dir), 
                self.project_name, 
                target_class,
                self.coverage_analyzer  # 传递覆盖率分析器
            )
            
            # 执行智能优化
            success = optimizer.optimize_final_tests(final_gen, target_tests)
            
            if success:
                print(f"\n✅ 智能优化成功完成!")
                print(f"📁 最优化测试文件: {target_class}TestV.java")
                print(f"📂 位置: dataset/{self.project_name}/src/test/java/.../{target_class}TestV.java")
            else:
                print(f"\n❌ 智能优化失败，保持原有测试")
                
        except Exception as e:
            print(f"\n❌ 智能优化失败: {e}")
            print(f"保持原有测试不变")
            import traceback
            traceback.print_exc()
    
    def _is_report_complete(self, report: Dict) -> bool:
        """检查测试报告是否完整"""
        required_fields = ['metrics', 'covered_methods', 'uncovered_methods', 'covered_paths', 'fitness']
        
        for field in required_fields:
            if field not in report:
                return False
        
        # 检查metrics是否有必要的字段
        metrics = report.get('metrics', {})
        required_metrics = ['line_coverage', 'branch_coverage', 'method_coverage']
        
        for metric in required_metrics:
            if metric not in metrics:
                return False
        
        return True
    
    def run_tests_and_generate_reports(self, test_classes: List[str], generation: int = None):
        """运行测试并生成覆盖率报告"""
        print(f"运行 {len(test_classes)} 个测试并生成覆盖率报告...")
        
        for test_class in test_classes:
            print(f"运行测试: {test_class}")
            
            try:
                # 使用集成的 TestExecutor 生成基础测试报告
                success = self.test_executor.run_test_and_generate_reports(test_class, generation)
                
                if success:
                    print(f"成功处理测试 {test_class}")
                else:
                    print(f"测试 {test_class} 处理失败")
                    
            except Exception as e:
                print(f"运行测试 {test_class} 时发生异常: {e}")
    
    
    
    def _run_coverage_analysis(self, generation: int = None):
        """运行覆盖率分析"""
        try:
            # 获取当前世代的所有测试类
            if generation:
                test_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}")
            else:
                test_reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
            
            if not os.path.exists(test_reports_dir):
                print(f"测试报告目录不存在: {test_reports_dir}")
                return
            
            # 处理每个测试类，如果指定了target_class则只处理该类
            for test_class in os.listdir(test_reports_dir):
                test_class_dir = os.path.join(test_reports_dir, test_class)
                if not os.path.isdir(test_class_dir) or test_class.startswith('Gen'):
                    continue
                
                # 如果指定了target_class，只处理该类的测试
                if self.target_class:
                    extracted_target = self._extract_target_class_from_test_name(test_class)
                    if extracted_target != self.target_class:
                        continue
                
                # 分析测试覆盖率
                report = self.coverage_analyzer.analyze_test_coverage(test_class, generation, use_cache=True)
                if report:
                    print(f"成功生成 {test_class} 的覆盖率报告")
                else:
                    print(f"生成 {test_class} 的覆盖率报告失败")
            
            print(f"成功生成覆盖率报告")
        except Exception as e:
            print(f"警告: 覆盖率分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def select_next_generation_by_target_class(self, next_gen: int, target_class: str, current_reports: Dict[str, Dict], new_tests: List[str]):
        """按被测类选择下一代的测试类
        
        Args:
            next_gen: 下一代代数
            target_class: 被测类名
            current_reports: 当前代该被测类的测试报告
            new_tests: 该被测类新生成的测试
        """
        print(f"为被测类 {target_class} 选择第 {next_gen} 代的测试...")
        
        # 收集该被测类的所有测试报告（原始10个 + 新生成的）
        all_reports = {}
        
        # 添加当前代该被测类的测试报告
        all_reports.update(current_reports)
        
        # 添加新生成的测试报告
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        for test_class in new_tests:
            # 先在当前代查找新生成的测试报告
            report_path = os.path.join(reports_base_dir, f"Gen{next_gen-1}", test_class, "coverage_report.json")
            if os.path.exists(report_path):
                report = load_json(report_path)
                if report:
                    all_reports[test_class] = report
        
        # 按适应度值排序
        sorted_tests = sorted(all_reports.items(), key=lambda x: x[1]["fitness"], reverse=True)
        
        # 选择前10个适应度最高的测试
        selected_tests = [pair[0] for pair in sorted_tests[:10]]
        
        print(f"  原始测试数: {len(current_reports)}, 新生成测试数: {len(new_tests)}")
        print(f"  选择前10个测试:")
        
        # 重新命名并复制到项目源码目录和evolution_process目录
        self._rename_and_copy_selected_tests(target_class, selected_tests, all_reports, next_gen)
        
        # 清理淘汰的测试
        all_test_names = list(all_reports.keys())
        eliminated_tests = [test for test in all_test_names if test not in selected_tests]
        if eliminated_tests:
            print(f"  清理 {len(eliminated_tests)} 个淘汰的测试:")
            self._cleanup_eliminated_tests(eliminated_tests, next_gen-1)
        
        # 保存最优测试到historical_best
        if selected_tests:
            best_test = selected_tests[0]
            best_fitness = all_reports[best_test]["fitness"]
            self._save_best_test_to_historical(best_test, next_gen-1, best_fitness)
        
        return selected_tests
    
    def _rename_and_copy_selected_tests(self, target_class: str, selected_tests: List[str], all_reports: Dict[str, Dict], next_gen: int):
        """重新命名选中的测试并复制到相应目录"""
        
        # 查找该被测类的原始测试目录
        target_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        target_package_dir = None
        
        import re
        for root, dirs, files in os.walk(target_test_dir):
            for file in files:
                if file.endswith('.java'):
                    # 检查是否是该被测类的测试
                    file_name = file.replace('.java', '')
                    inferred_target = self._extract_target_class_from_test_name(file_name)
                    
                    if inferred_target == target_class:
                        # 找到了该被测类的测试目录
                        target_package_dir = root
                        break
            if target_package_dir:
                break
        
        if not target_package_dir:
            print(f"警告: 未找到被测类 {target_class} 的测试目录")
            return
        
        # 1. 创建evolution_process目录
        next_gen_dir = os.path.join(self.evolution_dir, f"Gen{next_gen}")
        ensure_dir(next_gen_dir)
        
        # 创建对应的包目录结构
        relative_package_path = os.path.relpath(target_package_dir, target_test_dir)
        evolution_package_dir = os.path.join(next_gen_dir, relative_package_path)
        ensure_dir(evolution_package_dir)
        
        # 2. 重新命名并复制到两个目录
        for i, test_class in enumerate(selected_tests):
            test_file = self._find_test_source_file(test_class)
            fitness = all_reports[test_class]["fitness"]
            
            if test_file:
                # 新文件名：被测类名 + TestV + 序号
                new_file_name = f"{target_class}TestV{i+1}.java"
                new_class_name = f"{target_class}TestV{i+1}"
                
                # 读取源文件内容并修改类名
                with open(test_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 替换类名
                old_class_name = os.path.basename(test_file).replace('.java', '')
                content = content.replace(f"class {old_class_name}", f"class {new_class_name}")
                content = content.replace(f"public class {old_class_name}", f"public class {new_class_name}")
                
                # 复制到evolution_process目录（使用新名字）
                evolution_dst_path = os.path.join(evolution_package_dir, new_file_name)
                with open(evolution_dst_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # 复制到maven项目目录（覆盖原有测试）
                maven_dst_path = os.path.join(target_package_dir, new_file_name)
                with open(maven_dst_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                print(f"    {i+1}. {test_class} → {new_class_name}.java (适应度: {fitness:.4f})")
                print(f"        保存到evolution_process: {evolution_dst_path}")
                print(f"        覆盖到maven目录: {maven_dst_path}")
    
    def _cleanup_eliminated_tests(self, eliminated_tests: List[str], gen_num: int):
        """清理淘汰的测试文件和报告
        
        Args:
            eliminated_tests: 被淘汰的测试名列表
            gen_num: 当前代数
        """
        for test_name in eliminated_tests:
            print(f"    - 删除淘汰测试: {test_name}")
            
            # 1. 删除maven目录中的测试文件（只查找maven目录，避免误删evolution目录文件）
            test_file = self._find_maven_test_file(test_name)
            if test_file and os.path.exists(test_file):
                try:
                    os.remove(test_file)
                    print(f"      删除测试文件: {test_file}")
                except Exception as e:
                    print(f"      删除测试文件失败: {e}")
            else:
                print(f"      未找到测试文件: {test_name}")
            
            # 2. 删除测试报告目录
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}", test_name)
            if os.path.exists(reports_dir):
                try:
                    import shutil
                    shutil.rmtree(reports_dir)
                    print(f"      删除测试报告: {reports_dir}")
                except Exception as e:
                    print(f"      删除测试报告失败: {e}")
    
    def _find_maven_test_file(self, test_name: str) -> Optional[str]:
        """仅在maven目录中查找测试文件（用于清理操作）"""
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file == f"{test_name}.java":
                    return os.path.join(root, file)
        
        return None
    
    def _generate_reports_for_selected_tests(self, target_class: str, num_tests: int, gen_num: int):
        """为重命名后的基础测试生成新的测试报告"""
        print(f"为第{gen_num}代选中的{num_tests}个基础测试生成报告...")
        
        # 构建标准化的测试类名列表
        standard_test_names = []
        for i in range(1, num_tests + 1):
            standard_test_names.append(f"{target_class}TestV{i}")
        
        try:
            # 使用test_executor为这些测试生成报告
            self.test_executor.run_tests_and_generate_reports(standard_test_names, gen_num)
            print(f"成功为{len(standard_test_names)}个基础测试生成报告")
        except Exception as e:
            print(f"生成基础测试报告失败: {e}")
    
    def _save_best_test_to_historical(self, best_test: str, gen_num: int, fitness: float):
        """保存最优测试到historical_best目录 - 只保存在根目录"""
        save_dir = os.path.join(self.historical_best_dir, f"Gen{gen_num}")
        ensure_dir(save_dir)
        
        # 优先从maven目录查找已重命名的文件
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 查找包路径
        target_class = best_test.replace("TestV1", "").replace("Test", "")
        package_path = self._find_target_package_path(target_class)
        
        if package_path is not None:
            maven_package_dir = os.path.join(maven_test_dir, package_path.replace(".", os.sep))
            maven_file_path = os.path.join(maven_package_dir, f"{best_test}.java")
            
            if os.path.exists(maven_file_path):
                # 只保存在根目录，不使用包目录结构
                dst_path = os.path.join(save_dir, f"{best_test}.java")
                copy_file(maven_file_path, dst_path)
                print(f"保存最优测试 {best_test} (适应度: {fitness:.4f}) 到历史记录: {dst_path}")
                return
        
        # 如果maven目录找不到，尝试原来的查找方式
        test_file = self._find_test_source_file(best_test)
        if test_file:
            # 只保存在根目录，不使用包目录结构
            dst_path = os.path.join(save_dir, f"{best_test}.java")
            copy_file(test_file, dst_path)
            print(f"保存最优测试 {best_test} (适应度: {fitness:.4f}) 到历史记录: {dst_path}")
        else:
            print(f"警告: 未找到最优测试文件 {best_test}")
    
    def select_next_generation(self, next_gen: int, current_reports: Dict[str, Dict], new_tests: List[str]):
        """选择下一代的测试类 - 按被测类分别处理"""
        print(f"\n======== 选择第 {next_gen} 代测试 ========")
        
        # 按被测类分组处理
        grouped_current = self.group_tests_by_target_class(current_reports)
        grouped_new = {}
        
        # 将新测试按被测类分组
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        for test_class in new_tests:
            report_path = os.path.join(reports_base_dir, f"Gen{next_gen-1}", test_class, "coverage_report.json")
            if os.path.exists(report_path):
                report = load_json(report_path)
                if report:
                    # 推断被测类 - 修复版本：使用现有的提取函数
                    target_class = self._extract_target_class_from_test_name(test_class)
                    
                    if target_class not in grouped_new:
                        grouped_new[target_class] = {}
                    grouped_new[target_class][test_class] = report
        
        # 获取所有需要处理的被测类（当前代 + 新生成的）
        all_target_classes = set(grouped_current.keys()) | set(grouped_new.keys())
        
        # 对每个被测类分别选择下一代
        for target_class in all_target_classes:
            current_tests = grouped_current.get(target_class, {})
            new_tests_for_class = grouped_new.get(target_class, {})
            
            # 合并新旧测试名称列表
            new_test_names = list(new_tests_for_class.keys())
            
            # 只有当有测试数据时才进行选择
            if current_tests or new_tests_for_class:
                self.select_next_generation_by_target_class(
                    next_gen, target_class, current_tests, new_test_names
                )
            else:
                print(f"警告: 被测类 {target_class} 没有任何测试数据，跳过处理")
    
    def detect_generation_progress(self, gen_num: int) -> Dict:
        """检测当前代的完成状态
        
        Args:
            gen_num: 当前代数
            
        Returns:
            包含续传信息的字典
        """
        result = {
            'should_resume': False,
            'next_step': '',
            'existing_tests': []
        }
        
        # 查找现有的交叉和变异测试
        existing_tests = []
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    class_name = file.replace(".java", "")
                    # 检查是否是当前代的交叉或变异测试（或上一代的）
                    prev_gen = gen_num - 1
                    if (f"_Crossover_Gen{gen_num}_" in class_name or 
                        f"_Mutation_Gen{gen_num}_" in class_name or
                        f"_Crossover_Gen{prev_gen}_" in class_name or 
                        f"_Mutation_Gen{prev_gen}_" in class_name):
                        # 如果指定了target_class，只处理相关的测试
                        if self.target_class:
                            if self.target_class in class_name:
                                existing_tests.append(class_name)
                        else:
                            existing_tests.append(class_name)
        
        if not existing_tests:
            # 没有现有测试，正常开始演化
            return result
        
        # 检查是否已有测试报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
        existing_reports = []
        
        if os.path.exists(reports_dir):
            for test_class in existing_tests:
                report_path = os.path.join(reports_dir, test_class, "coverage_report.json")
                if os.path.exists(report_path):
                    existing_reports.append(test_class)
        
        result['existing_tests'] = existing_tests
        result['should_resume'] = True
        
        if len(existing_reports) == len(existing_tests):
            # 所有测试都有报告，检查是否需要执行交叉后变异
            crossover_tests = [t for t in existing_tests if "_Crossover_Gen" in t]
            mutation_tests = [t for t in existing_tests if "_Mutation_Gen" in t and "Crossover" not in t]
            
            print(f"检测到 {len(crossover_tests)} 个交叉测试: {crossover_tests}")
            print(f"检测到 {len(mutation_tests)} 个变异测试: {mutation_tests}")
            
            # 计算所有被测类应该生成的交叉对数量
            expected_crossover_pairs = self._calculate_total_expected_crossover_pairs(gen_num - 1)
            
            # 通过解析现有交叉测试名称来确定已完成的交叉对数量
            completed_pairs = self._count_completed_crossover_pairs(crossover_tests, gen_num - 1)
            
            print(f"预期交叉对数量: {expected_crossover_pairs}, 已完成交叉对数量: {completed_pairs}")
            print(f"实际交叉测试数量: {len(crossover_tests)}")
            
            if crossover_tests and completed_pairs >= expected_crossover_pairs:
                # 交叉测试完整且有报告，需要执行交叉后变异步骤
                result['next_step'] = 'crossover_mutation_step'
                result['crossover_tests'] = crossover_tests
            elif crossover_tests and completed_pairs < expected_crossover_pairs:
                # 交叉对不完整，需要继续交叉操作
                print(f"交叉操作未完成（已完成{completed_pairs}/{expected_crossover_pairs}个交叉对），需要继续执行交叉")
                result['next_step'] = 'continue_crossover'
                result['existing_crossover_tests'] = crossover_tests
            else:
                # 没有交叉测试，直接进行代际选择
                result['next_step'] = 'select_next_generation'
        else:
            # 有测试但缺少报告，需要运行测试
            result['next_step'] = 'run_existing_tests'
        
        return result

    def _scan_existing_crossover_tests(self, current_gen: int) -> List[str]:
        """重新扫描所有实际存在的交叉测试文件"""
        crossover_tests = []
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")

        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    class_name = file.replace(".java", "")
                    # 检查是否是当前代的交叉测试
                    if f"_Crossover_Gen{current_gen}_" in class_name:
                        # 如果指定了target_class，只处理相关的测试（精确匹配）
                        if self.target_class:
                            if class_name.startswith(f"{self.target_class}Test_Crossover_"):
                                crossover_tests.append(class_name)
                        else:
                            crossover_tests.append(class_name)

        return crossover_tests

    def handle_continue_crossover(self, current_gen: int, existing_crossover_tests: list):
        """处理未完成的交叉操作续传"""
        print(f"继续第{current_gen}代的交叉操作...")
        print(f"传入的交叉测试: {existing_crossover_tests}")

        # 重新扫描所有实际存在的交叉文件，确保信息最新
        actual_existing_crossover_tests = self._scan_existing_crossover_tests(current_gen)
        print(f"实际扫描到的交叉测试: {actual_existing_crossover_tests}")

        # 使用实际扫描结果而不是传入参数
        existing_crossover_tests = actual_existing_crossover_tests
        
        # 获取上一代的基础测试报告，按被测类分组
        base_gen = current_gen - 1 if current_gen > 1 else 1
        base_reports = self.diversity_calculator.get_test_reports(base_gen)
        
        if not base_reports:
            print(f"错误: 无法找到第{base_gen}代的基础测试报告")
            return
        
        # 按被测类分组处理交叉操作
        grouped_tests = self.group_tests_by_target_class(base_reports)
        
        print(f"需要处理 {len(grouped_tests)} 个被测类的交叉操作:")
        for target_class in grouped_tests.keys():
            print(f"  - {target_class}")
        
        all_new_tests = []
        
        # 对每个被测类分别处理交叉操作
        for target_class, target_tests in grouped_tests.items():
            print(f"\n--- 检查被测类 {target_class} 的交叉状态 ---")
            
            # 过滤出该被测类的现有交叉测试（精确匹配以避免误匹配）
            class_existing_crossover = [t for t in existing_crossover_tests
                                       if t.startswith(f"{target_class}Test_Crossover_")]
            
            print(f"该被测类已有 {len(class_existing_crossover)} 个交叉测试: {class_existing_crossover}")
            
            # 检查该被测类是否已经完成当前代的演化
            # 如果该被测类没有交叉测试，可能是因为：
            # 1. 还没开始交叉（需要生成）
            # 2. 当前代已经完成，在等其他类完成（不需要生成）
            if len(class_existing_crossover) == 0:
                # 检查该被测类是否已经真正完成当前代演化（仅基于evolution_process中的最终TestV*文件）
                current_gen_tests = self._get_current_generation_tests_for_class(target_class, current_gen)
                if current_gen_tests and len(current_gen_tests) >= TESTS_PER_GENERATION:
                    print(f"被测类 {target_class} 的第{current_gen}代evolution_process中已有最终文件，等待其他类完成")
                    continue
                else:
                    print(f"被测类 {target_class} 的第{current_gen}代evolution_process中无最终文件，需要开始交叉操作（支持断点续传）")
            
            # 计算该被测类应该生成的交叉对数量
            test_count = len(target_tests)
            if test_count >= TESTS_PER_GENERATION:
                expected_pairs = 5  # 标准情况下生成5个交叉对
            else:
                expected_pairs = min(test_count // 2, 3)  # 测试数量不足时的降级策略
            
            # 计算已完成的交叉对数量（只计算该被测类的）
            completed_pairs = self._count_completed_crossover_pairs_for_class(class_existing_crossover, target_class, list(target_tests.keys()))
            
            print(f"被测类 {target_class}: 预期 {expected_pairs} 个交叉对, 已完成 {completed_pairs} 个")
            
            if completed_pairs < expected_pairs:
                remaining_needed = expected_pairs - completed_pairs
                print(f"需要继续生成 {remaining_needed} 个交叉对")
                
                # 生成剩余需要的交叉对
                remaining_pairs = self._generate_missing_crossover_pairs(target_class, class_existing_crossover, target_tests, remaining_needed)
                
                print(f"剩余需要执行的交叉对:")
                for i, (test1, test2) in enumerate(remaining_pairs):
                    print(f"  交叉对 {i+1}: {test1} × {test2}")
                
                if remaining_pairs:
                    # 执行剩余的交叉操作
                    new_crossover_tests = self.crossover_operator.perform_crossover(
                        remaining_pairs, current_gen, base_gen
                    )
                    all_new_tests.extend(new_crossover_tests)
                    print(f"为 {target_class} 新生成 {len(new_crossover_tests)} 个交叉测试")
            else:
                print(f"被测类 {target_class} 的交叉操作已完成")
        
        # 后续处理：运行测试、生成报告、变异判断等
        if all_new_tests:
            print(f"\n=== 继续交叉操作完成 ===")
            print(f"总共生成了 {len(all_new_tests)} 个新的交叉测试")
            
            # 将已存在的交叉测试也加入到全部测试中
            all_tests_to_process = list(set(all_new_tests + existing_crossover_tests))
            
            # 运行测试并生成报告
            self.run_tests_and_generate_reports(all_tests_to_process, current_gen)
            
            # 生成覆盖率分析报告
            self._run_coverage_analysis(current_gen)
            
            # 执行交叉后变异步骤
            self.handle_crossover_mutation_resume(current_gen, all_tests_to_process)
        else:
            print("没有新的交叉测试生成，转入交叉后变异步骤")
            self.handle_crossover_mutation_resume(current_gen, existing_crossover_tests)
    
    def _continue_after_crossover(self, current_gen: int, crossover_tests: list, base_tests: list):
        """在交叉操作完成后继续执行后续流程"""
        print(f"\n=== 继续第{current_gen}代演化流程 ===")
        
        all_new_tests = crossover_tests.copy()
        
        # 获取目标测试数据
        target_tests = {}
        for test_name in base_tests:
            # 构建测试数据结构（这里简化处理，实际可能需要更复杂的数据）
            target_tests[test_name] = {}
        
        # 6. 对当前maven目录中的基础测试最优个体进行精英变异
        print(f"\n=== 精英变异 ===")
        # 获取当前maven目录中基础测试(TestV1-TestV10)的覆盖率报告
        current_maven_reports = self._get_current_maven_test_reports(target_class)
        if current_maven_reports:
            best_test = self.diversity_calculator.get_best_test(current_maven_reports)
            if best_test:
                print(f"对当前maven目录最优基础测试 {best_test} 进行精英变异...")
                # 精英变异使用当前代数，不需要指定源代数（直接从maven目录获取测试文件）
                mutated_elite = self.mutation_operator.perform_mutation_on_best(
                    best_test, current_gen, source_gen=None
                )
                if mutated_elite:
                    all_new_tests.append(mutated_elite)
                    print(f"生成精英变异测试: {mutated_elite}")
                else:
                    print(f"精英变异失败")
            else:
                print(f"未找到当前maven目录最优测试")
        else:
            print(f"未找到当前maven目录中 {target_class} 类的基础测试报告")
        
        # 7. 运行新生成的测试并生成覆盖率报告
        print(f"\n=== 运行新生成的测试 ===")
        for test_class in all_new_tests:
            should_run = (test_class not in crossover_tests or not self._has_test_report(test_class, current_gen) or self.force_overwrite)

            if should_run:
                if self.force_overwrite and self._has_test_report(test_class, current_gen):
                    print(f"强制重新运行测试（覆盖现有报告）: {test_class}")
                else:
                    print(f"运行测试: {test_class}")

                success = self.test_executor.run_test_and_generate_reports(test_class, current_gen)
                if success:
                    # 生成覆盖率分析报告
                    report = self.coverage_analyzer.analyze_test_coverage(test_class, current_gen, use_cache=False)
                    if report:
                        print(f"  ✓ 测试运行成功: {test_class}")
                    else:
                        print(f"  ✗ 覆盖率分析失败: {test_class}")
                else:
                    print(f"  ✗ 测试运行失败: {test_class}")
            else:
                print(f"跳过已有报告的测试: {test_class}")
        
        print(f"完成运行{len(all_new_tests)}个测试")
        
        # 9. 交叉后变异 (关键步骤)
        print(f"\n=== 交叉后变异 ===")
        crossover_only_tests = [t for t in crossover_tests if "_Crossover_" in t]
        crossover_mutated_tests = self._perform_crossover_mutation(crossover_only_tests, current_gen)
        if crossover_mutated_tests:
            all_new_tests.extend(crossover_mutated_tests)
            print(f"生成{len(crossover_mutated_tests)}个交叉后变异测试")
        else:
            print("所有交叉测试都不需要变异")
        
        # 10. 选择下一代测试 (核心步骤)
        print(f"\n=== 选择当代最优测试 ===")
        target_class = self._extract_target_class_from_tests(base_tests)
        if target_class:
            success = self.generation_manager.select_and_rename_next_generation(target_class, current_gen, self.diversity_calculator)
            if success:
                print(f"第{current_gen}代演化完成")
            else:
                print(f"第{current_gen}代选择下一代失败")
        else:
            print("无法确定目标类，跳过下一代选择")
    
    def _get_current_maven_test_reports(self, target_class: str) -> Dict[str, Dict]:
        """获取当前maven目录中基础测试(TestV1-TestV10)的覆盖率报告"""
        current_maven_reports = {}
        
        # 找到当前maven目录中所有基础测试
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 递归查找TestV1-TestV10格式的测试文件
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java"):
                    # 匹配TestV1-TestV10格式，严格过滤掉crossover和mutation测试
                    import re
                    match = re.match(rf'{re.escape(target_class)}TestV(\d+)\.java', file)
                    if match:
                        test_class = file[:-5]  # 移除.java后缀
                        
                        # 额外保障：确保不是crossover或mutation测试
                        if "_Crossover_Gen" in test_class or "_Mutation_Gen" in test_class:
                            print(f"跳过错误识别的crossover/mutation测试: {test_class}")
                            continue
                        
                        # 尝试从不同代数的报告中找到这个测试的最新报告
                        report_found = False
                        for gen in range(10, 0, -1):  # 从高代数往低代数查找
                            report_path = os.path.join(
                                self.base_dir, "test_reports", self.project_name, 
                                f"Gen{gen}", test_class, "coverage_report.json"
                            )
                            if os.path.exists(report_path):
                                report = load_json(report_path)
                                if report and 'fitness' in report:
                                    current_maven_reports[test_class] = report
                                    report_found = True
                                    break
                        
                        if not report_found:
                            print(f"    警告: 未找到 {test_class} 的有效覆盖率报告")
        
        return current_maven_reports
    
    def _has_test_report(self, test_class: str, generation: int) -> bool:
        """检查测试是否已有报告"""
        report_path = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}", test_class, "coverage_report.json")
        return os.path.exists(report_path)
    
    def _extract_target_class_from_tests(self, base_tests: list) -> str:
        """从基础测试名称中提取目标类名"""
        if not base_tests:
            return ""
        
        # 从测试名称中提取类名，例如 "TargetClassTestV1" -> "TargetClass"
        test_name = base_tests[0]
        if "TestV" in test_name:
            return test_name.split("TestV")[0]
        return ""
    
    def _calculate_expected_crossover_count(self, prev_gen: int) -> int:
        """计算应该生成的交叉测试数量（保持向后兼容）"""
        return self._calculate_expected_crossover_pairs(prev_gen)
    
    def _calculate_expected_crossover_pairs(self, prev_gen: int) -> int:
        """计算应该生成的交叉对数量"""
        # 获取上一代的基础测试数量
        prev_gen_tests = self._get_generation_tests(prev_gen)
        base_test_count = len(prev_gen_tests)
        
        # 使用与原始逻辑相同的计算方式
        if base_test_count >= TESTS_PER_GENERATION:
            return 5  # 标准情况下生成5个交叉对
        else:
            return min(base_test_count // 2, 3)  # 测试数量不足时的降级策略
    
    def _calculate_total_expected_crossover_pairs(self, prev_gen: int) -> int:
        """计算所有需要继续交叉操作的被测类应该生成的交叉对总数量"""
        # 获取上一代的测试报告
        prev_reports = self.diversity_calculator.get_test_reports(prev_gen)
        if not prev_reports:
            return 0
        
        # 按被测类分组
        grouped_tests = self.group_tests_by_target_class(prev_reports)
        
        total_pairs = 0
        current_gen = prev_gen + 1  # 当前要生成交叉测试的代数
        
        for target_class, tests in grouped_tests.items():
            # 检查该被测类是否已经真正完成了当前代的演化（仅基于evolution_process中的最终TestV*文件）
            current_gen_tests = self._get_current_generation_tests_for_class(target_class, current_gen)
            if current_gen_tests and len(current_gen_tests) >= TESTS_PER_GENERATION:
                print(f"被测类 {target_class}: 第{current_gen}代已在evolution_process中完成({len(current_gen_tests)}个最终测试) -> 跳过交叉")
                continue

            # 即使存在变异个体等中间文件，只要evolution_process中没有最终文件，就需要进行交叉
            print(f"被测类 {target_class}: 第{current_gen}代evolution_process中无最终文件，需要进行交叉操作")

            # 每个被测类单独计算交叉对数量
            test_count = len(tests)
            if test_count >= TESTS_PER_GENERATION:
                pairs_for_class = 5  # 标准情况下每个类生成5个交叉对
            else:
                pairs_for_class = min(test_count // 2, 3)  # 测试数量不足时的降级策略

            total_pairs += pairs_for_class
            print(f"被测类 {target_class}: {test_count} 个测试 -> {pairs_for_class} 个交叉对")
        
        print(f"总共应生成 {total_pairs} 个交叉对")
        return total_pairs
    
    def _count_completed_crossover_pairs_for_class(self, crossover_tests: List[str], target_class: str, class_test_list: List[str]) -> int:
        """计算特定被测类已完成的交叉对数量"""
        completed_pairs = set()
        
        for test_name in crossover_tests:
            # 解析交叉测试名称，提取交叉对索引
            # 例如：TargetClassTestV5_Crossover_Gen3_4x8 -> (4, 8)
            match = re.search(r'_Crossover_Gen\d+_(\d+)x(\d+)', test_name)
            if match:
                test1_idx = int(match.group(1))
                test2_idx = int(match.group(2))
                # 将交叉对标准化（小索引在前）
                pair = tuple(sorted([test1_idx, test2_idx]))
                completed_pairs.add(pair)
        
        return len(completed_pairs)
    
    def _get_completed_pair_indices_for_class(self, crossover_tests: List[str], all_pairs: List[tuple], class_test_list: List[str]) -> set:
        """获取特定被测类已完成的交叉对索引"""
        completed_pair_indices = set()
        
        for test_name in crossover_tests:
            # 解析交叉测试名称，提取交叉对索引
            match = re.search(r'_Crossover_Gen\d+_(\d+)x(\d+)', test_name)
            if match:
                test1_idx = int(match.group(1)) - 1  # 转换为0基础索引
                test2_idx = int(match.group(2)) - 1
                
                # 在all_pairs中查找匹配的交叉对
                for pair_idx, (t1, t2) in enumerate(all_pairs):
                    try:
                        if ((class_test_list.index(t1) == test1_idx and class_test_list.index(t2) == test2_idx) or
                            (class_test_list.index(t1) == test2_idx and class_test_list.index(t2) == test1_idx)):
                            completed_pair_indices.add(pair_idx)
                            break
                    except ValueError:
                        # 如果测试不在class_test_list中，跳过
                        continue
        
        return completed_pair_indices
    
    def _get_generation_tests(self, gen_num: int) -> List[str]:
        """获取指定代数的测试名称列表"""
        gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        if not os.path.exists(gen_dir):
            return []
        
        tests = []
        for file in os.listdir(gen_dir):
            if file.endswith('.java'):
                test_name = file[:-5]  # 去掉.java扩展名
                tests.append(test_name)
        
        return tests
    
    def _get_current_generation_tests_for_class(self, target_class: str, generation: int) -> List[str]:
        """获取指定被测类在指定代数的最终TestV*测试列表（仅检查evolution_process）

        单个类该代完成的标志是evolution_process内存在这个类的基础测试版本TestV*

        Args:
            target_class: 被测类名
            generation: 代数

        Returns:
            该被测类在指定代数的TestV*测试列表
        """
        current_tests = []

        # 只查找evolution_process目录中的最终TestV*文件（递归查找）
        # 这些是经过选择和重命名后的最终文件，代表该代演化真正完成
        gen_dir = os.path.join(self.evolution_dir, f"Gen{generation}")
        if os.path.exists(gen_dir):
            import re
            # 递归遍历所有子目录
            for root, dirs, files in os.walk(gen_dir):
                for file in files:
                    if file.endswith('.java'):
                        # 只匹配最终的TestV*格式，排除交叉(_Crossover_)和变异(_Mutation_)的中间文件
                        if re.match(rf'^{target_class}TestV\d+\.java$', file):
                            test_name = file[:-5]  # 去掉.java扩展名
                            current_tests.append(test_name)

        print(f"被测类 {target_class} 第{generation}代: evolution_process中找到 {len(current_tests)} 个最终TestV*文件（演化完成标志）")
        return current_tests
    
    def _count_completed_crossover_pairs(self, crossover_tests: List[str], prev_gen: int) -> int:
        """统计需要继续交叉操作的被测类的已完成交叉对数量"""            
        # 获取上一代的测试报告
        prev_reports = self.diversity_calculator.get_test_reports(prev_gen)
        if not prev_reports:
            return 0
        
        # 按被测类分组
        grouped_tests = self.group_tests_by_target_class(prev_reports)
        
        total_completed_pairs = 0
        current_gen = prev_gen + 1  # 当前要生成交叉测试的代数
        
        for target_class in grouped_tests.keys():
            # 检查该被测类是否已经完成了当前代的演化
            current_gen_tests = self._get_current_generation_tests_for_class(target_class, current_gen)
            if current_gen_tests and len(current_gen_tests) >= TESTS_PER_GENERATION:
                print(f"跳过已完成演化的被测类 {target_class} 的交叉对计数")
                continue
            
            # 过滤出该被测类的交叉测试
            class_crossover_tests = [t for t in crossover_tests if target_class in t]
            
            # 解析该被测类的已完成交叉对
            completed_pairs = set()
            for test_name in class_crossover_tests:
                # 解析交叉测试名称，提取交叉对索引
                match = re.search(r'_Crossover_Gen\d+_(\d+)x(\d+)', test_name)
                if match:
                    test1_idx = int(match.group(1))
                    test2_idx = int(match.group(2))
                    # 将交叉对标准化（小索引在前）
                    pair = tuple(sorted([test1_idx, test2_idx]))
                    completed_pairs.add(pair)
            
            class_completed_count = len(completed_pairs)
            total_completed_pairs += class_completed_count
            if class_completed_count > 0:
                print(f"被测类 {target_class}: 已完成 {class_completed_count} 个交叉对")
        
        return total_completed_pairs
    
    def _generate_missing_crossover_pairs(self, target_class: str, existing_crossover_tests: List[str], target_tests: Dict, needed_count: int) -> List[Tuple[str, str]]:
        """基于差异度生成缺失的交叉对，确保每个测试最多参与一次交叉"""
        # 解析已有的交叉对，统计已使用的测试
        existing_pairs = set()
        used_test_indices = set()
        
        print(f"分析已有的交叉测试:")
        for test_name in existing_crossover_tests:
            match = re.search(r'_Crossover_Gen\d+_(\d+)x(\d+)', test_name)
            if match:
                idx1 = int(match.group(1))
                idx2 = int(match.group(2))
                pair = tuple(sorted([idx1, idx2]))
                existing_pairs.add(pair)
                used_test_indices.add(idx1)
                used_test_indices.add(idx2)
                print(f"  {test_name} -> 使用测试 {idx1} 和 {idx2}")
        
        print(f"已使用的测试索引: {sorted(used_test_indices)}")
        
        # 获取未使用的测试
        test_list = list(target_tests.keys())
        test_count = len(test_list)
        all_indices = set(range(1, test_count + 1))
        available_indices = all_indices - used_test_indices
        
        print(f"可用的测试索引: {sorted(available_indices)}")
        
        # 使用差异度计算选择最优的交叉对
        new_pairs = []
        
        if len(available_indices) >= 2 * needed_count:
            # 只从未使用的测试中选择交叉对
            available_tests = {}
            for idx in available_indices:
                test_name = f"{target_class}TestV{idx}"
                if test_name in target_tests:
                    available_tests[test_name] = target_tests[test_name]
            
            if len(available_tests) >= 2:
                # 使用差异度计算选择交叉对
                selected_pairs = self.diversity_calculator.select_diverse_pairs(available_tests, needed_count)
                new_pairs = selected_pairs
                print(f"基于差异度从未使用测试中选择:")
                for i, (test1, test2) in enumerate(selected_pairs):
                    print(f"  选择对 {i+1}: {test1} × {test2}")
        
        # 如果没有足够的未使用测试，则允许重复使用但避免完全相同的对
        if len(new_pairs) < needed_count:
            print(f"可用未使用测试不足，从所有测试中选择剩余 {needed_count - len(new_pairs)} 对")
            # 重新计算所有可能的交叉对，排除已存在的
            remaining_needed = needed_count - len(new_pairs)
            all_possible_pairs = self.diversity_calculator.select_diverse_pairs(target_tests, remaining_needed + len(existing_pairs))
            
            for pair in all_possible_pairs:
                if len(new_pairs) >= needed_count:
                    break
                # 检查是否为新的交叉对
                test1_match = re.search(r'TestV(\d+)$', pair[0])
                test2_match = re.search(r'TestV(\d+)$', pair[1])
                if test1_match and test2_match:
                    idx1 = int(test1_match.group(1))
                    idx2 = int(test2_match.group(1))
                    pair_indices = tuple(sorted([idx1, idx2]))
                    if pair_indices not in existing_pairs:
                        new_pairs.append(pair)
                        existing_pairs.add(pair_indices)
                        print(f"  补充选择: {pair[0]} × {pair[1]} (索引: {pair_indices})")
        
        return new_pairs
    
    def handle_generation_selection_resume(self, current_gen: int):
        """处理已有完整报告的代际选择续传"""
        print(f"第{current_gen}代所有测试报告已存在，直接进行代际选择...")
        
        # 获取当前代的所有测试报告
        current_reports = self.diversity_calculator.get_test_reports(current_gen)
        if not current_reports:
            print(f"错误: 无法获取第{current_gen}代测试报告")
            return
        
        # 获取所有新生成的测试名称（交叉和变异测试）
        all_new_tests = []
        for test_name in current_reports.keys():
            if (f"_Crossover_Gen{current_gen}_" in test_name or 
                f"_Mutation_Gen{current_gen}_" in test_name):
                all_new_tests.append(test_name)
        
        # 执行代际选择
        self.select_next_generation(current_gen + 1, current_reports, all_new_tests)
        
        # 继续下一代演化
        self.continue_evolution_from_generation(current_gen + 1)
    
    def handle_existing_tests_resume(self, current_gen: int, existing_tests: List[str]):
        """处理现有测试但缺少报告的续传"""
        print(f"发现 {len(existing_tests)} 个现有测试，开始生成缺失的报告...")
        
        # 运行测试并生成报告
        self.run_tests_and_generate_reports(existing_tests, current_gen)
        
        # 生成覆盖率分析报告
        print(f"生成覆盖率分析报告...")
        self._run_coverage_analysis(current_gen)
        
        # 验证报告是否生成成功
        reports = self.diversity_calculator.get_test_reports(current_gen)
        print(f"验证报告生成: 找到 {len(reports)} 个测试报告")
        
        # 检查是否有交叉测试，并验证交叉操作是否完成
        crossover_tests = [t for t in existing_tests if "_Crossover_Gen" in t]
        if crossover_tests:
            # 计算应该生成的交叉对数量（使用基于报告的计算方法）
            expected_crossover_pairs = self._calculate_total_expected_crossover_pairs(current_gen - 1 if current_gen > 1 else 1)
            # 通过解析现有交叉测试名称来确定已完成的交叉对数量
            completed_pairs = self._count_completed_crossover_pairs(crossover_tests, current_gen - 1 if current_gen > 1 else 1)
            
            print(f"检测到 {len(crossover_tests)} 个交叉测试")
            print(f"预期交叉对数量: {expected_crossover_pairs}, 已完成交叉对数量: {completed_pairs}")
            
            if completed_pairs >= expected_crossover_pairs:
                # 交叉操作已完成，转入交叉后变异步骤
                print(f"交叉操作已完成，转入交叉后变异步骤...")
                self.handle_crossover_mutation_resume(current_gen, crossover_tests)
            else:
                # 交叉对不完整，需要继续交叉操作
                print(f"交叉操作未完成（已完成{completed_pairs}/{expected_crossover_pairs}个交叉对），需要继续执行交叉")
                self.handle_continue_crossover(current_gen, crossover_tests)
        else:
            # 继续代际选择
            self.handle_generation_selection_resume(current_gen)
    
    def handle_crossover_mutation_resume(self, current_gen: int, crossover_tests: List[str]):
        """处理交叉后变异步骤的续传
        
        这是用户要求的情况：
        1. 已有交叉测试和报告
        2. 根据报告计算变异率并决定是否变异
        3. 执行变异（如需要）
        4. 选择前10个最优测试
        """
        print(f"发现 {len(crossover_tests)} 个交叉测试，开始执行交叉后变异步骤...")
        
        try:
            all_new_tests = list(crossover_tests)  # 复制列表
            
            # 1. 对交叉测试进行变异判断
            print(f"\n=== 交叉后变异 ===")
            crossover_mutated = self._perform_crossover_mutation(crossover_tests, current_gen)
            if crossover_mutated:
                all_new_tests.extend(crossover_mutated)
                print(f"生成{len(crossover_mutated)}个交叉后变异测试")
            else:
                print(f"所有交叉测试都不需要变异")
            
            # 2. 执行精英变异（断点续传支持，与主流程一致）
            print(f"\n=== 检查精英变异（断点续传支持）===")
            # 检查是否已有精英变异测试 - 扫描Maven目录而不只是依赖test_reports
            existing_elite_mutation = []
            maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
            if os.path.exists(maven_test_dir):
                for root, dirs, files in os.walk(maven_test_dir):
                    for file in files:
                        # 查找精英变异文件（不包含交叉变异）
                        if f"_Mutation_Gen{current_gen}_" in file and "Crossover" not in file and file.endswith('.java'):
                            test_name = file.replace('.java', '')
                            existing_elite_mutation.append(test_name)

            if existing_elite_mutation:
                print(f"💾 检测到已存在的精英变异测试: {existing_elite_mutation}")
                print(f"这些变异个体将被保留并参与最终选择")
                all_new_tests.extend(existing_elite_mutation)
            
            if not existing_elite_mutation:
                # 从交叉测试中推断当前正在演化的目标类
                target_class = None
                if crossover_tests:
                    target_class = self._extract_target_class_from_test_name(crossover_tests[0])
                    print(f"从交叉测试推断目标类: {target_class}")
                
                if target_class:
                    # 检查当前目标类是否已经完成演化
                    if self._is_class_completed_in_generation(target_class, current_gen):
                        print(f"目标类 {target_class} 第{current_gen}代已完成演化，跳过精英变异")
                    else:
                        # 对当前maven目录中的基础测试最优个体进行精英变异
                        print(f"对 {target_class} 类执行精英变异...")
                        current_maven_reports = self._get_current_maven_test_reports(target_class)
                        if current_maven_reports:
                            best_test = self.diversity_calculator.get_best_test(current_maven_reports)
                            if best_test:
                                print(f"对当前maven目录最优基础测试 {best_test} 进行精英变异...")
                                mutated_elite = self.mutation_operator.perform_mutation_on_best(
                                    best_test, current_gen, source_gen=None
                                )
                                if mutated_elite:
                                    all_new_tests.append(mutated_elite)
                                    print(f"生成精英变异测试: {mutated_elite}")
                                    # 运行精英变异测试
                                    self.run_tests_and_generate_reports([mutated_elite], current_gen)
                                    self._run_coverage_analysis(current_gen)
                                else:
                                    print(f"精英变异失败")
                            else:
                                print(f"未找到当前maven目录最优测试")
                        else:
                            print(f"未找到当前maven目录中 {target_class} 类的基础测试报告")
                else:
                    print(f"无法从交叉测试推断目标类")
            else:
                print(f"已存在精英变异测试: {existing_elite_mutation}")
            
            # 3. 选择下一代测试 - 处理所有发现的目标类
            print(f"\n=== 选择下一代 ===")
            
            # 发现所有目标类
            target_classes = set()
            if self.target_class:
                target_classes.add(self.target_class)
            else:
                # 从所有交叉测试中推断所有目标类
                for test_name in crossover_tests:
                    target_class = self._extract_target_class_from_test_name(test_name)
                    if target_class:
                        target_classes.add(target_class)
            
            if not target_classes:
                print(f"错误: 无法推断目标类名")
                return
            
            print(f"发现 {len(target_classes)} 个目标类需要处理: {sorted(target_classes)}")
            
            # 对每个目标类分别进行代际选择
            all_success = True
            for target_class in sorted(target_classes):
                print(f"\n--- 处理目标类: {target_class} 的第{current_gen}代选择 ---")
                success = self.generation_manager.select_and_rename_next_generation(target_class, current_gen, self.diversity_calculator)
                
                if success:
                    print(f"✅ 目标类 {target_class} 第{current_gen}代选择完成")
                else:
                    print(f"❌ 目标类 {target_class} 第{current_gen}代选择失败")
                    all_success = False
            
            if all_success:
                print(f"\n✅ 所有目标类第{current_gen}代演化完成，继续下一代...")
                self.continue_evolution_from_generation(current_gen + 1)
            else:
                print(f"\n❌ 部分目标类第{current_gen}代演化失败")
                
        except Exception as e:
            print(f"交叉后变异步骤失败: {e}")
            import traceback
            traceback.print_exc()

    def run_evolution_range(self, start_gen: int, end_gen: int):
        """在指定代数范围内运行演化

        Args:
            start_gen: 起始代数
            end_gen: 结束代数
        """
        print(f"开始从第{start_gen}代到第{end_gen}代的演化范围...")

        # 验证起始代数的数据是否存在
        evolution_dir = os.path.join(self.base_dir, "evolution_process", self.project_name)
        start_gen_dir = os.path.join(evolution_dir, f"Gen{start_gen-1}")

        if start_gen > 1 and not os.path.exists(start_gen_dir):
            print(f"错误: 第{start_gen-1}代数据不存在 ({start_gen_dir})，无法从第{start_gen}代开始演化")
            return

        if start_gen == 1:
            # 从第1代开始，使用正常的 run_evolution 方法
            self.run_evolution(end_gen=end_gen)
        else:
            # 从指定代数开始，使用修改版的 continue_evolution_from_generation
            self.continue_evolution_from_generation_range(start_gen, end_gen)

    def continue_evolution_from_generation_range(self, start_gen: int, end_gen: int):
        """从指定代数开始到指定代数结束的演化"""
        current_gen = start_gen

        while current_gen <= end_gen:
            print(f"\n===== 开始第 {current_gen} 代演化 =====")

            # 获取基础代的测试报告
            base_gen = current_gen - 1
            test_reports = self.diversity_calculator.get_test_reports(base_gen)
            if not test_reports:
                print(f"错误: 无法获取第{base_gen}代测试报告")
                break

            # 执行正常的演化流程 - 按照正确的单代演化逻辑
            grouped_tests = self.group_tests_by_target_class(test_reports)

            # 如果指定了target_class，只处理该被测类
            if self.target_class:
                if self.target_class in grouped_tests:
                    grouped_tests = {self.target_class: grouped_tests[self.target_class]}
                else:
                    print(f"错误: 指定的被测类 {self.target_class} 在第{base_gen}代中没有测试报告")
                    break

            print(f"发现 {len(grouped_tests)} 个被测类:")
            for target_class, tests in grouped_tests.items():
                print(f"  - {target_class}: {len(tests)} 个测试")

            # 对每个被测类执行演化
            all_success = True
            for target_class, target_tests in grouped_tests.items():
                print(f"\n--- 处理被测类: {target_class} ---")
                success = self.evolve_single_generation(target_class, target_tests, current_gen)
                if not success:
                    print(f"被测类 {target_class} 第{current_gen}代演化失败")
                    all_success = False

            if not all_success:
                print(f"第{current_gen}代部分被测类演化失败，但继续演化")

            # 严格验证当前代所有类的完整性
            print(f"\n=== 验证第{current_gen}代完整性 ===")
            incomplete_classes = self._get_incomplete_classes_in_generation(current_gen, grouped_tests.keys())

            if incomplete_classes:
                print(f"⚠️ 发现 {len(incomplete_classes)} 个类第{current_gen}代演化未完成: {incomplete_classes}")
                print(f"正在自动完成这些类的选择和重命名过程...")

                # 尝试完成未完成的类
                completion_success = self._complete_incomplete_classes(incomplete_classes, current_gen)

                if completion_success:
                    print(f"✅ 已成功完成所有未完成类的演化过程")
                else:
                    print(f"❌ 部分类无法自动完成，将继续下一代（允许部分失败）")

            print(f"✅ 第{current_gen}代处理完成，进入第{current_gen+1}代")

            current_gen += 1

        print(f"演化范围 {start_gen}-{end_gen} 完成")

        # 演化结束
        self.finalize_evolution()

    def continue_evolution_from_generation(self, start_gen: int):
        """从指定代数继续演化"""
        current_gen = start_gen
        
        while current_gen <= MAX_GENERATIONS:
            print(f"\n===== 开始第 {current_gen} 代演化 =====")
            
            # 获取基础代的测试报告
            base_gen = current_gen - 1
            test_reports = self.diversity_calculator.get_test_reports(base_gen)
            if not test_reports:
                print(f"错误: 无法获取第{base_gen}代测试报告")
                break
            
            # 执行正常的演化流程 - 按照正确的单代演化逻辑
            grouped_tests = self.group_tests_by_target_class(test_reports)
            
            # 如果指定了target_class，只处理该被测类
            if self.target_class:
                if self.target_class in grouped_tests:
                    grouped_tests = {self.target_class: grouped_tests[self.target_class]}
                    print(f"指定测试被测类: {self.target_class}")
                else:
                    print(f"未找到指定的被测类: {self.target_class}")
                    break
            
            print(f"发现 {len(grouped_tests)} 个被测类:")
            for target_class, tests in grouped_tests.items():
                print(f"  - {target_class}: {len(tests)} 个测试")
            
            # 对每个被测类执行演化
            all_success = True
            for target_class, target_tests in grouped_tests.items():
                print(f"\n--- 处理被测类: {target_class} ---")
                success = self.evolve_single_generation(target_class, target_tests, current_gen)
                if not success:
                    print(f"被测类 {target_class} 第{current_gen}代演化失败")
                    all_success = False
            
            if not all_success:
                print(f"第{current_gen}代部分被测类演化失败，但继续演化")
                # 注意：这里不break，允许部分失败继续演化
            
            # 严格验证当前代所有类的完整性，确保代间进化的正确性
            print(f"\n=== 验证第{current_gen}代完整性 ===")
            incomplete_classes = self._get_incomplete_classes_in_generation(current_gen, grouped_tests.keys())
            
            if incomplete_classes:
                print(f"⚠️ 发现 {len(incomplete_classes)} 个类第{current_gen}代演化未完成: {incomplete_classes}")
                print(f"正在自动完成这些类的选择和重命名过程...")
                
                # 尝试完成未完成的类
                completion_success = self._complete_incomplete_classes(incomplete_classes, current_gen)
                
                if completion_success:
                    print(f"✅ 已成功完成所有未完成类的演化过程")
                else:
                    print(f"❌ 部分类无法自动完成，将继续下一代（允许部分失败）")
                    print(f"  建议手动检查以下内容:")
                    print(f"  1. evolution_process/{self.project_name}/Gen{current_gen}/ 目录结构")
                    print(f"  2. test_reports/{self.project_name}/Gen{current_gen}/ 目录结构")
                    print(f"  3. 中间文件是否需要手动清理")
            
            print(f"✅ 第{current_gen}代处理完成，进入第{current_gen+1}代")
            current_gen += 1
        
        # 演化结束
        self.finalize_evolution()
    
    def find_existing_crossover_tests(self) -> List[str]:
        """查找现有的交叉个体"""
        crossover_tests = []
        
        # 在项目测试目录中查找交叉测试
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, dirs, files in os.walk(test_src_dir):
            for file in files:
                if file.endswith(".java") and "_Crossover_" in file:
                    # 提取类名（不包括.java扩展名）
                    class_name = file.replace(".java", "")
                    
                    # 如果指定了target_class，只处理相关的交叉测试
                    if self.target_class:
                        if self.target_class in class_name:
                            crossover_tests.append(class_name)
                    else:
                        crossover_tests.append(class_name)
        
        return crossover_tests
    
    
    
    def finalize_evolution(self):
        """演化结束，输出最终结果"""
        print("\n==========================")
        print("演化优化过程已结束")
        print("==========================")
        
        # 获取历史最优适应度
        if self.historical_fitness:
            best_fitness = max(self.historical_fitness)
            final_fitness = self.historical_fitness[-1]
            initial_fitness = self.historical_fitness[0]
            
            print(f"初始适应度: {initial_fitness:.4f}")
            print(f"最终适应度: {final_fitness:.4f}")
            print(f"最优适应度: {best_fitness:.4f}")
            
            if initial_fitness > 0:
                improvement = ((final_fitness - initial_fitness) / initial_fitness) * 100
                print(f"提升比例: {improvement:.2f}%")
        
        # 寻找并输出最优测试类
        best_test_info = self._find_best_test_overall()
        
        if best_test_info:
            test_class, gen, fitness, report = best_test_info
            
            print(f"\n最优测试类: {test_class} (第 {gen} 代)")
            print(f"适应度值: {fitness:.4f}")
            
            metrics = report.get("metrics", {})
            print(f"分支覆盖率: {metrics.get('branch_coverage', 0):.2f}%")
            print(f"行覆盖率: {metrics.get('line_coverage', 0):.2f}%")
            print(f"方法覆盖率: {metrics.get('method_coverage', 0):.2f}%")
            
            # 将最优测试复制到项目外部
            self._save_final_best_test(test_class, gen)
            
            # 注意: 不再自动删除其他测试，保留最后一代的所有测试
            # 是否进行进一步优化由用户决定
        
        print("\n演化优化过程完成!")
    
    def _find_test_source_file(self, test_class: str) -> Optional[str]:
        """查找测试类源文件"""
        file_path = self.unified_manager.find_test_source_file(test_class)
        return str(file_path) if file_path else None
    
    def _is_base_test(self, test_name: str) -> bool:
        """判断是否为基础测试（TestV1-TestV10格式）"""
        import re
        # 匹配格式：{ClassName}TestV{数字}
        pattern = r'.*TestV\d+$'
        return bool(re.match(pattern, test_name))
    
    def _find_best_test_overall(self) -> Optional[Tuple[str, int, float, Dict]]:
        """在所有世代中寻找最优测试"""
        best_test = None
        best_fitness = -1
        best_gen = 0
        best_report = None
        
        # 遍历所有世代的历史最优目录
        for gen in range(1, MAX_GENERATIONS + 1):
            gen_dir = os.path.join(self.historical_best_dir, f"Gen{gen}")
            if not os.path.exists(gen_dir):
                break
            
            # 遍历该世代的测试
            for file in os.listdir(gen_dir):
                if file.endswith(".java"):
                    test_class = file.replace(".java", "")
                    
                    # 查找对应的测试报告
                    report_path = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen}", test_class, "coverage_report.json")
                    
                    if not os.path.exists(report_path):
                        # 尝试在原始test_reports目录中查找
                        report_path = os.path.join(self.base_dir, "test_reports", self.project_name, "Gen1", test_class, "coverage_report.json")
                    
                    if os.path.exists(report_path):
                        report = load_json(report_path)
                        if report and report.get("fitness", 0) > best_fitness:
                            best_test = test_class
                            best_fitness = report["fitness"]
                            best_gen = gen
                            best_report = report
        
        if best_test:
            return best_test, best_gen, best_fitness, best_report
        
        return None
    
    def _save_final_best_test(self, test_class: str, gen: int):
        """将最优测试保存到项目外部"""
        best_file_path = os.path.join(self.historical_best_dir, f"Gen{gen}", f"{test_class}.java")
        
        if os.path.exists(best_file_path):
            # 保存到项目根目录外
            dst_path = os.path.join(self.base_dir, f"{test_class}_best.java")
            copy_file(best_file_path, dst_path)
            print(f"\n最优测试类已保存到: {dst_path}")
    
    def _clean_and_keep_best_test(self, best_test_class: str, target_class: str):
        """在项目内删除其他测试，只保留最优测试并重命名"""
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        # 查找目标类的所有测试文件
        target_test_files = []
        for root, _, files in os.walk(test_src_dir):
            for file in files:
                # 匹配格式: [TargetClass]TestV[number].java 或 [TargetClass]Test_*.java
                if (file.startswith(target_class) and "Test" in file and file.endswith(".java")):
                    target_test_files.append(os.path.join(root, file))
        
        # 删除非最优测试文件
        for test_file in target_test_files:
            test_name = os.path.basename(test_file).replace(".java", "")
            if test_name != best_test_class:
                try:
                    os.remove(test_file)
                    print(f"删除测试文件: {test_file}")
                except Exception as e:
                    print(f"警告: 无法删除文件 {test_file}: {e}")
        
        # 将最优测试重命名为标准格式并复制到src/test目录
        best_test_file = self._find_test_source_file(best_test_class)
        if best_test_file:
            # 确定目标文件路径
            # 需要找到其他测试文件的包路径
            package_path = ""
            for test_file in target_test_files:
                if os.path.exists(test_file):  # 找一个现存的测试文件来确定包路径
                    rel_path = os.path.relpath(test_file, test_src_dir)
                    package_path = os.path.dirname(rel_path)
                    break
            
            # 如果没有找到包路径，尝试从原始文件中推断
            if not package_path:
                # 从最优测试文件路径推断包路径
                if "/src/test/java/" in best_test_file:
                    rel_path = best_test_file.split("/src/test/java/")[1]
                    package_path = os.path.dirname(rel_path)
                else:
                    package_path = ""
            
            new_name = f"{target_class}TestV.java"
            new_path = os.path.join(test_src_dir, package_path, new_name)
            
            # 确保目标目录存在
            ensure_dir(os.path.dirname(new_path))
            
            # 读取并修改类名
            with open(best_test_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 替换类名（更精确的正则匹配）
            import re
            new_content = re.sub(rf'class\s+{re.escape(best_test_class)}\b', f'class {target_class}TestV', content)
            
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"最优测试已保存为: {new_path}")
        else:
            print(f"警告: 未找到最优测试文件 {best_test_class}")
    
    def evolve_single_generation(self, target_class: str, target_tests: Dict[str, Dict], current_gen: int) -> bool:
        """执行一代完整的演化过程
        
        按照正确的执行流程：
        1. 输入: 10个基础测试 (类名TestV1.java - 类名TestV10.java) 在maven目录中
        2. 复制保存: 复制到 evolution_process/<project_name>/GenN/
        3. 交叉操作: 选择5对进行交叉 → 生成5个交叉测试
        4. 运行交叉测试: 生成覆盖率报告
        5. 交叉后变异: 根据变异率决定是否对交叉测试变异
        6. 精英变异: 对上一代最优测试进行变异（在所有交叉完成后）
        7. 适应度排序: 对所有测试(10个原始 + 5个交叉 + 变异测试)按适应度排序
        8. 选择下一代: 选择前10个最优测试
        9. 重命名覆盖: 将选中的10个测试重命名为 类名TestV1.java - 类名TestV10.java 覆盖maven目录
        10. 清理淘汰: 删除未选中测试的文件和报告
        11. 复制到下一代: 将新的10个测试复制到 evolution_process/<project_name>/GenN+1/
        """
        # 演化锁检查 - 防止多个类同时进行演化
        if self.evolution_in_progress:
            print(f"⚠️  演化进程冲突: 当前正在处理类 {self.current_evolution_class}，无法同时处理 {target_class}")
            print(f"   请等待当前类处理完成后再继续")
            return False
        
        # 设置演化锁
        self.evolution_in_progress = True
        self.current_evolution_class = target_class
        
        print(f"\n======== 🔒 开始执行第{current_gen}代演化 ========")
        print(f"被测类: {target_class} (已锁定)")
        print(f"当前测试数量: {len(target_tests)}")
        
        # 在演化开始前检查上一代的完整性（确保有完整的基础数据）
        if current_gen > 1:
            prev_gen = current_gen - 1
            print(f"检查并恢复Gen{prev_gen}目录的完整性...")
            self.generation_manager.restore_generation_integrity(target_class, prev_gen)
        
        try:
            # 1. 检查并保存最优测试到历史记录（避免重复保存）
            prev_gen = current_gen - 1
            historical_dir = os.path.join(self.historical_best_dir, f"Gen{prev_gen}")
            
            if not os.path.exists(historical_dir) or len(os.listdir(historical_dir)) == 0:
                print(f"第{prev_gen}代historical_best不存在，正在保存...")
                self.save_best_tests(prev_gen, target_tests)
            else:
                print(f"第{prev_gen}代historical_best已存在，跳过重复保存")
            
            # 2. 过滤出基础测试（排除交叉和变异测试）
            base_tests = self._filter_base_tests(target_tests)
            print(f"基础测试数量: {len(base_tests)}")
            
            if len(base_tests) < TESTS_PER_GENERATION:
                print(f"警告: 基础测试数量不足{TESTS_PER_GENERATION}个，实际数量: {len(base_tests)}")
            
            # 3. 选择5对进行交叉
            num_pairs = 5 if len(base_tests) >= TESTS_PER_GENERATION else min(len(base_tests) // 2, 3)
            crossover_pairs = self.diversity_calculator.select_diverse_pairs(base_tests, num_pairs)
            print(f"选择{len(crossover_pairs)}对进行交叉")
            
            all_new_tests = []
            crossover_tests = []
            
            # 5. 检查并执行交叉操作
            # 检查哪些交叉对已经完成，哪些还需要执行
            existing_crossover_files = []
            maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
            if os.path.exists(maven_test_dir):
                for root, dirs, files in os.walk(maven_test_dir):
                    for file in files:
                        if f"{target_class}Test_Crossover_Gen{current_gen}" in file and file.endswith('.java'):
                            test_name = file.replace('.java', '')
                            existing_crossover_files.append(test_name)
            
            # 检查交叉完整性：应该有的交叉数量 vs 实际存在的交叉数量
            expected_crossover_count = len(crossover_pairs) if crossover_pairs else 0
            actual_crossover_count = len(existing_crossover_files)
            
            if existing_crossover_files and actual_crossover_count >= expected_crossover_count:
                print(f"\n=== 交叉操作已完整完成 ===")
                print(f"发现{len(existing_crossover_files)}个已存在的交叉测试（期望{expected_crossover_count}个）:")
                for test in existing_crossover_files:
                    print(f"  - {test}")
                crossover_tests = existing_crossover_files
                all_new_tests.extend(crossover_tests)
            elif crossover_pairs:
                if existing_crossover_files:
                    print(f"\n=== 交叉操作部分完成 ===")
                    print(f"发现{actual_crossover_count}个已存在的交叉测试，但期望{expected_crossover_count}个")
                    print(f"继续完成剩余的交叉操作...")
                else:
                    print(f"\n=== 执行交叉操作 ===")
                
                # 执行交叉操作（已存在的会被跳过，只生成缺失的）
                crossover_tests = self.crossover_operator.perform_crossover(
                    crossover_pairs, current_gen, current_gen - 1 if current_gen > 1 else 1
                )
                
                # 合并已存在的和新生成的交叉测试
                all_crossover_tests = list(set(existing_crossover_files + crossover_tests))
                crossover_tests = all_crossover_tests
                all_new_tests.extend(crossover_tests)
                print(f"交叉完成：总共{len(crossover_tests)}个交叉测试（{len(existing_crossover_files)}个已存在，{len(crossover_tests)-len(existing_crossover_files)}个新生成）")
            else:
                print(f"\n=== 跳过交叉操作 ===")
                print(f"没有合适的交叉对")
            
            # 6. 运行交叉测试并生成覆盖率报告  
            print(f"\n=== 运行交叉测试并生成覆盖率报告 ===")
            tests_to_run = []
            
            # 检查每个交叉测试是否需要运行（是否已有报告）
            for test_class in crossover_tests:
                reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
                report_file = os.path.join(reports_dir, test_class, "coverage_report.json")

                if os.path.exists(report_file) and not self.force_overwrite:
                    print(f"  跳过已有报告的交叉测试: {test_class}")
                else:
                    tests_to_run.append(test_class)
                    if self.force_overwrite and os.path.exists(report_file):
                        print(f"  强制重新运行交叉测试（覆盖现有报告）: {test_class}")
                    else:
                        print(f"  需要运行交叉测试: {test_class}")
            
            # 运行需要运行的交叉测试
            for test_class in tests_to_run:
                print(f"运行交叉测试: {test_class}")
                success = self.test_executor.run_test_and_generate_reports(test_class, current_gen)
                if success:
                    # 生成覆盖率分析报告
                    report = self.coverage_analyzer.analyze_test_coverage(test_class, current_gen, use_cache=False)
                    if report:
                        print(f"  ✓ 交叉测试运行成功: {test_class}")
                    else:
                        print(f"  ✗ 交叉测试覆盖率分析失败: {test_class}")
                else:
                    print(f"  ✗ 交叉测试运行失败: {test_class}")
                    
            print(f"完成运行{len(tests_to_run)}个交叉测试，跳过{len(crossover_tests)-len(tests_to_run)}个已有报告的交叉测试")
            all_new_tests.extend(crossover_tests)
            
            # 7. 交叉后变异 (关键步骤)
            print(f"\n=== 交叉后变异 ===")
            crossover_mutated_tests = self._perform_crossover_mutation(crossover_tests, current_gen)
            if crossover_mutated_tests:
                all_new_tests.extend(crossover_mutated_tests)
                print(f"生成{len(crossover_mutated_tests)}个交叉后变异测试")
            else:
                print("所有交叉测试都不需要变异")
            
            # 8. 精英变异（在交叉完成后执行，支持断点续传，保护已生成的变异个体）
            print(f"\n=== 精英变异（断点续传支持）===")

            # 首先检查是否已有精英变异文件存在（断点续传 - 不删除已生成的变异个体）
            existing_mutation_files = []
            maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
            if os.path.exists(maven_test_dir):
                for root, dirs, files in os.walk(maven_test_dir):
                    for file in files:
                        if f"{target_class}Test_Mutation_Gen{current_gen}" in file and file.endswith('.java'):
                            test_name = file.replace('.java', '')
                            existing_mutation_files.append(test_name)

            print(f"扫描到 {len(existing_mutation_files)} 个已存在的变异个体（将被保留并整合到最终选择中）")
            
            # 首先保留并处理已存在的变异个体（断点续传核心逻辑）
            if existing_mutation_files:
                print(f"💾 断点续传：发现{len(existing_mutation_files)}个已存在的精英变异测试（将保留）:")
                for test in existing_mutation_files:
                    print(f"  - {test}")

                # 检查这些变异测试是否需要运行（生成报告）
                elite_tests_to_run = []
                for test_class in existing_mutation_files:
                    reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
                    report_file = os.path.join(reports_dir, test_class, "coverage_report.json")

                    if not os.path.exists(report_file):
                        elite_tests_to_run.append(test_class)
                        print(f"  需要运行: {test_class} (缺少测试报告)")
                    else:
                        print(f"  已有报告: {test_class}")

                # 运行需要运行的精英变异测试
                if elite_tests_to_run:
                    print(f"运行 {len(elite_tests_to_run)} 个变异测试以生成缺失的报告...")
                    for test_class in elite_tests_to_run:
                        print(f"运行精英变异测试: {test_class}")
                        success = self.test_executor.run_test_and_generate_reports(test_class, current_gen)
                        if success:
                            report = self.coverage_analyzer.analyze_test_coverage(test_class, current_gen, use_cache=False)
                            if report:
                                print(f"  ✓ 精英变异测试运行成功: {test_class}")
                            else:
                                print(f"  ✗ 精英变异测试覆盖率分析失败: {test_class}")
                        else:
                            print(f"  ✗ 精英变异测试运行失败: {test_class}")

                # 将所有已存在的变异个体加入到测试列表中（保证它们参与最终选择）
                all_new_tests.extend(existing_mutation_files)
                print(f"✅ 已将 {len(existing_mutation_files)} 个现有变异个体加入候选列表")

            # 判断是否需要生成新的精英变异（如果已有足够数量则跳过）
            if not existing_mutation_files:
                # 对当前maven目录中基础测试的最优个体进行精英变异
                print(f"🔬 没有现有变异个体，对 {target_class} 类执行新的精英变异...")
                current_maven_reports = self._get_current_maven_test_reports(target_class)
                if current_maven_reports:
                    best_test = self.diversity_calculator.get_best_test(current_maven_reports)
                    if best_test:
                        print(f"对当前maven目录最优基础测试 {best_test} 进行精英变异...")
                        mutated_elite = self.mutation_operator.perform_mutation_on_best(
                            best_test, current_gen, source_gen=None
                        )
                        if mutated_elite:
                            all_new_tests.append(mutated_elite)
                            print(f"生成精英变异测试: {mutated_elite}")

                            # 立即运行精英变异测试
                            print(f"运行精英变异测试: {mutated_elite}")
                            success = self.test_executor.run_test_and_generate_reports(mutated_elite, current_gen)
                            if success:
                                report = self.coverage_analyzer.analyze_test_coverage(mutated_elite, current_gen, use_cache=False)
                                if report:
                                    print(f"  ✓ 精英变异测试运行成功: {mutated_elite}")
                                else:
                                    print(f"  ✗ 精英变异测试覆盖率分析失败: {mutated_elite}")
                            else:
                                print(f"  ✗ 精英变异测试运行失败: {mutated_elite}")
                        else:
                            print(f"精英变异失败")
                    else:
                        print(f"未找到当前maven目录最优测试")
                else:
                    print(f"未找到当前maven目录中 {target_class} 类的基础测试报告")
            else:
                print(f"📋 检测到已有 {len(existing_mutation_files)} 个变异个体，跳过新的精英变异生成")
            
            # 10. 选择下一代测试 (核心步骤)
            print(f"\n=== 选择当代最优测试 ===")
            success = self.generation_manager.select_and_rename_next_generation(target_class, current_gen, self.diversity_calculator)
            
            print(f"🔓 类 {target_class} 第{current_gen}代演化完成，释放演化锁")
            return success
            
        except Exception as e:
            print(f"第{current_gen}代演化过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # 无论成功还是失败，都要释放演化锁
            if self.evolution_in_progress and self.current_evolution_class == target_class:
                self.evolution_in_progress = False
                self.current_evolution_class = None
                print(f"🔓 演化锁已释放 (target_class: {target_class})")
    
    def _copy_generation_to_evolution_process(self, target_class: str, target_tests: Dict[str, Dict], gen_num: int):
        """复制当前代测试到evolution_process目录"""
        print(f"复制第{gen_num}代测试到evolution_process...")
        
        # 创建目标目录
        gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        ensure_dir(gen_dir)
        
        # 复制每个测试文件
        for test_name in target_tests.keys():
            # 查找测试文件
            test_file = self._find_test_source_file(test_name)
            if test_file:
                dst_file = os.path.join(gen_dir, f"{test_name}.java")
                try:
                    shutil.copy2(test_file, dst_file)
                    print(f"复制: {test_name}.java")
                except Exception as e:
                    print(f"复制失败: {test_name} - {e}")
            else:
                print(f"警告: 未找到测试文件 {test_name}")
        
        print(f"完成复制到 evolution_process/Gen{gen_num}/")
    
    
    def _perform_crossover_mutation(self, crossover_tests: List[str], current_gen: int) -> List[str]:
        """对交叉测试进行变异判断和变异操作"""
        mutated_tests = []
        print(f"对{len(crossover_tests)}个交叉测试进行变异判断...")

        # 获取交叉测试的报告
        updated_test_reports = self.diversity_calculator.get_test_reports(current_gen)
        base_mutation_rate = self.mutation_operator.calculate_base_mutation_rate(current_gen)

        for crossover_test in crossover_tests:
            if crossover_test in updated_test_reports:
                fitness = updated_test_reports[crossover_test].get("fitness", 0.0)
                report = updated_test_reports[crossover_test]
                metrics = report.get("metrics", {})

                # 检查是否应该跳过变异（分支覆盖率已达到95%）
                if self.mutation_operator._should_skip_mutation(metrics, crossover_test):
                    print(f"    → {crossover_test} 跳过变异（分支覆盖率已达到95%阈值）")
                    continue

                mutation_rate = self.mutation_operator.calculate_individual_mutation_rate(fitness, base_mutation_rate)
                print(f"  {crossover_test}: 适应度={fitness:.4f}, 变异率={mutation_rate:.4f}")

                # 移除ENABLE_CROSSOVER_MUTATION的全局禁用逻辑，改为基于变异率和覆盖率的智能判断
                if self.mutation_operator.should_mutate(mutation_rate):
                    print(f"    → 决定对 {crossover_test} 进行变异")
                    # 使用专门的交叉后变异方法
                    mutated_test = self.mutation_operator.perform_crossover_mutation(crossover_test, current_gen)
                    if mutated_test:
                        mutated_tests.append(mutated_test)
                        print(f"    → 生成交叉后变异测试: {mutated_test}")

                        # 运行变异测试
                        self.run_tests_and_generate_reports([mutated_test], current_gen)
                        self._run_coverage_analysis(current_gen)
                    else:
                        print(f"    ✗ {crossover_test} 变异失败")
                else:
                    print(f"    → {crossover_test} 不需要变异（变异率判断）")

        return mutated_tests
    
    
    def _rename_and_overwrite_maven_tests(self, target_class: str, selected_tests: List[Tuple[str, Dict]], next_gen: int) -> bool:
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
            
            # 重命名并覆盖选中的测试
            for i, (old_test_name, report) in enumerate(selected_tests, 1):
                new_test_name = f"{target_class}TestV{i}"
                
                # 找到原始文件
                old_test_file = self._find_test_source_file(old_test_name)
                if not old_test_file:
                    print(f"警告: 未找到测试文件 {old_test_name}")
                    continue
                
                # 目标文件路径
                new_test_file = os.path.join(target_package_dir, f"{new_test_name}.java")
                
                # 复制并修改类名
                success = self._copy_and_rename_test_file(old_test_file, new_test_file, new_test_name)
                if success:
                    print(f"  {old_test_name} → {new_test_name}")
                    # 重命名对应的测试报告
                    self._rename_test_reports(old_test_name, new_test_name, next_gen - 1)
                else:
                    print(f"  错误: 重命名失败 {old_test_name}")
                    return False
            
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
        
        print(f"警告: 无法找到 {target_class} 的包路径，使用默认包")
        return ""  # 默认包作为最后回退
    
    def _rename_test_reports(self, old_test_name: str, new_test_name: str, target_gen: int):
        """重命名测试报告目录并更新内部XML文件内容以匹配新的测试名称"""
        reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
        
        # 只在目标代数中重命名报告，保持与选中的测试一致
        gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen}")
        if os.path.exists(gen_dir):
            old_report_dir = os.path.join(gen_dir, old_test_name)
            new_report_dir = os.path.join(gen_dir, new_test_name)
            
            # 如果目标代数中没有找到，且是基础测试，则从前一代复制
            if not os.path.exists(old_report_dir) and self._is_base_test(old_test_name) and target_gen > 1:
                prev_gen_dir = os.path.join(reports_base_dir, f"Gen{target_gen-1}")
                prev_old_report_dir = os.path.join(prev_gen_dir, old_test_name)
                
                if os.path.exists(prev_old_report_dir):
                    print(f"    从前一代复制基础测试报告: Gen{target_gen-1}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                    try:
                        import shutil
                        # 如果目标目录已存在，先删除它
                        if os.path.exists(new_report_dir):
                            shutil.rmtree(new_report_dir, ignore_errors=True)
                        
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
            if os.path.exists(old_report_dir):
                try:
                    import shutil
                    # 如果目标目录已存在，先删除它以避免冲突
                    if os.path.exists(new_report_dir):
                        print(f"    删除现有目标报告: Gen{target_gen}/{new_test_name}")
                        shutil.rmtree(new_report_dir, ignore_errors=True)
                    
                    # 移动目录
                    shutil.move(old_report_dir, new_report_dir)
                    print(f"    重命名测试报告目录: Gen{target_gen}/{old_test_name} → Gen{target_gen}/{new_test_name}")
                    
                    # 更新内部XML文件的测试类名引用
                    self._update_report_xml_content(new_report_dir, old_test_name, new_test_name)
                    
                except Exception as e:
                    print(f"    重命名测试报告失败 Gen{target_gen}/{old_test_name}: {e}")
            else:
                print(f"    未找到源报告目录: Gen{target_gen}/{old_test_name}")
        else:
            print(f"    代数目录不存在: Gen{target_gen}")
    
    def _update_report_xml_content(self, report_dir: str, old_test_name: str, new_test_name: str):
        """更新测试报告目录中XML文件的测试类名引用"""
        import os
        import re
        
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
                import json
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
    
    def _copy_and_rename_test_file(self, src_file: str, dst_file: str, new_class_name: str) -> bool:
        """复制测试文件并修改类名"""
        try:
            import re
            with open(src_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 首先提取原始类名（支持public class和非public class）
            class_match = re.search(r'(?:public\s+)?class\s+(\w+)', content)
            if class_match:
                old_class_name = class_match.group(1)
                
                # 替换所有出现的类名
                # 1. 替换class声明（无论是否有public修饰符）
                content = re.sub(
                    rf'((?:public\s+)?class\s+){old_class_name}(\s*(?:extends\s+\w+)?\s*(?:implements\s+[\w,\s]+)?\s*\{{)',
                    rf'\1{new_class_name}\2',
                    content
                )
                
                # 2. 替换构造函数名称（如果有的话）
                content = re.sub(
                    rf'\b{old_class_name}(\s*\()',
                    rf'{new_class_name}\1',
                    content
                )
                
                print(f"    将类名从 {old_class_name} 更改为 {new_class_name}")
            else:
                print(f"    警告: 无法在源文件中找到类名，使用通用替换")
            
            # 确保目标目录存在
            ensure_dir(os.path.dirname(dst_file))
            
            with open(dst_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return True
        except Exception as e:
            print(f"复制并重命名文件失败: {e}")
            return False
    
    
    def _cleanup_crossover_and_mutation_tests(self, target_class: str):
        """清理所有交叉和变异测试文件和报告"""
        print(f"清理所有{target_class}类的交叉和变异测试文件...")
        
        # 删除maven目录中所有包含_Crossover_或_Mutation_的测试文件
        import os
        import glob
        import shutil
        
        test_dir = os.path.join(self.project_dir, "src", "test", "java")
        patterns = [
            f"**/{target_class}Test_Crossover_*.java",
            f"**/{target_class}Test_Mutation_*.java"
        ]
        
        cleaned_files = []
        for pattern in patterns:
            files = glob.glob(os.path.join(test_dir, pattern), recursive=True)
            for file_path in files:
                try:
                    test_name = os.path.basename(file_path).replace('.java', '')
                    cleaned_files.append(test_name)
                    os.remove(file_path)
                    print(f"  删除文件: {os.path.basename(file_path)}")
                except Exception as e:
                    print(f"  删除文件失败 {file_path}: {e}")
        
        # 删除对应的测试报告
        for test_name in cleaned_files:
            # 查找所有代中该测试的报告
            reports_base_dir = os.path.join(self.base_dir, "test_reports", self.project_name)
            if os.path.exists(reports_base_dir):
                for gen_dir in os.listdir(reports_base_dir):
                    if gen_dir.startswith("Gen"):
                        report_dir = os.path.join(reports_base_dir, gen_dir, test_name)
                        if os.path.exists(report_dir):
                            try:
                                shutil.rmtree(report_dir)
                                print(f"  删除测试报告: {gen_dir}/{test_name}")
                            except Exception as e:
                                print(f"  删除测试报告失败 {report_dir}: {e}")
    
    def _copy_selected_to_evolution_process(self, target_class: str, selected_tests: List[Tuple[str, Dict]], gen_num: int):
        """复制已重命名的测试到evolution_process目录"""
        print(f"复制已重命名的测试到evolution_process/Gen{gen_num}/...")
        
        # 创建目标目录
        gen_dir = os.path.join(self.evolution_dir, f"Gen{gen_num}")
        ensure_dir(gen_dir)
        
        # 查找maven测试目录
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        target_package_dir = self._find_target_package_path(target_class)
        
        if target_package_dir is None:
            print(f"警告: 未找到被测类 {target_class} 的包路径，使用默认包")
            target_package_dir = ""
        
        # 构建maven中的包目录路径
        maven_package_dir = os.path.join(maven_test_dir, target_package_dir.replace(".", os.sep))
        
        # 创建evolution_process中对应的包目录结构
        evolution_package_dir = os.path.join(gen_dir, target_package_dir.replace(".", os.sep))
        ensure_dir(evolution_package_dir)
        
        # 复制已重命名的测试文件（此时maven中的文件已经是标准化名称）
        for i, (original_test_name, test_data) in enumerate(selected_tests, 1):
            # 标准化的文件名（已在maven中重命名）
            standard_test_name = f"{target_class}TestV{i}"
            maven_file_path = os.path.join(maven_package_dir, f"{standard_test_name}.java")
            
            fitness = test_data.get("fitness", 0.0)
            
            if os.path.exists(maven_file_path):
                # 直接复制已重命名的文件
                evolution_file_path = os.path.join(evolution_package_dir, f"{standard_test_name}.java")
                
                import shutil
                try:
                    shutil.copy2(maven_file_path, evolution_file_path)
                    print(f"  {i}. {original_test_name} → {standard_test_name}.java (适应度: {fitness:.4f})")
                    print(f"     保存到: {evolution_file_path}")
                except Exception as e:
                    print(f"  错误: 复制测试文件失败 {original_test_name}: {e}")
            else:
                print(f"  警告: 未找到已重命名的测试文件 {maven_file_path}")
        
        print(f"已完成复制 {len(selected_tests)} 个测试到evolution_process/Gen{gen_num}/目录")
    
    def _get_current_generation_tests(self, target_class: str, gen_num: int) -> Dict[str, Dict]:
        """获取当前代的正确测试状态（动态查找所有TestV*格式的测试）"""
        current_tests = {}
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
        
        if not os.path.exists(reports_dir):
            return current_tests
        
        # 动态查找所有TestV*格式的测试报告
        import re
        for item in os.listdir(reports_dir):
            if os.path.isdir(os.path.join(reports_dir, item)):
                # 检查是否匹配 TargetClassTestV数字 格式
                if re.match(rf'^{target_class}TestV\d+$', item):
                    test_name = item
                    report_file = os.path.join(reports_dir, test_name, "coverage_report.json")
            
                    if os.path.exists(report_file):
                        try:
                            report = load_json(report_file)
                            if report:
                                current_tests[test_name] = report
                        except Exception as e:
                            print(f"警告: 读取报告失败 {report_file}: {e}")
        
        print(f"当前第{gen_num}代找到 {len(current_tests)} 个标准格式测试")
        return current_tests
    
    def _filter_base_tests(self, target_tests: Dict[str, Dict]) -> Dict[str, Dict]:
        """过滤出基础测试（排除交叉和变异测试）
        
        只保留模式为 XxxTestVN 的测试，排除所有交叉和变异测试
        """
        base_tests = {}
        import re
        
        for test_name, test_data in target_tests.items():
            # 排除包含交叉或变异标识的测试
            if ("_Crossover_" not in test_name and 
                "_Mutation_" not in test_name and
                re.match(r'^\w+TestV\d+$', test_name)):  # 只保留模式为 XxxTestVN 的测试
                base_tests[test_name] = test_data
        return base_tests
    
    def _is_class_completed_in_generation(self, target_class: str, generation: int) -> bool:
        """检查指定类在指定代数是否已经完成
        
        完成标准（按用户要求）：
        1. test_reports内的gen代（本代）内存在该类的测试报告
        2. evolution_process内的gen代也存在复制进去的该类的测试文件
        
        Args:
            target_class: 被测类名
            generation: 代数
            
        Returns:
            bool: 是否已完成
        """
        print(f"\n检查类 {target_class} 第{generation}代完成状态:")
        
        # 检查1: test_reports中是否存在该类的测试报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{generation}")
        has_test_reports = False
        
        if os.path.exists(reports_dir):
            # 查找以target_class开头的测试报告目录
            for item in os.listdir(reports_dir):
                item_path = os.path.join(reports_dir, item)
                if os.path.isdir(item_path):
                    # 检查是否是目标类的测试（各种命名格式）
                    if self._is_target_class_test(item, target_class):
                        # 检查是否有coverage_report.json文件
                        report_file = os.path.join(item_path, "coverage_report.json")
                        if os.path.exists(report_file):
                            has_test_reports = True
                            print(f"  ✅ 找到测试报告: {item}")
                            break
        
        if not has_test_reports:
            print(f"  ❌ test_reports中未找到 {target_class} 的测试报告")
        
        # 检查2: evolution_process中是否存在该类的测试文件
        evolution_dir = os.path.join(self.base_dir, "evolution_process", self.project_name, f"Gen{generation}")
        has_evolution_tests = False
        found_evolution_files = []
        
        if os.path.exists(evolution_dir):
            # 递归查找.java文件
            for root, dirs, files in os.walk(evolution_dir):
                for file in files:
                    if file.endswith('.java'):
                        # 从文件名提取类名并检查是否匹配目标类
                        test_class_name = file[:-5]  # 移除.java后缀
                        if self._is_target_class_test(test_class_name, target_class):
                            has_evolution_tests = True
                            found_evolution_files.append(file)
        
        if has_evolution_tests:
            print(f"  ✅ evolution_process中找到 {len(found_evolution_files)} 个测试文件: {found_evolution_files[:3]}{'...' if len(found_evolution_files) > 3 else ''}")
        else:
            print(f"  ❌ evolution_process中未找到 {target_class} 的测试文件")
        
        result = has_test_reports and has_evolution_tests
        if result:
            print(f"  ✅ 类 {target_class} 第{generation}代已完成")
        else:
            print(f"  ❌ 类 {target_class} 第{generation}代未完成: reports={has_test_reports}, evolution={has_evolution_tests}")
        
        return result
    
    def _is_target_class_test(self, test_name: str, target_class: str) -> bool:
        """判断测试名是否属于目标类
        
        Args:
            test_name: 测试类名
            target_class: 目标被测类名
            
        Returns:
            是否匹配
        """
        # 提取测试类名的基础部分（去除各种后缀）
        base_patterns = [
            rf'^{re.escape(target_class)}Test.*',  # 标准格式：TargetClassTest*
            rf'^{re.escape(target_class)}TestV\d+.*',  # 版本格式：TargetClassTestV1
            rf'^{re.escape(target_class)}Test_.*',  # 交叉/变异格式：TargetClassTest_Crossover_*
        ]
        
        for pattern in base_patterns:
            if re.match(pattern, test_name):
                return True
        
        return False
    
    def _calculate_and_record_generation_fitness(self, target_class: str, generation: int):
        """计算并记录某个类某代的平均适应度
        
        只在类代数完成后调用此函数计算平均适应度
        
        Args:
            target_class: 被测类名
            generation: 代数
        """
        print(f"\n计算类 {target_class} 第{generation}代适应度:")
        
        # 获取该代最终的测试报告（只有V1-V10格式）
        final_tests = self._get_final_generation_tests(target_class, generation)
        
        if not final_tests:
            print(f"  警告: 无法获取 {target_class} 第{generation}代的最终测试报告")
            return
        
        # 计算平均适应度
        fitness_values = [report["fitness"] for report in final_tests.values()]
        current_avg_fitness = sum(fitness_values) / len(fitness_values)
        
        print(f"  参与计算的最终测试: {list(final_tests.keys())}")
        print(f"  适应度值: {[f'{f:.4f}' for f in fitness_values]}")
        print(f"  平均适应度: {current_avg_fitness:.4f}")
        
        # 初始化该类的适应度历史记录
        if target_class not in self.class_fitness_history:
            self.class_fitness_history[target_class] = []
        
        # 记录当前代适应度到历史记录
        self.class_fitness_history[target_class].append(current_avg_fitness)
        
        # 更新类状态
        self._update_class_state(target_class, generation, current_avg_fitness, "active")
        
        print(f"  ✅ {target_class} 第{generation}代适应度已记录: {current_avg_fitness:.4f}")
    
    def _verify_generation_completeness_for_all_classes(self, current_gen: int, target_classes) -> bool:
        """验证当前代所有类的完整性，确保代间进化的正确性
        
        检查内容:
        1. evolution_process/GenN 目录中每个类都有完整的测试文件
        2. test_reports/GenN 目录中每个类都有完整的测试报告
        3. 所有类的选择和重命名过程已完成（没有遗留的交叉/变异文件）
        
        Args:
            current_gen: 当前代数
            target_classes: 需要验证的目标类列表
            
        Returns:
            bool: 如果所有类都完成了当前代的演化返回True，否则返回False
        """
        print(f"开始验证第{current_gen}代所有类的完整性...")
        
        all_complete = True
        incomplete_classes = []
        
        for target_class in target_classes:
            print(f"\n检验类 {target_class}:")
            
            # 1. 检查 evolution_process/GenN 目录完整性
            evolution_gen_dir = os.path.join(self.evolution_dir, f"Gen{current_gen}")
            if not os.path.exists(evolution_gen_dir):
                print(f"  ❌ evolution_process/Gen{current_gen} 目录不存在")
                all_complete = False
                incomplete_classes.append(target_class)
                continue
            
            # 检查该类的测试文件是否存在（应该有V1-V10或选中的测试文件）
            class_files_found = []
            for root, dirs, files in os.walk(evolution_gen_dir):
                for file in files:
                    if file.endswith(".java") and target_class in file:
                        class_files_found.append(file)
            
            if len(class_files_found) == 0:
                print(f"  ❌ evolution_process/Gen{current_gen} 中未找到 {target_class} 的测试文件")
                all_complete = False
                incomplete_classes.append(target_class)
                continue
            else:
                print(f"  ✅ evolution_process/Gen{current_gen} 中找到 {len(class_files_found)} 个 {target_class} 测试文件")
            
            # 2. 检查 test_reports/GenN 目录完整性  
            reports_gen_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
            if not os.path.exists(reports_gen_dir):
                print(f"  ❌ test_reports/Gen{current_gen} 目录不存在")
                all_complete = False
                incomplete_classes.append(target_class)
                continue
            
            # 检查该类的测试报告是否存在
            class_reports_found = []
            for report_dir in os.listdir(reports_gen_dir):
                report_path = os.path.join(reports_gen_dir, report_dir)
                if os.path.isdir(report_path) and target_class in report_dir:
                    coverage_file = os.path.join(report_path, "coverage_report.json")
                    if os.path.exists(coverage_file):
                        class_reports_found.append(report_dir)
            
            if len(class_reports_found) == 0:
                print(f"  ❌ test_reports/Gen{current_gen} 中未找到 {target_class} 的有效测试报告")
                all_complete = False
                incomplete_classes.append(target_class)
                continue
            else:
                print(f"  ✅ test_reports/Gen{current_gen} 中找到 {len(class_reports_found)} 个 {target_class} 测试报告")
            
            # 3. 检查是否还有未清理的交叉/变异文件（说明选择过程未完成）
            maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
            remaining_intermediate_files = []
            
            if os.path.exists(maven_test_dir):
                for root, dirs, files in os.walk(maven_test_dir):
                    for file in files:
                        if file.endswith(".java") and target_class in file:
                            file_name = file.replace(".java", "")
                            # 检查是否为当前代的交叉或变异文件
                            if (f"{target_class}Test_Crossover_Gen{current_gen}" in file_name or 
                                f"{target_class}Test_Mutation_Gen{current_gen}" in file_name):
                                remaining_intermediate_files.append(file_name)
            
            if remaining_intermediate_files:
                print(f"  ❌ 发现未清理的第{current_gen}代中间文件: {remaining_intermediate_files}")
                print(f"     这表明 {target_class} 的选择和重命名过程可能未完成")
                all_complete = False
                incomplete_classes.append(target_class)
                continue
            else:
                print(f"  ✅ 没有遗留的第{current_gen}代中间文件，选择过程已完成")
            
            print(f"  ✅ 类 {target_class} 第{current_gen}代演化完整")
        
        if all_complete:
            print(f"\n✅ 第{current_gen}代所有 {len(target_classes)} 个类都已完整完成演化")
        else:
            print(f"\n❌ 第{current_gen}代有 {len(incomplete_classes)} 个类未完整完成演化:")
            for cls in incomplete_classes:
                print(f"   - {cls}")
        
        return all_complete
    
    def _get_incomplete_classes_in_generation(self, current_gen: int, target_classes) -> List[str]:
        """获取当前代未完成演化的类列表
        
        增强检查逻辑：
        1. 检查是否还有当前代的交叉/变异文件未清理
        2. 检查是否evolution_process中缺少当前代完整文件  
        3. 检查是否test_reports中缺少当前代完整报告
        4. 检查是否已经有下一代文件但当前代未完成（跨代问题）
        
        Args:
            current_gen: 当前代数
            target_classes: 需要检查的目标类列表
            
        Returns:
            List[str]: 未完成演化的类名列表
        """
        incomplete_classes = []
        
        for target_class in target_classes:
            is_incomplete = False
            reasons = []
            
            # 1. 检查是否还有未清理的当前代交叉/变异文件
            maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
            current_gen_intermediate_files = []
            future_gen_files = []  # 检查是否有未来代文件
            
            if os.path.exists(maven_test_dir):
                for root, dirs, files in os.walk(maven_test_dir):
                    for file in files:
                        if file.endswith(".java") and target_class in file:
                            file_name = file.replace(".java", "")
                            # 检查是否为当前代的交叉或变异文件
                            if (f"{target_class}Test_Crossover_Gen{current_gen}" in file_name or 
                                f"{target_class}Test_Mutation_Gen{current_gen}" in file_name):
                                current_gen_intermediate_files.append(file_name)
                            # 检查是否有更高代数的文件（跨代问题）
                            elif ("_Crossover_Gen" in file_name or "_Mutation_Gen" in file_name):
                                # 提取代数
                                if "_Crossover_Gen" in file_name:
                                    gen_part = file_name.split("_Crossover_Gen")[1].split("_")[0]
                                elif "_Mutation_Gen" in file_name:
                                    gen_part = file_name.split("_Mutation_Gen")[1].split("_")[0]
                                try:
                                    file_gen = int(gen_part)
                                    if file_gen > current_gen:
                                        future_gen_files.append((file_name, file_gen))
                                except ValueError:
                                    pass
            
            if current_gen_intermediate_files:
                is_incomplete = True
                reasons.append(f"当前代中间文件未清理: {current_gen_intermediate_files}")
            
            if future_gen_files:
                is_incomplete = True  
                max_future_gen = max(gen for _, gen in future_gen_files)
                reasons.append(f"检测到跨代问题：已有第{max_future_gen}代文件但第{current_gen}代未完成")
            
            # 2. 检查evolution_process完整性
            evolution_gen_dir = os.path.join(self.evolution_dir, f"Gen{current_gen}")
            if not os.path.exists(evolution_gen_dir):
                is_incomplete = True
                reasons.append(f"evolution_process/Gen{current_gen}目录不存在")
            else:
                # 检查该类的测试文件
                class_files = []
                for root, dirs, files in os.walk(evolution_gen_dir):
                    for file in files:
                        if file.endswith(".java") and target_class in file:
                            class_files.append(file)
                if len(class_files) == 0:
                    is_incomplete = True
                    reasons.append(f"evolution_process/Gen{current_gen}中缺少{target_class}测试文件")
            
            # 3. 检查test_reports完整性
            reports_gen_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{current_gen}")
            if not os.path.exists(reports_gen_dir):
                is_incomplete = True  
                reasons.append(f"test_reports/Gen{current_gen}目录不存在")
            else:
                # 检查该类的测试报告
                class_reports = []
                for report_dir in os.listdir(reports_gen_dir):
                    report_path = os.path.join(reports_gen_dir, report_dir)
                    if os.path.isdir(report_path) and target_class in report_dir:
                        coverage_file = os.path.join(report_path, "coverage_report.json")
                        if os.path.exists(coverage_file):
                            class_reports.append(report_dir)
                if len(class_reports) == 0:
                    is_incomplete = True
                    reasons.append(f"test_reports/Gen{current_gen}中缺少{target_class}有效报告")
            
            if is_incomplete:
                incomplete_classes.append(target_class)
                print(f"  类 {target_class} 未完成原因: {'; '.join(reasons)}")
        
        return incomplete_classes
    
    def _complete_incomplete_classes(self, incomplete_classes: List[str], current_gen: int) -> bool:
        """完成未完成类的演化过程（执行完整演化流程）

        Args:
            incomplete_classes: 未完成的类列表
            current_gen: 当前代数

        Returns:
            bool: 是否全部成功完成
        """
        all_success = True

        for target_class in incomplete_classes:
            print(f"\n--- 补充完成类 {target_class} 第{current_gen}代的完整演化过程 ---")

            # 🔥 修复：检查演化锁，避免并发冲突
            if self.evolution_in_progress and self.current_evolution_class == target_class:
                print(f"⚠️  跳过 {target_class}：该类当前正在进行演化，避免重复处理")
                continue
            elif self.evolution_in_progress and self.current_evolution_class != target_class:
                print(f"⚠️  演化冲突：当前 {self.current_evolution_class} 正在演化，{target_class} 等待处理")
                print(f"    建议：等待当前类完成或手动检查演化状态")
                all_success = False
                continue

            try:
                # 首先检查该类是否在当前代有交叉变异测试
                has_crossover_mutation = self._check_class_has_crossover_mutation_in_gen(target_class, current_gen)

                if has_crossover_mutation:
                    print(f"发现 {target_class} 在第{current_gen}代已有交叉变异测试，仅执行代际选择")
                    # 仅执行选择和重命名
                    success = self.generation_manager.select_and_rename_next_generation(
                        target_class, current_gen, self.diversity_calculator
                    )
                else:
                    print(f"{target_class} 在第{current_gen}代缺少演化操作，执行完整演化流程")
                    # 执行完整演化流程
                    success = self._execute_complete_evolution_for_class(target_class, current_gen)

                if success:
                    print(f"✅ 成功完成 {target_class} 第{current_gen}代演化")
                else:
                    print(f"❌ {target_class} 第{current_gen}代演化失败")
                    all_success = False

            except Exception as e:
                print(f"❌ 完成 {target_class} 演化过程时发生错误: {e}")
                import traceback
                traceback.print_exc()
                all_success = False

        return all_success

    def _check_class_has_crossover_mutation_in_gen(self, target_class: str, current_gen: int) -> bool:
        """检查指定类在指定代数是否有交叉变异测试"""
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        if not os.path.exists(maven_test_dir):
            return False

        crossover_count = 0
        mutation_count = 0

        for root, dirs, files in os.walk(maven_test_dir):
            for file in files:
                if file.endswith('.java'):
                    test_name = file.replace('.java', '')
                    if f"{target_class}Test_Crossover_Gen{current_gen}" in test_name:
                        crossover_count += 1
                    elif f"{target_class}Test_Mutation_Gen{current_gen}" in test_name:
                        mutation_count += 1

        print(f"  检查 {target_class} 第{current_gen}代: 交叉测试 {crossover_count} 个, 变异测试 {mutation_count} 个")
        return crossover_count > 0 or mutation_count > 0

    def _execute_complete_evolution_for_class(self, target_class: str, current_gen: int) -> bool:
        """为指定类执行完整的演化流程 - 修复：避免递归调用evolve_single_generation"""
        print(f"正在为 {target_class} 执行第{current_gen}代完整演化...")

        # 获取该类的当前测试
        target_tests = self._get_current_maven_tests(target_class)
        if not target_tests:
            print(f"错误: 无法获取 {target_class} 的maven测试")
            return False

        if len(target_tests) < 2:
            print(f"错误: {target_class} 测试数量不足({len(target_tests)})，无法进行演化")
            return False

        print(f"找到 {len(target_tests)} 个 {target_class} 的测试，开始非递归演化")

        # 🔥 修复：避免递归调用，直接执行缺失的演化步骤
        try:
            # 1. 检查并执行缺失的交叉操作
            success = self._ensure_crossover_operations(target_class, target_tests, current_gen)
            if not success:
                print(f"❌ {target_class} 交叉操作执行失败")
                return False

            # 2. 检查并执行缺失的变异操作
            success = self._ensure_mutation_operations(target_class, current_gen)
            if not success:
                print(f"❌ {target_class} 变异操作执行失败")
                return False

            # 3. 执行选择和重命名（这是安全的，不会递归）
            success = self.generation_manager.select_and_rename_next_generation(
                target_class, current_gen, self.diversity_calculator
            )
            if not success:
                print(f"❌ {target_class} 选择和重命名失败")
                return False

            print(f"✅ {target_class} 第{current_gen}代非递归演化完成")
            return True

        except Exception as e:
            print(f"❌ {target_class} 非递归演化过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _ensure_crossover_operations(self, target_class: str, target_tests: Dict[str, Dict], current_gen: int) -> bool:
        """确保交叉操作已完成 - 避免重复执行"""
        print(f"检查 {target_class} 第{current_gen}代的交叉操作...")

        # 检查现有交叉文件
        existing_crossover_files = []
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        if os.path.exists(maven_test_dir):
            for root, dirs, files in os.walk(maven_test_dir):
                for file in files:
                    if f"{target_class}Test_Crossover_Gen{current_gen}" in file and file.endswith('.java'):
                        test_name = file.replace('.java', '')
                        existing_crossover_files.append(test_name)

        # 如果已有足够的交叉文件，跳过
        if len(existing_crossover_files) >= 3:  # 期望至少3个交叉测试
            print(f"  已有 {len(existing_crossover_files)} 个交叉测试，跳过交叉操作")
            return True

        # 执行缺失的交叉操作
        print(f"  需要执行交叉操作（当前有 {len(existing_crossover_files)} 个）")

        base_tests = self._filter_base_tests(target_tests)
        if len(base_tests) < 2:
            print(f"  基础测试数量不足({len(base_tests)})，跳过交叉")
            return True

        num_pairs = min(3, len(base_tests) // 2)
        crossover_pairs = self.diversity_calculator.select_diverse_pairs(base_tests, num_pairs)

        if not crossover_pairs:
            print(f"  无合适的交叉对，跳过交叉操作")
            return True

        # 执行交叉操作
        try:
            crossover_tests = self.crossover_operator.perform_crossover(
                crossover_pairs, current_gen, current_gen - 1 if current_gen > 1 else 1
            )
            print(f"  成功生成 {len(crossover_tests)} 个交叉测试")
            return True
        except Exception as e:
            print(f"  交叉操作失败: {e}")
            return False

    def _ensure_mutation_operations(self, target_class: str, current_gen: int) -> bool:
        """确保变异操作已完成 - 避免重复执行"""
        print(f"检查 {target_class} 第{current_gen}代的变异操作...")

        # 检查现有变异文件
        existing_mutation_files = []
        maven_test_dir = os.path.join(self.project_dir, "src", "test", "java")
        if os.path.exists(maven_test_dir):
            for root, dirs, files in os.walk(maven_test_dir):
                for file in files:
                    if f"{target_class}Test_Mutation_Gen{current_gen}" in file and file.endswith('.java'):
                        test_name = file.replace('.java', '')
                        existing_mutation_files.append(test_name)

        # 如果已有变异文件，跳过
        if len(existing_mutation_files) >= 1:  # 期望至少1个变异测试
            print(f"  已有 {len(existing_mutation_files)} 个变异测试，跳过变异操作")
            return True

        print(f"  需要执行变异操作")

        # 执行精英变异
        try:
            # 获取上一代最优测试
            prev_gen = current_gen - 1 if current_gen > 1 else 1
            best_test = self._get_best_test_from_generation(target_class, prev_gen)

            if not best_test:
                print(f"  无法获取第{prev_gen}代最优测试，跳过变异")
                return True

            # 执行变异
            mutation_test = self.mutation_operator.perform_elite_mutation(best_test, current_gen)
            if mutation_test:
                print(f"  成功生成变异测试: {mutation_test}")
                return True
            else:
                print(f"  变异操作失败")
                return False

        except Exception as e:
            print(f"  变异操作失败: {e}")
            return False
