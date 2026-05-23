"""
Maven project analysis module.

Responsible for analyzing Maven project structure, Java version,
and dependency information.
"""

import os
import re
import logging
from typing import Dict, Any, Tuple, List, Optional

# Configure logging
logger = logging.getLogger(__name__)


class MavenProjectAnalyzer:
    """Analyzer for Maven projects."""

    def analyze_project_structure(self, project_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Analyze the Maven project structure, including Java version
        and dependency information.

        Args:
            project_path: Path to the project root directory.

        Returns:
            A tuple of (java_version, maven_dependencies).
        """
        return self._ensure_maven_test_structure(project_path)

    def _ensure_maven_test_structure(self, project_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Ensure the Maven test structure exists and detect the Java
        version and dependencies.

        Args:
            project_path: Path to the project root directory.

        Returns:
            A tuple of (java_version, maven_dependencies).
        """
        # Create the test directory
        test_dir = os.path.join(project_path, "src", "test", "java")
        os.makedirs(test_dir, exist_ok=True)

        # Detect the Java version; default to Java 8
        java_version = "8"

        # Inspect JUnit dependencies from pom.xml
        pom_path = os.path.join(project_path, "pom.xml")
        maven_dependencies = {
            "junit": True,
            "junit_version": "5",
            "mockito": False,
            "dependencies": [],
        }

        if os.path.exists(pom_path):
            try:
                with open(pom_path, "r", encoding="utf-8") as f:
                    pom_content = f.read()

                # Detect the JUnit version
                if "<junit.version>5" in pom_content or "junit-jupiter" in pom_content:
                    maven_dependencies["junit_version"] = "5"
                elif "junit" in pom_content:
                    maven_dependencies["junit_version"] = "4"

                # Detect Mockito
                if "mockito" in pom_content:
                    maven_dependencies["mockito"] = True

                # Extract the Java version
                java_version_match = re.search(r"<java.version>(\d+)</java.version>", pom_content)
                if java_version_match:
                    java_version = java_version_match.group(1)
                elif "<source>1.8</source>" in pom_content or "<target>1.8</target>" in pom_content:
                    java_version = "8"

                # Extract dependency entries
                dependencies = []
                for dep_match in re.finditer(
                    r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>(?:\s*<version>([^<]+)</version>)?",
                    pom_content,
                ):
                    group_id = dep_match.group(1)
                    artifact_id = dep_match.group(2)
                    version = dep_match.group(3) if dep_match.group(3) else "latest"
                    dependencies.append(
                        {
                            "groupId": group_id,
                            "artifactId": artifact_id,
                            "version": version,
                        }
                    )

                maven_dependencies["dependencies"] = dependencies

            except Exception as e:
                logger.warning(f"Error reading pom.xml: {e}")

        return java_version, maven_dependencies

    def get_test_directory(self, project_path: str) -> str:
        """
        Return the path to the test directory.

        Args:
            project_path: Path to the project root directory.

        Returns:
            The full test directory path.
        """
        return os.path.join(project_path, "src", "test", "java")
