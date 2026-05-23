"""
程序入口模块
"""

import argparse
import os
import sys
from .core import EvolutionaryTesting

def main():
    """主函数，用于初始化和运行演化测试过程"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='演化测试优化工具')
    parser.add_argument('--base_dir', type=str, required=True, help='项目基础目录路径')
    parser.add_argument('--project', type=str, required=True, help='目标项目名称')
    parser.add_argument('--max_gen', type=int, default=10, help='最大迭代代数，默认为10')
    parser.add_argument('--start_gen', type=int, default=1, help='起始代数，默认为1')
    parser.add_argument('--end_gen', type=int, default=None, help='结束代数，默认为None（使用max_gen）')
    parser.add_argument('--fitness_threshold', type=float, default=0.95, help='适应度阈值，默认为0.95')
    parser.add_argument('--branch_target', type=float, default=98.0, help='分支覆盖率目标，默认为98.0%%')
    parser.add_argument('--target_class', type=str, default=None, help='指定单个被测类进行测试（可选）')
    parser.add_argument('--force_overwrite', action='store_true', help='强制覆盖现有的测试报告，默认为False')
    
    args = parser.parse_args()

    # 验证代数参数
    if args.end_gen is None:
        args.end_gen = args.max_gen

    if args.start_gen < 1:
        print("错误: 起始代数必须大于等于1")
        sys.exit(1)

    if args.end_gen < args.start_gen:
        print("错误: 结束代数必须大于等于起始代数")
        sys.exit(1)

    if args.start_gen > args.max_gen:
        print("错误: 起始代数不能超过最大代数")
        sys.exit(1)

    # 验证基础目录存在
    if not os.path.exists(args.base_dir):
        print(f"错误: 基础目录 {args.base_dir} 不存在")
        sys.exit(1)
    
    # 验证项目目录存在
    project_dir = os.path.join(args.base_dir, "dataset", args.project)
    if not os.path.exists(project_dir):
        print(f"错误: 项目目录 {project_dir} 不存在")
        sys.exit(1)
    
    # 更新全局配置
    from . import core
    core.MAX_GENERATIONS = args.max_gen
    core.FITNESS_THRESHOLD = args.fitness_threshold
    core.BRANCH_COVERAGE_TARGET = args.branch_target
    
    print("=" * 50)
    print("演化测试优化系统")
    print("=" * 50)
    print(f"项目: {args.project}")
    print(f"基础目录: {args.base_dir}")
    print(f"最大迭代次数: {args.max_gen}")
    print(f"起始代数: {args.start_gen}")
    print(f"结束代数: {args.end_gen}")
    print(f"适应度阈值: {args.fitness_threshold}")
    print(f"分支覆盖率目标: {args.branch_target}%")
    if args.target_class:
        print(f"目标类: {args.target_class}")
    else:
        print("目标类: 自动发现所有TestV*测试类")
    print(f"强制覆盖: {'是' if args.force_overwrite else '否'}")
    print("=" * 50)
    
    try:
        # 初始化测试优化器
        tester = EvolutionaryTesting(args.base_dir, args.project, args.target_class)

        # 设置强制覆盖模式
        tester.force_overwrite = args.force_overwrite

        # 运行演化优化 - 使用指定的代数范围
        if args.start_gen == 1:
            # 从第1代开始正常运行
            tester.run_evolution(end_gen=args.end_gen)
        else:
            # 从指定代数继续演化
            tester.run_evolution_range(args.start_gen, args.end_gen)
        
    except KeyboardInterrupt:
        print("\n用户中断演化过程")
        sys.exit(0)
    except Exception as e:
        print(f"演化过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 