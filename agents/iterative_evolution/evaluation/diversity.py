"""
适应度计算和差异度评估模块
"""

import os
import json
import math
from typing import Dict, List, Tuple, Set
from itertools import combinations
from collections import Counter

from ..utils import load_json
from ..unified_manager import get_unified_manager

class DiversityCalculator:
    def __init__(self, base_dir: str, project_name: str):
        """初始化差异度计算器
        
        Args:
            base_dir: 项目基础目录
            project_name: 项目名称
        """
        self.base_dir = base_dir
        self.project_name = project_name
        self.project_dir = os.path.join(base_dir, "dataset", project_name)
        self.unified_manager = get_unified_manager(base_dir, project_name)
    
    def get_test_reports(self, gen_num: int, use_cache: bool = True) -> Dict[str, Dict]:
        """获取指定代数的所有测试报告

        Args:
            gen_num: 代数
            use_cache: 是否使用缓存

        Returns:
            测试报告字典，键为测试类名，值为报告内容
        """
        return self.unified_manager.get_test_reports(gen_num, use_cache)
    
    def get_best_test(self, test_reports: Dict[str, Dict]) -> str:
        """获取适应度最高的测试
        
        Args:
            test_reports: 测试报告字典
            
        Returns:
            适应度最高的测试类名
        """
        return self.unified_manager.get_best_test(test_reports)
    
    def get_best_and_second_best(self, test_reports: Dict[str, Dict]) -> Tuple[str, str]:
        """获取适应度最高和次高的测试
        
        Args:
            test_reports: 测试报告字典
            
        Returns:
            适应度最高和次高的测试类名元组
        """
        return self.unified_manager.get_best_and_second_best(test_reports)
    
    def select_diverse_pairs(self, test_reports: Dict[str, Dict], num_pairs: int = 5) -> List[Tuple[str, str]]:
        """计算差异度矩阵并选择差异度最大的测试对（避免重复选择）
        
        Args:
            test_reports: 测试报告字典
            num_pairs: 要选择的测试对数量，默认为5
            
        Returns:
            差异度最大的测试对列表（确保每个测试最多被选择一次）
        """
        test_classes = list(test_reports.keys())
        n = len(test_classes)
        
        if n < 2:
            print("警告: 测试数量不足，无法计算差异度")
            return []
        
        # 计算所有测试对的差异度
        diff_pairs = []
        
        for i in range(n):
            for j in range(i+1, n):
                class_a = test_classes[i]
                class_b = test_classes[j]
                
                # 计算三个维度的差异度
                semantic_diff = self.calculate_semantic_difference(test_reports[class_a], test_reports[class_b])
                method_diff = self.calculate_method_difference(test_reports[class_a], test_reports[class_b])
                path_diff = self.calculate_path_difference(test_reports[class_a], test_reports[class_b])
                
                # 总差异度 = 0.4×语义差异 + 0.3×方法覆盖差异 + 0.3×路径覆盖差异
                total_diff = 0.4 * semantic_diff + 0.3 * method_diff + 0.3 * path_diff
                
                diff_pairs.append((class_a, class_b, total_diff))
        
        # 按差异度降序排序
        diff_pairs.sort(key=lambda x: x[2], reverse=True)
        
        # 使用贪心算法避免重复选择：选择差异度最大且不重复的测试对
        selected_pairs = []
        used_tests = set()
        
        for class_a, class_b, diff_score in diff_pairs:
            # 如果这两个测试都没有被选择过，且还需要更多的测试对
            if class_a not in used_tests and class_b not in used_tests and len(selected_pairs) < num_pairs:
                selected_pairs.append((class_a, class_b))
                used_tests.add(class_a)
                used_tests.add(class_b)
                print(f"  选择对 {len(selected_pairs)}: {class_a} 和 {class_b} (差异度: {diff_score:.4f})")
        
        # 如果无法选择足够的不重复对，则放松条件：允许每个测试最多参与一次交叉
        if len(selected_pairs) < num_pairs and len(test_classes) >= num_pairs * 2:
            print("警告: 严格不重复选择无法满足需求，放松为每个测试最多参与一次")
            selected_pairs = []
            used_tests = set()
            
            for class_a, class_b, diff_score in diff_pairs:
                if len(selected_pairs) >= num_pairs:
                    break
                # 确保每个测试最多被选择一次
                if class_a not in used_tests and class_b not in used_tests:
                    selected_pairs.append((class_a, class_b))
                    used_tests.add(class_a)
                    used_tests.add(class_b)
                    print(f"  选择对 {len(selected_pairs)}: {class_a} 和 {class_b} (差异度: {diff_score:.4f})")
        
        # 如果仍然无法选择足够的对，则根据实际测试数量调整
        if len(selected_pairs) < num_pairs:
            print(f"警告: 只能选择 {len(selected_pairs)} 对交叉，因为测试数量不足以避免重复选择")
            # 不再放松条件，严格保证每个测试最多参与一次交叉
        
        print(f"最终选择了 {len(selected_pairs)} 对测试进行交叉操作")
        return selected_pairs
    
    def calculate_semantic_difference(self, report_a: Dict, report_b: Dict) -> float:
        """计算两个测试的语义差异度
        
        使用TF-IDF + 余弦距离计算语义差异
        
        Args:
            report_a: 第一个测试报告
            report_b: 第二个测试报告
            
        Returns:
            语义差异度，范围为0-1
        """
        # 提取测试方法信息
        methods_a = report_a.get("test_methods_info", [])
        methods_b = report_b.get("test_methods_info", [])
        
        # 提取方法名和DisplayName
        texts_a = []
        texts_b = []
        
        for method in methods_a:
            method_name = method.get("method_name", "")
            display_name = method.get("display_name", "")
            if method_name:
                texts_a.append(method_name)
            if display_name:
                texts_a.append(display_name)
        
        for method in methods_b:
            method_name = method.get("method_name", "")
            display_name = method.get("display_name", "")
            if method_name:
                texts_b.append(method_name)
            if display_name:
                texts_b.append(display_name)
        
        # 如果任一测试没有方法信息，返回最大差异度
        if not texts_a or not texts_b:
            return 1.0
        
        # 合并文本
        text_a = " ".join(texts_a)
        text_b = " ".join(texts_b)
        
        # 使用简单的词汇相似度计算
        try:
            # 分词并统计词频
            words_a = set(text_a.lower().split())
            words_b = set(text_b.lower().split())
            
            if not words_a or not words_b:
                return 1.0
            
            # 计算Jaccard相似度
            intersection = len(words_a.intersection(words_b))
            union = len(words_a.union(words_b))
            
            if union == 0:
                return 1.0
            
            jaccard_sim = intersection / union
            
            # 转换为差异度 (1 - 相似度)
            return 1.0 - jaccard_sim
        except Exception as e:
            print(f"语义差异度计算失败: {e}")
            return 0.5
    
    def calculate_method_difference(self, report_a: Dict, report_b: Dict) -> float:
        """计算两个测试的方法覆盖差异度
        
        使用Jaccard距离计算方法覆盖差异
        
        Args:
            report_a: 第一个测试报告
            report_b: 第二个测试报告
            
        Returns:
            方法覆盖差异度，范围为0-1
        """
        # 提取覆盖的方法
        covered_methods_a = set(report_a.get("covered_methods", []))
        covered_methods_b = set(report_b.get("covered_methods", []))
        
        # 如果两个测试都没有覆盖方法，差异度为0
        if not covered_methods_a and not covered_methods_b:
            return 0.0
        
        # 如果其中一个没有覆盖方法，返回最大差异度
        if not covered_methods_a or not covered_methods_b:
            return 1.0
        
        # 计算Jaccard距离 = 1 - |A∩B| / |A∪B|
        intersection = len(covered_methods_a.intersection(covered_methods_b))
        union = len(covered_methods_a.union(covered_methods_b))
        
        if union == 0:
            return 0.0
        
        jaccard_similarity = intersection / union
        return 1.0 - jaccard_similarity
    
    def calculate_path_difference(self, report_a: Dict, report_b: Dict) -> float:
        """计算两个测试的路径覆盖差异度
        
        使用Jaccard距离计算路径覆盖差异
        提取covered_paths中每个路径的起始method signature
        
        Args:
            report_a: 第一个测试报告
            report_b: 第二个测试报告
            
        Returns:
            路径覆盖差异度，范围为0-1
        """
        # 提取覆盖的路径
        covered_paths_a = report_a.get("covered_paths", [])
        covered_paths_b = report_b.get("covered_paths", [])
        
        # 提取路径的方法签名(起始method signature)
        method_signatures_a = set()
        method_signatures_b = set()
        
        for path in covered_paths_a:
            if path and len(path) > 0:
                # path[0]应该是method signature，例如：<package.TargetClass: void method(java.lang.String)>
                method_signatures_a.add(path[0])
        
        for path in covered_paths_b:
            if path and len(path) > 0:
                method_signatures_b.add(path[0])
        
        # 如果两个测试都没有覆盖路径，差异度为0
        if not method_signatures_a and not method_signatures_b:
            return 0.0
        
        # 如果其中一个没有覆盖路径，返回最大差异度
        if not method_signatures_a or not method_signatures_b:
            return 1.0
        
        # 计算Jaccard距离 = 1 - |A∩B| / |A∪B|
        intersection = len(method_signatures_a.intersection(method_signatures_b))
        union = len(method_signatures_a.union(method_signatures_b))
        
        if union == 0:
            return 0.0
        
        jaccard_similarity = intersection / union
        return 1.0 - jaccard_similarity
