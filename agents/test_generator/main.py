"""
测试生成器主模块
处理命令行参数和调度功能
"""
import os
import sys
import argparse
import logging
import time
import signal
import concurrent.futures
import json
import re
from typing import List, Tuple, Optional, Dict, Any
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
from pathlib import Path

# 添加当前目录到PYTHONPATH，便于导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入必要模块
from .file_writer import generate_for_class
from .config import config  # 导入config实例而不是具体常量
from .llm_interface import test_api_connection
from .json_extractor import (
    find_json_config, extract_valid_classes, 
    get_formatted_class_info_from_path
)
from .api_extractor import enhance_class_info
from .method_analyzer import calculate_test_distribution, generate_test_distribution_summary
from .json_extractor import find_all_repos  # 从json_extractor导入函数
from .prompt_builder import PromptBuilder
from .statistics import global_stats_collector

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# 获取默认测试套件数量
DEFAULT_TEST_SUITES_PER_CLASS = config.test_generation["suites_per_class"]

def setup_argparser() -> argparse.ArgumentParser:
    """设置命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='Java测试生成器 - 为Java类自动生成JUnit测试套件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 为项目中的所有类生成测试
  python -m agents.test_generator
  
  # 为指定的类生成测试
  python -m agents.test_generator --class ClassName
  
  # 为指定项目的所有类生成测试
  python -m agents.test_generator --project <project_name>
  
  # 修复已生成的测试文件
  python -m agents.test_generator --fix-all
  
  # 测试API连接
  python -m agents.test_generator --test-api
"""
    )
    
    # 生成模式参数
    generation_group = parser.add_argument_group('生成选项')
    generation_group.add_argument('--class', dest='class_name', help='只为指定的类生成测试')
    generation_group.add_argument('--count', type=int, default=DEFAULT_TEST_SUITES_PER_CLASS, 
                        help=f'每个类生成的测试套件数量 (默认: {DEFAULT_TEST_SUITES_PER_CLASS})')
    generation_group.add_argument('--project', help='只处理指定的项目')
    generation_group.add_argument('--parallel', action='store_true', help='启用并行测试生成（多线程）')
    generation_group.add_argument('--workers', type=int, default=4, help='并行工作线程数量（默认：4）')
    generation_group.add_argument('--verify-method-count', action='store_true', 
                                help='验证生成的测试方法数量是否足够')
    generation_group.add_argument('--analyze-only', action='store_true',
                                help='仅分析类复杂度并显示测试分布，不生成测试')
    
    # 修复模式参数
    fix_group = parser.add_argument_group('修复选项')
    fix_group.add_argument('--force-rename-classes', action='store_true', 
                      help='强制重命名类以匹配文件名（默认不重命名类名）')
    fix_group.add_argument('--regenerate-insufficient', action='store_true',
                      help='重新生成测试方法数量不足的测试类')
    
    # 其他选项
    misc_group = parser.add_argument_group('其他选项')
    misc_group.add_argument('--test-api', action='store_true', help='测试API连接是否正常')
    misc_group.add_argument('--verbose', action='store_true', help='显示详细输出')
    
    return parser

def generate_for_class_wrapper(args):
    """生成测试的多进程包装器"""
    cls_info, project_path, suite_index = args
    try:
        generate_for_class(cls_info, project_path, suite_index)
        return True, cls_info.get('className', 'Unknown')
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return False, f"Error generating tests for {cls_info.get('className', 'Unknown')}: {e}\n{trace}"

def handle_analyze_only(repos: List[Tuple[str, str, str]], args: argparse.Namespace) -> None:
    """
    仅分析模式处理函数
    
    Args:
        repos: 仓库列表
        args: 命令行参数
    """
    logger.info("仅分析模式...")
    
    target_class = args.class_name
    target_project = args.project
    
    try:
        for project_name, project_path, json_path in repos:
            if target_project and project_name.lower() != target_project.lower():
                continue
                
            logger.info(f"分析项目: {project_name}")
            
            # 加载类信息
            with open(json_path, 'r', encoding='utf-8') as f:
                classes = json.load(f)
            
            # 处理每个类
            for cls_info in classes:
                class_name = cls_info.get('className')
                
                # 如果指定了目标类，则只处理该类
                if target_class and class_name != target_class:
                    continue
                    
                logger.info(f"分析类: {class_name}")
                
                # 使用json_extractor.get_formatted_class_info获取格式化的类信息
                try:
                    enhanced_cls_info = get_formatted_class_info_from_path(project_path, class_name, json_path)
                except Exception as e:
                    logger.error(f"获取格式化类信息时出错: {e}")
                    continue
                
                # 获取方法信息
                methods_info = []
                if "method_details" in enhanced_cls_info and enhanced_cls_info["method_details"]:
                    methods_info = enhanced_cls_info["method_details"]
                elif "methods" in enhanced_cls_info:
                    # 如果只有方法名列表，简单处理
                    method_names = enhanced_cls_info["methods"]
                    for method_name in method_names:
                        if isinstance(method_name, str):
                            name = method_name
                            if '(' in method_name and ')' in method_name:
                                name = method_name.split('(')[0]
                            
                            methods_info.append({
                                "name": name,
                                "signature": method_name,
                                "is_getter_setter": name.startswith("get") or name.startswith("set") or name.startswith("is")
                            })
                
                # 计算测试分布
                methods_info = methods_info or []
                test_distribution = calculate_test_distribution(methods_info)
                enhanced_cls_info['test_distribution'] = test_distribution
            
                # 输出测试分布汇总
                summary = generate_test_distribution_summary(test_distribution)
                logger.info(f"类 {class_name} 的测试分布:\n{summary}")
                
                if target_class:
                    break
                    
    except Exception as e:
        logger.error(f"分析项目时出错: {e}")
        import traceback
        traceback.print_exc()

def is_test_file_exists(project_path: str, cls_info: Dict[str, Any], suite_index: int) -> bool:
    """
    检查测试文件是否已存在
    
    Args:
        project_path: 项目路径
        cls_info: 类信息字典
        suite_index: 测试套件索引
        
    Returns:
        如果测试文件已存在，则返回True，否则返回False
    """
    class_name = cls_info.get('className', '')
    package_name = cls_info.get('package', '')
    test_dir = cls_info.get('testDir', 'src/test/java')
    package_path = package_name.replace('.', '/')
    
    if suite_index > 0:
        final_class_name = f"{class_name}TestV{suite_index}"
    else:
        final_class_name = f"{class_name}Test"
        
    final_file_name = f"{final_class_name}.java"
    final_file_path = f"{test_dir}/{package_path}/{final_file_name}"
    final_file_path_full = os.path.join(project_path, final_file_path)
    
    return os.path.exists(final_file_path_full)

def handle_generate_mode(repos: List[Tuple[str, str, str]], args: argparse.Namespace) -> None:
    """
    处理测试生成模式
    
    Args:
        repos: 仓库列表，每个元素为(项目名, 项目路径, json文件路径)的元组
        args: 命令行参数
    """
    logger.info("开始生成测试...")
    
    if args.analyze_only:
        handle_analyze_only(repos, args)
        return
    
    target_class = args.class_name
    target_project = args.project
    suite_count = args.count
    use_parallel = args.parallel
    worker_count = args.workers
    verify_method_count = args.verify_method_count
    
    # 创建提示词构建器
    prompt_builder = PromptBuilder()
    
    total_generated = 0
    total_skipped = 0
    errors = []
    
    for project_name, project_path, json_path in repos:
        if target_project and project_name.lower() != target_project.lower():
            continue
            
        logger.info(f"处理项目: {project_name}")
        
        # 为当前项目设置统计收集器的项目路径
        global_stats_collector.project_path = project_path
        global_stats_collector.stats_dir = os.path.join(project_path, "stats")
        os.makedirs(global_stats_collector.stats_dir, exist_ok=True)
        
        # 增强代码：检查是否有Java文件
        java_dir = os.path.join(project_path, 'src', 'main', 'java')
        if not os.path.exists(java_dir):
            logger.warning(f"项目 {project_name} 中不存在Java源代码目录")
            continue
            
        try:
            # 加载类信息
            with open(json_path, 'r', encoding='utf-8') as f:
                classes = json.load(f)
                
            # 简单计算项目规模信息
            class_count = len(classes)
            total_methods = sum(len(cls.get('methods', [])) for cls in classes if isinstance(cls.get('methods', []), list))
            avg_methods = total_methods / class_count if class_count > 0 else 0
            max_methods = max((len(cls.get('methods', [])) for cls in classes if isinstance(cls.get('methods', []), list)), default=0)
            
            logger.info(f"项目规模: 类数量: {class_count}, "
                      f"平均每类方法数: {avg_methods:.1f}, "
                      f"最大方法数: {max_methods}")
            
            # 创建测试目录（如果不存在）
            test_dir = os.path.join(project_path, 'src', 'test', 'java')
            os.makedirs(test_dir, exist_ok=True)
            
            # 处理每个类
            if use_parallel and not target_class:
                # 构建参数列表
                tasks = []
                skipped_count = 0
                
                for cls_info in classes:
                    class_name = cls_info.get('className')
                    
                    # 如果指定了目标类，则只处理该类
                    if target_class and class_name != target_class:
                        continue
            
                    try:
                        # 使用json_extractor获取格式化的类信息
                        enhanced_cls_info = get_formatted_class_info_from_path(project_path, class_name, json_path)
                        logger.info(f"成功获取类 {class_name} 的信息")
                    except Exception as e:
                        logger.error(f"获取类 {class_name} 信息失败: {e}")
                        continue
                    
                    # 为每个测试套件创建任务，但只有在测试文件不存在时才添加
                    for i in range(1, suite_count + 1):
                        if not is_test_file_exists(project_path, enhanced_cls_info, i):
                            tasks.append((enhanced_cls_info, project_path, i))
                        else:
                            skipped_count += 1
                            logger.info(f"测试文件已存在，跳过生成: 类 {class_name} 套件 {i}")
                
                total_skipped += skipped_count
                logger.info(f"跳过了 {skipped_count} 个已存在的测试文件")
                
                if not tasks:
                    logger.info("没有需要生成的测试，所有测试文件都已存在")
                    continue
                
                # 使用线程池并行生成
                logger.info(f"并行生成测试，使用 {worker_count} 个工作线程")
                with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                    results = list(tqdm(executor.map(generate_for_class_wrapper, tasks), 
                                     total=len(tasks), 
                                     desc="生成测试"))
                        
                # 处理结果
                for success, result in results:
                    if success:
                        total_generated += 1
                    else:
                        errors.append(result)
            else:
                # 串行处理每个类
                for cls_info in classes:
                    class_name = cls_info.get('className')
                    
                    # 如果指定了目标类，则只处理该类
                    if target_class and class_name != target_class:
                        continue
                        
                    logger.info(f"为类 {class_name} 生成 {suite_count} 个测试套件")
                    
                    # 获取增强的类信息
                    try:
                        # 使用json_extractor获取格式化的类信息
                        enhanced_cls_info = get_formatted_class_info_from_path(project_path, class_name, json_path)
                        logger.info(f"成功获取类 {class_name} 的信息")
                    except Exception as e:
                        logger.error(f"获取类 {class_name} 的信息时出错: {e}")
                        continue
                    
                    # 生成测试分布信息并打印
                    try:
                        methods_info = []
                        if "method_details" in enhanced_cls_info and enhanced_cls_info["method_details"]:
                            methods_info = enhanced_cls_info["method_details"]
                        elif "methods" in enhanced_cls_info:
                            # 如果只有方法名列表，简单处理
                            method_names = enhanced_cls_info["methods"]
                            methods_info = []
                            for method_name in method_names:
                                if isinstance(method_name, str):
                                    name = method_name
                                    if '(' in method_name and ')' in method_name:
                                        name = method_name.split('(')[0]
                                    
                                    methods_info.append({
                                        "name": name,
                                        "signature": method_name,
                                        "is_getter_setter": name.startswith("get") or name.startswith("set") or name.startswith("is")
                                    })
                        
                        # 计算测试分布
                        methods_info = methods_info or []
                        test_distribution = calculate_test_distribution(methods_info)
                        summary = generate_test_distribution_summary(test_distribution)
                        logger.info(f"类 {class_name} 的测试分布:\n{summary}")
                    except Exception as e:
                        logger.error(f"计算测试分布时出错: {e}")
                    
                    # 为每个套件生成测试，但只有在测试文件不存在时才生成
                    skipped_count = 0
                    for i in range(1, suite_count + 1):
                        if not is_test_file_exists(project_path, enhanced_cls_info, i):
                            try:
                                generate_for_class(enhanced_cls_info, project_path, i)
                                total_generated += 1
                            except Exception as e:
                                error_msg = f"为类 {class_name} 生成测试套件 {i} 时出错: {e}"
                                logger.error(error_msg)
                                errors.append(error_msg)
                                import traceback
                                traceback.print_exc()
                        else:
                            skipped_count += 1
                            logger.info(f"测试文件已存在，跳过生成: 类 {class_name} 套件 {i}")
                    
                    total_skipped += skipped_count
                    if skipped_count > 0:
                        logger.info(f"类 {class_name} 跳过了 {skipped_count} 个已存在的测试文件")
                    
                    # 保存类级别统计汇总
                    global_stats_collector.save_class_summary(class_name)
                    
                    # 如果只生成指定类的测试，完成后退出循环
                    if target_class:
                        break
                        
            logger.info(f"项目 {project_name} 测试生成完成")
            
        except Exception as e:
            logger.error(f"处理项目 {project_name} 时出错: {e}")
            errors.append(f"项目 {project_name} 错误: {e}")
            import traceback
            traceback.print_exc()
    
    logger.info(f"测试生成完成，总共生成了 {total_generated} 个测试套件，跳过了 {total_skipped} 个已存在的测试套件")
    
    if errors:
        logger.warning(f"生成过程中有 {len(errors)} 个错误:")
        for i, error in enumerate(errors[:10]):  # 只显示前10个错误
            logger.warning(f"错误 {i+1}: {error}")
        if len(errors) > 10:
            logger.warning(f"... 以及 {len(errors) - 10} 个其他错误")
    
    # 输出统计报告
    global_stats_collector.print_session_summary()
    
    # 保存统计数据到文件
    stats_file = os.path.join(os.getcwd(), "test_generation_stats.json")
    global_stats_collector.save_statistics(stats_file)

def main() -> None:
    """主入口函数"""
    # 解析命令行参数
    parser = setup_argparser()
    args = parser.parse_args()
    
    # 处理 --verbose 参数
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("已启用详细日志输出")
    
    # 处理 --test-api 参数
    if args.test_api:
        logger.info("测试API连接...")
        if test_api_connection():
            logger.info("API连接测试成功！")
        else:
            logger.error("API连接测试失败")
        return
        
    # 使用json_extractor中的函数查找项目
    repos = find_all_repos()
    
    # 默认生成模式
    handle_generate_mode(repos, args)

# 程序入口
if __name__ == "__main__":
    # 设置信号处理，便于优雅退出
    def signal_handler(sig, frame):
        logger.info("收到中断信号，正在退出...")
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    
    main()
