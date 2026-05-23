"""
Java Unit Test Generation System

This package contains three main agents:
1. test_generator - Generates initial test suites for Java classes
2. test_repair - Fixes compilation and runtime errors in test code  
3. iterative_evolution - Evolves test suites to improve coverage and quality

The system is designed to be portable and work across different platforms.
"""

__version__ = "1.0.0"
__author__ = "Java Test Generation System"

# Import main classes from each agent for convenience
from .test_generator import TestFileWriter, PromptBuilder, MavenProjectAnalyzer
from .test_repair import TestRepairClient
from .iterative_evolution import EvolutionaryTesting

__all__ = [
    'TestFileWriter',
    'PromptBuilder', 
    'MavenProjectAnalyzer',
    'TestRepairClient',
    'EvolutionaryTesting'
]