"""
变异操作相关功能模块
针对测试中的问题用例进行智能修复和优化
"""

import os
import math
import random
from typing import Dict, List, Tuple, Optional

from ..utils import load_json, ensure_dir
from ..clients import LLMClient
from ..maven_utils import run_maven_test
from ..unified_manager import get_unified_manager

# 导入常量
from ..constants import MUTATION_MAX, MUTATION_MIN, MUTATION_DECAY_RATE

class MutationOperator:
    def __init__(self, base_dir: str, project_name: str, llm_client: LLMClient):
        """初始化变异操作器

        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
            llm_client: LLM客户端实例
        """
        self.base_dir = base_dir
        self.project_name = project_name
        self.project_dir = os.path.join(base_dir, "dataset", project_name)
        self.llm_client = llm_client
        self.unified_manager = get_unified_manager(base_dir, project_name)

    def calculate_base_mutation_rate(self, gen_num: int) -> float:
        """计算当前代的基础变异率 μ(t)

        使用指数衰减函数：μ(t) = μ_min + (μ_max - μ_min) * e^(-k * t)
        其中 μ_max=0.3, μ_min=0.1, k=0.1

        Args:
            gen_num: 当前代数 (从1开始)

        Returns:
            基础变异率
        """
        t = gen_num - 1  # 从0开始计算
        base_mutation_rate = MUTATION_MIN + (MUTATION_MAX - MUTATION_MIN) * math.exp(-MUTATION_DECAY_RATE * t)
        return base_mutation_rate

    def calculate_individual_mutation_rate(self, fitness: float, base_rate: float) -> float:
        """根据个体适应度计算个体变异率 μ_i

        Args:
            fitness: 个体适应度值
            base_rate: 基础变异率 μ(t)

        Returns:
            个体变异率
        """
        if fitness >= 0.8:
            # 适应度值≥0.8，μ_i = 0.5 * μ(t)
            individual_rate = 0.5 * base_rate
        elif fitness <= 0.3:
            # 适应度值≤0.3，μ_i = 1.2 * μ(t)
            individual_rate = 1.2 * base_rate
        else:
            # 其他情况，μ_i = μ(t)
            individual_rate = base_rate

        # 确保变异率在合理范围内
        individual_rate = max(MUTATION_MIN, min(individual_rate, MUTATION_MAX * 1.2))
        return individual_rate

    def calculate_mutation_rate(self, gen_num: int, best_test_fitness: float) -> float:
        """计算当前代的变异率（兼容性方法，主要用于最优测试）

        Args:
            gen_num: 当前代数 (从1开始)
            best_test_fitness: 最优测试的适应度值

        Returns:
            变异率
        """
        base_rate = self.calculate_base_mutation_rate(gen_num)
        individual_rate = self.calculate_individual_mutation_rate(best_test_fitness, base_rate)

        print(f"第{gen_num}代变异率: 基础={base_rate:.4f}, 最优测试调整后={individual_rate:.4f} (适应度={best_test_fitness:.4f})")

        return individual_rate

    def should_mutate(self, mutation_rate: float) -> bool:
        """决定是否执行变异操作

        Args:
            mutation_rate: 变异率

        Returns:
            是否执行变异
        """
        return random.random() < mutation_rate

    def perform_mutation_on_best(self, best_test: str, gen_num: int, source_gen: int = None) -> Optional[str]:
        """对适应度最高的测试执行精英变异操作

        这是第二种变异：精英变异
        - 对上一代最优的测试进行变异
        - 不考虑变异率，直接进行变异
        - 目的是在保持高适应度的基础上补充未覆盖的方法和路径

        Args:
            best_test: 适应度最高的测试类名
            gen_num: 当前代数
            source_gen: 源代数（从哪一代获取测试报告，如果为None则使用gen_num）

        Returns:
            变异后的测试类名，如果失败则返回None
        """
        print(f"对最优测试 {best_test} 执行智能变异操作...")

        # 获取测试报告（如果source_gen为None，说明是对当前maven目录基础测试进行变异，需要查找最新报告）
        if source_gen is None:
            # 对当前maven目录基础测试进行精英变异，查找最新的测试报告
            report_path = None
            for check_gen in range(gen_num, 0, -1):  # 从当前代数往前查找
                test_report_path = os.path.join(
                    self.base_dir, "test_reports", self.project_name,
                    f"Gen{check_gen}", best_test, "coverage_report.json"
                )
                if os.path.exists(test_report_path):
                    report_path = test_report_path
                    print(f"  找到基础测试 {best_test} 在第{check_gen}代的报告")
                    break

            if not report_path:
                print(f"警告: 未找到基础测试 {best_test} 的任何测试报告，跳过变异操作")
                return None
        else:
            # 使用指定的源代数
            report_gen = source_gen
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{report_gen}")
            report_path = os.path.join(reports_dir, best_test, "coverage_report.json")

            if not os.path.exists(report_path):
                print(f"警告: 第{source_gen}代测试报告不存在，跳过变异操作")
                return None

        # 读取测试报告
        report = load_json(report_path)
        if not report:
            print(f"警告: 测试报告为空，跳过变异操作")
            return None

        # 检查是否应该跳过变异（分支覆盖率已达到95%）
        metrics = report.get("metrics", {})
        if self._should_skip_mutation(metrics, best_test):
            return None

        # 获取测试类源码
        test_path = self._find_test_source_file(best_test)

        if not test_path:
            print(f"警告: 测试源文件不存在，跳过变异操作")
            return None

        # 读取测试类源码
        with open(test_path, 'r', encoding='utf-8') as f:
            test_code = f.read()

        # 从测试类名正确推断目标类名，不依赖报告中的值
        target_class = self._extract_base_class_name(best_test)

        # 生成变异后的测试类名
        new_version = self._generate_new_version()
        mutated_class = f"{target_class}Test_Mutation_Gen{gen_num}_V{new_version}"

        # 准备变异操作的提示词
        prompt = self._generate_mutation_prompt(report, test_code, best_test, mutated_class)

        # 记录提示词到日志文件
        self._log_llm_interaction("mutation", mutated_class, prompt, None, "发送提示词")

        # 输出LLM提示词到终端
        print("\n" + "="*80)
        print("🔄 变异操作 - LLM提示词")
        print("="*80)
        print(prompt)
        print("="*80 + "\n")

        # 调用LLM执行变异操作
        mutated_code = self.llm_client.generate_code(prompt)

        # 记录LLM回复到日志文件
        self._log_llm_interaction("mutation", mutated_class, None, mutated_code, "接收回复")

        if not mutated_code:
            print(f"警告: 变异操作失败，跳过该测试")
            return None

        # 保存变异后的测试类
        if self._save_mutated_test(mutated_code, mutated_class, test_code, gen_num):
            print(f"成功生成变异测试类: {mutated_class}")
            return mutated_class
        else:
            print(f"警告: 保存变异测试类失败: {mutated_class}")
            # 变异失败时调用修复模块
            print(f"  尝试使用修复模块修复变异测试...")
            if self._try_repair_failed_mutation(mutated_class, mutated_code, gen_num):
                print(f"  ✓ 修复成功: {mutated_class}")
                return mutated_class
            else:
                print(f"  ✗ 修复失败: {mutated_class}")
                # 检查文件是否被删除，如果删除了就不再尝试修复
                test_file_path = self._get_test_file_path(mutated_class)
                if not os.path.exists(test_file_path):
                    print(f"  文件已删除，停止处理: {mutated_class}")
                return None

    def perform_crossover_mutation(self, crossover_test: str, gen_num: int) -> Optional[str]:
        """对交叉生成的测试进行变异操作

        这是根据变异率判断是否需要变异的第一种变异：
        - 对交叉后的测试根据适应度计算变异率
        - 如果随机数小于变异率则进行变异
        - 目的是优化交叉结果，补充未覆盖的方法和路径

        Args:
            crossover_test: 交叉生成的测试类名
            gen_num: 当前代数

        Returns:
            变异后的测试类名，如果失败或不需要变异则返回None
        """
        print(f"对交叉测试 {crossover_test} 执行变异操作...")

        # 获取测试报告
        reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
        report_path = os.path.join(reports_dir, crossover_test, "coverage_report.json")

        if not os.path.exists(report_path):
            print(f"警告: 交叉测试报告不存在，跳过变异操作: {crossover_test}")
            return None

        # 读取测试报告
        report = load_json(report_path)
        if not report:
            print(f"警告: 交叉测试报告为空，跳过变异操作: {crossover_test}")
            return None

        # 检查是否应该跳过变异（分支覆盖率已达到95%）
        metrics = report.get("metrics", {})
        if self._should_skip_mutation(metrics, crossover_test):
            return None

        # 获取适应度值
        fitness = report.get("fitness", 0.0)

        # 计算基础变异率和个体变异率（用于显示）
        base_rate = self.calculate_base_mutation_rate(gen_num)
        individual_rate = self.calculate_individual_mutation_rate(fitness, base_rate)

        print(f"交叉测试 {crossover_test} 适应度: {fitness:.4f}, 变异率: {individual_rate:.4f}")
        print(f"已决定对交叉测试 {crossover_test} 进行变异，开始执行...")

        # 获取测试类源码
        test_path = self._find_test_source_file(crossover_test)

        if not test_path:
            print(f"警告: 交叉测试源文件不存在，跳过变异操作: {crossover_test}")
            return None

        # 读取测试类源码
        with open(test_path, 'r', encoding='utf-8') as f:
            test_code = f.read()

        # 从测试类名正确推断目标类名
        import re
        base_name = re.sub(r'Test_Crossover_Gen\d+_\d+x\d+$', '', crossover_test)
        target_class = base_name

        # 交叉后变异直接覆盖原有的交叉测试，保持相同的类名
        mutated_class = crossover_test

        # 准备变异操作的提示词
        prompt = self._generate_crossover_mutation_prompt(report, test_code, crossover_test, mutated_class)

        # 记录提示词到日志文件
        self._log_llm_interaction("crossover_mutation", mutated_class, prompt, None, "发送提示词")

        # 输出LLM提示词到终端
        print("\n" + "="*80)
        print("🔀 交叉变异操作 - LLM提示词")
        print("="*80)
        print(prompt)
        print("="*80 + "\n")

        # 调用LLM执行变异操作
        mutated_code = self.llm_client.generate_code(prompt)

        # 记录LLM回复到日志文件
        self._log_llm_interaction("crossover_mutation", mutated_class, None, mutated_code, "接收回复")

        if not mutated_code:
            print(f"警告: 交叉变异操作失败，跳过该测试")
            return None

        # 保存变异后的测试类（覆盖原有的交叉测试）
        if self._save_mutated_test(mutated_code, mutated_class, test_code, gen_num):
            print(f"成功对交叉测试进行变异并覆盖: {mutated_class}")
            # 标记这个测试已经经过了变异
            self._mark_test_as_mutated(mutated_class, gen_num)
            return mutated_class
        else:
            print(f"警告: 交叉测试变异失败: {mutated_class}")
            # 变异失败时调用修复模块
            print(f"  尝试使用修复模块修复交叉变异测试...")
            if self._try_repair_failed_mutation(mutated_class, mutated_code, gen_num):
                print(f"  ✓ 修复成功: {mutated_class}")
                # 修复成功后也要标记为已变异（只有修复成功才标记）
                self._mark_test_as_mutated(mutated_class, gen_num)
                return mutated_class
            else:
                print(f"  ✗ 修复失败: {mutated_class}")
                # 检查文件是否被删除，如果删除了就不再尝试修复
                test_file_path = self._get_test_file_path(mutated_class)
                if not os.path.exists(test_file_path):
                    print(f"  文件已删除，停止处理: {mutated_class}")
                return None

    def _find_test_source_file(self, test_class: str) -> Optional[str]:
        """查找测试类源文件"""
        file_path = self.unified_manager.find_test_source_file(test_class)
        return str(file_path) if file_path else None

    def _generate_new_version(self) -> str:
        """生成新的版本号"""
        # 查找当前最大的版本号
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        max_version = 0

        for root, _, files in os.walk(test_src_dir):
            for file in files:
                if "TestV" in file and file.endswith(".java"):
                    # 提取版本号
                    import re
                    match = re.search(r'TestV(\d+)\.java', file)
                    if match:
                        version = int(match.group(1))
                        max_version = max(max_version, version)

                    # 也检查Mutation格式
                    match = re.search(r'Test_Mutation_Gen\d+_V(\d+)\.java', file)
                    if match:
                        version = int(match.group(1))
                        max_version = max(max_version, version)

        return str(max_version + 1)

    def _generate_mutation_prompt(self, report: Dict, test_code: str, test_class: str, mutated_class: str) -> str:
        """生成变异操作提示词 - 基于分支覆盖率提升的新策略"""

        # 提取未覆盖的分支信息
        uncovered_branches = self._extract_uncovered_branches(report)

        # 提取这些分支对应的方法源码（最多10个）
        branch_methods_info = self._extract_branch_methods_source_code(uncovered_branches[:10])

        # 提取现有的测试方法信息
        existing_tests = self._extract_existing_tests_for_methods(test_code, branch_methods_info)

        # 获取失败的测试用例
        failed_tests = self._extract_failed_test_cases_info(report)

        prompt = f"""You are a Java unit test expert focused on improving branch coverage. Perform mutation on test class `{test_class}` to create `{mutated_class}` with enhanced branch coverage.

**BRANCH COVERAGE MUTATION STRATEGY**:
Focus on improving branch coverage by targeting uncovered branches in these methods:

**UNCOVERED BRANCHES ANALYSIS** ({len(uncovered_branches)} branches):"""

        # 添加未覆盖分支的详细信息
        for i, branch_info in enumerate(uncovered_branches[:10], 1):
            prompt += f"""

Branch {i}: {branch_info.get('method', 'Unknown method')}
- Uncovered Condition: {branch_info.get('condition', 'Unknown condition')}
- Branch Type: {branch_info.get('branch_type', 'conditional')}"""

            if branch_info.get('source_code'):
                prompt += f"""
- Source Code:
```java
{branch_info['source_code']}
```"""

        # 添加现有测试信息
        if existing_tests:
            prompt += f"""

**EXISTING TESTS FOR THESE METHODS** ({len(existing_tests)} found):"""
            for method_name, tests in existing_tests.items():
                prompt += f"""

Method: {method_name}
- Existing Tests: {len(tests)}"""
                for test in tests[:3]:  # 最多显示3个测试
                    prompt += f"""
  - {test.get('name', '')}: {test.get('display_name', '')}"""

        # 添加失败测试信息
        if failed_tests:
            prompt += f"""

**FAILED TESTS TO FIX** ({len(failed_tests)} failures):"""
            for test in failed_tests[:5]:  # 最多显示5个失败测试
                prompt += f"""
- {test['name']}: {test['reason']}"""
                if test.get('detail'):
                    prompt += f"""
  Detail: {test['detail']}"""

        prompt += f"""

**MUTATION GOAL**:
1. Fix the failed tests listed above by analyzing their failure details
2. Improve branch coverage by referencing existing tests for similar methods and extending them to cover missing branches
3. For branches with no existing tests, generate new comprehensive test methods

**ORIGINAL TEST CODE**:
```java
{self.unified_manager.strip_license_header(test_code)}
```

Generate the complete mutated test class `{mutated_class}` that improves branch coverage by targeting the uncovered branches listed above."""

        return prompt

    def _generate_crossover_mutation_prompt(self, report: Dict, test_code: str, test_class: str, mutated_class: str) -> str:
        """生成交叉变异操作的提示词"""

        # 提取覆盖信息
        covered_methods = report.get("covered_methods", [])
        uncovered_methods = report.get("uncovered_methods", [])
        covered_paths = report.get("covered_paths", [])
        uncovered_paths = report.get("uncovered_paths", [])

        # 提取测试方法信息
        methods = report.get("test_methods_info", [])

        # 提取失败的测试用例
        failed_tests = []
        if "test_summary" in report and "failed_test_cases" in report["test_summary"]:
            for case in report["test_summary"]["failed_test_cases"]:
                failed_tests.append({
                    "name": case.get("name", ""),
                    "reason": case.get("reason", ""),
                    "detail": case.get("detail", ""),
                    "message": case.get("message", ""),
                    "type": case.get("type", "")
                })


        # 构建提示词
        prompt = f"""You are a Java unit test optimization expert. Perform crossover mutation on test class `{test_class}` to create improved version `{mutated_class}`.

**CROSSOVER MUTATION STRATEGY**:
Focus on preserving crossover advantages while improving coverage and fixing issues.

**COVERED METHODS** ({len(covered_methods)}):
{chr(10).join([f"  - {method}" for method in covered_methods])}

**UNCOVERED METHODS** ({len(uncovered_methods)} - Focus Areas):
{chr(10).join([f"  - {method}" for method in uncovered_methods])}

**PATH COVERAGE STATUS**:
- Covered Paths: {len(covered_paths)}
- Uncovered Paths: {len(uncovered_paths)}"""

        if failed_tests:
            prompt += f"""

**FAILED TESTS TO FIX** ({len(failed_tests)} failures):"""
            for test in failed_tests:
                prompt += f"""
- {test['name']}: {test['reason']}"""
                if test.get('detail'):
                    prompt += f"""
  Detail: {test['detail']}"""

        prompt += f"""

**CROSSOVER MUTATION GOAL**:
1. Fix the failed tests listed above by analyzing their failure details
2. Preserve crossover advantages while adding new tests for uncovered methods
3. For uncovered methods, reference existing similar tests and extend coverage

**ORIGINAL CROSSOVER TEST CODE**:
```java
{self.unified_manager.strip_license_header(test_code)}
```

Generate the improved crossover mutation test class `{mutated_class}`:"""

        return prompt

    def _save_mutated_test(self, mutated_code: str, mutated_class: str, reference_code: str, gen_num: int) -> bool:
        """保存变异后的测试类"""
        try:
            # 提取包路径
            import re
            package_match = re.search(r'package\s+([\w.]+);', reference_code)
            if package_match:
                package_path = package_match.group(1)
            else:
                package_path = ""

            # 构建测试类路径
            test_dir = os.path.join(self.project_dir, "src", "test", "java",
                                  package_path.replace(".", os.sep)) if package_path else os.path.join(self.project_dir, "src", "test", "java")
            ensure_dir(test_dir)

            # 修正代码中的类名以匹配文件名
            corrected_code = self._fix_class_name_in_code(mutated_code, mutated_class)

            # 确保包含完整的类结构（License头部 + Package声明）
            corrected_code = self.unified_manager.ensure_complete_class_structure(corrected_code, mutated_class)

            # 保存文件
            mutated_file = os.path.join(test_dir, f"{mutated_class}.java")
            with open(mutated_file, 'w', encoding='utf-8') as f:
                f.write(corrected_code)

            # Maven验证
            if self._verify_maven_compilation(mutated_class, gen_num):
                print(f"✓ 变异测试类Maven验证通过: {mutated_class}")
                return True
            else:
                print(f"✗ 变异测试类Maven验证失败: {mutated_class}")
                # 不要立即删除文件，让调用者决定
                return False

        except Exception as e:
            print(f"保存变异测试类失败: {e}")
            return False

    def _fix_class_name_in_code(self, code: str, correct_class_name: str) -> str:
        """修正代码中的类名以匹配文件名"""
        import re

        # 匹配类声明行 (class ClassName 或 public class ClassName)
        class_pattern = r'((?:public\s+)?class\s+)(\w+)(\s*\{)'

        def replace_class_name(match):
            prefix = match.group(1)  # "class " 或 "public class "
            suffix = match.group(3)  # " {"
            return f"{prefix}{correct_class_name}{suffix}"

        # 替换类名
        corrected_code = re.sub(class_pattern, replace_class_name, code)

        # 验证内部类和构造函数一致性
        corrected_code = self._validate_inner_class_consistency(corrected_code)

        return corrected_code

    def _verify_maven_compilation(self, test_class: str, gen_num: int) -> bool:
        """使用Maven验证测试类并集成修复组件"""
        try:
            # 直接使用test_repair模块进行测试和修复
            return self._execute_repair_workflow(test_class, gen_num)

        except Exception as e:
            print(f"Maven验证异常: {e}")
            return False

    def _execute_repair_workflow(self, test_class: str, gen_num: int) -> bool:
        """执行修复流程：使用test_repair模块进行测试和修复"""
        try:
            # 使用test_repair agent
            from ..utils import setup_test_repair_import
            setup_test_repair_import()

            from test_repair.repair_client import TestRepairClient

            # 创建修复客户端
            repair_client = TestRepairClient(self.base_dir)

            # 使用修复客户端进行测试和修复
            test_file_relative = self._get_test_file_relative_path(test_class)

            # 动态获取包名
            package_name = self._extract_package_name(test_class)

            # 按照用户要求：新生成的测试需要build success且没有测试失败
            cls_info = {
                'project_path': self.project_dir,
                'package': package_name,
                'className': test_class,
                'suite_index': 0
            }
            result_path, repair_stats = repair_client.repair_test_file(test_file_relative, cls_info)

            if result_path and repair_stats.success:
                print(f"  ✓ 修复成功: {test_class}")
                return True
            else:
                print(f"  ✗ 修复失败: {test_class} (test_repair模块已处理文件删除)")
                # 检查文件是否已被删除，如果删除了就不要继续修复
                test_file_path = self._get_test_file_path(test_class)
                if not os.path.exists(test_file_path):
                    print(f"  文件已删除，终止修复流程: {test_class}")
                return False

        except ImportError as e:
            print(f"    导入test_repair agent失败: {e}")
            print(f"  导入失败: {test_class}")
            return False
        except Exception as e:
            print(f"    修复过程异常: {e}")
            print(f"  异常: {test_class}")
            return False



    def _try_repair_failed_mutation(self, mutated_class: str, mutated_code: str, gen_num: int) -> bool:
        """尝试修复失败的变异测试"""
        try:
            # 首先检查文件是否已经被删除
            existing_file_path = self._get_test_file_path(mutated_class)
            if existing_file_path and not os.path.exists(existing_file_path):
                print(f"  测试文件已被删除，跳过修复: {mutated_class}")
                return False

            # 先保存文件以便修复
            test_dir = os.path.join(self.project_dir, "src", "test", "java")

            # 寻找正确的包路径
            import re
            package_match = re.search(r'package\s+([\w.]+);', mutated_code)
            if package_match:
                package_path = package_match.group(1)
                test_dir = os.path.join(test_dir, package_path.replace(".", os.sep))

            ensure_dir(test_dir)

            # 临时保存文件
            temp_file = os.path.join(test_dir, f"{mutated_class}.java")
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(mutated_code)

            # 直接调用修复模块
            return self._execute_repair_workflow(mutated_class, gen_num)

        except Exception as e:
            print(f"修复变异测试时发生异常: {e}")
            return False

    def _get_test_file_relative_path(self, test_class: str) -> str:
        """获取测试文件的相对路径"""
        # 动态查找实际的文件路径
        test_file_path = self._get_test_file_path(test_class)
        if test_file_path and os.path.exists(test_file_path):
            # 计算相对于项目根目录的路径
            rel_path = os.path.relpath(test_file_path, self.project_dir)
            return rel_path
        else:
            # 如果找不到文件，返回通用测试源码根路径
            return f"src/test/java/{test_class}.java"

    def _get_test_file_path(self, test_class: str) -> str:
        """获取测试文件路径"""
        # 动态查找文件路径，因为可能在不同的包下
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")

        # 递归查找文件
        for root, dirs, files in os.walk(test_src_dir):
            if f"{test_class}.java" in files:
                return os.path.join(root, f"{test_class}.java")

        # 如果找不到，返回通用测试源码根路径
        test_dir = os.path.join(self.project_dir, "src", "test", "java")
        return os.path.join(test_dir, f"{test_class}.java")

    def _extract_package_name(self, test_class: str) -> str:
        """从测试文件中提取包名"""
        return self.unified_manager.extract_package_name(test_class)

    def _extract_base_class_name(self, test_class: str) -> str:
        """从测试类名提取基础类名"""
        return self.unified_manager.extract_base_class_name(test_class)

    def _validate_inner_class_consistency(self, code: str) -> str:
        """验证和修复内部类与构造函数名的一致性"""
        import re

        lines = code.split('\n')
        result_lines = []
        current_inner_class = None

        for line_num, line in enumerate(lines):
            # 检测内部类声明
            inner_class_match = re.search(r'(\s*)(static\s+class\s+)(\w+)(\s*\{)', line)
            if inner_class_match:
                current_inner_class = inner_class_match.group(3)
                result_lines.append(line)
                continue

            # 检测构造函数声明
            constructor_match = re.search(r'(\s*)(?:public\s+)?(\w+)(\s*\([^)]*\)\s*\{)', line)
            if constructor_match and current_inner_class:
                indent = constructor_match.group(1)
                constructor_name = constructor_match.group(2)
                params_and_brace = constructor_match.group(3)

                # 如果构造函数名与当前内部类名不匹配，修复它
                if (constructor_name[0].isupper() and
                    constructor_name != current_inner_class and
                    not constructor_name.startswith('get') and
                    not constructor_name.startswith('set') and
                    constructor_name not in ['String', 'Integer', 'Boolean', 'Object', 'Test']):

                    print(f"    变异修复构造函数: {constructor_name} -> {current_inner_class} (行 {line_num+1})")
                    result_lines.append(f"{indent}public {current_inner_class}{params_and_brace}")
                else:
                    result_lines.append(line)
            else:
                result_lines.append(line)

            # 重置当前类（简单的检测方式）
            if line.strip() == '}' and current_inner_class:
                current_inner_class = None

        return '\n'.join(result_lines)

    def _mark_test_as_mutated(self, test_class: str, gen_num: int):
        """在测试报告中标记该测试已经过变异"""
        try:
            # 查找测试报告文件
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
            report_path = os.path.join(reports_dir, test_class, "coverage_report.json")

            if os.path.exists(report_path):
                # 读取现有报告
                report = load_json(report_path)
                if report:
                    # 添加变异标记
                    import datetime
                    report["mutation_applied"] = True
                    report["mutation_type"] = "crossover_mutation"
                    report["mutation_timestamp"] = datetime.datetime.now().isoformat()

                    # 保存更新后的报告
                    import json
                    with open(report_path, 'w', encoding='utf-8') as f:
                        json.dump(report, f, indent=2, ensure_ascii=False)

                    print(f"    已标记测试 {test_class} 为变异后状态")
        except Exception as e:
            print(f"    标记变异状态失败: {e}")

    def _mark_elite_mutation(self, test_class: str, gen_num: int):
        """标记精英变异测试"""
        try:
            # 查找测试报告文件
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{gen_num}")
            report_path = os.path.join(reports_dir, test_class, "coverage_report.json")

            if os.path.exists(report_path):
                # 读取现有报告
                report = load_json(report_path)
                if report:
                    # 添加精英变异标记
                    import datetime
                    report["mutation_applied"] = True
                    report["mutation_type"] = "elite_mutation"
                    report["mutation_timestamp"] = datetime.datetime.now().isoformat()

                    # 保存更新后的报告
                    import json
                    with open(report_path, 'w', encoding='utf-8') as f:
                        json.dump(report, f, indent=2, ensure_ascii=False)

                    print(f"    已标记测试 {test_class} 为精英变异状态")
        except Exception as e:
            print(f"    标记精英变异状态失败: {e}")

    def _delete_failed_test_file(self, test_class: str):
        """删除修复失败的测试文件"""
        test_file = self._get_test_file_path(test_class)
        if test_file and os.path.exists(test_file):
            try:
                os.remove(test_file)
                print(f"    已删除失败的测试文件: {test_file}")
            except Exception as e:
                print(f"    删除文件失败: {e}")

    def _get_test_file_path_full(self, test_class: str) -> str:
        """获取测试文件的完整路径"""
        # 动态查找文件路径，因为可能在不同的包下
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")

        # 递归查找文件
        for root, dirs, files in os.walk(test_src_dir):
            if f"{test_class}.java" in files:
                return os.path.join(root, f"{test_class}.java")

        # 如果找不到，返回通用测试源码根路径
        test_dir = os.path.join(self.project_dir, "src", "test", "java")
        return os.path.join(test_dir, f"{test_class}.java")

    def _extract_failed_test_cases_info(self, report: Dict) -> List[Dict]:
        """从测试报告中提取失败测试用例的详细信息并分类"""
        failed_cases = []

        if "test_summary" in report and "failed_test_cases" in report["test_summary"]:
            for case in report["test_summary"]["failed_test_cases"]:
                failure_info = {
                    "name": case.get("name", ""),
                    "reason": case.get("reason", ""),
                    "detail": case.get("detail", ""),
                    "message": case.get("message", ""),
                    "type": case.get("type", ""),
                    "failure_category": self._classify_failure_type(case)
                }
                failed_cases.append(failure_info)

        return failed_cases

    def _classify_failure_type(self, case: Dict) -> str:
        """分类失败用例的类型"""
        reason = case.get("reason", "").lower()
        message = case.get("message", "").lower()
        detail = case.get("detail", "").lower()

        # 断言失败
        if any(keyword in reason + message + detail for keyword in [
            "assertion", "expected", "but was", "should be", "断言", "期望", "实际"
        ]):
            return "assertion_failure"

        # 异常错误
        elif any(keyword in reason + message for keyword in [
            "exception", "error", "nullpointer", "异常", "错误", "null"
        ]):
            return "exception_error"

        # 超时
        elif "timeout" in reason + message:
            return "timeout_error"

        # 编译相关
        elif any(keyword in reason + message for keyword in [
            "compilation", "cannot find", "compile", "编译", "找不到"
        ]):
            return "compilation_error"

        return "unknown_failure"

    def _format_path_simple(self, path) -> str:
        """简化格式化路径信息"""
        if isinstance(path, list):
            if len(path) == 0:
                return "Empty path"
            elif len(path) == 1:
                return f"{path[0]}"
            else:
                return f"{path[0]} → {path[1]}" + (f" → ...({len(path)} steps)" if len(path) > 2 else "")
        else:
            return f"{path}"

    def _extract_uncovered_branches(self, report: Dict) -> List[Dict]:
        """从测试报告中提取未覆盖的分支信息"""
        uncovered_branches = []

        # 从路径信息中推断未覆盖的分支
        uncovered_paths = report.get("uncovered_paths", [])

        filtered_count = 0
        for path in uncovered_paths:
            branch_info = self._analyze_path_for_branches(path)
            if branch_info:
                uncovered_branches.append(branch_info)
            else:
                filtered_count += 1

        # 显示过滤效果
        if filtered_count > 0:
            print(f"  过滤了 {filtered_count} 个无意义的技术性分支，保留 {len(uncovered_branches)} 个有意义的分支")

        # 也从未覆盖方法中推断分支（经过筛选）
        uncovered_methods = report.get("uncovered_methods", [])

        method_filtered_count = 0
        for method in uncovered_methods:
            if self._is_meaningful_method(method):
                source_code = self._get_method_source_code(method)
                branch_info = {
                    'method': method,
                    'condition': 'Method not covered',
                    'branch_type': 'method_entry',
                    'source_code': source_code
                }
                uncovered_branches.append(branch_info)
            else:
                method_filtered_count += 1

        # 显示方法过滤效果
        if method_filtered_count > 0:
            print(f"  过滤了 {method_filtered_count} 个无意义的未覆盖方法，保留 {len([m for m in uncovered_methods if self._is_meaningful_method(m)])} 个有意义的方法")

        # 最终统计
        total_branches = len(uncovered_branches)
        total_filtered = filtered_count + (method_filtered_count if 'method_filtered_count' in locals() else 0)
        if total_filtered > 0:
            print(f"  总计：过滤了 {total_filtered} 个无意义项，保留 {total_branches} 个有意义的分支")

        return uncovered_branches

    def _is_meaningful_method(self, method_signature: str) -> bool:
        """判断未覆盖方法是否有意义（值得生成测试）"""
        if not method_signature:
            return False

        method_lower = method_signature.lower()

        # ✅ 保留：构造器方法（重要的API入口）
        if '<init>' in method_signature:
            # 过滤掉无参构造器或默认构造器（通常不重要）
            if method_signature.endswith('<init>()V'):
                return False
            # 保留有参数的构造器
            return True

        # ✅ 保留：公共API方法（通过方法名判断）
        if any(keyword in method_lower for keyword in [
            'public', 'process', 'execute', 'handle', 'create', 'build',
            'parse', 'validate', 'convert', 'transform', 'calculate'
        ]):
            return True

        # ✅ 保留：重要的业务方法
        if any(keyword in method_lower for keyword in [
            'write', 'read', 'open', 'close', 'flush', 'reset',
            'add', 'remove', 'update', 'delete', 'find', 'search',
            'start', 'stop', 'run', 'finish'
        ]):
            return True

        # ❌ 丢弃：明显的工具方法
        if any(pattern in method_lower for pattern in [
            'get', 'set', 'is', 'has', 'tostring', 'hashcode', 'equals',
            'clone', 'notify', 'wait', 'finalize'
        ]):
            return False

        # ❌ 丢弃：内部或私有方法标识
        if any(pattern in method_lower for pattern in [
            'private', 'internal', 'helper', 'util', '$', 'lambda$'
        ]):
            return False

        # ❌ 丢弃：测试相关方法（避免在变异中包含测试工具方法）
        if any(pattern in method_lower for pattern in [
            'test', 'mock', 'stub', 'fake', 'assert'
        ]):
            return False

        # 默认保留其他方法（谨慎起见）
        return True

    def _is_meaningful_branch(self, condition: str) -> bool:
        """判断分支是否有意义（能通过测试用例覆盖）"""
        condition_lower = condition.lower()

        # ✅ 保留：含有条件跳转的分支
        if any(keyword in condition_lower for keyword in ['if', 'goto', 'branch']):
            return True

        # ✅ 保留：含有异常相关的分支
        if any(keyword in condition_lower for keyword in ['throw', 'athrow', 'exception']):
            return True

        # ✅ 保留：异常构造相关（前面有new异常）
        if 'invoke' in condition_lower and '<init>' in condition_lower:
            # 检查是否是异常类的构造
            if any(exc in condition_lower for exc in ['exception', 'error', 'throwable']):
                return True

        # ❌ 丢弃：纯赋值操作
        if any(pattern in condition_lower for pattern in ['@parameter', ':=', 'r0 :=']):
            # 检查是否只是简单赋值，没有其他逻辑
            if not any(keyword in condition_lower for keyword in ['if', 'invoke', 'new', 'throw']):
                return False

        # ❌ 丢弃：只有new但没有throw的
        if 'new' in condition_lower and 'exception' in condition_lower:
            if 'throw' not in condition_lower and 'athrow' not in condition_lower:
                return False

        # ❌ 丢弃：纯技术性的JVM内部操作
        if any(tech_pattern in condition_lower for tech_pattern in [
            'node_0:', 'node_1:', 'node_2:',  # 字节码节点
            'specialinvoke r0.<java.lang.object',  # 父类构造调用
            '@this:',  # this指针赋值
            'return;'  # 简单返回
        ]):
            return False

        # 默认保留其他情况
        return True

    def _analyze_path_for_branches(self, path) -> Optional[Dict]:
        """从路径信息分析未覆盖的分支"""
        try:
            if isinstance(path, list) and len(path) >= 2:
                # 尝试从路径中提取方法和条件信息
                method_info = path[0] if path else "Unknown"
                condition_info = path[1] if len(path) > 1 else "Unknown condition"

                # 过滤无意义的分支
                if not self._is_meaningful_branch(str(condition_info)):
                    return None

                return {
                    'method': str(method_info),
                    'condition': str(condition_info),
                    'branch_type': 'conditional',
                    'source_code': self._get_method_source_code(str(method_info))
                }
            elif isinstance(path, str):
                # 对字符串路径也进行过滤
                if not self._is_meaningful_branch(path):
                    return None

                return {
                    'method': path,
                    'condition': 'Path not covered',
                    'branch_type': 'path',
                    'source_code': self._get_method_source_code(path)
                }
        except Exception as e:
            print(f"  分析路径分支失败: {e}")

        return None

    def _extract_branch_methods_source_code(self, uncovered_branches: List[Dict]) -> Dict[str, str]:
        """提取分支对应方法的源码（最多10个）"""
        methods_source = {}
        processed_methods = set()

        for branch_info in uncovered_branches[:10]:
            method_name = branch_info.get('method', '')
            if method_name and method_name not in processed_methods:
                source_code = self._get_method_source_code(method_name)
                if source_code:
                    methods_source[method_name] = source_code
                    processed_methods.add(method_name)

        return methods_source

    def _get_method_source_code(self, method_signature: str) -> str:
        """获取方法的源码（改进版，支持构造器和特殊方法）"""
        if not method_signature:
            return ""

        try:
            # 处理不同的方法签名格式
            if '(' in method_signature:
                # 标准格式: package.Class.method(params)
                if '.' in method_signature:
                    class_part = '.'.join(method_signature.split('.')[:-1])
                    method_part = method_signature.split('.')[-1]
                    method_name = method_part.split('(')[0]
                else:
                    # 只有方法名和参数: method(params)
                    method_name = method_signature.split('(')[0]
                    class_part = None
            else:
                # 没有参数的格式
                if '.' in method_signature:
                    class_part = '.'.join(method_signature.split('.')[:-1])
                    method_name = method_signature.split('.')[-1]
                else:
                    method_name = method_signature
                    class_part = None

            # 特殊处理构造器
            if method_name == '<init>':
                method_name = 'constructor'
                search_pattern = 'public.*\\(.*\\)'
            else:
                search_pattern = method_name

            # 尝试找到源文件
            if class_part:
                java_file_path = self._find_java_source_file(class_part, method_signature)
                if java_file_path and os.path.exists(java_file_path):
                    return self._extract_method_from_file(java_file_path, method_name, method_signature)
            else:
                # 如果没有类名，尝试从当前目标类查找
                return self._try_find_method_in_target_class(method_name, method_signature)

        except Exception as e:
            print(f"  获取方法源码失败 {method_signature}: {e}")

        # 如果找不到源码，返回方法签名作为提示
        return f"// Method signature: {method_signature}\n// Source code not found"

    def _try_find_method_in_target_class(self, method_name: str, method_signature: str) -> str:
        """在当前目标类中查找方法"""
        try:
            # 尝试从项目中推断目标类
            # 这里可以使用统一管理器来获取目标类信息
            target_classes = self._get_likely_target_classes()

            for class_name in target_classes:
                java_file_path = self._find_java_source_file(class_name, method_signature)
                if java_file_path and os.path.exists(java_file_path):
                    source_code = self._extract_method_from_file(java_file_path, method_name, method_signature)
                    if source_code and source_code != "":
                        return source_code
        except Exception as e:
            print(f"  在目标类中查找方法失败: {e}")

        return ""

    def _get_likely_target_classes(self) -> List[str]:
        """获取可能的目标类列表"""
        source_dirs = self._discover_source_directories()
        likely_classes = []

        for src_dir in source_dirs:
            if not os.path.exists(src_dir):
                continue
            for root, _, files in os.walk(src_dir):
                for file in files:
                    if file.endswith(".java"):
                        likely_classes.append(os.path.splitext(file)[0])

        return sorted(set(likely_classes))

    def _find_java_source_file(self, class_name: str, method_signature: str = "") -> Optional[str]:
        """查找Java源文件 - 改进版，支持跨项目智能搜索"""
        print(f"  查找源文件: {class_name}")

        # 提取简单类名
        simple_class_name = class_name.split('.')[-1]
        if '$' in simple_class_name:
            simple_class_name = simple_class_name.split('$')[0]

        # 1. 智能发现所有可能的源码目录
        source_dirs = self._discover_source_directories()

        # 2. 在所有源码目录中递归搜索目标类（支持多个同名类）
        all_candidate_files = []
        for src_dir in source_dirs:
            candidate_files = self._recursive_find_all_class_files(src_dir, simple_class_name)
            all_candidate_files.extend(candidate_files)

        if all_candidate_files:
            if len(all_candidate_files) == 1:
                print(f"  ✓ 找到唯一文件: {all_candidate_files[0]}")
                return all_candidate_files[0]
            else:
                # 多个同名类，需要智能选择
                print(f"  找到多个同名类文件，进行智能选择...")
                # 如果有方法签名信息，用它来选择最佳文件
                if method_signature:
                    # 从方法签名创建未覆盖方法集合进行评分
                    uncovered_methods = {method_signature}
                    best_file = self._select_best_matching_file_for_uncovered_methods(all_candidate_files, uncovered_methods)
                else:
                    # 没有方法签名时使用默认选择逻辑
                    best_file = self._select_best_matching_file(all_candidate_files, class_name)
                print(f"  ✓ 智能选择最佳匹配: {best_file}")
                return best_file

        print(f"  ✗ 未找到源文件: {class_name}")
        return None

    def _extract_method_from_file(self, file_path: str, method_name: str, method_signature: str = "") -> str:
        """从文件中提取指定方法的源码"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = content.split('\n')

            # 特殊处理构造器
            if method_name == 'constructor' or '<init>' in method_signature:
                return self._extract_constructor_from_content(content, method_signature)

            # 普通方法提取
            method_lines = []
            in_method = False
            brace_count = 0

            for i, line in enumerate(lines):
                # 更精确的方法匹配
                if not in_method:
                    # 匹配方法声明: public/private/protected ... methodName(
                    import re
                    method_pattern = rf'\b(?:public|private|protected|static|final).*\s+{re.escape(method_name)}\s*\('
                    if re.search(method_pattern, line):
                        in_method = True
                        # 包含方法的注解和修饰符
                        start_line = max(0, i - 3)  # 向前查找3行以包含注解
                        for j in range(start_line, i):
                            if lines[j].strip().startswith('@') or lines[j].strip().startswith('/**') or lines[j].strip().startswith('*'):
                                method_lines.append(lines[j])

                        method_lines.append(line)
                        brace_count = line.count('{') - line.count('}')
                        continue

                if in_method:
                    method_lines.append(line)
                    brace_count += line.count('{') - line.count('}')

                    if brace_count <= 0:
                        break

            if method_lines:
                # 限制源码长度以控制Token使用
                source_code = '\n'.join(method_lines)
                if len(source_code) > 1000:  # 如果太长，只返回前面部分
                    source_code = source_code[:1000] + "\n    // ... (method continues)"
                return source_code

        except Exception as e:
            print(f"  提取方法源码失败: {e}")

        return ""

    def _extract_existing_tests_for_methods(self, test_code: str, branch_methods_info: Dict[str, str]) -> Dict[str, List[Dict]]:
        """从测试代码中提取对应方法的现有测试"""
        existing_tests = {}

        # 提取所有测试方法
        all_test_methods = self._extract_test_methods_from_code(test_code)

        # 为每个方法查找相关的测试
        for method_signature in branch_methods_info.keys():
            method_short_name = method_signature.split('.')[-1].split('(')[0]
            related_tests = []

            for test_method in all_test_methods:
                if self._test_likely_covers_method(test_method, method_short_name):
                    related_tests.append(test_method)

            if related_tests:
                existing_tests[method_short_name] = related_tests

        return existing_tests

    def _extract_test_methods_from_code(self, test_code: str) -> List[Dict]:
        """从测试代码中提取所有测试方法"""
        import re

        test_methods = []
        lines = test_code.split('\n')

        for i, line in enumerate(lines):
            # 查找@Test注解
            if '@Test' in line:
                # 在后续几行中查找方法声明
                for j in range(i + 1, min(i + 5, len(lines))):
                    method_match = re.search(r'\s+(public|private|protected)?\s*(void|\w+)\s+(\w+)\s*\(', lines[j])
                    if method_match:
                        method_name = method_match.group(3)
                        display_name = self._extract_display_name_from_lines(lines, i)

                        test_methods.append({
                            'name': method_name,
                            'display_name': display_name,
                            'line': j
                        })
                        break

        return test_methods

    def _extract_display_name_from_lines(self, lines: List[str], start_line: int) -> str:
        """从指定位置往前查找@DisplayName注解"""
        import re

        # 向前查找@DisplayName注解
        for i in range(max(0, start_line - 3), start_line + 3):
            if i < len(lines) and '@DisplayName' in lines[i]:
                match = re.search(r'@DisplayName\("([^"]+)"\)', lines[i])
                if match:
                    return match.group(1)
        return ""

    def _test_likely_covers_method(self, test_method: Dict, target_method_name: str) -> bool:
        """判断测试方法是否可能覆盖目标方法"""
        test_name = test_method.get('name', '').lower()
        display_name = test_method.get('display_name', '').lower()
        target_name = target_method_name.lower()

        # 多种匹配策略
        return (
            target_name in test_name or
            target_name in display_name or
            test_name.replace('test', '') in target_name or
            any(word in test_name for word in target_name.split('_')) or
            any(word in display_name for word in target_name.split('_'))
        )

    def _log_llm_interaction(self, operation_type: str, test_class: str, prompt: str, response: str, action: str):
        """记录LLM交互到日志文件"""
        import datetime
        import os

        # 创建日志目录
        log_dir = os.path.join(self.base_dir, "llm_logs")
        os.makedirs(log_dir, exist_ok=True)

        # 创建日志文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"{operation_type}_{test_class}_{timestamp}.log")

        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"操作类型: {operation_type}\n")
                f.write(f"测试类: {test_class}\n")
                f.write(f"动作: {action}\n")
                f.write(f"{'='*80}\n")

                if prompt:
                    f.write(f"\n【提示词】:\n{prompt}\n")

                if response:
                    f.write(f"\n【LLM回复】:\n{response}\n")

                f.write(f"\n{'='*80}\n\n")

        except Exception as e:
            print(f"记录LLM交互日志失败: {e}")

    def _should_skip_mutation(self, coverage_metrics: dict, test_class: str) -> bool:
        """判断是否跳过变异操作（分支覆盖率已达到95%）

        Args:
            coverage_metrics: 覆盖率指标字典
            test_class: 测试类名

        Returns:
            bool: 如果分支覆盖率 >= 95% 则返回True，跳过变异
        """
        branch_coverage = coverage_metrics.get('branch_coverage', 0)

        if branch_coverage >= 95.0:
            print(f"跳过变异：{test_class} 分支覆盖率已达到95%阈值 (当前: {branch_coverage:.1f}%)")
            return True

        return False

    def should_skip_elite_mutation(self, coverage_metrics: dict) -> bool:
        """判断是否跳过精英变异（保持兼容性，内部调用新的方法）

        Args:
            coverage_metrics: 覆盖率指标字典

        Returns:
            bool: 如果分支覆盖率 >= 95% 则返回True，跳过精英变异
        """
        return self._should_skip_mutation(coverage_metrics, "精英测试")

    def _calculate_composite_coverage(self, coverage_metrics: dict) -> float:
        """计算综合覆盖率（保持兼容性）

        Args:
            coverage_metrics: 覆盖率指标字典

        Returns:
            float: 综合覆盖率百分比
        """
        line_coverage = coverage_metrics.get('line_coverage', 0)
        branch_coverage = coverage_metrics.get('branch_coverage', 0)
        method_coverage = coverage_metrics.get('method_coverage', 0)

        # 综合覆盖率 = 50%行覆盖率 + 40%分支覆盖率 + 10%方法覆盖率
        composite_coverage = 0.5 * line_coverage + 0.4 * branch_coverage + 0.1 * method_coverage

        return composite_coverage

    def _extract_constructor_from_content(self, content: str, method_signature: str) -> str:
        """从内容中提取构造器源码"""
        try:
            lines = content.split('\n')

            # 获取类名（从文件中查找public class ClassName）
            class_name = None
            for line in lines:
                import re
                class_match = re.search(r'public\s+class\s+(\w+)', line)
                if class_match:
                    class_name = class_match.group(1)
                    break

            if not class_name:
                return ""

            # 查找构造器
            constructor_lines = []
            in_constructor = False
            brace_count = 0

            for i, line in enumerate(lines):
                if not in_constructor:
                    # 匹配构造器: public ClassName( 或 protected ClassName( 等
                    import re
                    constructor_pattern = rf'\b(?:public|private|protected)\s+{re.escape(class_name)}\s*\('
                    if re.search(constructor_pattern, line):
                        # 检查参数是否匹配（简单检查）
                        if self._constructor_signature_matches(line, method_signature):
                            in_constructor = True
                            # 包含构造器的注解和修饰符
                            start_line = max(0, i - 2)
                            for j in range(start_line, i):
                                if lines[j].strip().startswith('@') or lines[j].strip().startswith('/**'):
                                    constructor_lines.append(lines[j])

                            constructor_lines.append(line)
                            brace_count = line.count('{') - line.count('}')
                            continue

                if in_constructor:
                    constructor_lines.append(line)
                    brace_count += line.count('{') - line.count('}')

                    if brace_count <= 0:
                        break

            if constructor_lines:
                source_code = '\n'.join(constructor_lines)
                if len(source_code) > 1000:
                    source_code = source_code[:1000] + "\n    // ... (constructor continues)"
                return source_code

        except Exception as e:
            print(f"  提取构造器源码失败: {e}")

        return ""

    def _constructor_signature_matches(self, line: str, method_signature: str) -> bool:
        """检查构造器签名是否匹配"""
        try:
            # 简单的参数个数匹配
            if '(' not in method_signature or ')' not in method_signature:
                return True

            # 从签名中提取参数
            sig_params = method_signature.split('(')[1].split(')')[0]
            if sig_params.strip() == '':
                sig_param_count = 0
            else:
                sig_param_count = len([p.strip() for p in sig_params.split(';') if p.strip()])

            # 从代码行中粗略估计参数个数
            line_params = line.split('(')[1].split(')')[0] if '(' in line and ')' in line else ''
            if line_params.strip() == '':
                line_param_count = 0
            else:
                line_param_count = len([p.strip() for p in line_params.split(',') if p.strip()])

            return sig_param_count == line_param_count

        except:
            return True  # 如果解析失败，默认匹配

    def _discover_source_directories(self) -> List[str]:
        """智能发现所有可能的源码目录（跨项目搜索）"""
        source_dirs = []

        # 搜索根目录列表 - 扩展到所有项目
        search_roots = [
            self.base_dir,
            os.path.join(self.base_dir, "dataset")
        ]

        # 如果有指定项目，优先搜索指定项目
        if self.project_name:
            search_roots.insert(0, os.path.join(self.base_dir, "dataset", self.project_name))

        # 过滤None值并检查存在性
        search_roots = [root for root in search_roots if root and os.path.exists(root)]

        # 在每个根目录下查找src/main/java目录
        for root in search_roots:
            # 如果是dataset目录，枚举所有项目子目录
            if root.endswith("dataset"):
                try:
                    for project_dir in os.listdir(root):
                        project_path = os.path.join(root, project_dir)
                        if os.path.isdir(project_path):
                            java_src_path = os.path.join(project_path, "src", "main", "java")
                            if os.path.exists(java_src_path):
                                has_java_files = self._directory_contains_java_files(java_src_path)
                                if has_java_files:
                                    source_dirs.append(java_src_path)
                except Exception as e:
                    continue
            else:
                # 递归查找src/main/java目录
                for dirpath, dirnames, filenames in os.walk(root):
                    # 检查是否是src/main/java目录
                    if dirpath.endswith(os.path.join("src", "main", "java")):
                        # 验证是否包含.java文件
                        has_java_files = self._directory_contains_java_files(dirpath)
                        if has_java_files:
                            source_dirs.append(dirpath)

                    # 限制搜索深度，避免过深的递归
                    if len(dirpath.split(os.sep)) - len(root.split(os.sep)) > 6:
                        dirnames.clear()

        # 去重并排序，优先当前项目
        source_dirs = sorted(list(set(source_dirs)), key=lambda x: (
            0 if self.project_name and self.project_name in x else 1,
            x
        ))
        return source_dirs

    def _directory_contains_java_files(self, directory: str) -> bool:
        """检查目录是否包含Java文件"""
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith('.java'):
                        return True
                # 只检查前几个子目录层级
                if len(root.split(os.sep)) - len(directory.split(os.sep)) > 3:
                    dirs.clear()
            return False
        except Exception:
            return False

    def _recursive_find_all_class_files(self, src_dir: str, target_class: str) -> List[str]:
        """在指定源码目录中递归查找所有同名类文件"""
        found_files = []
        try:
            for root, dirs, files in os.walk(src_dir):
                target_filename = f"{target_class}.java"
                if target_filename in files:
                    file_path = os.path.join(root, target_filename)
                    # 验证文件内容是否确实包含目标类定义
                    if self._verify_class_file_content(file_path, target_class):
                        found_files.append(file_path)
            return found_files
        except Exception as e:
            return []

    def _verify_class_file_content(self, file_path: str, expected_class: str) -> bool:
        """验证Java文件是否确实包含预期的类定义"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 简单验证：检查是否包含类声明
            import re
            class_pattern = r'\b(?:public\s+)?(?:abstract\s+)?class\s+' + re.escape(expected_class) + r'\b'
            return bool(re.search(class_pattern, content))
        except Exception:
            return False

    def _select_best_matching_file_for_uncovered_methods(self, candidate_files: List[str], uncovered_methods: set) -> str:
        """专门针对未覆盖方法选择最佳匹配文件（从crossover移植）"""
        if len(candidate_files) == 1:
            return candidate_files[0]

        # 提取所有未覆盖的方法名
        all_method_names = self._extract_all_method_names_from_signatures(uncovered_methods)

        # 为每个文件计算方法覆盖评分
        best_file = candidate_files[0]
        best_score = 0

        for file_path in candidate_files:
            score = self._calculate_comprehensive_method_score(file_path, uncovered_methods, all_method_names)
            rel_path = self._get_relative_path(file_path)
            print(f"    {rel_path}: 综合评分 {score}")

            if score > best_score:
                best_score = score
                best_file = file_path

        return best_file

    def _select_best_matching_file(self, candidate_files: List[str], class_name: str) -> str:
        """默认的文件选择逻辑"""
        # 简单地返回第一个文件
        return candidate_files[0]

    def _extract_all_method_names_from_signatures(self, uncovered_methods: set) -> List[str]:
        """从未覆盖方法签名中提取所有方法名"""
        method_names = []
        for method_sig in uncovered_methods:
            try:
                if '(' in method_sig:
                    method_part = method_sig.split('(')[0]
                    if '.' in method_part:
                        method_name = method_part.split('.')[-1]
                    else:
                        method_name = method_part

                    if method_name not in ['<init>', '<clinit>'] and len(method_name) > 1:
                        method_names.append(method_name)
            except:
                continue
        return list(set(method_names))

    def _calculate_comprehensive_method_score(self, file_path: str, uncovered_methods: set, method_names: List[str]) -> float:
        """计算文件的综合方法覆盖评分（从crossover移植）"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            score = 0.0

            # 1. 基础方法名匹配评分
            for method_name in method_names:
                if self._method_exists_in_content(content, method_name):
                    score += 1.0

            # 2. JVM签名特定匹配评分（更高权重）
            for method_sig in uncovered_methods:
                if self._signature_specific_match(content, method_sig):
                    score += 2.0

            return score

        except Exception:
            return 0.0

    def _method_exists_in_content(self, content: str, method_name: str) -> bool:
        """检查方法是否在内容中存在"""
        import re
        patterns = [
            r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)?' + re.escape(method_name) + r'\s*\(',
            r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:[\w<>,\s]+\s+)?' + re.escape(method_name) + r'\s*\(',
            r'\b' + re.escape(method_name) + r'\s*\('
        ]

        for pattern in patterns:
            if re.search(pattern, content, re.MULTILINE | re.DOTALL):
                return True
        return False

    def _signature_specific_match(self, content: str, method_sig: str) -> bool:
        """基于JVM签名进行特定匹配"""
        try:
            if '(' not in method_sig:
                return False

            method_part = method_sig.split('(')[0]
            method_name = method_part.split('.')[-1] if '.' in method_part else method_part

            if method_name in ['<init>', '<clinit>']:
                return False

            if not self._method_exists_in_content(content, method_name):
                return False
            return True

        except Exception:
            return False


    def _get_relative_path(self, file_path: str) -> str:
        """获取文件的相对路径用于显示"""
        try:
            parts = file_path.replace('\\', '/').split('/')
            if 'java' in parts:
                idx = parts.index('java')
                return '/'.join(parts[idx+1:])
            else:
                return '/'.join(parts[-3:])
        except:
            return file_path.split('/')[-1]

