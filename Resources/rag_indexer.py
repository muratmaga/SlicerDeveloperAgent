"""
RAG Indexer for Slicer Documentation

Builds a searchable index of Slicer code examples from official documentation.
Run this script to rebuild the index when documentation updates.

Usage:
    python rag_indexer.py
"""

import json
import os
import time
from urllib.request import urlopen, Request
from html.parser import HTMLParser
import re

# Documentation sources to index
DOC_SOURCES = {
    'script_repository': 'https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html',
    'segmentations': 'https://slicer.readthedocs.io/en/latest/developer_guide/modules/segmentations.html',
    'api_reference': 'https://slicer.readthedocs.io/en/latest/developer_guide/api.html',
}

INDEX_FILE = os.path.join(os.path.dirname(__file__), 'slicer_rag_index.json')


class CodeExtractor(HTMLParser):
    """Extract code blocks and surrounding context from HTML"""
    
    def __init__(self):
        super().__init__()
        self.in_code = False
        self.in_heading = False
        self.in_paragraph = False
        self.current_heading = ""
        self.current_paragraph = ""
        self.current_code = []
        self.code_blocks = []
        
    def handle_starttag(self, tag, attrs):
        if tag in ('pre', 'code'):
            self.in_code = True
            self.current_code = []
        elif tag in ('h1', 'h2', 'h3', 'h4'):
            self.in_heading = True
            self.current_heading = ""
        elif tag == 'p':
            self.in_paragraph = True
            self.current_paragraph = ""
    
    def handle_endtag(self, tag):
        if tag in ('pre', 'code'):
            self.in_code = False
            if self.current_code:
                code = ''.join(self.current_code).strip()
                # Only include if it looks like Python and mentions slicer
                if code and (('slicer' in code.lower()) or ('import' in code) or len(code) > 30):
                    self.code_blocks.append({
                        'code': code,
                        'heading': self.current_heading,
                        'description': self.current_paragraph[:200],  # Last paragraph before code
                    })
                self.current_code = []
        elif tag in ('h1', 'h2', 'h3', 'h4'):
            self.in_heading = False
        elif tag == 'p':
            self.in_paragraph = False
    
    def handle_data(self, data):
        if self.in_code:
            self.current_code.append(data)
        elif self.in_heading:
            self.current_heading += data
        elif self.in_paragraph:
            self.current_paragraph = data  # Only keep most recent paragraph


def fetch_documentation(url):
    """Fetch HTML content from URL"""
    headers = {'User-Agent': 'Mozilla/5.0 Slicer DeveloperAgent RAG Indexer'}
    request = Request(url, headers=headers)
    
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"  ✗ Failed to fetch {url}: {e}")
        return None


def extract_keywords(code, heading, description):
    """Extract searchable keywords from code example"""
    keywords = []
    
    # Extract API calls (pattern: slicer.something or module.method())
    api_calls = re.findall(r'slicer\.\w+(?:\.\w+)*|\w+\.(?:Add|Get|Set|Create)\w+', code)
    keywords.extend(api_calls[:10])  # Limit to avoid clutter
    
    # Extract imports
    imports = re.findall(r'import\s+(\w+)', code)
    keywords.extend(imports)
    
    # Add words from heading
    if heading:
        keywords.extend(heading.lower().split())
    
    # Add key terms from description
    if description:
        key_terms = ['segment', 'volume', 'load', 'render', 'threshold', 'markup', 'transform']
        for term in key_terms:
            if term in description.lower():
                keywords.append(term)
    
    return list(set(keywords))  # Remove duplicates


def create_embeddings_simple(examples):
    """Create simple keyword-based search index (fallback without ML)"""
    for example in examples:
        # Combine all text for searching
        searchable_text = ' '.join([
            example.get('heading', ''),
            example.get('description', ''),
            ' '.join(example.get('keywords', [])),
            example['code'][:500]  # First 500 chars of code
        ]).lower()
        
        example['searchable'] = searchable_text
    
    return examples


def try_create_ml_embeddings(examples):
    """Try to create ML-based embeddings if sentence-transformers available"""
    try:
        from sentence_transformers import SentenceTransformer
        print("  Using sentence-transformers for embeddings...")
        
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        for example in examples:
            text = f"{example.get('heading', '')} {example.get('description', '')} {' '.join(example.get('keywords', [])[:5])}"
            example['embedding'] = model.encode(text).tolist()
        
        print("  ✓ Created ML embeddings")
        return examples, True
    except ImportError:
        print("  → sentence-transformers not available, using keyword search")
        return create_embeddings_simple(examples), False


def build_index(verbose=True):
    """Build searchable index from all documentation sources"""
    all_examples = []
    
    if verbose:
        print("=" * 70)
        print("BUILDING SLICER RAG INDEX")
        print("=" * 70)
    
    # Fetch and parse each source
    for source_name, url in DOC_SOURCES.items():
        if verbose:
            print(f"\nProcessing {source_name}...")
            print(f"  URL: {url}")
        
        html = fetch_documentation(url)
        if not html:
            continue
        
        # Extract code blocks
        parser = CodeExtractor()
        try:
            parser.feed(html)
        except Exception as e:
            print(f"  ✗ Parse error: {e}")
            continue
        
        if verbose:
            print(f"  ✓ Found {len(parser.code_blocks)} code blocks")
        
        # Add metadata
        for block in parser.code_blocks:
            block['source'] = source_name
            block['url'] = url
            block['keywords'] = extract_keywords(
                block['code'],
                block.get('heading', ''),
                block.get('description', '')
            )
            all_examples.append(block)
    
    if verbose:
        print(f"\n{'=' * 70}")
        print(f"Total examples extracted: {len(all_examples)}")
    
    # Create embeddings
    if verbose:
        print("\nCreating embeddings...")
    
    indexed_examples, has_ml = try_create_ml_embeddings(all_examples)
    
    # Save index
    index_data = {
        'version': '1.0',
        'created_at': time.time(),
        'example_count': len(indexed_examples),
        'has_ml_embeddings': has_ml,
        'examples': indexed_examples
    }
    
    with open(INDEX_FILE, 'w') as f:
        json.dump(index_data, f, indent=2)
    
    if verbose:
        print(f"\n{'=' * 70}")
        print(f"✓ Index saved to: {INDEX_FILE}")
        print(f"  Examples: {len(indexed_examples)}")
        print(f"  ML embeddings: {'Yes' if has_ml else 'No (keyword fallback)'}")
        print(f"  File size: {os.path.getsize(INDEX_FILE) / 1024:.1f} KB")
        print(f"{'=' * 70}")
    
    return indexed_examples


if __name__ == '__main__':
    build_index(verbose=True)
