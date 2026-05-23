"""
迭代进化算法的常量定义
解决循环依赖问题
"""

# 进化算法参数
MAX_GENERATIONS = 10
FITNESS_THRESHOLD = 0.0        # 不设门槛，任何适应度都检查收敛
LINE_COVERAGE_TARGET = 98.0    # 行覆盖率目标（平均）
BRANCH_COVERAGE_TARGET = 98.0  # 分支覆盖率目标
TESTS_PER_GENERATION = 10      # 每代测试数量

# 交叉操作参数
ENABLE_CROSSOVER_MUTATION = True  # 默认对交叉后的测试进行变异

# 变异操作参数
MUTATION_MAX = 0.3
MUTATION_MIN = 0.1
MUTATION_DECAY_RATE = 0.1

# 文件路径常量
DEFAULT_PACKAGE = " "   #自己指定

# 覆盖率阈值
BRANCH_COVERAGE_SKIP_THRESHOLD = 95.0  # 分支覆盖率达到95%时跳过变异