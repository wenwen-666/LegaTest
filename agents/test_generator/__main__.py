"""
Entry point for the test generator package.
"""

import os
import sys

# Add the project root to the Python path.
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from agents.test_generator.main import main

if __name__ == "__main__":
    main()
