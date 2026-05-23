"""
交叉操作相关功能模块 - 优化版
针对一个类生成的多个测试版本进行两两交叉操作
"""

import os
import re
from typing import Dict, List, Tuple, Optional

try:
    import javalang
except ImportError:
    raise ImportError("javalang library is required. Please run 'pip install javalang'")

from ..utils import load_json, ensure_dir
from ..clients import LLMClient
from ..maven_utils import run_maven_test
from ..unified_manager import get_unified_manager

class CrossoverOperator:
    def __init__(self, base_dir: str, project_name: str, llm_client: LLMClient):
        """初始化交叉操作器
        
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
    
    def perform_crossover(self, test_pairs: List[Tuple[str, str]], gen_num: int, source_gen: int = None) -> List[str]:
        """对选择的测试对进行交叉操作
        
        Args:
            test_pairs: 测试对列表，每个元素是一个(test_class_a, test_class_b)元组
            gen_num: 当前代数（用于保存新生成的测试）
            source_gen: 源代数（从哪一代获取测试报告，如果为None则使用gen_num）
            
        Returns:
            交叉生成的测试类名列表
        """
        crossover_tests = []
        
        for i, (class_a, class_b) in enumerate(test_pairs):
            print(f"对同一目标类的两个测试版本进行交叉: {class_a} × {class_b}")

            # 生成交叉后的测试类名
            base_name_a = re.sub(r'TestV?\d*$', '', class_a)
            if base_name_a.endswith('Test'):
                target_class = base_name_a[:-4]  # 移除末尾的'Test'
            else:
                target_class = base_name_a

            version_a = self._extract_version(class_a)
            version_b = self._extract_version(class_b)
            crossover_class = f"{target_class}Test_Crossover_Gen{gen_num}_{version_a}x{version_b}"

            # 检查目标交叉文件是否已经存在
            crossover_file_path = self._get_expected_crossover_file_path(crossover_class)
            if os.path.exists(crossover_file_path):
                print(f"⚠️  交叉测试文件已存在，跳过生成: {crossover_class}")
                print(f"   文件路径: {crossover_file_path}")
                crossover_tests.append(crossover_class)
                continue
            
            # 获取测试报告（使用源代数或当前代数）
            report_gen = source_gen if source_gen is not None else gen_num
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{report_gen}")
            
            report_a_path = os.path.join(reports_dir, class_a, "coverage_report.json")
            report_b_path = os.path.join(reports_dir, class_b, "coverage_report.json")
            
            if not os.path.exists(report_a_path) or not os.path.exists(report_b_path):
                print(f"警告: 测试报告不存在，跳过交叉操作")
                continue
            
            # 读取测试报告
            report_a = load_json(report_a_path)
            report_b = load_json(report_b_path)
            
            if not report_a or not report_b:
                print(f"警告: 测试报告为空，跳过交叉操作")
                continue
            
            # 获取测试类源码
            test_a_path = self._find_test_source_file(class_a)
            test_b_path = self._find_test_source_file(class_b)
            
            if not test_a_path or not test_b_path:
                print(f"警告: 测试源文件不存在，跳过交叉操作")
                continue
            
            # 读取测试类源码
            with open(test_a_path, 'r', encoding='utf-8') as f:
                test_a_code = f.read()
            
            with open(test_b_path, 'r', encoding='utf-8') as f:
                test_b_code = f.read()
            
            
            # 准备交叉操作的提示词
            prompt = self._generate_crossover_prompt(report_a, report_b, test_a_code, test_b_code, 
                                                   class_a, class_b, crossover_class)
            
            # 在终端输出提示词内容
            print(f"\n{'='*80}")
            print(f"🤖 LLM交叉操作提示词 | 类名: {crossover_class}")
            print(f"📏 提示词长度: {len(prompt)} 字符 | 估计token数: {len(prompt) // 4}")
            print(f"{'='*80}")
            print(prompt)
            print(f"{'='*80}")
            print("🚀 开始调用LLM...\n")
            
            # 记录提示词到日志文件
            self._log_llm_interaction("crossover", crossover_class, prompt, None, "发送提示词")
            
            # 调用LLM执行交叉操作 - 智能重试机制
            crossover_code = self._generate_with_retry(prompt, crossover_class, max_retries=2)
            
            # 记录LLM回复到日志文件
            self._log_llm_interaction("crossover", crossover_class, None, crossover_code, "接收回复")
            
            if not crossover_code:
                print(f"❌ 交叉操作失败，LLM未生成有效代码")
                continue
            
            # 保存交叉后的测试类
            if self._save_crossover_test(crossover_code, crossover_class, test_a_code):
                crossover_tests.append(crossover_class)
                print(f"🎉 交叉测试类生成成功: {crossover_class}")
            else:
                print(f"❌ 交叉测试类保存或验证失败: {crossover_class}")
        
        # 输出交叉操作统计
        self._print_crossover_summary(test_pairs, crossover_tests)
        return crossover_tests
    
    def generate_crossover_code_only(self, class_a: str, class_b: str, gen_num: int, source_gen: int = None) -> Optional[Dict]:
        """只生成交叉代码，不保存和验证文件
        
        Args:
            class_a: 测试类A名称
            class_b: 测试类B名称
            gen_num: 当前代数
            source_gen: 源代数
            
        Returns:
            包含生成代码信息的字典，格式：{
                'code': '生成的代码',
                'class_name': '交叉类名',
                'reference_code': '参考代码'
            }
        """
        try:
            # 获取测试报告（使用源代数或当前代数）
            report_gen = source_gen if source_gen is not None else gen_num
            reports_dir = os.path.join(self.base_dir, "test_reports", self.project_name, f"Gen{report_gen}")
            
            report_a_path = os.path.join(reports_dir, class_a, "coverage_report.json")
            report_b_path = os.path.join(reports_dir, class_b, "coverage_report.json")
            
            if not os.path.exists(report_a_path) or not os.path.exists(report_b_path):
                print(f"警告: 测试报告不存在，跳过交叉操作")
                return None
            
            # 读取测试报告
            report_a = load_json(report_a_path)
            report_b = load_json(report_b_path)
            
            if not report_a or not report_b:
                print(f"警告: 测试报告为空，跳过交叉操作")
                return None
            
            # 获取测试类源码
            test_a_path = self._find_test_source_file(class_a)
            test_b_path = self._find_test_source_file(class_b)
            
            if not test_a_path or not test_b_path:
                print(f"警告: 测试源文件不存在，跳过交叉操作")
                return None
            
            # 读取测试类源码
            with open(test_a_path, 'r', encoding='utf-8') as f:
                test_a_code = f.read()
            
            with open(test_b_path, 'r', encoding='utf-8') as f:
                test_b_code = f.read()
            
            
            # 准备交叉操作的提示词
            prompt = self._generate_crossover_prompt(report_a, report_b, test_a_code, test_b_code, 
                                                   class_a, class_b, crossover_class)
            
            # 在终端输出提示词内容
            print(f"\n{'='*80}")
            print(f"🤖 LLM交叉操作提示词 | 类名: {crossover_class}")
            print(f"📏 提示词长度: {len(prompt)} 字符 | 估计token数: {len(prompt) // 4}")
            print(f"{'='*80}")
            print(prompt)
            print(f"{'='*80}")
            print("🚀 开始调用LLM...\n")
            
            # 记录提示词到日志文件
            self._log_llm_interaction("crossover", crossover_class, prompt, None, "发送提示词")
            
            # 调用LLM执行交叉操作 - 智能重试机制
            crossover_code = self._generate_with_retry(prompt, crossover_class, max_retries=2)
            
            # 记录LLM回复到日志文件
            self._log_llm_interaction("crossover", crossover_class, None, crossover_code, "接收回复")
            
            if not crossover_code:
                print(f"❌ 交叉代码生成失败，LLM未生成有效代码")
                return None
            
            return {
                'code': crossover_code,
                'class_name': crossover_class,
                'reference_code': test_a_code
            }
            
        except Exception as e:
            print(f"生成交叉代码异常: {e}")
            return None
    
    def save_and_verify_crossover_test(self, crossover_code: str, crossover_class: str, reference_code: str) -> bool:
        """保存交叉测试类并验证
        
        Args:
            crossover_code: 交叉代码
            crossover_class: 交叉类名
            reference_code: 参考代码
            
        Returns:
            是否成功保存和验证
        """
        return self._save_crossover_test(crossover_code, crossover_class, reference_code)
    
    def _find_test_source_file(self, test_class: str) -> Optional[str]:
        """查找测试类源文件"""
        # 首先在evolution_process目录中查找
        evolution_dir = os.path.join(self.base_dir, "evolution_process", self.project_name)
        from ..core import MAX_GENERATIONS
        for gen in range(1, MAX_GENERATIONS + 1):  # 查找所有代
            gen_dir = os.path.join(evolution_dir, f"Gen{gen}")
            if os.path.exists(gen_dir):
                for root, _, files in os.walk(gen_dir):
                    for file in files:
                        if file == f"{test_class}.java":
                            return os.path.join(root, file)
        
        # 然后在src/test目录中查找
        test_src_dir = os.path.join(self.project_dir, "src", "test", "java")
        
        for root, _, files in os.walk(test_src_dir):
            for file in files:
                if file == f"{test_class}.java":
                    return os.path.join(root, file)
        
        return None
    
    def _extract_version(self, test_class: str) -> str:
        """从测试类名中提取版本号"""
        # 匹配TestV后面的数字
        match = re.search(r'TestV(\d+)', test_class)
        if match:
            return match.group(1)
        # 匹配其他格式
        match = re.search(r'Test_(\w+)_Gen(\d+)', test_class)
        if match:
            return f"{match.group(1)}{match.group(2)}"
        return "1"

    def _get_expected_crossover_file_path(self, crossover_class: str) -> str:
        """获取交叉文件的预期路径"""
        # 从交叉类名提取目标类名
        if "_Crossover_" in crossover_class:
            target_class = crossover_class.split("Test_Crossover_")[0]
        else:
            target_class = crossover_class.replace("Test", "")

        # 构建文件路径
        test_src_dir = os.path.join(self.base_dir, "dataset", self.project_name, "src", "test", "java")

        # 先递归查找已存在的交叉文件
        if os.path.exists(test_src_dir):
            for root, _, files in os.walk(test_src_dir):
                if f"{crossover_class}.java" in files:
                    return os.path.join(root, f"{crossover_class}.java")

        # 根据已有同目标测试文件的位置确定保存目录，避免项目专用包路径硬编码
        reference_candidates = [
            f"{target_class}TestV1",
            f"{target_class}Test",
            target_class,
        ]
        for reference_class in reference_candidates:
            reference_path = self._find_test_source_file(reference_class)
            if reference_path:
                return os.path.join(os.path.dirname(reference_path), f"{crossover_class}.java")

        if os.path.exists(test_src_dir):
            for root, _, files in os.walk(test_src_dir):
                if any(file.startswith(f"{target_class}Test") and file.endswith(".java") for file in files):
                    return os.path.join(root, f"{crossover_class}.java")

        return os.path.join(test_src_dir, f"{crossover_class}.java")

    def _generate_crossover_prompt(self, report_a: Dict, report_b: Dict, test_a_code: str, 
                                 test_b_code: str, class_a: str, class_b: str, 
                                 crossover_class: str) -> str:
        """生成片段化的LLM交叉操作提示词"""
        
        # 提取覆盖信息
        covered_methods_a = report_a.get("covered_methods", [])
        uncovered_methods_a = report_a.get("uncovered_methods", [])
        uncovered_paths_a = report_a.get("uncovered_paths", [])
        
        covered_methods_b = report_b.get("covered_methods", [])
        uncovered_methods_b = report_b.get("uncovered_methods", [])
        uncovered_paths_b = report_b.get("uncovered_paths", [])
        
        # 分析互补性
        common_uncovered = set(uncovered_methods_a) & set(uncovered_methods_b)
        
        # 1. 提取版本A的已覆盖方法代码片段和上下文（去除license）
        snippets_a = self._extract_covered_methods_with_context(
            self.unified_manager.strip_license_header(test_a_code), covered_methods_a)
        
        # 2. 提取版本B的已覆盖方法代码片段和上下文（去除license）
        snippets_b = self._extract_covered_methods_with_context(
            self.unified_manager.strip_license_header(test_b_code), covered_methods_b)
        
        # 3. 从源码提取共同未覆盖方法的源码
        uncovered_source = self._extract_uncovered_methods_source(common_uncovered, report_a, report_b)
        
        # 4. 简化路径信息（前10个）
        limited_paths = (uncovered_paths_a[:10] + uncovered_paths_b[:10])[:10]
        
        # 生成英文简化提示词
        prompt = f"""You are a Java testing expert. Perform crossover operation to merge two test classes into `{crossover_class}` with higher coverage.

**CROSSOVER GOAL**: Merge the best tests from both versions and add new tests for uncovered methods to maximize coverage.

**Version A tests:**
{snippets_a}

**Version B tests:**
{snippets_b}"""
        
        # 添加未覆盖方法信息
        if common_uncovered:
            prompt += f"""

**Uncovered methods to test ({len(common_uncovered)} methods):**"""
            
            if uncovered_source.strip():
                prompt += f"""
{uncovered_source}

Generate comprehensive tests for these methods to improve coverage."""
            else:
                method_list = []
                for method_sig in list(common_uncovered)[:5]:
                    method_name = method_sig.split('(')[0].split('.')[-1] if '(' in method_sig else method_sig.split('.')[-1]
                    method_list.append(f"- {method_name} (signature: {method_sig})")
                prompt += f"""
{chr(10).join(method_list)}

Generate tests for these methods based on their signatures."""

        prompt += f"""

Generate the merged test class `{crossover_class}` that combines the best tests from both versions and adds tests for uncovered methods."""
        
        return prompt
    
    def _extract_covered_methods_with_context(self, test_code: str, covered_methods: List[str]) -> str:
        """提取已覆盖方法的代码片段及其必要上下文"""
        try:
            # 使用javalang解析测试类
            tree = javalang.parse.parse(test_code)
            lines = test_code.split('\n')
            
            # 提取所有导入语句（包括显式和隐式使用的类）
            imports = self._extract_all_imports(tree, test_code)
            
            # 提取类和字段
            cls_iter = tree.filter(javalang.tree.ClassDeclaration)
            cls_tuple = next(cls_iter, None)
            if not cls_tuple:
                return "// 无法解析测试类"
            
            cls = cls_tuple[1]
            
            # 提取字段定义（智能去重）
            fields = self._extract_unique_fields(cls, lines)
            
            # 提取setup方法和测试方法，并进行智能合并
            setup_methods, test_methods = self._extract_and_merge_methods(cls, lines, covered_methods)
            
            # 组装结果
            result_parts = []
            
            if imports:
                result_parts.append("// 相关导入:")
                result_parts.extend(imports[:15])  # 增加导入数量限制
                result_parts.append("")
            
            if fields:
                result_parts.append("// 字段定义:")
                result_parts.extend(fields)
                result_parts.append("")
            
            if setup_methods:
                result_parts.append("// Setup方法:")
                result_parts.extend(setup_methods)
                result_parts.append("")
            
            if test_methods:
                result_parts.append("// 已覆盖方法的测试:")
                result_parts.extend(test_methods)
            
            return '\n'.join(result_parts)
            
        except Exception as e:
            return f"// 提取代码片段失败: {str(e)}"
    
    def _infer_target_class_from_test_name(self, test_name: str) -> str:
        """从测试类名通用推断目标类名"""
        import re
        # 移除测试类后缀：ZipFileTestV1 -> ZipFile, ArrayIteratorTest -> ArrayIterator
        base_name = re.sub(r'Test(V\d+)?(_.*)?$', '', test_name)
        return base_name if base_name else test_name
    
    def _extract_uncovered_methods_source(self, uncovered_methods: set, report_a: Dict, report_b: Dict) -> str:
        """从目标类源码中提取未覆盖方法的源码和签名"""
        print("=" * 80)
        print("💡 CROSSOVER 源码提取被调用了！！！")
        print("=" * 80)
        print(f"  开始提取未覆盖方法源码，方法数量: {len(uncovered_methods)}")
        if not uncovered_methods:
            return ""
        
        result_parts = []
        
        # 改进的目标类推断逻辑
        target_class = self._get_enhanced_target_class(report_a, report_b)
        target_source_file = None
        
        if target_class:
            # 查找目标类的源文件（传入未覆盖方法用于智能选择）
            target_source_file = self._find_target_source_file(target_class, uncovered_methods)
            print(f"  目标类 {target_class} 的源文件: {target_source_file}")
        
        # 如果目标类推断失败或找不到源文件，使用通用搜索策略
        if not target_source_file:
            print("  启用通用搜索策略...")
            target_source_file = self._find_any_relevant_source_file(uncovered_methods)
            if target_source_file:
                # 从文件路径推断类名
                target_class = os.path.basename(target_source_file).replace('.java', '')
                print(f"  通用搜索找到: {target_source_file} -> {target_class}")
        
        if not target_source_file:
            print("  所有源码查找策略失败，使用降级策略")
            return self._generate_method_signatures_only(uncovered_methods)
        
        try:
            with open(target_source_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用javalang解析目标类
            tree = javalang.parse.parse(content)
            lines = content.split('\n')
            
            # 提取未覆盖的方法源码和签名
            for method_sig in list(uncovered_methods)[:5]:  # 增加到5个方法
                print(f"  处理未覆盖方法: {method_sig}")
                method_info = self._parse_method_signature(method_sig)
                method_found = False
                
                # 处理构造方法
                if method_info['is_constructor']:
                    print("  调用 _extract_constructor_info")
                    method_found = self._extract_constructor_info(tree, lines, method_info, target_class, result_parts)
                    print(f"  构造器提取结果: {method_found}")
                else:
                    # 处理普通方法（只提取公共API方法）
                    print("  调用 _extract_public_method_info")
                    method_found = self._extract_public_method_info(tree, lines, method_info, result_parts)
                
                # 如果未找到方法实现，提供签名和提示
                if not method_found:
                    print("  未找到方法实现，添加签名信息")
                    self._add_method_signature_info(method_info, result_parts)
                    
        except Exception as e:
            print(f"  提取源码失败: {e}")
            import traceback
            traceback.print_exc()
            return self._generate_method_signatures_only(uncovered_methods)
        
        final_result = '\n'.join(result_parts) if result_parts else self._generate_method_signatures_only(uncovered_methods)
        print(f"  最终提取结果长度: {len(final_result)} 字符")
        return final_result
    
    def _method_covers_target(self, test_method_name: str, covered_methods: List[str]) -> bool:
        """判断测试方法是否覆盖了目标方法"""
        test_name_lower = test_method_name.lower()
        
        # 如果covered_methods为空，认为是有用的测试
        if not covered_methods:
            return True
            
        for method_sig in covered_methods:
            # 提取方法名
            if '.' in method_sig:
                method_name = method_sig.split('(')[0].split('.')[-1].lower()
            else:
                method_name = method_sig.split('(')[0].lower()
            
            # 改进匹配逻辑：检查测试名是否包含目标方法名
            if method_name and len(method_name) > 2:  # 避免匹配过短的方法名
                if method_name in test_name_lower:
                    return True
                    
        return False
    
    def _find_method_in_source(self, src_root: str, method_name: str, method_sig: str) -> Optional[str]:
        """在源码中查找方法定义"""
        try:
            # 遍历源码目录
            for root, dirs, files in os.walk(src_root):
                for file in files:
                    if file.endswith('.java'):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            # 使用javalang解析
                            tree = javalang.parse.parse(content)
                            lines = content.split('\n')
                            
                            # 查找方法
                            for _, method in tree.filter(javalang.tree.MethodDeclaration):
                                if method.name == method_name:
                                    # 简单检查参数匹配
                                    if self._method_signature_matches(method, method_sig):
                                        return self._get_node_source_code(method, lines)
                        except:
                            continue
            return None
        except:
            return None
    
    def _constructor_signature_matches(self, constructor_node, target_sig: str) -> bool:
        """检查构造方法签名是否匹配"""
        try:
            actual_param_count = len(constructor_node.parameters) if constructor_node.parameters else 0
            print(f"  实际构造器参数个数: {actual_param_count}")
            
            # 处理JVM签名格式：<init>(Ljava/io/OutputStream;I)V
            if 'Ljava/io/OutputStream;I' in target_sig:
                expected_count = 2  # OutputStream + int
                print(f"  期望构造器参数个数: {expected_count} (OutputStream + int)")
                return actual_param_count == expected_count
            
            # 通用处理
            target_params = target_sig.split('(')[1].split(')')[0] if '(' in target_sig else ""
            if not target_params.strip():
                expected_count = 0
            else:
                # 对JVM签名的简单计数
                expected_count = target_params.count('L') + target_params.count('I') + target_params.count('J') + target_params.count('F') + target_params.count('D') + target_params.count('Z') + target_params.count('B') + target_params.count('C') + target_params.count('S')
                if expected_count == 0:
                    expected_count = len([p.strip() for p in target_params.split(',') if p.strip()])
            
            print(f"  期望参数个数: {expected_count}")
            return actual_param_count == expected_count
        except Exception as e:
            print(f"  构造器签名匹配失败: {e}")
            return True  # 解析失败时认为匹配
    
    def _method_signature_matches(self, method_node, target_sig: str) -> bool:
        """检查方法签名是否匹配"""
        try:
            # 简单的匹配策略
            if '(' not in target_sig:
                return True  # 只有方法名，认为匹配
            
            # 提取参数个数
            target_params = target_sig.split('(')[1].split(')')[0]
            target_param_count = len([p.strip() for p in target_params.split(',') if p.strip()]) if target_params.strip() else 0
            
            actual_param_count = len(method_node.parameters) if method_node.parameters else 0
            
            return target_param_count == actual_param_count
        except:
            return True  # 解析失败时认为匹配
    
    def _get_reference_code(self, test_class: str) -> str:
        """获取测试类的源码"""
        test_path = self._find_test_source_file(test_class)
        if test_path and os.path.exists(test_path):
            with open(test_path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
    
    def _get_node_source_code(self, node, all_lines: List[str], strip_braces: bool = False) -> str:
        """从AST节点提取源代码"""
        if not node or not hasattr(node, 'position') or not node.position:
            return ""
        
        try:
            # For methods with annotations, we need to find the actual start including annotations
            start_line, _ = node.position
            actual_start = start_line - 1
            
            # Look backwards for annotations (@Test, @DisplayName, etc.)
            if hasattr(node, 'annotations') and node.annotations:
                # Find the first annotation position
                for annotation in node.annotations:
                    if hasattr(annotation, 'position') and annotation.position:
                        ann_line, _ = annotation.position
                        actual_start = min(actual_start, ann_line - 1)
            
            end_line_est = start_line + str(node).count('\n') + 2
            node_lines = all_lines[actual_start:end_line_est]
            code_block = "\n".join(node_lines)
            open_braces = code_block.count('{')
            close_braces = code_block.count('}')
            current = end_line_est
            while (open_braces > close_braces) and current < len(all_lines):
                code_block += "\n" + all_lines[current]
                current += 1
                open_braces = code_block.count('{')
                close_braces = code_block.count('}')
            if strip_braces:
                first = code_block.find('{')
                last = code_block.rfind('}')
                if first != -1 and last != -1:
                    return code_block[first+1:last].strip()
            return code_block.strip()
        except:
            return ""
    
    def _generate_with_retry(self, prompt: str, crossover_class: str, max_retries: int = 2) -> Optional[str]:
        """带重试机制的LLM代码生成"""
        for attempt in range(max_retries + 1):
            try:
                print(f"📤 LLM交叉生成 (尝试 {attempt + 1}/{max_retries + 1}): {crossover_class}")
                
                # 第一次尝试使用原始提示词
                if attempt == 0:
                    result = self.llm_client.generate_code(prompt)
                else:
                    # 后续尝试添加更多约束
                    retry_prompt = self._add_retry_constraints(prompt, attempt)
                    result = self.llm_client.generate_code(retry_prompt)
                
                if result and result.strip():
                    # 简单验证生成的代码
                    if self._basic_code_validation(result, crossover_class):
                        print(f"✅ LLM交叉生成成功 (尝试 {attempt + 1})")
                        return result
                    else:
                        print(f"⚠️  代码验证失败 (尝试 {attempt + 1})")
                        
                if attempt < max_retries:
                    print(f"🔄 重试中...")
                    
            except Exception as e:
                print(f"❌ LLM调用异常 (尝试 {attempt + 1}): {e}")
                if attempt < max_retries:
                    print(f"🔄 重试中...")
        
        print(f"❌ LLM交叉生成最终失败: {crossover_class}")
        return None
    
    def _add_retry_constraints(self, original_prompt: str, attempt: int) -> str:
        """为重试添加额外约束"""
        retry_suffix = f"""

⚠️  **重试指令 (第{attempt + 1}次尝试)**:
- 前一次生成失败，请更加严格遵循要求
- 确保类名完全匹配文件名
- 确保所有导入语句正确
- 确保所有字段和方法定义完整
- 生成更简洁但功能完整的测试方法
- 避免复杂的边界情况处理

请重新生成完整的Java测试类代码。"""
        
        return original_prompt + retry_suffix
    
    def _basic_code_validation(self, code: str, expected_class: str) -> bool:
        """基础代码验证"""
        try:
            # 检查是否包含预期的类声明
            if f"class {expected_class}" not in code and f"public class {expected_class}" not in code:
                return False
            
            # 检查是否包含基本的测试框架导入
            if "@Test" not in code:
                return False
                
            # 检查是否是完整的Java类结构
            if not (code.strip().endswith("}") and "{" in code):
                return False
                
            return True
            
        except Exception:
            return False
    
    def _print_crossover_summary(self, test_pairs: List[Tuple[str, str]], successful_tests: List[str]):
        """打印交叉操作总结"""
        print(f"\n{'='*60}")
        print(f"🔄 LLM智能交叉操作总结")
        print(f"{'='*60}")
        print(f"📝 尝试交叉对数: {len(test_pairs)}")
        print(f"✅ 成功生成数量: {len(successful_tests)}")
        print(f"❌ 失败数量: {len(test_pairs) - len(successful_tests)}")
        print(f"📊 成功率: {len(successful_tests)/len(test_pairs)*100:.1f}%" if test_pairs else "0%")
        
        if successful_tests:
            print(f"\n🎉 成功生成的交叉测试类:")
            for i, test_class in enumerate(successful_tests, 1):
                print(f"   {i}. {test_class}")
        
        if len(successful_tests) < len(test_pairs):
            failed_pairs = test_pairs[len(successful_tests):]
            print(f"\n❌ 失败的交叉对:")
            for i, (class_a, class_b) in enumerate(failed_pairs, 1):
                print(f"   {i}. {class_a} × {class_b}")
        
        print(f"{'='*60}\n")
    
    def _format_path(self, path) -> str:
        """格式化路径信息为可读的字符串"""
        if isinstance(path, list):
            if len(path) == 0:
                return "Empty path"
            elif len(path) == 1:
                return f"`{path[0]}`"
            else:
                return f"`{path[0]}` → `{path[1]}`" + (f" → ... ({len(path)} steps)" if len(path) > 2 else "")
        else:
            return f"`{path}`"
    
    def _get_target_class_from_project(self) -> str:
        """从当前交叉操作推断目标类名"""
        # 从测试报告中获取target_class信息会更准确
        return ""
    
    def _save_crossover_test(self, crossover_code: str, crossover_class: str, reference_code: str) -> bool:
        """保存交叉后的测试类"""
        try:
            # 首先确定正确的文件保存路径（基于reference_code的实际位置）
            correct_package_path, test_dir = self._determine_correct_package_path(crossover_class, reference_code)
            
            # 修正代码中的类名以匹配文件名
            corrected_code = self._fix_class_name_in_code(crossover_code, crossover_class)
            
            # 根据实际保存路径生成正确的包声明
            corrected_code = self._ensure_correct_package_declaration(corrected_code, correct_package_path, crossover_class)
            
            # 保存文件
            crossover_file = os.path.join(test_dir, f"{crossover_class}.java")
            print(f"  正在保存文件到: {crossover_file}")
            with open(crossover_file, 'w', encoding='utf-8') as f:
                f.write(corrected_code)
            
            # 立即检查文件是否保存成功
            if os.path.exists(crossover_file):
                print(f"  ✓ 文件保存成功: {crossover_file}")
            else:
                print(f"  ✗ 文件保存失败: {crossover_file}")
                return False
            
            # 执行test_repair修复流程
            if self._execute_repair_workflow(crossover_class):
                print(f"✓ 交叉测试类修复成功: {crossover_class}")
                return True
            else:
                print(f"✗ 交叉测试类修复失败: {crossover_class}")
                # 保留文件用于调试，不删除
                return False
            
        except Exception as e:
            print(f"保存交叉测试类失败: {e}")
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
        
        return corrected_code
    
    def _verify_maven_compilation(self, test_class: str) -> bool:
        """使用Maven验证测试类"""
        try:
            # 使用简单的文件存在性验证，跳过复杂的test_repair
            print(f"  验证文件创建: {test_class}")
            test_file = self._get_test_file_path(test_class)
            if os.path.exists(test_file):
                print(f"  ✓ 文件创建成功: {test_class}")
                return True
            else:
                print(f"  ✗ 文件创建失败: {test_class}")
                return False
                    
        except Exception as e:
            print(f"⚠️ Maven验证异常: {test_class} - {e}")
            return False

    def _execute_repair_workflow(self, test_class: str) -> bool:
        """执行修复流程：使用test_repair模块进行测试和修复"""
        try:
            # 使用test_repair agent
            import sys
            # 计算到项目根目录的路径
            # crossover.py在 agents/iterative_evolution/operators/ 下
            # 需要向上3级到达项目根目录，然后添加agents目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            agents_path = os.path.join(project_root, 'agents')
            if agents_path not in sys.path:
                sys.path.insert(0, agents_path)
            
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
                return False
                    
        except ImportError as e:
            print(f"    导入test_repair agent失败: {e}")
            print(f"  导入失败: {test_class}")
            return False
        except Exception as e:
            print(f"    修复过程异常: {e}")
            print(f"  异常: {test_class}")
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
    
    def _extract_package_name(self, test_class: str) -> str:
        """从测试文件中提取包名"""
        test_file_path = self._get_test_file_path(test_class)
        if test_file_path and os.path.exists(test_file_path):
            try:
                with open(test_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # 查找package声明
                import re
                package_match = re.search(r'package\s+([^;]+);', content)
                if package_match:
                    return package_match.group(1).strip()
            except Exception as e:
                print(f"读取包名失败: {e}")
        
        # 找不到时返回空包名，避免项目专用默认值
        return ""
    
    def _extract_base_class_name(self, test_class: str) -> str:
        """从测试类名提取基础类名"""
        import re
        # 移除各种测试类后缀
        base_name = re.sub(r'Test_Crossover_Gen\d+_\d+x\d+$', '', test_class)
        base_name = re.sub(r'TestV?\d*$', '', base_name)
        if base_name.endswith('Test'):
            base_name = base_name[:-4]
        return base_name
    
    def _delete_failed_test_file(self, test_class: str):
        """删除修复失败的测试文件"""
        test_file = self._get_test_file_path(test_class)
        if test_file and os.path.exists(test_file):
            try:
                os.remove(test_file)
                print(f"    已删除失败的测试文件: {test_file}")
            except Exception as e:
                print(f"    删除文件失败: {e}")
    
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
    
    
    def _extract_all_imports(self, tree, test_code: str) -> List[str]:
        """提取所有导入语句，包括显式导入和代码中使用的类"""
        imports = []
        
        # 1. 提取显式导入
        for imp in tree.imports:
            import_str = f"import {'static ' if imp.static else ''}{imp.path}{'.*' if imp.wildcard else ''};"
            imports.append(import_str)
        
        # 2. 检测代码中使用但未显式导入的常见 JDK 类
        implicit_imports = self._detect_implicit_imports(test_code, imports)
        imports.extend(implicit_imports)
        
        return imports
    
    def _detect_implicit_imports(self, code: str, existing_imports: List[str]) -> List[str]:
        """检测代码中使用但未显式导入的类"""
        implicit_imports = []
        existing_import_names = {imp.split('.')[-1].replace(';', '') for imp in existing_imports}
        
        # 常见的Java类映射
        common_classes = {
            'ZipOutputStream': 'java.util.zip.ZipOutputStream',
            'ZipEntry': 'java.util.zip.ZipEntry', 
            'FileOutputStream': 'java.io.FileOutputStream',
            'ByteArrayOutputStream': 'java.io.ByteArrayOutputStream',
            'BufferedInputStream': 'java.io.BufferedInputStream',
            'FileInputStream': 'java.io.FileInputStream',
            'ZipException': 'java.util.zip.ZipException',
            'Files': 'java.nio.file.Files',
            'Paths': 'java.nio.file.Paths'
        }
        
        # 检测代码中使用的类
        for class_name, full_path in common_classes.items():
            if class_name in code and class_name not in existing_import_names:
                implicit_imports.append(f"import {full_path};")
        
        return implicit_imports
    
    def _extract_unique_fields(self, cls, lines: List[str]) -> List[str]:
        """提取并去重字段定义"""
        fields = []
        seen_field_names = set()
        
        if cls.fields:
            for field in cls.fields:
                field_code = self._get_node_source_code(field, lines)
                if field_code.strip():
                    # 提取字段名进行去重
                    field_names = self._extract_field_names_from_code(field_code)
                    
                    # 检查是否有新字段
                    has_new_field = any(name not in seen_field_names for name in field_names)
                    
                    if has_new_field:
                        fields.append(field_code.strip())
                        seen_field_names.update(field_names)
        
        return fields
    
    def _extract_field_names_from_code(self, field_code: str) -> List[str]:
        """从字段代码中提取所有字段名"""
        import re
        field_names = []
        
        # 匹配各种字段声明格式
        # private Type field1, field2;
        # private Type field1 = value;
        # @Annotation private Type field;
        
        # 移除注解和修饰符，找到类型和字段名部分
        clean_code = re.sub(r'@\w+(?:\([^)]*\))?\s*', '', field_code)  # 移除注解
        clean_code = re.sub(r'\b(?:private|protected|public|static|final|volatile|transient)\s+', '', clean_code)  # 移除修饰符
        
        # 匹配字段声明：Type field1, field2 = value, field3;
        field_pattern = r'\b(\w+)\s+([\w,\s=\[\]"\'.\(\)]+);'
        match = re.search(field_pattern, clean_code)
        
        if match:
            field_declarations = match.group(2)
            # 分割多个字段声明
            for field_decl in field_declarations.split(','):
                field_name = re.split(r'[\s=\[\]]', field_decl.strip())[0]
                if field_name and field_name.isidentifier():
                    field_names.append(field_name)
        
        return field_names
    
    def _is_setup_method(self, annotations) -> bool:
        """通用的setup方法识别"""
        setup_annotations = {
            'BeforeEach', 'BeforeAll', 'AfterEach', 'AfterAll',  # JUnit 5
            'Before', 'After', 'BeforeClass', 'AfterClass',      # JUnit 4
            'SetUp', 'TearDown'  # 其他测试框架
        }
        
        return any(
            annotation.name in setup_annotations or
            annotation.name.split('.')[-1] in setup_annotations
            for annotation in annotations
        )
    
    def _is_test_method(self, annotations) -> bool:
        """通用的测试方法识别"""
        test_annotations = {
            'Test', 'ParameterizedTest', 'RepeatedTest',  # JUnit 5
            'TestTemplate', 'TestFactory'  # JUnit 5 其他
        }
        
        return any(
            annotation.name in test_annotations or
            annotation.name.split('.')[-1] in test_annotations
            for annotation in annotations
        )
    
    def _extract_and_merge_methods(self, cls, lines: List[str], covered_methods: List[str]) -> Tuple[List[str], List[str]]:
        """提取并智能合并Setup方法和测试方法"""
        setup_methods = []
        priority_tests = []  # 覆盖目标方法的测试
        other_tests = []     # 其他测试
        teardown_methods = [] # 清理方法
        
        if cls.methods:
            for method in cls.methods:
                method_code = self._get_node_source_code(method, lines)
                if method.annotations:
                    method_type = self._classify_method_type(method.annotations)
                    
                    if method_type == 'setup':
                        setup_methods.append(method_code.strip())
                    elif method_type == 'teardown':
                        teardown_methods.append(method_code.strip())
                    elif method_type == 'test':
                        method_code_stripped = method_code.strip()
                        if self._method_covers_target(method.name, covered_methods):
                            priority_tests.append(method_code_stripped)
                        else:
                            other_tests.append(method_code_stripped)
        
        # 智能合并Setup方法（优先JUnit 5现代方式）
        merged_setup = self._merge_setup_methods(setup_methods)
        
        # 智能选择测试方法
        merged_tests = self._select_optimal_test_methods(priority_tests, other_tests)
        
        return merged_setup, merged_tests
    
    def _classify_method_type(self, annotations) -> str:
        """对方法进行分类：setup/teardown/test/other"""
        setup_annotations = {
            'BeforeEach', 'BeforeAll', 'Before', 'BeforeClass', 'SetUp'
        }
        
        teardown_annotations = {
            'AfterEach', 'AfterAll', 'After', 'AfterClass', 'TearDown'
        }
        
        test_annotations = {
            'Test', 'ParameterizedTest', 'RepeatedTest', 'TestTemplate', 'TestFactory'
        }
        
        for annotation in annotations:
            ann_name = annotation.name.split('.')[-1]
            if ann_name in setup_annotations:
                return 'setup'
            elif ann_name in teardown_annotations:
                return 'teardown'
            elif ann_name in test_annotations:
                return 'test'
        
        return 'other'
    
    def _merge_setup_methods(self, setup_methods: List[str]) -> List[str]:
        """智能合并Setup方法，优先选择最佳实践"""
        if not setup_methods:
            return []
        
        # 如果只有一个setup方法，直接返回
        if len(setup_methods) == 1:
            return setup_methods
        
        # 优先级：@TempDir > @BeforeEach > @Before
        junit5_setups = [s for s in setup_methods if '@TempDir' in s or 'tempDir' in s]
        if junit5_setups:
            return junit5_setups[:1]  # 选择最好的JUnit 5 setup
        
        modern_setups = [s for s in setup_methods if '@BeforeEach' in s]
        if modern_setups:
            return modern_setups[:1]
        
        # 如果都是传统方式，选择最完整的
        return [max(setup_methods, key=len)]
    
    def _select_optimal_test_methods(self, priority_tests: List[str], other_tests: List[str]) -> List[str]:
        """智能选择最优测试方法组合"""
        selected_tests = []
        total_chars = 0
        max_chars = 12000  # 增加上限
        
        # 1. 首先包含所有优先级测试
        for test in priority_tests:
            selected_tests.append(test)
            total_chars += len(test)
        
        # 2. 根据剩余空间选择其他测试
        # 优先选择较短但有代表性的测试
        other_tests_sorted = sorted(other_tests, key=lambda x: (len(x), -x.count('@Test')))
        
        for test in other_tests_sorted:
            if total_chars + len(test) < max_chars:
                selected_tests.append(test)
                total_chars += len(test)
            elif len(selected_tests) < 8:  # 确保最少测试数量
                selected_tests.append(test)
                total_chars += len(test)
            else:
                break
        
        return selected_tests

    def _get_enhanced_target_class(self, report_a: Dict, report_b: Dict) -> str:
        """通用的目标类推断逻辑"""
        print(f"  开始智能目标类推断...")
        
        # 策略1: 从覆盖报告的target_class字段直接获取
        target_class = report_a.get('target_class') or report_b.get('target_class')
        if target_class:
            # 简单验证：去掉包路径，只保留类名
            simple_class_name = target_class.split('.')[-1]
            print(f"  策略1 - 报告字段获取: {target_class} -> {simple_class_name}")
            return simple_class_name
        
        # 策略2: 从所有覆盖方法中统计最频繁的类
        target_class = self._extract_most_frequent_class_from_methods(report_a, report_b)
        if target_class:
            print(f"  策略2 - 方法统计获取: {target_class}")
            return target_class
        
        # 策略3: 从测试类名推断
        test_class_a = report_a.get('test_class', '')
        test_class_b = report_b.get('test_class', '')
        for test_class in [test_class_a, test_class_b]:
            if test_class:
                target_class = self._infer_target_class_from_test_name(test_class)
                if target_class:
                    print(f"  策略3 - 测试类名推断: {test_class} -> {target_class}")
                    return target_class
        
        # 策略4: 如果以上都失败，使用通用搜索策略
        print(f"  所有推断策略失败，将使用通用搜索")
        return None
    
    def _extract_most_frequent_class_from_methods(self, report_a: Dict, report_b: Dict) -> str:
        """从覆盖方法中统计最频繁出现的类名"""
        class_counts = {}
        
        # 收集所有覆盖方法
        all_methods = []
        all_methods.extend(report_a.get('covered_methods', []))
        all_methods.extend(report_b.get('covered_methods', []))
        all_methods.extend(report_a.get('uncovered_methods', []))
        all_methods.extend(report_b.get('uncovered_methods', []))
        
        for method_sig in all_methods:
            try:
                if '.' in method_sig and '(' in method_sig:
                    # 提取类名：package.path.TargetClass.method(...) -> TargetClass
                    class_method = method_sig.split('(')[0]
                    if '.' in class_method:
                        full_class_path = class_method.rsplit('.', 1)[0]
                        simple_class_name = full_class_path.split('.')[-1]
                        
                        # 过滤掉测试类和内部类
                        if not self._should_exclude_class_name(simple_class_name):
                            class_counts[simple_class_name] = class_counts.get(simple_class_name, 0) + 1
            except Exception as e:
                continue
        
        if not class_counts:
            return None
            
        # 返回出现频率最高的类名
        most_frequent_class = max(class_counts.items(), key=lambda x: x[1])[0]
        print(f"    类名统计: {class_counts}")
        return most_frequent_class
    
    def _should_exclude_class_name(self, class_name: str) -> bool:
        """判断是否应该排除某个类名"""
        exclude_patterns = [
            'Test',     # 测试类
            'Mock',     # Mock类
            'Stub',     # Stub类  
            'Abstract', # 抽象类有时不是主要目标
        ]
        
        # 检查是否包含排除模式
        for pattern in exclude_patterns:
            if pattern in class_name:
                return True
                
        # 检查是否为内部类（包含$符号的类名已在方法签名解析时处理）
        return False
    
    def _find_any_relevant_source_file(self, uncovered_methods: set) -> str:
        """通用搜索策略：基于方法签名智能搜索相关源文件"""
        if not uncovered_methods:
            return None
            
        # 从方法签名中推断类名和包路径
        candidate_classes = self._extract_class_candidates_from_signatures(uncovered_methods)
        
        if not candidate_classes:
            # 降级到方法名搜索
            return self._fallback_method_name_search(uncovered_methods)
            
        print(f"  从方法签名推断的候选类: {candidate_classes}")
        
        # 发现所有源码目录
        source_dirs = self._discover_source_directories()
        
        # 按优先级搜索候选类，但优先考虑方法匹配度高的类
        # 重新排序：优先选择可能包含更多目标方法的类
        prioritized_candidates = self._prioritize_candidates_by_method_relevance(candidate_classes, uncovered_methods)
        
        for class_info in prioritized_candidates:
            class_name = class_info['class_name']
            package_hints = class_info.get('package_hints', [])
            
            for src_dir in source_dirs:
                # 首先尝试包路径匹配
                for hint in package_hints:
                    potential_path = os.path.join(src_dir, hint.replace('.', '/'), f"{class_name}.java")
                    if os.path.exists(potential_path):
                        # 验证这个文件确实包含目标方法
                        method_names = self._extract_method_names_from_signatures(uncovered_methods)
                        if self._calculate_method_coverage_score(potential_path, method_names) > 0:
                            print(f"  ✓ 通过包路径找到: {potential_path}")
                            return potential_path
                
                # 递归搜索类名（可能找到多个同名类）
                target_files = self._recursive_find_all_class_files(src_dir, class_name)
                if target_files:
                    # 如果找到多个同名类，选择最匹配的那个
                    best_file = self._select_best_matching_file(target_files, uncovered_methods)
                    if best_file:
                        print(f"  ✓ 通过递归搜索找到: {best_file}")
                        return best_file
        
        # 最终降级到方法名搜索
        return self._fallback_method_name_search(uncovered_methods)
    
    def _prioritize_candidates_by_method_relevance(self, candidates: List[Dict], uncovered_methods: set) -> List[Dict]:
        """根据方法相关性重新排序候选类"""
        method_names = self._extract_method_names_from_signatures(uncovered_methods)
        
        # 启发式评分：检查类名是否与方法名相关
        for candidate in candidates:
            class_name = candidate['class_name'].lower()
            method_relevance = 0
            
            # 如果方法签名中提到了这个类名，优先级更高
            for method_sig in uncovered_methods:
                if class_name in method_sig.lower():
                    method_relevance += 2
            
            # 特殊类名的启发式评分
            if any(method in ['buildNew', 'intersection'] for method in method_names):
                if 'subline' in class_name or 'line' in class_name:
                    method_relevance += 3
                elif 'hyperplane' in class_name or 'region' in class_name:
                    method_relevance += 1
            
            candidate['method_relevance'] = method_relevance
        
        # 按照方法相关性和原始置信度重新排序
        return sorted(candidates, key=lambda x: (x.get('method_relevance', 0), x['confidence']), reverse=True)
    
    def _extract_method_names_from_signatures(self, uncovered_methods: set) -> List[str]:
        """从方法签名中提取方法名"""
        method_names = []
        for method_sig in uncovered_methods:
            try:
                if '(' in method_sig:
                    method_part = method_sig.split('(')[0]
                    if '.' in method_part:
                        method_name = method_part.split('.')[-1]
                    else:
                        method_name = method_part
                    
                    if method_name not in ['<init>', '<clinit>'] and len(method_name) > 2:
                        method_names.append(method_name)
            except:
                continue
        return method_names
    
    def _extract_class_candidates_from_signatures(self, uncovered_methods: set) -> List[Dict]:
        """从方法签名中提取候选类信息"""
        class_candidates = {}
        
        for method_sig in uncovered_methods:
            try:
                # 解析参数类型中的类引用
                if '(' in method_sig and ')' in method_sig:
                    param_part = method_sig.split('(')[1].split(')')[0]
                    
                    # 从JVM签名中提取类名：L...;格式
                    import re
                    class_refs = re.findall(r'L([^;]+);', param_part)
                    
                    for class_ref in class_refs:
                        # 转换路径：package/path/TargetClass
                        if '/' in class_ref:
                            package_path = class_ref.replace('/', '.')
                            class_name = package_path.split('.')[-1]
                            package = '.'.join(package_path.split('.')[:-1])
                            
                            if class_name not in class_candidates:
                                class_candidates[class_name] = {
                                    'class_name': class_name,
                                    'package_hints': [],
                                    'confidence': 0
                                }
                            
                            class_candidates[class_name]['package_hints'].append(package)
                            class_candidates[class_name]['confidence'] += 1
                        
                # 从返回类型中提取
                if ')' in method_sig:
                    return_part = method_sig.split(')')[-1]
                    return_refs = re.findall(r'L([^;]+);', return_part)
                    
                    for class_ref in return_refs:
                        if '/' in class_ref:
                            package_path = class_ref.replace('/', '.')
                            class_name = package_path.split('.')[-1]
                            package = '.'.join(package_path.split('.')[:-1])
                            
                            if class_name not in class_candidates:
                                class_candidates[class_name] = {
                                    'class_name': class_name,
                                    'package_hints': [],
                                    'confidence': 0
                                }
                            
                            if package not in class_candidates[class_name]['package_hints']:
                                class_candidates[class_name]['package_hints'].append(package)
                            class_candidates[class_name]['confidence'] += 0.5  # 返回类型权重稍低
                            
            except Exception as e:
                continue
        
        # 按置信度排序
        candidates = list(class_candidates.values())
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        return candidates
    
    def _fallback_method_name_search(self, uncovered_methods: set) -> str:
        """降级策略：基于方法名搜索"""
        # 提取方法名（去掉参数和类路径）
        method_names = []
        for method_sig in list(uncovered_methods)[:3]:  # 只取前3个方法
            try:
                if '(' in method_sig:
                    method_part = method_sig.split('(')[0]
                    if '.' in method_part:
                        method_name = method_part.split('.')[-1]
                    else:
                        method_name = method_part
                    
                    # 过滤特殊方法
                    if method_name not in ['<init>', '<clinit>'] and len(method_name) > 2:
                        method_names.append(method_name)
            except:
                continue
        
        if not method_names:
            return None
            
        print(f"  降级到方法名搜索: {method_names}")
        
        # 发现所有源码目录
        source_dirs = self._discover_source_directories()
        
        # 在所有源码文件中搜索这些方法
        for src_dir in source_dirs:
            for root, dirs, files in os.walk(src_dir):
                for file in files:
                    if file.endswith('.java'):
                        file_path = os.path.join(root, file)
                        if self._file_contains_methods(file_path, method_names):
                            print(f"  找到包含目标方法的文件: {file_path}")
                            return file_path
        
        return None
    
    def _select_best_matching_file_for_uncovered_methods(self, candidate_files: List[str], uncovered_methods: set) -> str:
        """专门针对未覆盖方法选择最佳匹配文件"""
        if len(candidate_files) == 1:
            return candidate_files[0]
            
        print(f"    找到多个同名类文件: {[self._get_relative_path(f) for f in candidate_files]}")
        
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
    
    def _get_relative_path(self, file_path: str) -> str:
        """获取文件的相对路径用于显示"""
        try:
            parts = file_path.split('/')
            if 'euclidean' in parts:
                idx = parts.index('euclidean')
                return '/'.join(parts[idx:])
            elif 'java' in parts:
                idx = parts.index('java')
                return '/'.join(parts[idx+1:])
            else:
                return '/'.join(parts[-3:])
        except:
            return file_path.split('/')[-1]
    
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
        return list(set(method_names))  # 去重
    
    def _calculate_comprehensive_method_score(self, file_path: str, uncovered_methods: set, method_names: List[str]) -> float:
        """计算文件的综合方法覆盖评分"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            score = 0.0
            
            # 1. 基础方法名匹配评分
            for method_name in method_names:
                if self._method_exists_in_content(content, method_name):
                    score += 1.0
            
            # 2. JVM签名特定匹配评分（更高权重）
            signature_match_count = 0
            for method_sig in uncovered_methods:
                if self._signature_specific_match(content, method_sig):
                    score += 2.0  # 签名特定匹配给更高权重
                    signature_match_count += 1
            
            # 3. 参数类型匹配加分
            score += self._calculate_parameter_type_bonus(content, uncovered_methods)
            
            # 4. 特殊方法存在性加分（针对twod vs threed区分）
            score += self._calculate_dimensional_specificity_bonus(content, uncovered_methods, file_path)
            
            # 5. 关键方法优先级加分
            score += self._calculate_key_method_bonus(content, uncovered_methods)
            
            print(f"      详细评分 - 基础方法:{len([m for m in method_names if self._method_exists_in_content(content, m)])}, "
                  f"签名匹配:{signature_match_count}, 类型加分:{self._calculate_parameter_type_bonus(content, uncovered_methods):.1f}, "
                  f"维度加分:{self._calculate_dimensional_specificity_bonus(content, uncovered_methods, file_path):.1f}, "
                  f"关键方法:{self._calculate_key_method_bonus(content, uncovered_methods):.1f}")
            
            return score
            
        except Exception:
            return 0.0
    
    def _method_exists_in_content(self, content: str, method_name: str) -> bool:
        """检查方法是否在内容中存在"""
        import re
        patterns = [
            # 标准方法声明
            r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)?' + re.escape(method_name) + r'\s*\(',
            # 多行声明
            r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:[\w<>,\s]+\s+)?' + re.escape(method_name) + r'\s*\(',
            # 简单匹配
            r'\b' + re.escape(method_name) + r'\s*\('
        ]
        
        for pattern in patterns:
            if re.search(pattern, content, re.MULTILINE | re.DOTALL):
                return True
        return False
    
    def _signature_specific_match(self, content: str, method_sig: str) -> bool:
        """基于JVM签名进行特定匹配"""
        try:
            # 解析签名
            if '(' not in method_sig:
                return False
                
            method_part = method_sig.split('(')[0]
            method_name = method_part.split('.')[-1] if '.' in method_part else method_part
            
            if method_name in ['<init>', '<clinit>']:
                return False  # 构造方法另外处理
            
            param_part = method_sig.split('(')[1].split(')')[0]
            
            # 检查方法是否存在
            if not self._method_exists_in_content(content, method_name):
                return False
            
            # 特殊检查：对于重要方法给予额外验证
            if method_name in ['setAngle', 'revertSelf', 'translateToPoint']:
                # 这些是twod.Line特有的方法
                return 'twod' in content or 'Euclidean2D' in content
                
            return True
            
        except Exception:
            return False
    
    def _calculate_parameter_type_bonus(self, content: str, uncovered_methods: set) -> float:
        """根据参数类型匹配计算加分"""
        bonus = 0.0
        
        # 检查内容中是否包含相关的参数类型
        type_indicators = {
            'Vector2D': 1.0,      # twod相关
            'Euclidean2D': 1.0,   # twod相关  
            'Vector3D': 0.5,      # threed相关
            'Euclidean3D': 0.5,   # threed相关
            'PolygonsSet': 1.0,   # twod相关
        }
        
        for type_name, weight in type_indicators.items():
            if type_name in content:
                bonus += weight
        
        return bonus
    
    def _calculate_dimensional_specificity_bonus(self, content: str, uncovered_methods: set, file_path: str) -> float:
        """计算维度特异性加分，区分twod和threed"""
        bonus = 0.0
        
        # 检查文件路径维度信息
        path_dimension_bonus = 0.0
        if 'twod' in file_path:
            path_dimension_bonus = 1.0
        elif 'threed' in file_path:
            path_dimension_bonus = 0.3
        
        # 检查是否包含twod特有的方法
        twod_specific_methods = {'setAngle', 'revertSelf', 'translateToPoint', 'contains'}
        has_twod_methods = any(
            method_name in str(uncovered_methods) for method_name in twod_specific_methods
        )
        
        if has_twod_methods:
            # 如果需要twod特有方法，给twod路径额外加分
            if 'twod' in file_path:
                bonus += 3.0  # 强烈偏向twod
            elif 'threed' in file_path:
                bonus -= 1.0  # 惩罚threed
        
        # 检查包声明中的维度信息
        import re
        package_match = re.search(r'package\s+([^;]+);', content)
        if package_match:
            package_name = package_match.group(1)
            if 'twod' in package_name:
                bonus += 1.5
            elif 'threed' in package_name:
                bonus += 0.5
        
        # 检查导入语句中的维度信息
        import_twod_count = len(re.findall(r'import.*\.twod\.', content))
        import_threed_count = len(re.findall(r'import.*\.threed\.', content))
        
        if import_twod_count > import_threed_count:
            bonus += 1.0
        elif import_threed_count > import_twod_count:
            bonus += 0.3
        
        return bonus + path_dimension_bonus
    
    def _calculate_key_method_bonus(self, content: str, uncovered_methods: set) -> float:
        """计算关键方法加分"""
        bonus = 0.0
        
        # 定义关键方法及其权重
        key_methods = {
            'setAngle': 3.0,        # 非常重要的twod特有方法
            'revertSelf': 3.0,      # 非常重要的twod特有方法
            'translateToPoint': 2.0, # 重要的twod方法
            'contains': 2.0,        # 重要方法
            'getOffset': 1.5,       # 通用但重要
            'intersection': 1.5,    # 通用但重要
        }
        
        for method_sig in uncovered_methods:
            for key_method, weight in key_methods.items():
                if key_method in method_sig and self._method_exists_in_content(content, key_method):
                    bonus += weight
        
        return bonus
    
    def _recursive_find_all_class_files(self, src_dir: str, target_class: str) -> List[str]:
        """在指定源码目录中递归查找所有同名类文件"""
        found_files = []
        try:
            for root, dirs, files in os.walk(src_dir):
                # 检查是否有完全匹配的文件
                target_filename = f"{target_class}.java"
                if target_filename in files:
                    file_path = os.path.join(root, target_filename)
                    # 验证文件内容是否确实包含目标类定义
                    if self._verify_class_file_content(file_path, target_class):
                        found_files.append(file_path)
            return found_files
        except Exception as e:
            print(f"    搜索异常: {e}")
            return []
    
    def _select_best_matching_file(self, candidate_files: List[str], uncovered_methods: set) -> str:
        """从多个候选文件中选择最匹配的那个"""
        if len(candidate_files) == 1:
            return candidate_files[0]
            
        print(f"    找到多个同名类文件: {[f.split('/')[-3:] for f in candidate_files]}")
        
        # 提取方法名进行匹配评分
        method_names = []
        for method_sig in uncovered_methods:
            try:
                if '(' in method_sig:
                    method_part = method_sig.split('(')[0]
                    if '.' in method_part:
                        method_name = method_part.split('.')[-1]
                    else:
                        method_name = method_part
                    
                    if method_name not in ['<init>', '<clinit>'] and len(method_name) > 2:
                        method_names.append(method_name)
            except:
                continue
        
        # 为每个文件评分
        best_file = candidate_files[0]
        best_score = 0
        
        for file_path in candidate_files:
            score = self._calculate_method_coverage_score(file_path, method_names)
            print(f"    {file_path.split('/')[-3:]}: 方法覆盖评分 {score}")
            
            if score > best_score:
                best_score = score
                best_file = file_path
        
        return best_file
    
    def _calculate_method_coverage_score(self, file_path: str, method_names: List[str]) -> int:
        """计算文件对目标方法的覆盖评分"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            score = 0
            for method_name in method_names:
                # 检查方法声明（支持多行和不同修饰符）
                import re
                # 更宽松的模式，支持多行声明
                method_patterns = [
                    # 标准单行声明
                    r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)?' + re.escape(method_name) + r'\s*\(',
                    # 多行声明（如buildNew）
                    r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:[\w<>,\s]+\s+)?' + re.escape(method_name) + r'\s*\(',
                    # 简单匹配（作为降级）
                    r'\b' + re.escape(method_name) + r'\s*\('
                ]
                
                found = False
                for pattern in method_patterns:
                    if re.search(pattern, content, re.MULTILINE | re.DOTALL):
                        found = True
                        break
                
                if found:
                    score += 1
            
            return score
            
        except Exception:
            return 0
    
    def _file_contains_methods(self, file_path: str, method_names: List[str]) -> bool:
        """检查文件是否包含指定的方法"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查是否包含多个目标方法（提高准确性）
            found_methods = 0
            for method_name in method_names:
                # 简单的方法声明匹配
                import re
                method_pattern = r'\b(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)?' + re.escape(method_name) + r'\s*\('
                if re.search(method_pattern, content):
                    found_methods += 1
            
            # 如果找到超过一半的方法，认为匹配
            return found_methods >= max(1, len(method_names) // 2)
            
        except Exception:
            return False
    
    def _is_main_target_class(self, class_name: str) -> bool:
        """通用的目标类验证（排除测试、内部类等）"""
        if not class_name:
            return False
        
        # 排除明显的非目标类
        exclude_patterns = ['Test', 'Mock', 'Stub', '$']
        return not any(pattern in class_name for pattern in exclude_patterns)
    
    def _parse_method_signature(self, method_sig: str) -> Dict[str, any]:
        """解析方法签名"""
        method_info = {
            'signature': method_sig,
            'is_constructor': False,
            'class_name': '',
            'method_name': '',
            'parameters': []
        }
        
        try:
            # 检查是否为构造方法
            if '<init>' in method_sig:
                method_info['is_constructor'] = True
                method_info['method_name'] = '<init>'
                print(f"  检测到构造器签名: {method_sig}")
                
                # 对于构造器，类名需要从上下文推断，暂时留空
                # 因为签名格式通常是 <init>(参数类型)V
                
            else:
                # 普通方法
                if '.' in method_sig and '(' in method_sig:
                    class_method = method_sig.split('(')[0]
                    if '.' in class_method:
                        method_info['class_name'] = class_method.rsplit('.', 1)[0]
                        method_info['method_name'] = class_method.rsplit('.', 1)[1]
                    else:
                        method_info['method_name'] = class_method
                else:
                    method_info['method_name'] = method_sig.split('(')[0] if '(' in method_sig else method_sig
            
            # 提取参数信息（简化版）
            if '(' in method_sig and ')' in method_sig:
                param_part = method_sig.split('(')[1].split(')')[0]
                if param_part.strip():
                    # 对于JVM签名格式，解析参数类型
                    if method_info['is_constructor'] and 'Ljava' in param_part:
                        # 处理JVM签名格式：Ljava/io/OutputStream;I -> OutputStream, int
                        params = []
                        if 'Ljava/io/OutputStream;' in param_part:
                            params.append('OutputStream')
                        if 'I' in param_part.replace('Ljava/io/OutputStream;', ''):
                            params.append('int')
                        method_info['parameters'] = params
                    else:
                        method_info['parameters'] = [p.strip() for p in param_part.split(',')]
        
        except Exception as e:
            print(f"  解析方法签名失败: {e}")
        
        print(f"  解析结果: {method_info}")
        return method_info
    
    def _extract_constructor_info(self, tree, lines: List[str], method_info: Dict, target_class: str, result_parts: List[str]) -> bool:
        """提取构造方法信息"""
        found = False
        
        try:
            # 查找构造方法
            for _, constructor in tree.filter(javalang.tree.ConstructorDeclaration):
                if self._constructor_signature_matches(constructor, method_info['signature']):
                    source_code = self._get_node_source_code(constructor, lines)
                    if source_code:
                        result_parts.append(f"构造方法 {target_class}:")
                        result_parts.append(source_code)
                        result_parts.append("")
                        found = True
                        break
        except Exception as e:
            print(f"  提取构造方法失败: {e}")
        
        return found
    
    def _extract_public_method_info(self, tree, lines: List[str], method_info: Dict, result_parts: List[str]) -> bool:
        """提取公共方法信息"""
        found = False
        
        try:
            # 查找普通方法
            for _, method in tree.filter(javalang.tree.MethodDeclaration):
                if method.name == method_info['method_name']:
                    print(f"  找到匹配的方法名: {method.name}")
                    if self._method_signature_matches(method, method_info['signature']):
                        source_code = self._get_node_source_code(method, lines)
                        if source_code:
                            result_parts.append(f"方法 {method_info['method_name']}:")
                            result_parts.append(source_code)
                            result_parts.append("")
                            found = True
                            print(f"  ✓ 成功提取方法源码: {method_info['method_name']}")
                            break
                    else:
                        print(f"  方法签名不匹配: {method.name}")
        except Exception as e:
            print(f"  提取方法失败: {e}")
        
        return found
    
    def _add_method_signature_info(self, method_info: Dict, result_parts: List[str]):
        """添加方法签名信息作为降级策略"""
        if method_info['is_constructor']:
            result_parts.append(f"构造方法签名: {method_info['signature']}")
        else:
            result_parts.append(f"方法签名: {method_info['method_name']} - {method_info['signature']}")
        
        if method_info['parameters']:
            result_parts.append(f"参数: {', '.join(method_info['parameters'])}")
        
        result_parts.append("")
    
    def _generate_method_signatures_only(self, uncovered_methods: set) -> str:
        """生成仅包含方法签名的降级版本"""
        result_parts = []
        result_parts.append("无法获取源码，仅提供方法签名:")
        
        for method_sig in list(uncovered_methods)[:5]:
            method_info = self._parse_method_signature(method_sig)
            self._add_method_signature_info(method_info, result_parts)
        
        return '\n'.join(result_parts)
    
    def _find_target_source_file(self, target_class: str, uncovered_methods: set = None) -> str:
        """通用的目标类源文件查找器"""
        print(f"  开始通用源码查找: {target_class}")
        
        # 1. 智能发现所有可能的源码目录
        source_dirs = self._discover_source_directories()
        
        if not source_dirs:
            print(f"  未发现任何源码目录")
            return None
        
        # 2. 在所有源码目录中递归搜索目标类（支持多个同名类）
        all_candidate_files = []
        for src_dir in source_dirs:
            print(f"  搜索源码目录: {src_dir}")
            candidate_files = self._recursive_find_all_class_files(src_dir, target_class)
            all_candidate_files.extend(candidate_files)
        
        if all_candidate_files:
            if len(all_candidate_files) == 1:
                print(f"  ✓ 找到目标类文件: {all_candidate_files[0]}")
                return all_candidate_files[0]
            else:
                # 多个同名类，需要智能选择
                print(f"  找到多个同名类文件，进行智能选择...")
                # 这里传入原始的未覆盖方法集合进行评分
                best_file = self._select_best_matching_file_for_uncovered_methods(
                    all_candidate_files, uncovered_methods)
                print(f"  ✓ 智能选择最佳匹配: {best_file}")
                return best_file
        
        print(f"  在所有源码目录中未找到目标类: {target_class}")
        return None
    
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
            print(f"    扫描根目录: {root}")
            
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
                                    print(f"    ✓ 发现源码目录: {java_src_path}")
                except Exception as e:
                    print(f"    扫描dataset目录异常: {e}")
            else:
                # 递归查找src/main/java目录
                for dirpath, dirnames, filenames in os.walk(root):
                    # 检查是否是src/main/java目录
                    if dirpath.endswith(os.path.join("src", "main", "java")):
                        # 验证是否包含.java文件
                        has_java_files = self._directory_contains_java_files(dirpath)
                        if has_java_files:
                            source_dirs.append(dirpath)
                            print(f"    ✓ 发现源码目录: {dirpath}")
                    
                    # 限制搜索深度，避免过深的递归
                    if len(dirpath.split(os.sep)) - len(root.split(os.sep)) > 6:
                        dirnames.clear()  # 不再深入子目录
        
        # 去重并排序，优先当前项目
        source_dirs = sorted(list(set(source_dirs)), key=lambda x: (
            0 if self.project_name and self.project_name in x else 1,  # 当前项目优先
            x  # 字母排序
        ))
        print(f"  总共发现 {len(source_dirs)} 个源码目录")
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
    
    def _recursive_find_class_file(self, src_dir: str, target_class: str) -> str:
        """在指定源码目录中递归查找目标类文件"""
        try:
            for root, dirs, files in os.walk(src_dir):
                # 检查是否有完全匹配的文件
                target_filename = f"{target_class}.java"
                if target_filename in files:
                    file_path = os.path.join(root, target_filename)
                    # 双重验证：检查文件内容是否确实包含目标类定义
                    if self._verify_class_file_content(file_path, target_class):
                        return file_path
            return None
        except Exception as e:
            print(f"    搜索异常: {e}")
            return None
    
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
    

    def _determine_correct_package_path(self, crossover_class: str, reference_code: str) -> tuple:
        """确定正确的包路径和测试目录
        
        Args:
            crossover_class: 交叉类名
            reference_code: 参考代码
            
        Returns:
            (package_path, test_dir): 包路径和测试目录的元组
        """
        # 首先尝试从reference_code中找到实际的测试文件
        reference_test_class = self._extract_class_name_from_code(reference_code)
        if reference_test_class:
            # 查找参考测试类的实际文件位置
            reference_file_path = self._find_test_source_file(reference_test_class)
            if reference_file_path and os.path.exists(reference_file_path):
                # 从实际文件路径推导包路径
                package_path = self._extract_package_from_file_path(reference_file_path)
                if package_path:
                    test_dir = os.path.join(self.project_dir, "src", "test", "java", 
                                          package_path.replace(".", os.sep))
                    ensure_dir(test_dir)
                    return package_path, test_dir
        
        # 降级策略：从reference_code中提取包声明
        package_match = re.search(r'package\s+([\w.]+);', reference_code)
        if package_match:
            package_path = package_match.group(1)
        else:
            package_path = ""
        
        test_dir = os.path.join(self.project_dir, "src", "test", "java", 
                              package_path.replace(".", os.sep)) if package_path else os.path.join(self.project_dir, "src", "test", "java")
        ensure_dir(test_dir)
        return package_path, test_dir
    
    def _extract_class_name_from_code(self, code: str) -> str:
        """从代码中提取类名"""
        class_match = re.search(r'(?:public\s+)?class\s+(\w+)', code)
        return class_match.group(1) if class_match else ""
    
    def _extract_package_from_file_path(self, file_path: str) -> str:
        """从文件路径提取包名"""
        try:
            # 找到src/test/java之后的路径部分
            java_path = file_path.split(os.sep + "src" + os.sep + "test" + os.sep + "java" + os.sep)
            if len(java_path) == 2:
                # 获取包路径部分（去掉文件名）
                package_path_parts = java_path[1].split(os.sep)[:-1]  # 去掉最后的.java文件
                return ".".join(package_path_parts)
        except Exception as e:
            print(f"  从文件路径提取包名失败: {e}")
        return ""
    
    def _ensure_correct_package_declaration(self, code: str, package_path: str, test_class: str) -> str:
        """确保代码包含正确的包声明
        
        Args:
            code: Java代码
            package_path: 正确的包路径
            test_class: 测试类名
            
        Returns:
            包含正确包声明的Java代码
        """
        # 首先确保有license头部
        code_with_license = self.unified_manager.ensure_license_header(code)
        
        # 移除现有的错误包声明
        code_without_package = re.sub(r'package\s+[^;]+;\s*\n?', '', code_with_license)
        
        # 获取license头部
        license_header = self.unified_manager.get_apache_license_header()
        
        # 分离license头部和代码内容
        if "Licensed to the Apache Software Foundation" in code_without_package:
            code_after_license = code_without_package[len(license_header):].lstrip()
        else:
            code_after_license = code_without_package
        
        # 构建正确的包声明
        package_declaration = f"package {package_path};"
        
        # 构建完整的文件结构
        complete_code = license_header + "\n\n" + package_declaration + "\n\n" + code_after_license.lstrip()
        
        return complete_code

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
