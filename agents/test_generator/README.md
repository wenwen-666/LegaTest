# Test Generator

## Overview

Test Generator is an LLM-based Java unit test generation system that can automatically generate high-quality JUnit test suites for Java classes. It integrates intelligent code analysis, automatic error repair, and detailed statistics.

## 🚀 Key Features

### Main Features
- Intelligent code analysis: in-depth parsing of Java class structure, method signatures, dependencies, and API usage patterns
- Diverse test strategies: 10 different test-focus strategies; each test suite targets different dimensions
- Automatic error repair: integrates the `test_repair` module to automatically fix compile errors in generated tests
- Parallel generation support: multi-threaded generation to significantly speed up large-scale projects
- Detailed statistics: real-time collection and analysis of generation metrics, including LLM call statistics and cost estimates
- Flexible configuration system: supports environment variables and JSON configuration files

## Workflow

Full process of test generation:

1. Class info extraction: extract Java class structure from JSON (class name, package, methods, fields, etc.)
2. Code analysis: analyze API usage, method complexity, and dependencies; compute distribution suggestions
3. Prompt construction: build detailed prompts according to strategies and class information
4. LLM code generation: call LLM API to generate test code (supports retries and fallback models)
5. Temporary file validation: create a temporary test file and validate with Maven
6. Automatic error repair: when compilation fails, call the `test_repair` module for three-phase repair (rules → LLM → deletion)
7. Final file output: rename to final test file on success; delete the test file on failure

## 🏗️ Module Architecture

### Core Modules

| Module File | Main Function | Lines |
|-------------|---------------|-------|
| `main.py` | CLI entry, argument parsing, task scheduling | ~460 |
| `file_writer.py` | Core logic for generating and writing test files | ~670 |
| `llm_interface.py` | LLM API interaction, supports retry and fallback | ~350 |
| `config.py` | Configuration management, supports env vars and JSON | ~190 |

### Analysis Modules

| Module File | Main Function | Lines |
|-------------|---------------|-------|
| `json_extractor.py` | Extract class info from JSON and format | ~1,580 |
| `api_extractor.py` | Extract and analyze API usage patterns | ~860 |
| `method_analyzer.py` | Analyze method complexity and compute distribution | ~450 |
| `type_analyzer.py` | Type analysis and inference | ~330 |

### Helper Modules

| Module File | Main Function | Lines |
|-------------|---------------|-------|
| `prompt_builder.py` | Build LLM prompts | ~340 |
| `statistics.py` | Collect and analyze statistics | ~790 |
| `token_counter.py` | Token counting and cost estimation | ~350 |
| `maven_analyzer.py` | Maven project analysis | ~105 |

### External Dependencies
- `test_repair` module: repairs compile errors in generated tests (three-phase strategy)
- Maven: compile validation for generated tests

## Automatic Error Repair Mechanism

The test generator integrates deeply with `test_repair` to achieve automatic error repair:

### Repair Flow

1. Temporary file validation: after generation, create a temporary test file (e.g., `ClassNameTestV1Temp.java`)
2. Maven compile check: compile the temporary file with Maven and detect compile errors
3. Call `test_repair`: if compilation fails, pass error info to the `test_repair` module
4. Three-phase repair:
   - Rules repair: use predefined rules to fix common errors (imports, syntax, etc.)
   - LLM repair: if rules fail, attempt LLM repair (up to 2 times)
   - Deletion strategy: if all attempts fail, delete the test file
5. Rename output: on success, rename to final file name (e.g., `ClassNameTestV1.java`)

### Repair Guarantees

- ✅ Only compile-successful test files are kept
- ✅ Tests that fail to repair will not be retained
- ✅ All repair statistics are recorded in the global stats system
- ✅ Existing final test files will not be overwritten (generation skips existing files)

## Directory Structure

```
agents/test_generator/
├── __init__.py               # module initialization and exports
├── __main__.py               # run as a module entry
├── main.py                   # main logic (CLI, scheduling)
├── config.py                 # configuration (env + JSON)
├── file_writer.py            # core logic to generate and write tests
├── llm_interface.py          # LLM API interface
├── prompt_builder.py         # prompt builder
├── json_extractor.py         # extract and format JSON class info
├── api_extractor.py          # API usage extraction and analysis
├── method_analyzer.py        # method complexity and distribution
├── type_analyzer.py          # type analysis and inference
├── maven_analyzer.py         # Maven project analysis
├── statistics.py             # statistics collection and reporting
├── token_counter.py          # token counting and cost estimation
└── prompts/                  # prompt templates
    ├── enhanced_system_prompt.txt    # LLM system prompt
    ├── main_template.txt             # main prompt template
    ├── common_rules.txt              # common rules
    ├── footer.txt                    # prompt footer
    └── example.txt                   # example test code
```

**Important Notes**:
- Maven output parsing is provided by `agents/test_repair/maven_parser.py` (to avoid duplication)
- Error repair is fully delegated to the independent `agents/test_repair/` module
- `test_generator` focuses on test generation; repair is handled by the dedicated module

## Programmatic API

### Primary API

```python
from agents.test_generator import generate_for_class

# Generate tests for a single class (recommended)
success = generate_for_class(
    cls_info={
        'className': 'Calculator',
        'package': 'package.name',
        'methods': [...],
        'fields': [...]
    },
    project_path='/path/to/project',
    suite_index=1  # Generate the 1st test suite using strategy #1
)
```

> Note: `cls_info` is recommended to include at least:
> - `className`: target class name (required)
> - `package`: package name (required)
> - `testDir`: test source dir (optional, default `src/test/java`)
> Other fields like `methods`, `fields`, and `method_details` are optional.

### Exports

```python
from agents.test_generator import (
    TestFileWriter,        # test file writer class
    file_writer,           # global writer instance
    generate_for_class,    # convenience function to generate tests
    PromptBuilder,         # prompt builder
    MavenProjectAnalyzer,  # Maven project analyzer
    MavenOutputParser,     # Maven output parser (from test_repair)
    run_maven_test,        # run Maven test
    run_and_parse_test     # run and parse Maven test
)
```

## 🚀 CLI Usage

### Basic Commands

```bash
# Generate tests for all detected projects
python -m agents.test_generator

# Generate tests for a specific class
python -m agents.test_generator --class Calculator

# Generate tests for a specific project
python -m agents.test_generator --project <project_name>

# Customize generated suite count per class (default 10)
python -m agents.test_generator --count 5
```

### Parallel Generation (Use with Caution)

```bash
# Enable parallel generation with 4 workers
python -m agents.test_generator --parallel --workers 4

# Recommended config for large projects
python -m agents.test_generator --project myproject \
  --parallel --workers 8 \
  --count 10
```

Note: Parallel generation significantly increases CPU/memory/disk IO usage. Choose `--workers` according to machine resources (do not exceed CPU cores).

### Analysis Mode

```bash
# Analyze class complexity and distribution only (no generation)
python -m agents.test_generator --analyze-only

# Analyze a specific class
python -m agents.test_generator --class Calculator --analyze-only

# Analyze a specific project
python -m agents.test_generator --project repo --analyze-only
```

### Debug and Validation

```bash
# Test API connectivity
python -m agents.test_generator --test-api

# Enable verbose logging
python -m agents.test_generator --verbose
```

### Full Parameter List

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--class` | Generate tests for the specified class only | None (process all) |
| `--count` | Number of test suites per class | 10 |
| `--project` | Process the specified project only | None (process all) |
| `--parallel` | Enable parallel test generation | False |
| `--workers` | Number of parallel worker threads | 4 |
| `--verify-method-count` | Verify the number of test methods | False |
| `--analyze-only` | Analyze only; do not generate tests | False |
| `--test-api` | Test API connectivity | False |
| `--verbose` | Show verbose output | False |

## ⚙️ Configuration System

### 1. Environment Variables (Recommended)

```bash
# ===== API config (required) =====
export DEEPSEEK_API_KEY=""
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export API_MODEL="deepseek-chat"
export API_REQUEST_TIMEOUT="120"

# ===== Test generation config (optional) =====
export MIN_TEST_METHODS_COUNT="3"           # minimum test methods
export MIN_CODE_LENGTH="100"                # minimum code length
export DEFAULT_TEST_SUITES_PER_CLASS="10"   # suites per class

# ===== Statistics output config (optional) =====
export STATS_OUTPUT_TO_FILE="true"          # write stats to file
export DETAILED_STATS_FILE="test_generation_detailed_stats.txt"
export SHOW_DETAILED_CONSOLE="false"        # show detailed stats in console

# ===== Prompt config (optional) =====
export PROMPT_LANGUAGE="en"                 # prompt language: en or zh
export USE_BILINGUAL_TAGS="false"           # use bilingual tags or not
```

### 2. JSON Configuration File

Create `config.json` under `agents/test_generator/`:

```json
{
  "api": {
    "key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "timeout": 120
  },
  "test_generation": {
    "min_test_methods": 3,
    "min_code_length": 100,
    "suites_per_class": 10
  },
  "prompt": {
    "language": "en",
    "use_bilingual": false
  },
  "statistics": {
    "output_to_file": true,
    "detailed_stats_file": "test_generation_detailed_stats.txt",
    "show_detailed_console": false
  }
}
```

**Configuration loading priority**: JSON file > Environment variables > Defaults

### 3. Test Strategy Configuration

The system includes 10 built-in test-focus strategies (cycled by `suite_index`):

| Strategy # | Focus | Use Case |
|------------|-------|---------|
| 1 | Functional validation | Basic functionality and normal inputs |
| 2 | Boundary testing | Extremes and edge cases |
| 3 | Exception handling | Error scenarios and exception handling |
| 4 | Dependency isolation | Use mocks to validate behavior in isolation |
| 5 | State transitions | Data transformation and state changes |
| 6 | Innovative scenarios | Meaningful edge/creative cases |
| 7 | Balanced suite | Combine best practices and innovation |
| 8 | Broad coverage | Maximize code coverage |
| 9 | Intelligent free testing | AI-guided best test generation |
| 10 | Structured comprehensive | Detailed prompt for complete tests |

These strategies are defined in `config.py` under `focus_approaches` and can be overridden via JSON config.

## 📊 Output Structure

Project structure after generation:

```
project_root/
├── src/
│   ├── main/java/                      # source code
│   │   └── com/example/
│   │       └── Calculator.java
│   └── test/java/                      # generated tests
│       └── com/example/
│           ├── CalculatorTest.java     # 1st test suite (strategy #1)
│           ├── CalculatorTestV2.java   # 2nd suite (strategy #2)
│           ├── CalculatorTestV3.java   # 3rd suite (strategy #3)
│           └── ...                     # other suites
│
├── 
```

Note: Paths are relative to the current working directory and may vary depending on where you run the tool.


## 🔧 Requirements

### Runtime Environment

| Component | Minimum | Recommended | Description |
|-----------|---------|-------------|-------------|
| Python | 3.8+ | 3.10+ | async support |
| Java | 8+ | 11+ | used for Maven compile validation |
| Maven | 3.6+ | 3.8+ | build tool and dependency management |

### Python Dependencies

```bash
# Core dependencies
pip install aiohttp>=3.8.0      # async HTTP client (LLM API)
pip install tqdm>=4.64.0        # progress bars

# Standard library (usually included)
# - asyncio (async programming)
# - pathlib (paths)
# - logging (logs)
# - json (JSON handling)
# - re (regex)
```

### Project Dependencies

```bash
# Install all dependencies
cd /path/to/LegaTest
pip install -r requirements.txt
```

### System Requirements
- Memory: at least 4GB RAM (8GB+ recommended; more for parallel mode)
- Disk: at least 500MB free (for generated tests and statistics)
- Network: stable internet (LLM API calls)
- API Key: valid DeepSeek API key (or compatible LLM service)

## 🎯 Use Cases

### Recommended
- Need to quickly generate test suites for existing Java classes
- Need diversified tests (multiple strategies)
- Maven-based projects
- Batch generation (supports parallel)
- Require detailed generation statistics and cost analysis

### Not Recommended
- Non-Maven projects (Maven is required for compile validation)
- No internet access (LLM API required)
- Strict environments without human review (generated tests should be reviewed)

### Typical Workflow

```bash
# 1. Configure API key
export DEEPSEEK_API_KEY=""

# 2. Test API connectivity
python -m agents.test_generator --test-api

# 3. Analyze project (optional)
python -m agents.test_generator --project myproject --analyze-only

# 4. Generate tests (parallel recommended for large projects)
python -m agents.test_generator --project myproject --parallel --workers 4

# 5. View statistics
cat test_generation_detailed_stats.txt
cat test_generation_stats.json
```

## 📝 Data Sources

### JSON Configuration Structure

```json
[
  {
    "className": "Calculator",
    "package": "package.name",
    "testDir": "src/test/java",
    "methods": [
      "add(int, int)",
      "subtract(int, int)",
      "multiply(int, int)",
      "divide(int, int)"
    ],
    "fields": [
      "private static final double EPSILON"
    ],
    "imports": [
      "java.util.List",
      "java.math.BigDecimal"
    ],
    "sourceCode": "public class Calculator { ... }"
  }
]
```

### Project Discovery

The function `find_all_repos()` in `json_extractor.py` automatically discovers projects:

1. Find directories containing `pom.xml`
2. Search for `*_classes.json` files under the project directory
3. Return tuples `(project_name, project_path, json_path)`

## ⚠️ Notes

### Important Tips

1. **API Cost**: Each LLM call incurs cost; monitor cost estimates in `test_generation_stats.json`.
2. **Compile Time**: Maven validation takes time; parallel mode is recommended for large projects.
3. **Test Quality**: Generated tests should be reviewed and adjusted by humans.
4. **File Overwrite**: Existing test files are not overwritten by default (delete them before regeneration if needed).
5. **Temporary Files**: The system creates temporary files (`*Temp.java`) and cleans them up under normal conditions.

### FAQ

**Q: What if the generated tests fail to compile?**
A: The system will automatically call the `test_repair` module. If repair fails, the test file will be deleted and not retained.

**Q: How to customize test strategies?**
A: Modify the `focus_approaches` list in `config.py`, or override via JSON configuration.

**Q: How to control concurrency in parallel mode?**
A: Use `--workers N` to set the number of worker threads; do not exceed CPU core count.

**Q: How to skip already generated tests?**
A: The system automatically detects existing test files and skips regeneration to avoid duplicates.

**Q: What if statistics files become too large?**
A: Set `STATS_OUTPUT_TO_FILE=false` to disable file output, or clean up files periodically.

## 🔗 Related Modules

- **test_repair**: test repair module with three-phase repair
- **iterative_evolution**: evolutionary module for optimizing test suites
- **dataset_parser**: dataset parser for Defects4J and others

## 📄 License

Generated test code automatically adds an Apache License 2.0 header (configurable).

## 🤝 Contributing

For questions or suggestions, please open an Issue or Pull Request.
