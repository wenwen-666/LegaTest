"""
演化测试框架包

这是一个基于遗传算法的测试套件演化优化框架，通过自动化交叉、变异和选择操作，
不断优化测试套件以提高代码覆盖率和测试质量。
"""

from .core import EvolutionaryTesting
from .evaluation import DiversityCalculator
from .operators import CrossoverOperator, MutationOperator
from .clients import LLMClient
from .test_executor import TestExecutor
from .coverage_analyzer import CoverageAnalyzer

__version__ = "1.0.0"
__all__ = [
    'EvolutionaryTesting',
    'DiversityCalculator',
    'CrossoverOperator',
    'MutationOperator',
    'LLMClient',
    'TestExecutor',
    'CoverageAnalyzer'
] 