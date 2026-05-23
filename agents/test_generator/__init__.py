"""
Test generation package.

Responsible for generating Java test code.
"""

from .file_writer import TestFileWriter, file_writer, generate_for_class
from .prompt_builder import PromptBuilder
from .maven_analyzer import MavenProjectAnalyzer

# Reuse the Maven parser from test_repair to keep error parsing consistent.
import sys
import os

# Add the current agents directory to sys.path so sibling packages can be imported.
current_agents_dir = os.path.dirname(os.path.dirname(__file__))
if current_agents_dir not in sys.path:
    sys.path.insert(0, current_agents_dir)

from test_repair.maven_parser import MavenOutputParser, run_maven_test, run_and_parse_test

__all__ = [
    "TestFileWriter",
    "file_writer",
    "generate_for_class",
    "PromptBuilder",
    "MavenProjectAnalyzer",
    "MavenOutputParser",
    "run_maven_test",
    "run_and_parse_test",
]
