# DeveloperAgent Prompt Customization Guide

## Overview

The DeveloperAgent now uses an external prompt configuration system that allows you to easily customize and iterate on the prompts without modifying the main module code.

## File Structure

- `Resources/prompts_config.py` - Main prompt configuration file (edit this to customize prompts)
  - Stored in Resources subdirectory so Slicer doesn't load it as a module
- `DeveloperAgent.py` - Main module (loads prompts from Resources/prompts_config.py)
- `PROMPT_CUSTOMIZATION.md` - This guide

## How It Works

1. **Automatic Loading**: When DeveloperAgent loads, it automatically looks for `Resources/prompts_config.py`
2. **Fallback System**: If the custom prompt file isn't found or has errors, it falls back to built-in minimal prompts
3. **Hot-Reload**: To use updated prompts, simply reload the DeveloperAgent module in Slicer
4. **Resources Subdirectory**: Config is in Resources/ so Slicer doesn't try to load it as a module

## Customizing Prompts

### Step 1: Edit Resources/prompts_config.py

The file contains several configurable sections:

```python
SYSTEM_PROMPT_BASE          # Main AI persona and instructions
SYSTEM_PROMPT_SCRIPT_REQUIREMENTS  # Script-specific requirements
USER_PROMPT_TEMPLATE        # Template for user requests
ERROR_ANALYSIS_SECTION      # Debugging framework for failures
AI_PARAMETERS              # Temperature, max_tokens, etc.
AVAILABLE_MODELS           # List of AI models to show in dropdown
DEFAULT_MODEL              # Which model to select by default
```

### Step 2: Test Your Changes

1. Save your edits to `slicer_prompts.py`
2. In Slicer, go to the Python console
3. Reload the module:
   ```python
   import importlib
   import DeveloperAgent
   importlib.reload(DeveloperAgent)
   ```
4. Test with a simple request to see if the changes improved code quality

### Step 3: Iterate

- Add more working examples to `SYSTEM_PROMPT_BASE`
- Adjust error analysis patterns in `ERROR_ANALYSIS_SECTION`
- Modify AI parameters (temperature, max_tokens)
- Version your changes for A/B testing

## Example New AI Models

As GitHub adds new models to their API (https://github.com/marketplace/models), you can easily add them to the dropdown:

In `Resources/prompts_config.py`, add to the `AVAILABLE_MODELS` list:

```python
AVAILABLE_MODELS = [
    ("GPT-4o (Recommended)", "gpt-4o"),
    ("GPT-4o Mini (Faster, Lower Quota)", "gpt-4o-mini"),
    # Add new models here:
    ("New Model Name", "new-model-id"),
    ("Another Model", "another-model-id"),
]

# Change the default if desired
DEFAULT_MODEL = "gpt-4o"  # or "new-model-id"
```

Reload the module and the new models will appear in the dropdown!

### Adding Customizations

### Adding a New API Pattern

In `Resources/prompts_config.py`, add to the "PROVEN SLICER API PATTERNS" section:

```python
## PATTERN 8: Your New Pattern
import slicer

print("Doing something new...")
# Your example code here
```

### Adjusting AI Creativity

In `Resources/prompts_config.py`, modify `AI_PARAMETERS`:

```python
AI_PARAMETERS = {
    "temperature": 0.5,  # Higher = more creative (0.0-1.0)
    "max_tokens": 10000,  # More tokens for longer scripts
}
```

### Adding Domain-Specific Guidance

For specialized use cases (e.g., cardiac imaging, neurosurgery), add a section:

```python
SYSTEM_PROMPT_BASE = """...

=== DOMAIN-SPECIFIC GUIDANCE: CARDIAC IMAGING ===
- Always use 4D data for cardiac analysis
- Common modules: HeartValveLib, CardiacAnalysis
- Typical workflow: Load 4D → Extract phases → Segment chambers
...
"""
```

## Version Control

Track your prompt iterations by updating:

```python
PROMPT_VERSION = "2.1.0"  # Increment when you make changes
PROMPT_LAST_UPDATED = "2025-12-13"
```

This helps you correlate code quality with specific prompt versions.

## Best Practices

1. **Start Small**: Make one change at a time and test
2. **Keep Examples Concrete**: Real, working code is better than abstract descriptions
3. **Document Gotchas**: Add common errors you encounter to the error patterns
4. **Share Improvements**: If you develop better prompts, share them with the community
5. **A/B Test**: Keep multiple prompt files (e.g., `slicer_prompts_v1.py`, `slicer_prompts_v2.py`) and compare results

## Troubleshooting

### Module doesn't load custom prompts

Check the Slicer Python console for messages like:
```
DeveloperAgent: Using custom prompts from /path/to/Resources/prompts_config.py
```

If you see:
```
DeveloperAgent: Using built-in prompts (error: ...)
```

Then there's an issue loading your file. Common causes:
- Syntax error in Resources/prompts_config.py
- Resources directory not present
- File permissions issue

### Code quality didn't improve

1. Check the "AI CALL DIAGNOSTIC" output to confirm your prompts are being used
2. Verify `PROMPT_VERSION` in diagnostics matches your file
3. Try increasing temperature if code is too repetitive
4. Add more specific examples for your use case

## Advanced: Multiple Prompt Profiles

Create different prompt files for different scenarios:

```
Resources/prompts_config_beginner.py  # Simplified with more explanation
Resources/prompts_config_advanced.py  # Concise, assumes expertise
Resources/prompts_config_research.py  # Focus on experimental features
```

Symlink or copy the one you want to `prompts_config.py`:
```bash
cd /path/to/DeveloperAgent/Resources
ln -sf prompts_config_advanced.py prompts_config.py
```

## Support

- Report issues: [Your issue tracker]
- Share improvements: [Your repo]
- Discuss prompts: [Your forum]

---

**Remember**: The quality of generated code is directly related to the quality of your prompts. Invest time in refining them!
