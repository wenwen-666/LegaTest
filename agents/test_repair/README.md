# Test Repair

## Overview

Test Repair is an automated repair system specifically designed to fix Java test code compile errors and runtime errors. It ensures that only compilable test code is output through a three‑phase repair strategy (Rules Repair → LLM Repair → Deletion Strategy).

### Key Features

- Three‑phase repair flow: Rules repair → LLM repair (2 attempts) → Delete failing tests
- Automatic quality assurance: test files that fail to repair are automatically deleted, no uncompilable code is kept
- Intelligent error categorization: automatically recognizes 7 major error categories and applies targeted fixes
- Deep LLM integration: supports two LLM repair attempts with smart token optimization

## 🏗️ Module Architecture

### Core Modules

| File | Purpose | ~Lines |
|------|---------|--------|
| `repair_client.py` | Repair client providing a unified repair interface | ~268 |
| `config.py` | Configuration management (API keys, etc.) | ~29 |
| `maven_parser.py` | Maven output parsing and error categorization | actual |
| `llm_interface.py` | LLM API interaction interface | actual |

### Repair Modules

| Path | Purpose | ~Lines |
|------|---------|--------|
| `rule_fixer/rule_repair.py` | Core rules‑based repair logic and flow control | ~1,287 |
| `rule_fixer/classify_and_fix.py` | Error categorization and rule fix functions | ~819 |
| `rule_fixer/error_categories.py` | Error category definitions | ~93 |
| `llm_fixer/llm_repair.py` | LLM repair implementation with token optimization | ~1,267 |

**Total code size**: ~5,645 lines

## 🔄 Three‑Phase Repair Flow

### Phase 1: Rules Repair

Use predefined rules to fix common compile errors.

**Supported error categories**:
1. Import errors (`IMPORT_ERRORS`): missing, redundant, or incorrect import statements
2. Duplicate definition errors (`DUPLICATE_DEFINITION_ERRORS`): duplicated modifiers/annotations/imports
3. Access modifier errors (`ACCESS_MODIFIER_ERRORS`): duplicate public/private, etc.
4. API compatibility errors (`API_COMPATIBILITY_ERRORS`): APIs incompatible with the Java version
5. Private access errors (`PRIVATE_ACCESS_ERRORS`): accessing private methods/fields
6. Constructor errors (`CONSTRUCTOR_ERRORS`): constructor invocation issues
7. Resource management errors (`RESOURCE_MANAGEMENT_ERRORS`): try‑with‑resources syntax issues

**Flow**:
```
Maven error output → Error categorization → Apply rule fixes → Maven validation → Success/Fail
```

**Success**: directly output the repaired test file

**Fail**: proceed to Phase 2 (LLM repair)

### Phase 2: LLM Repair (two attempts)

Use LLM smart repair when rules repair fails or the error cannot be categorized.

**First LLM repair**:
- Generate repair prompts based on Maven error information
- Include the CUT (class under test) source code as context (smart extraction, remove comments to save tokens)
- Use different strategies for compile errors vs. test failures
- Validate the repair result

**Second LLM repair**:
- If the first attempt fails, try again with updated error information
- Improve based on the result of the first attempt
- Last chance to repair

**Token optimization strategies**:
- Remove license headers (automatically restored after repair)
- Remove source code comments

**Success**: output the repaired test file

**Fail**: proceed to Phase 3 (deletion strategy)

### Phase 3: Deletion Strategy

If both LLM repair attempts fail, try deleting problematic test methods.

**Generation mode** (test generation):
1. Attempt to delete identified failing test methods
2. Validate whether remaining tests compile
3. If it still fails, delete the entire test file

**Evolution mode** (iterative evolution):
1. Use more aggressive strategies to locate and delete failing methods
2. Delete one by one and validate
3. If it cannot be repaired, delete the entire test file

**Final result**:
- ✅ Success: keep the subset of usable tests
- ❌ Failure: delete the entire test file (never keep uncompilable code)

## 💻 Usage

### 1. Via TestRepairClient (Recommended)

```python
from agents.test_repair import TestRepairClient

# Initialize the repair client
repair_client = TestRepairClient()

# Prepare class info
cls_info = {
    'project_path': '/path/to/project',
    'package': ' ',  # specify according to actual situation
    'className': 'TargetClass',  # or full test class name
    'suite_index': 1,
    # Optional: pass existing Maven output to avoid recompilation
    'maven_output': '...',
    'maven_success': False,
    'maven_parsed_output': parsed_output_obj,
}

# Execute repair
final_path, repair_stats = repair_client.repair_test_file(
    'src/test/java/package/path/TargetClassTest.java',
    cls_info
)

if final_path:
    print(f"Repair succeeded: {final_path}")
    print(f"Stats: {repair_stats.to_dict()}")
else:
    print("Repair failed, test file has been deleted")
```

### 2. Repair based on error output (iterative_evolution scenario)

```python
from agents.test_repair import TestRepairClient

repair_client = TestRepairClient()

# Use Maven error output for repair
success = repair_client.repair_with_error_output(
    test_file_path='src/test/java/.../MyTest.java',
    error_output=maven_error_output,
    project_path='/path/to/project',
    class_name='MyTest',
    package_name='package.name'  # optional
)
```

### 3. Use rule repair function directly

```python
from agents.test_repair.rule_fixer.rule_repair import process_test

# Class info
cls_info = {
    'project_path': '/path/to/project',
    'package': 'package.name',
    'className': 'Calculator',
    'suite_index': 1,
}

# Execute repair
result = process_test('src/test/java/.../CalculatorTest.java', cls_info)
```

## 📊 Repair Statistics

```python
@dataclass
class RepairStats:
    """Repair process statistics"""
    repair_attempts: int = 0        # number of repair attempts
    rule_fixes_applied: int = 0     # number of rule fixes applied
    llm_fixes_applied: int = 0      # number of LLM fixes applied
    llm_calls: int = 0              # number of LLM calls
    total_repair_time: float = 0.0  # total repair time
    llm_repair_time: float = 0.0    # time spent on LLM repair
    rule_repair_time: float = 0.0   # time spent on rule repair
    success: bool = False           # whether repair succeeded
```

Example output:
```python
{
    'repair_attempts': 2,
    'rule_fixes_applied': 0,
    'llm_fixes_applied': 1,
    'llm_calls': 2,
    'total_repair_time': 15.3,
    'llm_repair_time': 14.8,
    'rule_repair_time': 0.5,
    'success': True
}
```

## ⚙️ Configuration

### Environment Variables

```bash
# API configuration (required)
export DEEPSEEK_API_KEY=""
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export API_MODEL="deepseek-chat"
export API_REQUEST_TIMEOUT="180"
```

### Config Class

`config.py` provides simple configuration management:

```python
from agents.test_repair.config import config

# Get API config
api_config = config.get_api_config()
# {'key': '...', 'base_url': '...', 'model': '...', 'timeout': 180}
```

## 🔍 Error Categorization System

### Error Category Definitions

Located in `rule_fixer/error_categories.py`:

```python
ERROR_CATEGORIES = {
    "IMPORT_ERRORS": [...],
    "DUPLICATE_DEFINITION_ERRORS": [...],
    "ACCESS_MODIFIER_ERRORS": [...],
    "API_COMPATIBILITY_ERRORS": [...],
    "PRIVATE_ACCESS_ERRORS": [...],
    "CONSTRUCTOR_ERRORS": [...],
    "RESOURCE_MANAGEMENT_ERRORS": [...]
}
```

### Intelligent Error Categorization

Function `classify_error()` in `classify_and_fix.py`:
- Analyze Maven error information
- Match against predefined error patterns
- Return error category
- Return None if unmatched (trigger LLM repair)

## 🎯 Repair Examples

### Example 1: Import Error Repair

**Error**:
```
[ERROR] cannot find symbol: class MissingDependency
```

**Rule repair**:
- Recognized as `IMPORT_ERRORS`
- Add the required import or dependency for the missing class
- Maven validation succeeded ✅

### Example 2: Duplicate Modifier Error

**Error**:
```
[ERROR] duplicate modifier 'public'
```

**Rule repair**:
- Recognized as `ACCESS_MODIFIER_ERRORS`
- Remove the duplicated `public` modifier
- Maven validation succeeded ✅

### Example 3: Private Method Access Error

**Error**:
```
[ERROR] privateMethod() has private access in TargetClass
```

**Rule repair attempt**:
- Recognized as `PRIVATE_ACCESS_ERRORS`
- Rule repair: remove the private method call
- Maven validation failed ❌

**LLM repair**:
- Generate a repair prompt including CUT API
- LLM identifies correct public API to use
- Replace with the appropriate public method call
- Maven validation succeeded ✅

### Example 4: Complex Error (Deletion Strategy)

**First LLM repair failed + Second LLM repair failed**:

**Deletion strategy**:
- Identify failing test method: `testComplexScenario`
- Delete the test method
- Validate remaining tests
- If successful, keep the partial test ✅
- If still failing, delete the entire file ❌

## 🚀 Integration with test_generator

The `test_repair` module is designed to integrate tightly with `test_generator`:

```python
# In test_generator/file_writer.py:
from agents.test_repair import TestRepairClient

# Auto-repair after generation
repair_client = TestRepairClient()
final_path, repair_stats = repair_client.repair_test_file(temp_test_path, cls_info)
```

**Shared Maven parser**:
- `maven_parser.py` is shared by both `test_generator` and `test_repair`
- Avoids duplication and keeps error parsing logic consistent

## 📝 Working Modes

### Generation Mode (test_generator)

- Test file name: `ClassNameTestV1Temp.java` → `ClassNameTestV1.java`
- On success: rename temp file to final file
- On failure: delete the temp file

### Evolution Mode (iterative_evolution)

- Test file name: `ClassNameTestV1.java` (modified directly)
- On success: keep the repaired file
- On failure: delete the original file

**Mode detection**: automatically inferred by class name (contains "Crossover"/"Mutation" or "TestV" means Evolution mode)

## ⚠️ Notes

### Important Tips

1. **No retention on failure**: This is by design to ensure code quality
2. **LLM dependency**: Complex errors may require LLM API; ensure proper configuration
3. **Token cost**: LLM repair incurs API cost; token usage is optimized by the system
4. **Maven required**: All validation is done via Maven; ensure Maven is available
5. **Detailed logs**: Every repair step logs details to help with debugging

### Performance Considerations

- **Rules repair**: milliseconds, very fast
- **LLM repair**: 10–30s per call (depends on API latency)
- **Maven validation**: 5–15s per compile (depends on project size)
- **Estimated total time**: simple errors < 1 min; complex errors 1–3 min

### Success Rates (based on practical use)

- Rules repair success rate: ~30–40% (for common/simple errors)
- First LLM repair success rate: ~50–60%
- Second LLM repair success rate: ~20–30%
- Deletion strategy success rate: ~10–15% (retain partial tests)
- Overall success rate: ~70–80% (at least partial usable tests retained)

## 🔗 Dependencies

### Internal Dependencies

- `test_generator`: shares `maven_parser` module
- `iterative_evolution`: uses `repair_with_error_output` interface

### External Dependencies

- **Python 3.8+**: dataclass support required
- **Java 8+**: for compile validation
- **Maven 3.6+**: build tool
- **LLM API**: DeepSeek or other compatible services

### Python Package Dependencies

```bash
# Standard library (usually included)
# - logging
# - re
# - dataclasses
# - typing
```

## 📚 Directory Layout

```
agents/test_repair/
├── __init__.py                      # module export (TestRepairClient)
├── repair_client.py                 # repair client main class
├── config.py                        # configuration management
├── maven_parser.py                  # Maven output parser
├── llm_interface.py                 # LLM API interface
├── rule_fixer/                      # rules repair module
│   ├── __init__.py
│   ├── rule_repair.py              # core rule repair logic
│   ├── classify_and_fix.py         # error categorization & fixes
│   └── error_categories.py         # error category definitions
└── llm_fixer/                       # LLM repair module
    ├── __init__.py
    └── llm_repair.py               # LLM repair implementation
```

## 🤝 Contributing

To add new rule fixes:

1. Add error patterns in `error_categories.py`
2. Implement fix functions in `classify_and_fix.py`
3. Register in `FIXERS` dict of `rule_repair.py`
4. Test and validate

---
