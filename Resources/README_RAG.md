# RAG (Retrieval-Augmented Generation) System for Slicer Agent

## Overview

The DeveloperAgent now uses RAG to dynamically retrieve relevant Slicer code examples based on each user request, instead of including all documentation in every prompt.

## Components

### 1. `rag_indexer.py` - Documentation Indexer
- **Run once** (or when docs update) to build the searchable index
- Fetches from official Slicer documentation
- Extracts 354 code examples from HTML
- Creates keyword-based search index (ML embeddings optional)
- Output: `slicer_rag_index.json` (611 KB)

```bash
cd Resources
python3 rag_indexer.py
```

### 2. `rag_retriever.py` - Runtime Retriever
- Loads pre-built index at runtime
- Searches for relevant examples based on user query
- Returns top-K most relevant examples
- Formats them for AI prompt (max 3000 chars)

### 3. Integration in `DeveloperAgent.py`
- `_get_prompts()` now accepts `user_request` parameter
- Calls RAG retriever with user's specific request
- Only includes relevant examples (5 max) in prompt
- Saves tokens, stays under 8000 token limit

## How It Works

```
User: "segment a volume using threshold"
         ↓
RAG Retriever searches 354 examples
         ↓
Returns top 5 matches:
  - Import labelmap into segmentation
  - Process segment using VTK filter
  - Mask volume using segmentation
  - Create segmentation from labelmap
  - Show segmentation in 3D
         ↓
Formats to ~2000 chars for AI prompt
         ↓
AI generates code using relevant examples
```

##Benefits

✅ **Token efficient**: Only ~2000 chars of docs per request (vs 50K+ previously)
✅ **Targeted**: User asks about segmentation → gets segmentation examples
✅ **Scalable**: Can add more docs without bloating prompts
✅ **No API limits**: Stays well under 8000 token limit
✅ **No retraining**: Uses existing AI models

## Limitations

⚠️ **Incomplete documentation**: Official Slicer docs don't contain complete workflow examples for:
- Segment Editor full workflows (missing `AddEmptySegment`, `SetSelectedSegmentID`)
- Some advanced API patterns

**Workaround**: The ERROR_ANALYSIS_SECTION in prompts still contains hardcoded error→fix patterns that trigger when code fails.

## Dependencies

### Required (built-in):
- `urllib` - for fetching documentation
- `json` - for index storage
- `re` - for text processing

### Optional (better search):
```bash
pip install sentence-transformers
```

If installed, uses ML embeddings for semantic search. Otherwise, falls back to keyword matching (still works well).

## Documentation Sources

Currently indexed from:
1. **Script Repository**: https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html
   - 330 code examples
2. **Segmentations Module**: https://slicer.readthedocs.io/en/latest/developer_guide/modules/segmentations.html
   - 14 code examples
3. **API Reference**: https://slicer.readthedocs.io/en/latest/developer_guide/api.html
   - 10 code examples

**Total**: 354 examples indexed

## Maintenance

### When to rebuild index:
- Slicer releases new version with API changes
- Documentation is updated
- New documentation sources added

Simply run:
```bash
cd Resources
python3 rag_indexer.py
```

The new index will be automatically used on next agent invocation.

## Testing

Test the retriever:
```bash
cd Resources
python3 rag_retriever.py
```

Sample output:
```
Query: 'segment a volume using threshold'
Found 3 relevant examples:
  1. [script_repository] Import labelmap node into segmentation
  2. [script_repository] Process segment using VTK filter
  3. [script_repository] Mask volume using segmentation
```

## Future Improvements

1. **Add more documentation sources**:
   - https://apidocs.slicer.org/main/namespaces.html (C++ API docs)
   - Community scripts from Slicer forums
   - Module-specific documentation pages

2. **Add curated examples**:
   - Create `curated_examples.json` with hand-written complete workflows
   - Prioritize these in retrieval

3. **ML embeddings**:
   - Install `sentence-transformers` for semantic search
   - Better matching of intent vs keywords

4. **Error-driven learning**:
   - When agent fails, extract the fixed code
   - Add to index as verified example
   - Agent learns from mistakes over time

## Version

RAG System Version: 1.0
Created: December 13, 2025
Index Size: 354 examples, 611 KB
