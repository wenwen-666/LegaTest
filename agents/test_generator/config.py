"""
Configuration management module with support for loading settings
from multiple sources.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
import logging
import time

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager."""

    def __init__(self):
        # API configuration
        self.api = {
            "key": os.getenv("DEEPSEEK_API_KEY", "your api key"),
            "base_url": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            "model": os.getenv("API_MODEL", "deepseek-chat"),
            "timeout": int(os.getenv("API_REQUEST_TIMEOUT", "120")),
        }

        # Apache License header
        self.LICENSE_HEADER = """/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */"""

        # Test generation configuration
        self.test_generation = {
            "min_test_methods": int(os.getenv("MIN_TEST_METHODS_COUNT", "3")),
            "min_code_length": int(os.getenv("MIN_CODE_LENGTH", "100")),
            "suites_per_class": int(os.getenv("DEFAULT_TEST_SUITES_PER_CLASS", "10")),
        }

        # Prompt configuration
        self.prompt = {
            "language": os.getenv("PROMPT_LANGUAGE", "en"),
            "use_bilingual": os.getenv("USE_BILINGUAL_TAGS", "false").lower() == "true",
        }

        # Statistics output configuration
        self.statistics = {
            "output_to_file": os.getenv("STATS_OUTPUT_TO_FILE", "true").lower() == "true",
            "detailed_stats_file": os.getenv("DETAILED_STATS_FILE", "test_generation_detailed_stats.txt"),
            "show_detailed_console": os.getenv("SHOW_DETAILED_CONSOLE", "false").lower() == "true",
        }

        # Path configuration
        self.paths = {
            "prompt_dir": Path(os.path.dirname(__file__)) / "prompts",
        }

        # Test focus strategies
        self.focus_approaches = [
            "Focus on NORMAL INPUTS and BASIC FUNCTIONALITY verification. ONLY test public methods directly.",
            "Focus on EDGE CASES and BOUNDARY CONDITIONS testing. ONLY test public methods directly.",
            "Focus on EXCEPTION HANDLING and ERROR SCENARIOS. ONLY test public methods directly.",
            "Focus on ISOLATED and MOCKED DEPENDENCIES to verify the class behavior independently of external systems. ONLY test public methods directly.",
            "Focus on DATA TRANSFORMATION and STATE CHANGES caused by method calls. ONLY test public methods directly.",
            "Create an INNOVATIVE test suite with valid, compilable, and meaningful edge or rare scenarios. ONLY test public methods directly.",
            "Design a BALANCED test suite that combines creativity with standard testing practices. ONLY test public methods directly.",
            "Focus on COMPREHENSIVE CODE COVERAGE including methods, branches, and conditions while following JUnit 5 best practices. ONLY test public methods directly.",
            "Generate a test suite WITHOUT ANY SPECIFIC FOCUS. Use your best judgment and test design intuition. ONLY test public methods directly.",
            "Use the GIVEN PROMPT DETAILS to generate a COMPLETE and STRUCTURED test suite without assuming extra behavior. ONLY test public methods directly.",
        ]

    def load_from_file(self, file_path: str) -> bool:
        """Load configuration from a JSON file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            # Update API settings
            if "api" in config_data:
                self.api.update(config_data["api"])

            # Update test generation settings
            if "test_generation" in config_data:
                self.test_generation.update(config_data["test_generation"])

            # Update prompt settings
            if "prompt" in config_data:
                self.prompt.update(config_data["prompt"])

            # Update statistics settings
            if "statistics" in config_data:
                self.statistics.update(config_data["statistics"])

            # Update path settings
            if "paths" in config_data:
                for key, value in config_data["paths"].items():
                    self.paths[key] = Path(value)

            # Update test focus strategies
            if "focus_approaches" in config_data:
                self.focus_approaches = config_data["focus_approaches"]

            # Update the license header
            if "license_header" in config_data:
                self.LICENSE_HEADER = config_data["license_header"]

            logger.info(f"Successfully loaded configuration from file: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration from file: {e}")
            return False

    def validate(self) -> bool:
        """Validate the current configuration."""
        try:
            # Validate API settings
            assert self.api["base_url"], "API base URL cannot be empty"
            assert self.api["model"], "API model cannot be empty"
            assert self.api["timeout"] > 0, "timeout must be greater than 0"

            # Validate test generation settings
            assert self.test_generation["min_test_methods"] > 0, "min_test_methods must be greater than 0"
            assert self.test_generation["min_code_length"] > 0, "min_code_length must be greater than 0"
            assert self.test_generation["suites_per_class"] > 0, "suites_per_class must be greater than 0"

            # Validate prompt settings
            assert self.prompt["language"] in ["en", "zh"], "language must be either 'en' or 'zh'"

            # Validate path settings
            assert self.paths["prompt_dir"].exists(), "Prompt directory does not exist"

            # Validate test focus strategies
            assert len(self.focus_approaches) > 0, "focus_approaches cannot be empty"

            logger.info("Configuration validation passed")
            return True
        except AssertionError as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during configuration validation: {e}")
            return False

    def get_api_config(self) -> Dict[str, Any]:
        """Return the API configuration."""
        return self.api.copy()

    def get_test_config(self) -> Dict[str, Any]:
        """Return the test generation configuration."""
        return self.test_generation.copy()

    def get_prompt_config(self) -> Dict[str, Any]:
        """Return the prompt configuration."""
        return self.prompt.copy()

    def get_paths(self) -> Dict[str, Path]:
        """Return the configured paths."""
        return self.paths.copy()

    def get_focus_approaches(self) -> list:
        """Return the list of test focus strategies."""
        return self.focus_approaches.copy()

    def get_statistics_config(self) -> Dict[str, Any]:
        """Return the statistics configuration."""
        return self.statistics.copy()


# Create the global configuration instance
config = Config()

# Try loading settings from the local config file
config_file = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(config_file):
    config.load_from_file(config_file)

# Validate the resulting configuration
if not config.validate():
    logger.warning("Falling back to the default configuration")
