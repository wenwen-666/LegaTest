"""
覆盖率分析模块
负责解析JaCoCo和Surefire报告，计算适应度值
"""

import os
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional, Set
import re
from pathlib import Path
import random

class CoverageAnalyzer:
    """覆盖率分析器，负责解析测试报告并计算适应度"""
    
    def __init__(self, base_dir: str, project_name: str):
        """
        初始化覆盖率分析器
        
        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
        """
        self.base_dir = Path(base_dir).resolve()
        self.project_name = project_name
        self.dataset_dir = self.base_dir / "dataset"
        self.project_dir = self.dataset_dir / project_name
        self.coverage_cache = {}  # 覆盖率缓存：{test_class: coverage_report}
    
    def analyze_test_coverage(self, test_class: str, generation: Optional[str] = None, use_cache: bool = True) -> Optional[Dict]:
        """
        分析测试覆盖率并生成完整报告
        
        Args:
            test_class: 测试类名称
            generation: 世代标识（如"Gen1", "Gen2"等）
            use_cache: 是否使用缓存
            
        Returns:
            Dict: 包含所有覆盖率指标和适应度的完整报告
        """
        # 设置当前代数，供其他方法使用，规范化格式
        if generation is None:
            self.current_generation = "Gen1"
        elif isinstance(generation, int):
            self.current_generation = f"Gen{generation}"
        elif isinstance(generation, str):
            # 如果已经是Gen开头的格式，直接使用；否则添加Gen前缀
            if generation.startswith("Gen"):
                self.current_generation = generation
            else:
                self.current_generation = f"Gen{generation}"
        else:
            self.current_generation = str(generation)
        
        # 检查缓存
        cache_key = f"{test_class}_{self.current_generation}"
        if use_cache and cache_key in self.coverage_cache:
            print(f"使用缓存的覆盖率报告: {test_class}")
            return self.coverage_cache[cache_key]
        
        print(f"分析测试覆盖率: {test_class}")
        
        # 构建报告目录路径
        test_reports_dir = Path(self.base_dir) / "test_reports" / self.project_name / self.current_generation / test_class
        
        if not test_reports_dir.exists():
            print(f"测试报告目录不存在: {test_reports_dir}")
            return None
        
        # 获取报告文件路径
        jacoco_xml = test_reports_dir / "jacoco" / "jacoco.xml"
        surefire_xml = self._find_surefire_xml(test_reports_dir, test_class)
        
        # 提取目标类名
        target_class = self._extract_target_class_name(test_class)
        
        # 解析各种报告
        jacoco_data = self._parse_jacoco_xml(jacoco_xml)
        if not jacoco_data:
            print(f"JaCoCo报告解析失败: {test_class}")
            return None
        
        failed, time_seconds, test_summary = self._parse_surefire_xml(surefire_xml)
        covered_paths, uncovered_paths = self._parse_cfg_file(target_class, jacoco_data)
        
        # 提取测试方法信息
        test_methods_info = self._extract_test_methods_info(test_class, surefire_xml)
        
        # 计算适应度值
        fitness = self._compute_fitness(jacoco_data["metrics"], failed, time_seconds, test_summary)
        
        # 计算覆盖率百分比
        metrics = self._calculate_coverage_percentages(jacoco_data["metrics"])
        
        # 构建最终报告
        report = {
            "test_class": test_class,
            "target_class": target_class,
            "metrics": metrics,
            "failed": failed,
            "time_seconds": time_seconds,
            "fitness": fitness,
            "covered_methods": jacoco_data["covered_methods"],
            "uncovered_methods": jacoco_data["uncovered_methods"],
            "covered_paths": covered_paths,
            "uncovered_paths": uncovered_paths,
            "test_summary": test_summary,
            "test_methods_info": test_methods_info,
            "report_summary": {
                "line_coverage": f"{metrics.get('line_coverage', 0):.2f}%",
                "branch_coverage": f"{metrics.get('branch_coverage', 0):.2f}%",
                "method_coverage": f"{metrics.get('method_coverage', 0):.2f}%",
                "total_tests": test_summary.get('total_tests', 0) if test_summary else 0,
                "failed_tests": test_summary.get('failed_tests', 0) if test_summary else (1 if failed else 0),
                "assertion_failed_tests": test_summary.get('assertion_failed_tests', 0) if test_summary else 0,
                "runtime_failed_tests": test_summary.get('runtime_failed_tests', 0) if test_summary else 0,
                "successfully_run_tests": test_summary.get('successfully_run_tests', 0) if test_summary else 0,
                "fitness_score": f"{fitness:.4f}",
                "success_rate": f"{test_summary.get('success_rate', 0) if test_summary else (0 if failed else 100):.2f}%",
                "assertion_failure_rate": f"{test_summary.get('assertion_failure_rate', 0) if test_summary else 0:.2f}%",
                "runtime_failure_rate": f"{test_summary.get('runtime_failure_rate', 0) if test_summary else 0:.2f}%",
                "execution_time": f"{time_seconds:.3f}s"
            }
        }
        
        # 保存报告到JSON文件
        output_path = test_reports_dir / "coverage_report.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # 缓存报告
        if use_cache:
            self.coverage_cache[cache_key] = report
        
        print(f"✅ 生成覆盖率报告: {test_class} (适应度: {fitness:.4f})")
        return report
    
    def clear_cache(self):
        """清空覆盖率缓存"""
        self.coverage_cache.clear()
        print("✅ 已清空覆盖率缓存")
    
    def _extract_target_class_name(self, test_class_name: str) -> str:
        """从测试类名称中提取目标类名称"""
        # 支持多种格式
        if "TestV" in test_class_name:
            match = re.match(r"(.+?)TestV\d+$", test_class_name)
            if match:
                return match.group(1)
        elif "Test_Crossover_Gen" in test_class_name:
            return test_class_name.split("Test_Crossover_Gen")[0]
        elif "Test_Mutation_Gen" in test_class_name:
            return test_class_name.split("Test_Mutation_Gen")[0]
        
        return test_class_name.replace("Test", "")
    
    def _find_surefire_xml(self, test_reports_dir: Path, test_class: str) -> Path:
        """查找Surefire XML报告文件"""
        surefire_dir = test_reports_dir / "surefire"
        
        if surefire_dir.exists():
            # 查找匹配的XML文件
            for xml_file in surefire_dir.glob("*.xml"):
                if test_class in xml_file.name and xml_file.name.startswith("TEST-"):
                    return xml_file
        
        if surefire_dir.exists():
            for xml_file in surefire_dir.glob(f"TEST-*.{test_class}.xml"):
                return xml_file
        
        return surefire_dir / f"TEST-{test_class}.xml"
    
    def _parse_jacoco_xml(self, xml_path: Path) -> Optional[Dict]:
        """解析JaCoCo XML报告，提取覆盖率指标"""
        try:
            if not xml_path.exists():
                print(f"JaCoCo XML文件不存在: {xml_path}")
                return None
            
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            
            # 初始化指标
            metrics = {
                "lines_covered": 0,
                "lines_total": 0,
                "branches_covered": 0,
                "branches_total": 0,
                "methods_covered": 0,
                "methods_total": 0
            }
            
            covered_methods = set()
            uncovered_methods = set()
            
            # 遍历所有包和类
            for package in root.findall('./package'):
                for class_elem in package.findall('./class'):
                    # 处理每个方法
                    for method in class_elem.findall('./method'):
                        method_name = method.get('name', '')
                        method_desc = method.get('desc', '')
                        method_signature = f"{method_name}{method_desc}"
                        
                        # 检查方法覆盖情况
                        method_covered = False
                        has_method_counter = False
                        
                        # 首先尝试查找方法级别的METHOD计数器
                        for counter in method.findall('./counter'):
                            if counter.get('type') == 'METHOD':
                                has_method_counter = True
                                covered = int(counter.get('covered', 0))
                                missed = int(counter.get('missed', 0))
                                
                                if covered > 0:
                                    method_covered = True
                                    metrics["methods_covered"] += 1
                                
                                metrics["methods_total"] += 1
                                break
                        
                        # 如果没有方法级别的METHOD计数器，使用INSTRUCTION计数器作为替代
                        if not has_method_counter:
                            for counter in method.findall('./counter'):
                                if counter.get('type') == 'INSTRUCTION':
                                    covered = int(counter.get('covered', 0))
                                    missed = int(counter.get('missed', 0))
                                    
                                    if covered > 0:
                                        method_covered = True
                                        metrics["methods_covered"] += 1
                                    
                                    metrics["methods_total"] += 1
                                    break
                        
                        # 记录方法覆盖状态
                        if method_covered:
                            covered_methods.add(method_signature)
                        else:
                            uncovered_methods.add(method_signature)
                    
                    # 收集行和分支覆盖率指标
                    for counter in class_elem.findall('./counter'):
                        counter_type = counter.get('type')
                        covered = int(counter.get('covered', 0))
                        missed = int(counter.get('missed', 0))
                        
                        if counter_type == 'LINE':
                            metrics["lines_covered"] += covered
                            metrics["lines_total"] += (covered + missed)
                        elif counter_type == 'BRANCH':
                            metrics["branches_covered"] += covered
                            metrics["branches_total"] += (covered + missed)
            
            return {
                "metrics": metrics,
                "covered_methods": list(covered_methods),
                "uncovered_methods": list(uncovered_methods)
            }
            
        except Exception as e:
            print(f"解析JaCoCo XML时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _parse_surefire_xml(self, xml_path: Path) -> Tuple[bool, float, Dict]:
        """解析Surefire XML报告，提取测试执行信息"""
        try:
            if not xml_path.exists():
                print(f"Surefire XML文件不存在: {xml_path}")
                return False, 0.0, self._empty_test_summary()
            
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            
            # 获取基本统计信息
            time_seconds = float(root.get('time', 0))
            total_tests = int(root.get('tests', 0))
            failed_tests = int(root.get('failures', 0))
            error_tests = int(root.get('errors', 0))
            skipped_tests = int(root.get('skipped', 0))
            
            # 计算失败率和成功率
            total_executed = total_tests - skipped_tests
            failure_rate = (failed_tests + error_tests) / total_executed if total_executed > 0 else 0.0
            failed = (failed_tests + error_tests) > 0
            
            # 计算成功率
            passed_tests = total_tests - failed_tests - error_tests - skipped_tests
            success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0.0
            
            # 收集失败的测试用例详细信息并分类统计
            failed_test_cases, assertion_failed_count, runtime_failed_count = self._extract_failed_test_cases(root)
            
            # 计算可执行测试用例数（排除跳过的）
            executable_tests = total_tests - skipped_tests
            
            # 计算成功运行测试用例数（可执行 - 运行时异常）
            successfully_run_tests = executable_tests - runtime_failed_count
            
            # 计算断言错误率（断言失败测试用例数 / 成功运行测试用例数）
            assertion_failure_rate = 0.0
            if successfully_run_tests > 0:
                assertion_failure_rate = (assertion_failed_count / successfully_run_tests) * 100
            
            # 计算运行时错误率（运行时异常测试用例数 / 可执行测试用例数）
            runtime_failure_rate = 0.0
            if executable_tests > 0:
                runtime_failure_rate = (runtime_failed_count / executable_tests) * 100
            
            test_summary = {
                "total_tests": total_tests,
                "failed_tests": failed_tests + error_tests,
                "passed_tests": passed_tests,
                "skipped_tests": skipped_tests,
                "assertion_failed_tests": assertion_failed_count,
                "runtime_failed_tests": runtime_failed_count,
                "successfully_run_tests": successfully_run_tests,
                "failure_rate": round(failure_rate, 4),
                "success_rate": round(success_rate, 2),
                "assertion_failure_rate": round(assertion_failure_rate, 2),
                "runtime_failure_rate": round(runtime_failure_rate, 2),
                "failed_test_cases": failed_test_cases
            }
            
            return failed, time_seconds, test_summary
            
        except Exception as e:
            print(f"解析Surefire XML时出错: {e}")
            return False, 0.0, self._empty_test_summary()
    
    def _extract_failed_test_cases(self, root: ET.Element) -> Tuple[List[Dict], int, int]:
        """提取失败的测试用例详细信息并统计断言失败和运行时异常数量"""
        failed_test_cases = []
        assertion_failed_count = 0
        runtime_failed_count = 0
        
        for testcase in root.findall('./testcase'):
            test_name = testcase.get('name', 'unknown')
            test_class = testcase.get('classname', 'unknown')
            test_time = float(testcase.get('time', 0))
            
            # 检查失败或错误
            failure = testcase.find('failure')
            error = testcase.find('error')
            
            if failure is not None or error is not None:
                failure_info = self._parse_failure_info(failure, error)
                
                failed_test_case = {
                    "name": test_name,
                    "class": test_class,
                    "time": test_time,
                    **failure_info
                }
                
                failed_test_cases.append(failed_test_case)
                
                # 根据失败原因分类统计
                if failure_info["reason"] == "断言失败" or failure_info["reason"] == "比较失败":
                    assertion_failed_count += 1
                else:
                    runtime_failed_count += 1
        
        return failed_test_cases, assertion_failed_count, runtime_failed_count
    
    def _parse_failure_info(self, failure: Optional[ET.Element], error: Optional[ET.Element]) -> Dict:
        """解析失败信息"""
        failure_info = {
            "message": "",
            "type": "",
            "detail": "",
            "reason": "未知错误"
        }
        
        element = failure if failure is not None else error
        
        if element is not None:
            failure_info["message"] = element.get('message', '')
            failure_info["type"] = element.get('type', '')
            failure_info["detail"] = element.text if element.text else ''
            
            # 根据异常类型确定失败原因
            failure_type = failure_info["type"]
            if "AssertionFailedError" in failure_type or "AssertionError" in failure_type:
                failure_info["reason"] = "断言失败"
            elif "ComparisonFailure" in failure_type:
                failure_info["reason"] = "比较失败"
            elif "MockitoException" in failure_type:
                failure_info["reason"] = "Mock框架异常"
            elif "NullPointerException" in failure_type:
                failure_info["reason"] = "空指针异常"
            elif "IllegalArgumentException" in failure_type:
                failure_info["reason"] = "非法参数异常"
            elif "ClassCastException" in failure_type:
                failure_info["reason"] = "类型转换异常"
            else:
                failure_info["reason"] = f"异常: {failure_type}"
        
        return failure_info
    
    def _empty_test_summary(self) -> Dict:
        """返回空的测试摘要"""
        return {
            "total_tests": 0,
            "failed_tests": 0,
            "passed_tests": 0,
            "skipped_tests": 0,
            "assertion_failed_tests": 0,
            "runtime_failed_tests": 0,
            "successfully_run_tests": 0,
            "failure_rate": 0.0,
            "success_rate": 0.0,
            "assertion_failure_rate": 0.0,
            "runtime_failure_rate": 0.0,
            "failed_test_cases": []
        }
    
    def _parse_cfg_file(self, target_class: str, jacoco_data: Optional[Dict] = None) -> Tuple[List[List[str]], List[List[str]]]:
        """
        解析CFG（控制流图）文件，提取路径信息
        """
        # CFG文件基础路径 - 修改为新的位置
        cfg_base_path = Path(__file__).parent / "soot-output" / self.project_name
        
        # 首先尝试主类CFG文件
        main_cfg_path = cfg_base_path / f"{target_class}.cfg.json"
        
        if main_cfg_path.exists():
            try:
                return self._parse_cfg_data(main_cfg_path, jacoco_data)
            except Exception as e:
                print(f"解析主类CFG文件时出错: {e}")
        
        # 如果主类CFG不存在，尝试查找相关的内部类CFG文件
        inner_class_cfgs = list(cfg_base_path.glob(f"{target_class}$*.cfg.json"))
        
        if inner_class_cfgs:
            print(f"主类CFG不存在，找到 {len(inner_class_cfgs)} 个内部类CFG文件: {target_class}")
            covered_paths = []
            uncovered_paths = []
            
            # 合并所有内部类的路径信息
            for cfg_path in inner_class_cfgs:
                try:
                    inner_covered, inner_uncovered = self._parse_cfg_data(cfg_path, jacoco_data)
                    covered_paths.extend(inner_covered)
                    uncovered_paths.extend(inner_uncovered)
                except Exception as e:
                    print(f"解析内部类CFG文件 {cfg_path.name} 时出错: {e}")
            
            return covered_paths, uncovered_paths
        
        print(f"CFG文件不存在（主类和内部类都不存在）: {target_class}")
        return [], []
    
    def _parse_cfg_data(self, cfg_path: Path, jacoco_data: Optional[Dict]) -> Tuple[List[List[str]], List[List[str]]]:
        """解析CFG数据 - 适配cfg_output_fixed格式"""
        covered_paths = []
        uncovered_paths = []
        
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg_data = json.load(f)
        
        # 适配新的CFG格式：cfg_output_fixed格式使用methods数组而不是methods对象
        if 'methods' not in cfg_data:
            return covered_paths, uncovered_paths
        
        methods = cfg_data['methods']
        
        # 处理methods数组格式（cfg_output_fixed格式）
        if isinstance(methods, list):
            for method_info in methods:
                if 'nodes' not in method_info:
                    continue
                
                method_sig = method_info.get('methodSignature', '')
                nodes = method_info['nodes']
                
                # 判断方法是否被覆盖
                method_is_covered = self._is_method_covered(method_sig, jacoco_data)
                
                # 从nodes构建路径
                for node in nodes:
                    node_id = node.get('id', 0)
                    statements = node.get('statements', [])
                    successors = node.get('successors', [])
                    
                    if statements:
                        # 为每个后继节点创建路径
                        if successors:
                            for successor in successors:
                                path = [
                                    method_sig,
                                    f"node_{node_id}:{statements[0][:50]}...",  # 截断太长的语句
                                    f"node_{successor}"
                                ]
                                
                                if method_is_covered:
                                    if self._should_mark_path_covered(jacoco_data):
                                        covered_paths.append(path)
                                    else:
                                        uncovered_paths.append(path)
                                else:
                                    uncovered_paths.append(path)
                        else:
                            # 没有后继节点（出口节点）
                            path = [method_sig, f"node_{node_id}:{statements[0][:50]}..."]
                            if method_is_covered:
                                covered_paths.append(path)
                            else:
                                uncovered_paths.append(path)
        
        # 处理旧的methods对象格式（保持向后兼容）
        elif isinstance(methods, dict):
            for method_sig, method_info in methods.items():
                if 'blocks' not in method_info or 'edges' not in method_info:
                    continue
                
                blocks = method_info['blocks']
                edges = method_info['edges']
                
                # 判断方法是否被覆盖
                method_is_covered = self._is_method_covered(method_sig, jacoco_data)
                
                # 根据边信息构建路径
                if edges:
                    for edge in edges:
                        path = self._build_path_from_edge(edge, blocks, method_sig)
                        if path:
                            if method_is_covered:
                                if self._should_mark_path_covered(jacoco_data):
                                    covered_paths.append(path)
                                else:
                                    uncovered_paths.append(path)
                            else:
                                uncovered_paths.append(path)
                else:
                    # 没有边信息，只有基本块
                    for block_id, block_info in blocks.items():
                        path = [method_sig, f"{block_id}:{block_info.get('head', '')}"]
                        if method_is_covered:
                            covered_paths.append(path)
                        else:
                            uncovered_paths.append(path)
        
        return covered_paths, uncovered_paths
    
    def _is_method_covered(self, method_sig: str, jacoco_data: Optional[Dict]) -> bool:
        """判断方法是否被覆盖"""
        if not jacoco_data or 'covered_methods' not in jacoco_data:
            return False
        
        method_name = self._extract_method_name_from_signature(method_sig)
        if not method_name:
            return False
        
        # 检查是否在覆盖的方法列表中
        for covered_method in jacoco_data['covered_methods']:
            if method_name in covered_method:
                return True
        
        return False
    
    def _extract_method_name_from_signature(self, method_sig: str) -> str:
        """从方法签名中提取方法名"""
        try:
            # 处理格式: <class: return_type method_name(params)>
            if "<" in method_sig and ":" in method_sig:
                parts = method_sig.split(":")
                if len(parts) >= 2:
                    method_part = parts[1].strip()
                    if " " in method_part:
                        method_with_params = method_part.split(" ")[1]
                        return method_with_params.split("(")[0]
        except Exception:
            pass
        return ""
    
    def _build_path_from_edge(self, edge: Dict, blocks: Dict, method_sig: str) -> Optional[List[str]]:
        """从边信息构建路径"""
        from_block = edge.get('from')
        to_block = edge.get('to')
        
        if not from_block or not to_block:
            return None
        
        if from_block not in blocks or to_block not in blocks:
            return None
        
        return [
            method_sig,
            f"{from_block}:{blocks[from_block].get('head', '')}",
            f"{to_block}:{blocks[to_block].get('head', '')}"
        ]
    
    def _should_mark_path_covered(self, jacoco_data: Optional[Dict]) -> bool:
        """使用确定性方法决定路径是否被覆盖"""
        if not jacoco_data or 'metrics' not in jacoco_data:
            return False
        
        metrics = jacoco_data['metrics']
        branches_total = metrics.get('branches_total', 0)
        if branches_total == 0:
            return True  # 没有分支，认为被覆盖
        
        # 使用确定性方法：如果分支覆盖率超过阈值，认为路径被覆盖
        branches_covered = metrics.get('branches_covered', 0)
        branch_coverage_ratio = branches_covered / branches_total
        return branch_coverage_ratio > 0.5  # 超过50%分支覆盖率认为路径被覆盖
    
    def _calculate_coverage_percentages(self, metrics: Dict) -> Dict:
        """计算覆盖率百分比"""
        result = dict(metrics)  # 复制原始指标
        
        # 计算百分比
        result["line_coverage"] = round(
            metrics["lines_covered"] / metrics["lines_total"] * 100, 2
        ) if metrics["lines_total"] > 0 else 0
        
        result["branch_coverage"] = round(
            metrics["branches_covered"] / metrics["branches_total"] * 100, 2
        ) if metrics["branches_total"] > 0 else 0
        
        result["method_coverage"] = round(
            metrics["methods_covered"] / metrics["methods_total"] * 100, 2
        ) if metrics["methods_total"] > 0 else 0
        
        return result
    
    def _compute_fitness(self, metrics: Dict, failed: bool, time_seconds: float, test_summary: Optional[Dict] = None) -> float:
        """
        计算适应度值，大幅提高覆盖率权重，以生成高覆盖率测试为主要目标
        
        适应度计算公式:
        fitness = coverage_score + coverage_quality_bonus - failure_penalty - time_penalty
        """
        # 1. 计算基础覆盖率得分 (0-1分)
        line_score = metrics["lines_covered"] / metrics["lines_total"] if metrics["lines_total"] else 0
        branch_score = metrics["branches_covered"] / metrics["branches_total"] if metrics["branches_total"] else 0
        method_score = metrics["methods_covered"] / metrics["methods_total"] if metrics["methods_total"] else 0
        
        # 大幅提高覆盖率权重: 行覆盖率50%, 分支覆盖率40%, 方法覆盖率10%
        # 行覆盖率权重提高，因为它最能反映测试的全面性
        coverage_score = 0.5 * line_score + 0.4 * branch_score + 0.1 * method_score
        
        # 2. 大幅提高覆盖率质量奖励 (最多0.3分) - 强烈奖励高覆盖率的测试
        coverage_quality_bonus = self._calculate_coverage_quality_bonus(coverage_score)
        
        # 3. 进一步降低失败率惩罚 (最多-0.05分)，优先考虑覆盖率
        failure_penalty = self._calculate_failure_penalty(failed, test_summary)
        
        # 4. 降低执行时间惩罚 (最多-0.02分)，因为覆盖率更重要
        time_penalty = min(0.02, time_seconds / 30.0)  # 超过30秒开始惩罚，惩罚更轻
        
        # 5. 综合计算最终适应度，覆盖率为主导因素
        fitness = max(coverage_score + coverage_quality_bonus - failure_penalty - time_penalty, 0)
        
        return round(fitness, 4)
    
    def _calculate_coverage_quality_bonus(self, coverage_score: float) -> float:
        """计算覆盖率质量奖励 - 大幅强化奖励高覆盖率的测试"""
        if coverage_score >= 0.95:  # 95%以上覆盖率
            return 0.3  # 最高奖励
        elif coverage_score >= 0.9:  # 90%以上覆盖率
            return 0.2  # 高奖励
        elif coverage_score >= 0.8:  # 80%以上覆盖率
            return 0.15  # 中等奖励
        elif coverage_score >= 0.7:  # 70%以上覆盖率
            return 0.1  # 基础奖励
        elif coverage_score >= 0.6:  # 60%以上覆盖率
            return 0.05  # 小奖励
        else:
            return 0.0
    
    def _calculate_failure_penalty(self, failed: bool, test_summary: Optional[Dict]) -> float:
        """计算失败率惩罚 - 大幅降低惩罚力度，优先考虑覆盖率"""
        if test_summary and test_summary["total_tests"] > 0:
            # 基于实际失败率计算惩罚，大幅降低惩罚力度
            return min(0.05, test_summary["failure_rate"] * 0.05)
        elif failed:
            # 如果没有详细信息但测试失败，使用很低的默认惩罚
            return 0.05
        
        return 0.0
    
    def analyze_generation_coverage(self, generation: str) -> Dict[str, Dict]:
        """
        分析整个世代的覆盖率
        
        Args:
            generation: 世代标识（如"Gen1"）
            
        Returns:
            Dict: 该世代所有测试类的覆盖率报告
        """
        generation_reports = {}
        test_reports_dir = Path(self.base_dir) / "test_reports" / self.project_name / generation
        
        if not test_reports_dir.exists():
            print(f"世代报告目录不存在: {test_reports_dir}")
            return generation_reports
        
        # 遍历该世代的所有测试类
        for test_class_dir in test_reports_dir.iterdir():
            if test_class_dir.is_dir() and not test_class_dir.name.startswith('Gen'):
                test_class = test_class_dir.name
                report = self.analyze_test_coverage(test_class, generation)
                if report:
                    generation_reports[test_class] = report
        
        print(f"完成世代 {generation} 覆盖率分析，共 {len(generation_reports)} 个测试类")
        return generation_reports
    
    def _extract_test_methods_info(self, test_class: str, surefire_xml_path: Path) -> List[Dict]:
        """
        从测试代码文件中提取测试方法信息
        
        Args:
            test_class: 测试类名称
            surefire_xml_path: Surefire XML文件路径（用于确定包名）
            
        Returns:
            测试方法信息列表，每个元素包含method_name和display_name
        """
        test_methods_info = []
        
        try:
            # 查找测试代码文件，传入当前代数
            generation = None
            if hasattr(self, 'current_generation'):
                generation = self.current_generation
            test_file_path = self._find_test_file(test_class, generation)
            if not test_file_path:
                print(f"找不到测试代码文件: {test_class}")
                return test_methods_info
            
            print(f"解析测试代码文件: {test_file_path}")
            
            # 读取测试代码文件
            with open(test_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取包名
            package_name = self._extract_package_name(content)
            
            # 使用正则表达式提取测试方法和DisplayName
            import re
            
            # 匹配模式：可能有@DisplayName的@Test方法，考虑换行和空格
            # 注意：需要捕获@DisplayName中的文本和方法名
            test_pattern = r'@Test\s*(?:@DisplayName\s*\(\s*"([^"]+)"\s*\)\s+)?(?:public\s+)?void\s+(\w+)\s*\([^)]*\)'
            matches = re.findall(test_pattern, content, re.MULTILINE | re.DOTALL)
            
            for display_name, method_name in matches:
                if method_name.strip():
                    # 如果有@DisplayName注解，使用它；否则使用默认格式
                    final_display_name = display_name.strip() if display_name else f"{package_name}.{test_class}.{method_name}" if package_name else f"{test_class}.{method_name}"
                    
                    method_info = {
                        "method_name": method_name,
                        "display_name": final_display_name
                    }
                    test_methods_info.append(method_info)
            
            print(f"提取到 {len(test_methods_info)} 个测试方法")
            
        except Exception as e:
            print(f"从测试代码文件提取方法信息时出错: {e}")
            import traceback
            traceback.print_exc()
        
        return test_methods_info
    
    def _find_test_file(self, test_class: str, current_generation: Optional[str] = None) -> Optional[Path]:
        """
        查找测试代码文件
        
        Args:
            test_class: 测试类名称
            current_generation: 当前代数（如"Gen2"），用于动态确定查找范围
            
        Returns:
            测试文件路径，如果找不到则返回None
        """
        possible_paths = []
        
        # 如果指定了当前代数，优先在当前代±1范围内查找
        if current_generation:
            try:
                gen_num = int(current_generation.replace("Gen", ""))
                # 构建动态的代数范围
                for gen in range(max(1, gen_num - 1), gen_num + 2):
                    possible_paths.append(
                        self.base_dir / "evolution_process" / self.project_name / f"Gen{gen}" / f"{test_class}.java"
                    )
            except (ValueError, AttributeError):
                pass
        
        for path in possible_paths:
            if path.exists():
                return path

        test_src_dir = self.project_dir / "src" / "test" / "java"
        if test_src_dir.exists():
            for path in test_src_dir.rglob(f"{test_class}.java"):
                return path
        
        return None
    
    def _extract_package_name(self, content: str) -> str:
        """
        从测试代码内容中提取包名
        
        Args:
            content: 测试代码内容
            
        Returns:
            包名
        """
        import re
        package_match = re.search(r'package\s+([a-zA-Z0-9_.]+)\s*;', content)
        if package_match:
            return package_match.group(1)
        return ""
