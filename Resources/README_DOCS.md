# Dynamic Documentation System

## Overview

The DeveloperAgent can now fetch live Slicer API documentation from official sources to ensure generated code uses current, correct APIs.

## How It Works

1. **Documentation Sources**: Three official Slicer documentation pages:
   - Script Repository: Examples and patterns
   - API Reference: Function signatures and usage
   - Modules Guide: Module-specific APIs

2. **Caching**: Documentation is cached for 7 days to avoid repeated fetching

3. **Integration**: Cached docs are automatically loaded into prompts when available

## Refreshing Documentation

To force a documentation refresh (e.g., after a Slicer update):

```python
import sys
sys.path.append('/Users/amaga/Desktop/DeveloperAgent/Resources')
from doc_fetcher import get_documentation
docs = get_documentation(force_refresh=True)
```

Or click the "Refresh API Docs" button in the DeveloperAgent module (coming soon).

## Benefits

- **Always Current**: Uses latest API documentation from readthedocs.org
- **No Manual Maintenance**: Examples update automatically when Slicer docs update
- **Offline Capable**: Works from cache when network unavailable
- **Extensible**: Easy to add more documentation sources

## Current Status

- ✓ Documentation fetcher implemented
- ✓ Caching system implemented
- ✓ Integration with prompt system (in progress)
- ☐ UI refresh button (todo)
