"""
智能测试优化器
基于覆盖信息的增量分析法，实现最少测试达到最高覆盖率
"""

import os
import json
import shutil
from typing import Dict, List, Tuple, Optional, Set
from pathlib import Path
import re


class IntelligentTestOptimizer:
    """基于覆盖信息的智能测试优化器"""
    
    def __init__(self, base_dir: str, project_name: str, target_class: str, coverage_analyzer):
        """
        初始化智能测试优化器
        
        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
            target_class: 目标被测类
            coverage_analyzer: 覆盖率分析器实例
        """
        self.base_dir = Path(base_dir).resolve()
        self.project_name = project_name
        self.target_class = target_class
        self.coverage_analyzer = coverage_analyzer
        self.project_dir = self.base_dir / "dataset" / project_name
        self.test_src_dir = self.project_dir / "src" / "test" / "java"
        
    def optimize_final_tests(self, final_gen: int, initial_test_reports: Dict[str, Dict]) -> bool:
        """
        执行最终的测试优化
        
        Args:
            final_gen: 最终代数
            initial_test_reports: 初始测试报告字典
            
        Returns:
            是否成功优化
        """
        print(f"\n{'='*60}")
        print(f"🎯 开始智能测试优化: {self.target_class}")
        print(f"{'='*60}")
        
        try:
            # 1. 检查和补充缺失的覆盖率报告
            complete_test_reports = self._ensure_complete_coverage_reports(final_gen, initial_test_reports)
            if not complete_test_reports:
                print(f"❌ 无法获取完整的测试报告")
                return False
            
            # 2. 过滤出目标类的测试
            target_tests = self._filter_target_tests(complete_test_reports)
            if not target_tests:
                print(f"❌ 没有找到被测类 {self.target_class} 的测试")
                return False
            
            print(f"📊 找到 {len(target_tests)} 个测试进行优化")
            
            # 3. 基于覆盖信息的智能选择
            optimal_combination = self._intelligent_test_selection(target_tests)
            if not optimal_combination:
                print(f"❌ 无法找到最优测试组合")
                return False
            
            # 4. 精确冗余检测
            deduplicated_tests = self._precise_redundancy_detection(optimal_combination)
            
            # 5. 生成最终覆盖率报告
            final_coverage = self._calculate_combined_coverage(deduplicated_tests)
            self._display_optimization_results(deduplicated_tests, final_coverage)
            
            # 6. 测试合并和更新
            success = self._merge_and_update_tests(deduplicated_tests)
            
            if success:
                print(f"✅ 智能优化完成，从 {len(target_tests)} 个测试优化到 {len(deduplicated_tests)} 个测试")
                return True
            else:
                print(f"❌ 更新maven目录失败")
                return False
                
        except Exception as e:
            print(f"❌ 智能优化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _ensure_complete_coverage_reports(self, final_gen: int, initial_reports: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        确保所有测试都有完整的覆盖率报告
        """
        print(f"\n🔍 检查覆盖率报告完整性...")
        
        complete_reports = {}
        missing_reports = []
        
        # 检查每个测试是否有完整的覆盖率报告
        for test_name, report in initial_reports.items():
            if self._is_coverage_report_complete(report):
                complete_reports[test_name] = report
                print(f"   ✅ {test_name}: 报告完整")
            else:
                missing_reports.append(test_name)
                print(f"   ❌ {test_name}: 报告缺失或不完整")
        
        # 为缺失的测试生成覆盖率报告
        if missing_reports:
            print(f"\n📋 为 {len(missing_reports)} 个测试生成覆盖率报告...")
            
            for test_name in missing_reports:
                print(f"   🔄 生成 {test_name} 的覆盖率报告...")
                
                # 使用coverage_analyzer生成报告
                report = self.coverage_analyzer.analyze_test_coverage(test_name, f"Gen{final_gen}", use_cache=False)
                
                if report and self._is_coverage_report_complete(report):
                    complete_reports[test_name] = report
                    print(f"     ✅ 成功生成报告")
                else:
                    print(f"     ❌ 生成报告失败")
        
        print(f"\n📊 最终获得 {len(complete_reports)} 个完整的测试报告")
        return complete_reports
    
    def _is_coverage_report_complete(self, report: Dict) -> bool:
        """
        检查覆盖率报告是否完整
        """
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
    
    def _filter_target_tests(self, test_reports: Dict[str, Dict]) -> Dict[str, Dict]:
        """过滤出目标类的测试"""
        target_tests = {}
        for test_name, report in test_reports.items():
            extracted_class = self._extract_target_class_from_test_name(test_name)
            if extracted_class == self.target_class:
                target_tests[test_name] = report
        return target_tests
    
    def _extract_target_class_from_test_name(self, test_name: str) -> str:
        """从测试类名中提取被测类名"""
        match = re.match(r'^(\w+?)Test(?:V\d+|_Crossover_.*|_Mutation_.*|.*)?$', test_name)
        if match:
            return match.group(1)
        
        # 备用方案
        base_name = re.sub(r'Test.*$', '', test_name)
        return base_name if base_name else test_name
    
    def _intelligent_test_selection(self, target_tests: Dict[str, Dict]) -> List[Tuple[str, Dict]]:
        """
        基于覆盖信息的智能测试选择
        使用贪心算法，每次选择能提供最多新覆盖的测试
        """
        print(f"\n🧠 开始智能测试选择...")
        
        # 1. 按适应度排序，选择最优测试作为基础
        sorted_tests = sorted(target_tests.items(), key=lambda x: x[1]["fitness"], reverse=True)
        best_test_name, best_report = sorted_tests[0]
        
        print(f"📈 基础测试: {best_test_name}")
        print(f"   行覆盖率: {best_report['metrics']['line_coverage']:.2f}%")
        print(f"   分支覆盖率: {best_report['metrics']['branch_coverage']:.2f}%")
        print(f"   方法覆盖率: {best_report['metrics']['method_coverage']:.2f}%")
        print(f"   适应度: {best_report['fitness']:.4f}")
        
        # 2. 初始化已覆盖集合
        covered_methods = set(best_report.get('covered_methods', []))
        covered_paths = set()
        for path in best_report.get('covered_paths', []):
            if isinstance(path, list):
                covered_paths.add(tuple(path))  # 转换为元组便于集合操作
            else:
                covered_paths.add(path)
        
        # 3. 计算所有测试的总覆盖目标（并集）
        all_methods = set()
        all_paths = set()
        
        for test_name, report in target_tests.items():
            all_methods.update(report.get('covered_methods', []))
            for path in report.get('covered_paths', []):
                if isinstance(path, list):
                    all_paths.add(tuple(path))
                else:
                    all_paths.add(path)
        
        print(f"📊 总覆盖目标: {len(all_methods)} 个方法, {len(all_paths)} 个路径")
        
        # 4. 贪心选择补充测试
        selected_tests = [(best_test_name, best_report)]
        remaining_tests = [(name, report) for name, report in sorted_tests[1:]]
        
        iteration = 1
        while remaining_tests:
            print(f"\n🔄 第 {iteration} 轮选择...")
            
            best_contribution = 0
            best_candidate = None
            best_details = None
            
            # 计算每个候选测试的贡献
            for test_name, report in remaining_tests:
                contribution, details = self._calculate_test_contribution(
                    report, covered_methods, covered_paths
                )
                
                print(f"   {test_name}: 贡献 {contribution} (方法: {details['new_methods']}, 路径: {details['new_paths']})")
                
                if contribution > best_contribution:
                    best_contribution = contribution
                    best_candidate = (test_name, report)
                    best_details = details
            
            # 如果没有测试能提供显著贡献，停止选择
            if best_contribution == 0:
                print(f"   ❌ 没有测试能提供新覆盖，停止选择")
                break
            
            # 添加最佳候选测试
            selected_tests.append(best_candidate)
            remaining_tests.remove(best_candidate)
            
            # 更新已覆盖集合
            covered_methods.update(best_candidate[1].get('covered_methods', []))
            for path in best_candidate[1].get('covered_paths', []):
                if isinstance(path, list):
                    covered_paths.add(tuple(path))
                else:
                    covered_paths.add(path)
            
            print(f"   ✅ 选择: {best_candidate[0]} (贡献: {best_contribution})")
            print(f"   📊 累计覆盖: {len(covered_methods)} 个方法, {len(covered_paths)} 个路径")
            
            iteration += 1
        
        # 5. 检查是否达到完美覆盖
        coverage_ratio = (len(covered_methods) + len(covered_paths)) / (len(all_methods) + len(all_paths))
        print(f"\n📋 智能选择结果:")
        print(f"   选择测试数: {len(selected_tests)}")
        print(f"   覆盖完整度: {coverage_ratio:.2%}")
        
        for i, (test_name, report) in enumerate(selected_tests, 1):
            print(f"   {i}. {test_name} (适应度: {report['fitness']:.4f})")
        
        return selected_tests
    
    def _calculate_test_contribution(self, report: Dict, covered_methods: Set, covered_paths: Set) -> Tuple[int, Dict]:
        """计算测试的贡献度"""
        test_methods = set(report.get('covered_methods', []))
        test_paths = set()
        
        for path in report.get('covered_paths', []):
            if isinstance(path, list):
                test_paths.add(tuple(path))
            else:
                test_paths.add(path)
        
        # 计算新覆盖的方法和路径
        new_methods = test_methods - covered_methods
        new_paths = test_paths - covered_paths
        
        # 计算总贡献（可以调整权重）
        contribution = len(new_methods) + len(new_paths)
        
        details = {
            'new_methods': len(new_methods),
            'new_paths': len(new_paths),
            'new_methods_list': list(new_methods),
            'new_paths_list': list(new_paths)
        }
        
        return contribution, details
    
    def _precise_redundancy_detection(self, tests: List[Tuple[str, Dict]]) -> List[Tuple[str, Dict]]:
        """
        精确的冗余检测
        基于每个测试的独特贡献来决定是否保留
        """
        print(f"\n🔍 开始精确冗余检测...")
        
        if len(tests) <= 1:
            return tests
        
        # 计算每个测试的独特贡献
        unique_tests = []
        total_covered_methods = set()
        total_covered_paths = set()
        
        for i, (test_name, report) in enumerate(tests):
            test_methods = set(report.get('covered_methods', []))
            test_paths = set()
            
            for path in report.get('covered_paths', []):
                if isinstance(path, list):
                    test_paths.add(tuple(path))
                else:
                    test_paths.add(path)
            
            # 计算这个测试的独特贡献
            unique_methods = test_methods - total_covered_methods
            unique_paths = test_paths - total_covered_paths
            
            unique_contribution = len(unique_methods) + len(unique_paths)
            
            print(f"   {i+1}. {test_name}:")
            print(f"      独特方法: {len(unique_methods)}")
            print(f"      独特路径: {len(unique_paths)}")
            print(f"      总贡献: {unique_contribution}")
            
            # 如果有独特贡献，保留测试
            if unique_contribution > 0:
                unique_tests.append((test_name, report))
                total_covered_methods.update(test_methods)
                total_covered_paths.update(test_paths)
                print(f"      ✅ 保留")
            else:
                print(f"      ❌ 冗余，删除")
        
        print(f"\n📊 冗余检测结果: {len(tests)} → {len(unique_tests)} 个测试")
        return unique_tests
    
    def _calculate_combined_coverage(self, selected_tests: List[Tuple[str, Dict]]) -> Dict:
        """计算组合测试的覆盖率"""
        combined_methods = set()
        combined_paths = set()
        
        for test_name, report in selected_tests:
            combined_methods.update(report.get('covered_methods', []))
            for path in report.get('covered_paths', []):
                if isinstance(path, list):
                    combined_paths.add(tuple(path))
                else:
                    combined_paths.add(path)
        
        # 计算组合覆盖率（这里使用简化的方法）
        # 实际应该基于目标类的总方法数和路径数
        if selected_tests:
            # 使用最优测试的metrics作为基准，然后估算提升
            base_metrics = selected_tests[0][1]['metrics']
            
            # 简化计算：假设组合覆盖率不低于最优测试
            combined_coverage = {
                'method_coverage': base_metrics.get('method_coverage', 0),
                'line_coverage': base_metrics.get('line_coverage', 0),
                'branch_coverage': base_metrics.get('branch_coverage', 0),
                'covered_methods_count': len(combined_methods),
                'covered_paths_count': len(combined_paths)
            }
        else:
            combined_coverage = {
                'method_coverage': 0,
                'line_coverage': 0,
                'branch_coverage': 0,
                'covered_methods_count': 0,
                'covered_paths_count': 0
            }
        
        return combined_coverage
    
    def _display_optimization_results(self, selected_tests: List[Tuple[str, Dict]], coverage: Dict):
        """显示优化结果"""
        print(f"\n📊 优化结果摘要:")
        print(f"   最终测试数量: {len(selected_tests)}")
        print(f"   覆盖方法数: {coverage['covered_methods_count']}")
        print(f"   覆盖路径数: {coverage['covered_paths_count']}")
        print(f"   估计方法覆盖率: {coverage['method_coverage']:.2f}%")
        print(f"   估计行覆盖率: {coverage['line_coverage']:.2f}%")
        print(f"   估计分支覆盖率: {coverage['branch_coverage']:.2f}%")
        
        print(f"\n🎯 最终选择的测试:")
        for i, (test_name, report) in enumerate(selected_tests, 1):
            print(f"   {i}. {test_name} (适应度: {report['fitness']:.4f})")
    
    def _merge_and_update_tests(self, selected_tests: List[Tuple[str, Dict]]) -> bool:
        """合并测试并更新maven目录"""
        print(f"\n🔧 开始测试合并和更新...")
        
        try:
            if len(selected_tests) == 1:
                # 只有一个测试，直接重命名
                return self._update_single_test(selected_tests[0])
            else:
                # 多个测试，需要合并
                return self._merge_multiple_tests(selected_tests)
        except Exception as e:
            print(f"❌ 合并和更新失败: {e}")
            return False
    
    def _update_single_test(self, test_info: Tuple[str, Dict]) -> bool:
        """更新单个测试"""
        test_name, report = test_info
        print(f"   📝 更新单个测试: {test_name}")
        
        # 查找原始测试文件
        original_file = self._find_test_source_file(test_name)
        if not original_file:
            print(f"   ❌ 未找到测试文件: {test_name}")
            return False
        
        # 读取并重命名
        with open(original_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 重命名类名
        new_class_name = f"{self.target_class}TestV"
        content = self._rename_class_in_content(content, new_class_name)
        
        # 更新maven目录
        return self._write_final_test(content, new_class_name)
    
    def _merge_multiple_tests(self, selected_tests: List[Tuple[str, Dict]]) -> bool:
        """合并多个测试"""
        print(f"   📝 合并 {len(selected_tests)} 个测试...")
        
        merged_content = self._create_merged_test_content(selected_tests)
        if not merged_content:
            return False
        
        new_class_name = f"{self.target_class}TestV"
        return self._write_final_test(merged_content, new_class_name)
    
    def _create_merged_test_content(self, selected_tests: List[Tuple[str, Dict]]) -> Optional[str]:
        """创建合并的测试内容"""
        imports = set()
        package_declaration = ""
        all_methods = []
        
        for i, (test_name, report) in enumerate(selected_tests):
            print(f"     处理测试 {i+1}: {test_name}")
            
            test_file = self._find_test_source_file(test_name)
            if not test_file:
                print(f"       ❌ 未找到测试文件: {test_name}")
                continue
            
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取包声明、导入和测试方法
            if i == 0:
                package_declaration = self._extract_package_declaration(content)
            
            imports.update(self._extract_imports(content))
            methods = self._extract_test_methods(content, i + 1)
            all_methods.extend(methods)
            
            print(f"       ✅ 提取了 {len(methods)} 个测试方法")
        
        if not all_methods:
            print(f"     ❌ 没有提取到任何测试方法")
            return None
        
        # 生成合并后的测试文件
        merged_content = self._generate_merged_test_file(
            package_declaration, imports, all_methods
        )
        
        print(f"     ✅ 成功合并 {len(all_methods)} 个测试方法")
        return merged_content
    
    def _find_test_source_file(self, test_name: str) -> Optional[str]:
        """查找测试源文件"""
        for root, dirs, files in os.walk(self.test_src_dir):
            for file in files:
                if file == f"{test_name}.java":
                    return os.path.join(root, file)
        return None
    
    def _extract_package_declaration(self, content: str) -> str:
        """提取包声明"""
        match = re.search(r'package\s+[^;]+;', content)
        return match.group(0) if match else ""
    
    def _extract_imports(self, content: str) -> Set[str]:
        """提取导入语句"""
        imports = set()
        for match in re.finditer(r'import\s+[^;]+;', content):
            imports.add(match.group(0))
        return imports
    
    def _extract_test_methods(self, content: str, test_index: int) -> List[str]:
        """提取测试方法"""
        methods = []
        
        # 更精确的测试方法匹配
        # 匹配 @Test 注解后的方法
        pattern = r'(@Test[^}]*?public\s+void\s+(\w+)\s*\([^)]*\)\s*\{(?:[^{}]*\{[^{}]*\}[^{}]*)*[^{}]*\})'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            method_content = match.group(1)
            method_name = match.group(2)
            
            # 重命名方法以避免冲突
            new_method_name = f"{method_name}_from_test{test_index}"
            new_method_content = method_content.replace(
                f"public void {method_name}(", 
                f"public void {new_method_name}("
            )
            
            methods.append(new_method_content)
        
        return methods
    
    def _generate_merged_test_file(self, package_declaration: str, imports: Set[str], methods: List[str]) -> str:
        """生成合并后的测试文件"""
        lines = []
        
        # 添加包声明
        if package_declaration:
            lines.append(package_declaration)
            lines.append("")
        
        # 添加导入语句
        if imports:
            lines.extend(sorted(imports))
            lines.append("")
        
        # 添加类声明
        lines.append(f"public class {self.target_class}TestV {{")
        lines.append("")
        
        # 添加所有测试方法
        for method in methods:
            # 缩进处理
            indented_method = "\n".join("    " + line for line in method.split("\n"))
            lines.append(indented_method)
            lines.append("")
        
        # 结束类
        lines.append("}")
        
        return "\n".join(lines)
    
    def _rename_class_in_content(self, content: str, new_class_name: str) -> str:
        """重命名类名"""
        # 替换类声明
        content = re.sub(r'public\s+class\s+\w+', f'public class {new_class_name}', content)
        return content
    
    def _write_final_test(self, content: str, class_name: str) -> bool:
        """写入最终测试文件"""
        try:
            # 查找包路径
            package_path = self._find_target_package_path()
            if package_path is None:
                print(f"❌ 无法找到 {self.target_class} 的包路径")
                return False
            
            target_package_dir = self.test_src_dir / package_path.replace(".", "/")
            
            # 删除现有的测试文件
            print(f"   🗑️  删除现有测试文件...")
            # 导入配置常量
            from .constants import TESTS_PER_GENERATION
            for i in range(1, TESTS_PER_GENERATION + 1):
                test_file = target_package_dir / f"{self.target_class}TestV{i}.java"
                if test_file.exists():
                    test_file.unlink()
                    print(f"     删除: {self.target_class}TestV{i}.java")
            
            # 创建新的优化测试文件
            final_test_file = target_package_dir / f"{class_name}.java"
            with open(final_test_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"   ✅ 创建最终测试文件: {class_name}.java")
            return True
            
        except Exception as e:
            print(f"   ❌ 写入最终测试文件失败: {e}")
            return False
    
    def _find_target_package_path(self) -> Optional[str]:
        """查找目标类的包路径"""
        # 策略1: 搜索现有的TestV1文件
        for root, dirs, files in os.walk(self.test_src_dir):
            for file in files:
                if file == f"{self.target_class}TestV1.java":
                    rel_path = os.path.relpath(root, self.test_src_dir)
                    if rel_path == ".":
                        return ""  # 默认包
                    else:
                        return rel_path.replace(os.sep, ".")
        
        # 策略2: 搜索任意包含目标类名的测试文件
        for root, dirs, files in os.walk(self.test_src_dir):
            for file in files:
                if file.startswith(f"{self.target_class}Test") and file.endswith(".java"):
                    rel_path = os.path.relpath(root, self.test_src_dir)
                    if rel_path == ".":
                        return ""  # 默认包
                    else:
                        return rel_path.replace(os.sep, ".")
        
        # 策略3: 从源码目录查找目标类
        src_dir = self.project_dir / "src" / "main" / "java"
        if src_dir.exists():
            for root, dirs, files in os.walk(src_dir):
                for file in files:
                    if file == f"{self.target_class}.java":
                        rel_path = os.path.relpath(root, src_dir)
                        if rel_path == ".":
                            return ""  # 默认包
                        else:
                            return rel_path.replace(os.sep, ".")
        
        return ""  # 默认包作为最后回退