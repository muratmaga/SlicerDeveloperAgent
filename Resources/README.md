# DeveloperAgent Resources

This directory contains configuration files that are loaded by DeveloperAgent but are not Slicer modules themselves.

## Files

- **prompts_config.py** - AI prompt configuration
  - System prompts for code generation
  - Error analysis frameworks
  - Available AI models list
  - AI parameters (temperature, tokens, etc.)

## Why This Directory?

Slicer automatically tries to load all `.py` files in the top-level module directory as Slicer modules. By placing configuration files in this `Resources` subdirectory, they're protected from being incorrectly loaded as modules while still being accessible to DeveloperAgent.

## Editing Configuration

Simply edit `prompts_config.py` and reload the DeveloperAgent module in Slicer to apply changes.

See [../PROMPT_CUSTOMIZATION.md](../PROMPT_CUSTOMIZATION.md) for detailed customization guide.
