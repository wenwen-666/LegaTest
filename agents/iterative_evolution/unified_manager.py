"""
统一的测试报告和文件管理工具类
解决代码重复和循环依赖问题
"""

import os
import json
import re
from typing import Dict, List, Optional, Tuple, Set
from pathlib import Path

class UnifiedTestManager:
    """统一的测试管理器 - 提供所有模块共用的功能"""
    
    def __init__(self, base_dir: str, project_name: str):
        """
        初始化统一测试管理器
        
        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
        """
        self.base_dir = Path(base_dir).resolve()
        self.project_name = project_name
        self.project_dir = self.base_dir / "dataset" / project_name
        self._reports_cache = {}  # 报告缓存
        self._file_path_cache = {}  # 文件路径缓存
    
    # ==================== 路径管理 ====================
    
    def get_reports_dir(self, gen_num: int) -> Path:
        """获取测试报告目录路径"""
        return self.base_dir / "test_reports" / self.project_name / f"Gen{gen_num}"
    
    def get_evolution_dir(self, gen_num: int) -> Path:
        """获取进化过程目录路径"""
        return self.base_dir / "evolution_process" / self.project_name / f"Gen{gen_num}"
    
    def get_test_src_dir(self) -> Path:
        """获取测试源码目录路径"""
        return self.project_dir / "src" / "test" / "java"
    
    def get_main_src_dir(self) -> Path:
        """获取主源码目录路径"""
        return self.project_dir / "src" / "main" / "java"
    
    # ==================== 测试报告管理 ====================
    
    def get_test_reports(self, gen_num: int, use_cache: bool = True) -> Dict[str, Dict]:
        """
        获取指定代数的所有测试报告
        
        Args:
            gen_num: 代数
            use_cache: 是否使用缓存
            
        Returns:
            测试报告字典，键为测试类名，值为报告内容
        """
        cache_key = f"reports_gen_{gen_num}"
        
        if use_cache and cache_key in self._reports_cache:
            return self._reports_cache[cache_key]
        
        reports_dir = self.get_reports_dir(gen_num)
        test_reports = {}

        print(f"🔍 调试: 检查测试报告目录 {reports_dir}")
        if not reports_dir.exists():
            print(f"警告: 测试报告目录 {reports_dir} 不存在")
            return test_reports
        
        for item in reports_dir.iterdir():
            print(f"🔍 调试: 检查项目 {item} (is_dir: {item.is_dir()})")
            if item.is_dir():
                report_file = item / "coverage_report.json"
                print(f"🔍 调试: 检查报告文件 {report_file} (exists: {report_file.exists()})")
                if report_file.exists():
                    try:
                        with open(report_file, 'r', encoding='utf-8') as f:
                            report = json.load(f)
                        if report:  # 确保报告不为空
                            test_reports[item.name] = report
                            print(f"✅ 调试: 成功加载报告 {item.name}")
                        else:
                            print(f"警告: 报告文件 {report_file} 为空或无效")
                    except Exception as e:
                        print(f"警告: 读取报告文件 {report_file} 失败: {e}")
                else:
                    print(f"🔍 调试: 报告文件不存在 {report_file}")
            else:
                print(f"🔍 调试: 跳过非目录项 {item}")
        
        if use_cache:
            self._reports_cache[cache_key] = test_reports

        print(f"🔍 调试: 最终返回 {len(test_reports)} 个测试报告: {list(test_reports.keys())}")
        return test_reports
    
    def get_test_report(self, test_name: str, gen_num: int) -> Optional[Dict]:
        """
        获取单个测试的报告
        
        Args:
            test_name: 测试类名
            gen_num: 代数
            
        Returns:
            测试报告或None
        """
        report_path = self.get_reports_dir(gen_num) / test_name / "coverage_report.json"
        
        if not report_path.exists():
            return None
        
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 读取报告文件 {report_path} 失败: {e}")
            return None
    
    def is_coverage_report_complete(self, report: Dict) -> bool:
        """
        检查覆盖率报告是否完整
        
        Args:
            report: 测试报告
            
        Returns:
            是否完整
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
    
    # ==================== 文件查找和管理 ====================
    
    def find_test_source_file(self, test_class: str, use_cache: bool = True) -> Optional[Path]:
        """
        查找测试源文件
        
        Args:
            test_class: 测试类名
            use_cache: 是否使用缓存
            
        Returns:
            文件路径或None
        """
        if not test_class:
            print("警告: 测试类名为空")
            return None
            
        cache_key = f"test_file_{test_class}"
        
        try:
            if use_cache and cache_key in self._file_path_cache:
                cached_path = self._file_path_cache[cache_key]
                if cached_path and cached_path.exists():
                    return cached_path
                else:
                    # 缓存的路径不存在了，清除缓存
                    del self._file_path_cache[cache_key]
            
            # 首先在evolution_process目录中查找
            for gen in range(1, 11):  # 查找所有代
                try:
                    evolution_dir = self.get_evolution_dir(gen)
                    if evolution_dir.exists():
                        for java_file in evolution_dir.rglob(f"{test_class}.java"):
                            if use_cache:
                                self._file_path_cache[cache_key] = java_file
                            return java_file
                except Exception as e:
                    print(f"警告: 搜索evolution目录Gen{gen}时出错: {e}")
                    continue
            
            # 然后在src/test目录中查找
            try:
                test_src_dir = self.get_test_src_dir()
                if test_src_dir.exists():
                    for java_file in test_src_dir.rglob(f"{test_class}.java"):
                        if use_cache:
                            self._file_path_cache[cache_key] = java_file
                        return java_file
            except Exception as e:
                print(f"警告: 搜索src/test目录时出错: {e}")
            
            return None
            
        except Exception as e:
            print(f"错误: 查找测试文件 {test_class} 时出现异常: {e}")
            return None
    
    def find_main_source_file(self, class_name: str) -> Optional[Path]:
        """
        查找主源码文件
        
        Args:
            class_name: 类名
            
        Returns:
            文件路径或None
        """
        main_src_dir = self.get_main_src_dir()
        if not main_src_dir.exists():
            return None
        
        # 尝试直接匹配类名
        for java_file in main_src_dir.rglob("*.java"):
            if java_file.stem == class_name or class_name.endswith(java_file.stem):
                return java_file
        
        return None
    
    # ==================== 测试类名解析 ====================
    
    def is_target_class_test(self, test_name: str, target_class: str) -> bool:
        """
        判断测试名是否属于目标类
        
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
    
    def extract_target_class_from_test_name(self, test_name: str) -> str:
        """
        从测试类名中提取被测类名
        
        Args:
            test_name: 测试类名
            
        Returns:
            被测类名
        """
        # 匹配标准格式
        match = re.match(r'^(\w+?)Test(?:V\d+|_Crossover_.*|_Mutation_.*|.*)?$', test_name)
        if match:
            return match.group(1)
        
        # 备用方案
        base_name = re.sub(r'Test.*$', '', test_name)
        return base_name if base_name else test_name
    
    def extract_base_class_name(self, test_class: str) -> str:
        """
        从测试类名提取基础类名
        
        Args:
            test_class: 测试类名
            
        Returns:
            基础类名
        """
        # 移除各种测试类后缀
        base_name = re.sub(r'Test_(Mutation|CrossoverMutation)_Gen\d+_V\d+$', '', test_class)
        base_name = re.sub(r'TestV?\d*$', '', base_name)
        base_name = re.sub(r'Test_Crossover_Gen\d+_\d+x\d+$', '', base_name)
        if base_name.endswith('Test'):
            base_name = base_name[:-4]
        return base_name
    
    # ==================== 测试选择和过滤 ====================
    
    def filter_target_tests(self, test_reports: Dict[str, Dict], target_class: str) -> Dict[str, Dict]:
        """
        过滤出目标类的测试
        
        Args:
            test_reports: 测试报告字典
            target_class: 目标类名
            
        Returns:
            过滤后的测试报告字典
        """
        target_tests = {}
        for test_name, report in test_reports.items():
            extracted_class = self.extract_target_class_from_test_name(test_name)
            if extracted_class == target_class:
                target_tests[test_name] = report
        return target_tests
    
    def get_best_test(self, test_reports: Dict[str, Dict]) -> Optional[str]:
        """
        获取适应度最高的测试
        
        Args:
            test_reports: 测试报告字典
            
        Returns:
            适应度最高的测试类名或None
        """
        if not test_reports:
            return None
        
        # 按适应度值排序
        sorted_tests = sorted(test_reports.items(), key=lambda x: x[1].get("fitness", 0), reverse=True)
        
        # 返回适应度最高的测试
        return sorted_tests[0][0]
    
    def get_best_and_second_best(self, test_reports: Dict[str, Dict]) -> Tuple[Optional[str], Optional[str]]:
        """
        获取适应度最高和次高的测试
        
        Args:
            test_reports: 测试报告字典
            
        Returns:
            适应度最高和次高的测试类名元组
        """
        if len(test_reports) < 2:
            return None, None
        
        # 按适应度值排序
        sorted_tests = sorted(test_reports.items(), key=lambda x: x[1].get("fitness", 0), reverse=True)
        
        return sorted_tests[0][0], sorted_tests[1][0]
    
    # ==================== 包和路径解析 ====================
    
    def extract_package_name(self, test_class: str) -> str:
        """
        从测试文件中提取包名
        
        Args:
            test_class: 测试类名
            
        Returns:
            包名
        """
        test_file = self.find_test_source_file(test_class)
        if test_file and test_file.exists():
            try:
                with open(test_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # 查找package声明
                package_match = re.search(r'package\s+([^;]+);', content)
                if package_match:
                    return package_match.group(1).strip()
            except Exception as e:
                print(f"读取包名失败: {e}")
        
        # 找不到时返回空包名，避免项目专用默认值
        return ""
    
    def get_package_path(self, test_class: str) -> str:
        """
        获取测试类的包路径
        
        Args:
            test_class: 测试类名
            
        Returns:
            包路径（相对于src/test/java）
        """
        package_name = self.extract_package_name(test_class)
        return package_name.replace(".", os.sep) if package_name else ""
    
    # ==================== 代码生成和许可证处理 ====================
    
    def get_apache_license_header(self) -> str:
        """
        获取Apache License头部
        
        Returns:
            Apache License头部字符串
        """
        license_file = Path(__file__).parent / "apache_license_header.txt"
        try:
            if license_file.exists():
                with open(license_file, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # 如果文件不存在，返回硬编码的许可证头部
                return self._get_default_license_header()
        except Exception as e:
            print(f"警告: 读取许可证头文件失败: {e}")
            return self._get_default_license_header()
    
    def _get_default_license_header(self) -> str:
        """返回默认的Apache许可证头部"""
        return """/*
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
 */"""
    
    def ensure_license_header(self, java_code: str) -> str:
        """
        确保Java代码包含Apache License头部
        
        Args:
            java_code: Java源代码
            
        Returns:
            包含许可证头部的Java代码
        """
        if not java_code:
            return java_code
        
        # 检查是否已包含许可证头部
        if "Licensed to the Apache Software Foundation" in java_code:
            return java_code
        
        license_header = self.get_apache_license_header()
        
        # 在许可证头部和代码之间添加空行
        return license_header + "\n\n" + java_code.lstrip()
    
    def ensure_complete_class_structure(self, java_code: str, test_class: str) -> str:
        """
        确保Java代码包含完整的类结构：License头部 + Package声明 + 导入语句 + 类定义
        
        Args:
            java_code: Java源代码
            test_class: 测试类名
            
        Returns:
            包含完整结构的Java代码
        """
        if not java_code:
            return java_code
        
        # 首先确保有license头部
        code_with_license = self.ensure_license_header(java_code)
        
        # 检查是否已有package声明
        if "package " in code_with_license:
            return code_with_license
        
        # 获取正确的package声明
        package_declaration = self._get_package_declaration_for_test(test_class)
        
        if not package_declaration:
            return code_with_license
        
        # 分离license头部和代码内容
        license_header = self.get_apache_license_header()
        
        if "Licensed to the Apache Software Foundation" in code_with_license:
            # 如果已有license，找到license结束位置
            code_after_license = code_with_license[len(license_header):].lstrip()
        else:
            code_after_license = code_with_license
        
        # 构建完整的文件结构
        complete_code = license_header + "\n\n" + package_declaration + "\n\n" + code_after_license.lstrip()
        
        return complete_code
    
    def _get_package_declaration_for_test(self, test_class: str) -> str:
        """
        根据测试类名获取正确的package声明
        
        Args:
            test_class: 测试类名
            
        Returns:
            package声明字符串
        """
        # 提取被测类名
        target_class = self.extract_target_class_from_test_name(test_class)
        
        # 查找对应的主源代码文件来确定正确的package
        main_source_file = self.find_main_source_file(target_class)
        
        if main_source_file and main_source_file.exists():
            try:
                with open(main_source_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 从主源代码中提取package声明
                package_match = re.search(r'package\s+([^;]+);', content)
                if package_match:
                    package_name = package_match.group(1).strip()
                    return f"package {package_name};"
            except Exception as e:
                print(f"警告: 读取主源代码文件失败: {e}")
        
        # 如果找不到主源代码，尝试从现有测试文件中获取package信息
        existing_test_file = self.find_test_source_file(f"{target_class}TestV1")
        if existing_test_file and existing_test_file.exists():
            try:
                with open(existing_test_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                package_match = re.search(r'package\s+([^;]+);', content)
                if package_match:
                    package_name = package_match.group(1).strip()
                    return f"package {package_name};"
            except Exception as e:
                print(f"警告: 读取现有测试文件失败: {e}")
        
        return ""
    
    def strip_license_header(self, java_code: str) -> str:
        """
        移除Java代码中的License头部，用于代码分析
        
        Args:
            java_code: Java源代码
            
        Returns:
            移除许可证头部的Java代码
        """
        if not java_code:
            return java_code
        
        lines = java_code.split('\n')
        result_lines = []
        in_license = False
        license_end = False
        
        for line in lines:
            if line.strip().startswith('/*') and 'Licensed to the Apache Software Foundation' in java_code:
                in_license = True
                continue
            elif in_license and line.strip().endswith('*/'):
                in_license = False
                license_end = True
                continue
            elif in_license:
                continue
            elif license_end and line.strip() == '':
                # 跳过许可证后的空行
                continue
            else:
                license_end = False
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    # ==================== 缓存管理 ====================
    
    def clear_cache(self):
        """清除所有缓存"""
        self._reports_cache.clear()
        self._file_path_cache.clear()
    
    def clear_reports_cache(self):
        """清除测试报告缓存"""
        self._reports_cache.clear()
    
    def clear_file_cache(self):
        """清除文件路径缓存"""
        self._file_path_cache.clear()


# 全局实例管理
_managers = {}

def get_unified_manager(base_dir: str, project_name: str) -> UnifiedTestManager:
    """
    获取统一管理器实例（单例模式）
    
    Args:
        base_dir: 项目基础目录
        project_name: 项目名称
        
    Returns:
        统一管理器实例
    """
    key = f"{base_dir}:{project_name}"
    if key not in _managers:
        _managers[key] = UnifiedTestManager(base_dir, project_name)
    return _managers[key]
