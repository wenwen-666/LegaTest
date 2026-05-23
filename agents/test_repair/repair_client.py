"""
测试修复客户端

提供统一的测试代码修复接口，封装规则修复和LLM修复的完整流程
"""

import os
import sys
import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# 配置日志
logger = logging.getLogger(__name__)

@dataclass
class RepairStats:
    """修复过程统计信息"""
    repair_attempts: int = 0
    rule_fixes_applied: int = 0
    llm_fixes_applied: int = 0
    llm_calls: int = 0
    total_repair_time: float = 0.0
    llm_repair_time: float = 0.0
    rule_repair_time: float = 0.0
    success: bool = False
    
    def update_total_repair_time(self):
        """更新总修复时间"""
        self.total_repair_time = self.llm_repair_time + self.rule_repair_time
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class TestRepairClient:
    """测试修复客户端"""
    
    def __init__(self, base_dir: str = None):
        """
        初始化修复客户端
        
        Args:
            base_dir: 项目基础目录
        """
        if base_dir is None:
            # 从当前文件位置推断base_dir
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        else:
            self.base_dir = base_dir
            
        # 添加当前模块路径到sys.path
        repair_module_path = os.path.dirname(os.path.abspath(__file__))
        if repair_module_path not in sys.path:
            sys.path.insert(0, repair_module_path)
    
    def repair_test_file(self, test_file_path: str, cls_info: Dict[str, Any]) -> Tuple[str, RepairStats]:
        """
        修复测试文件的完整流程
        
        Args:
            test_file_path: 测试文件路径（相对于项目根目录）
            cls_info: 类信息，包含：
                - project_path: 项目路径
                - package: 包名
                - className: 类名
                - suite_index: 测试套件索引
                - maven_output: Maven输出（可选）
                - maven_success: Maven是否成功（可选）
                - maven_parsed_output: 解析后的Maven输出（可选）
                - parsed_error_prompt: 解析后的错误提示（可选）
                
        Returns:
            (最终文件路径, 修复统计信息) - 文件路径为空字符串表示失败
        """
        repair_stats = RepairStats()
        start_time = time.time()
        
        try:
            # 导入修复组件，使用绝对导入避免相对导入错误
            import sys
            import os
            
            # 确保test_repair模块在sys.path中
            test_repair_dir = os.path.dirname(os.path.abspath(__file__))
            if test_repair_dir not in sys.path:
                sys.path.insert(0, test_repair_dir)
            
            # 需要修改process_test，让它能返回统计信息
            # 暂时先调用原有的process_test逻辑，后续改进
            from rule_fixer.rule_repair import process_test
            
            # 在cls_info中添加统计收集器，供process_test使用
            cls_info['repair_stats'] = repair_stats
            
            # 调用修复逻辑
            result = process_test(test_file_path, cls_info)
            
            # 完成统计
            actual_total_time = time.time() - start_time
            # 使用实际总时间和累积的修复时间中的较大值
            if repair_stats.llm_repair_time + repair_stats.rule_repair_time > 0:
                repair_stats.update_total_repair_time()  # 使用累积的修复时间
            else:
                repair_stats.total_repair_time = actual_total_time  # 使用实际总时间
            repair_stats.success = bool(result)
            
            return result, repair_stats
            
        except Exception as e:
            logger.error(f"修复测试文件失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            repair_stats.total_repair_time = time.time() - start_time
            repair_stats.success = False
            return "", repair_stats
    
    def repair_with_error_output(self, test_file_path: str, error_output: str, 
                                project_path: str, class_name: str, package_name: str = None) -> bool:
        """
        基于错误输出进行修复（适用于iterative_evolution）
        
        Args:
            test_file_path: 测试文件路径
            error_output: Maven错误输出
            project_path: 项目路径
            class_name: 类名
            package_name: 包名（可选，如果为None则尝试自动检测）
            
        Returns:
            修复是否成功
        """
        try:
            # 导入解析组件（使用绝对导入）
            import sys
            import os
            
            # 确保test_repair模块在sys.path中
            test_repair_dir = os.path.dirname(os.path.abspath(__file__))
            if test_repair_dir not in sys.path:
                sys.path.insert(0, test_repair_dir)
            
            from maven_parser import MavenOutputParser
            from rule_fixer.rule_repair import process_test
            
            # 解析Maven错误
            parser = MavenOutputParser()
            parsed_output = parser.parse(error_output)
            
            # 如果没有提供包名，尝试从文件路径推断
            if package_name is None:
                package_name = self._infer_package_name(test_file_path, project_path)
            
            # 构建类信息
            cls_info = {
                'project_path': project_path,
                'package': package_name,
                'className': class_name,
                'suite_index': 0,
                'maven_output': error_output,
                'maven_success': False,
                'maven_parsed_output': parsed_output,
                'parsed_error_prompt': parsed_output.get_error_prompt()
            }
            
            # 调用修复
            result = process_test(test_file_path, cls_info)
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"基于错误输出修复失败: {e}")
            return False
    
    def _infer_package_name(self, test_file_path: str, project_path: str) -> str:
        """
        从文件路径推断包名
        
        Args:
            test_file_path: 测试文件路径
            project_path: 项目路径
            
        Returns:
            推断的包名
        """
        try:
            # 尝试从文件内容中读取package声明
            full_file_path = os.path.join(project_path, test_file_path)
            if os.path.exists(full_file_path):
                with open(full_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    import re
                    package_match = re.search(r'package\s+([\w.]+)\s*;', content)
                    if package_match:
                        return package_match.group(1)
            
            # 如果无法从文件读取，尝试从路径推断
            # 假设路径格式为 src/test/java/package/path/TestClass.java
            relative_path = os.path.relpath(test_file_path, project_path)
            if 'src/test/java/' in relative_path:
                package_path = relative_path.split('src/test/java/')[1]
                package_dir = os.path.dirname(package_path)
                if package_dir:
                    return package_dir.replace(os.path.sep, '.')
            
            return ''
            
        except Exception as e:
            logger.warning(f"推断包名失败: {e}")
            return ''
    
    def get_maven_parser(self):
        """
        获取Maven解析器实例
        
        Returns:
            MavenOutputParser实例，失败时返回None
        """
        try:
            import sys
            import os
            
            # 确保test_repair模块在sys.path中
            test_repair_dir = os.path.dirname(os.path.abspath(__file__))
            if test_repair_dir not in sys.path:
                sys.path.insert(0, test_repair_dir)
            
            from maven_parser import MavenOutputParser
            return MavenOutputParser()
        except ImportError as e:
            logger.error(f"导入Maven解析器失败: {e}")
            return None
        except Exception as e:
            logger.error(f"创建Maven解析器失败: {e}")
            return None
    
    def run_maven_test(self, project_dir: str, test_class: str) -> tuple[str, bool]:
        """
        运行Maven测试
        
        Args:
            project_dir: Maven项目目录
            test_class: 测试类名
            
        Returns:
            (输出结果, 是否成功)
        """
        try:
            import sys
            import os
            
            # 确保test_repair模块在sys.path中
            test_repair_dir = os.path.dirname(os.path.abspath(__file__))
            if test_repair_dir not in sys.path:
                sys.path.insert(0, test_repair_dir)
            
            from maven_parser import run_maven_test
            return run_maven_test(project_dir, test_class)
        except ImportError as e:
            error_msg = f"导入Maven测试函数失败: {e}"
            logger.error(error_msg)
            return error_msg, False
        except Exception as e:
            error_msg = f"执行Maven测试失败: {e}"
            logger.error(error_msg)
            return error_msg, False
