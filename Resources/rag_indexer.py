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
TUTORIALS_INDEX_FILE = os.path.join(os.path.dirname(__file__), 'slicermorph_tutorials_index.json')

# SlicerMorph Tutorials GitHub config
SLICERMORPH_GITHUB_API   = 'https://api.github.com/repos/SlicerMorph/Tutorials/contents'
SLICERMORPH_GITHUB_RAW   = 'https://raw.githubusercontent.com/SlicerMorph/Tutorials/main'
SLICERMORPH_TUTORIAL_URL = 'https://github.com/SlicerMorph/Tutorials/tree/main'


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


# ---------------------------------------------------------------------------
# SlicerMorph Tutorials: Markdown parser and GitHub fetcher
# ---------------------------------------------------------------------------

class MarkdownParser:
    """Parse Markdown tutorial files into searchable section entries."""

    # Slicer / SlicerMorph domain terms used for keyword extraction
    DOMAIN_TERMS = [
        'segment', 'segmentation', 'markup', 'markups', 'volume', 'model',
        'threshold', 'island', 'paint', 'scissors', 'transform', 'registration',
        'landmark', 'landmarking', 'gpa', 'pca', 'morphometrics', 'microct',
        'imagestack', 'image stack', 'sample data', 'ruler', 'fiducial',
        'surface', 'mesh', 'labelmap', 'render', 'rendering', 'slice', 'view',
        'alpaca', 'malpaca', 'animator', 'colorize', 'heatmap', 'slicermorph',
        'semi-landmark', 'semilandmark', 'pseudolandmark', 'fastmlalign',
        'quickalign', 'mrml', 'scene', 'module', 'extension', 'effect',
    ]

    def parse(self, text, tutorial_name, tutorial_url):
        """Parse markdown text into a list of index entries."""
        # Strip HTML tags and markdown images
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)

        sections = []
        current_heading = tutorial_name
        current_body_lines = []
        current_code_blocks = []
        in_code = False
        code_lang = ''
        current_code_lines = []

        for line in text.split('\n'):
            fence = re.match(r'^(`{3,})(.*)', line)
            if fence:
                if not in_code:
                    in_code = True
                    code_lang = fence.group(2).strip().lower()
                    current_code_lines = []
                else:
                    in_code = False
                    code_text = '\n'.join(current_code_lines).strip()
                    if code_text:
                        current_code_blocks.append({'lang': code_lang, 'code': code_text})
                    current_code_lines = []
                continue

            if in_code:
                current_code_lines.append(line)
                continue

            heading_match = re.match(r'^(#{1,4})\s+(.*)', line)
            if heading_match:
                body = '\n'.join(current_body_lines).strip()
                if body or current_code_blocks:
                    sections.append(self._make_entry(
                        current_heading, body, current_code_blocks,
                        tutorial_name, tutorial_url))
                current_heading = f"{tutorial_name} > {heading_match.group(2).strip()}"
                current_body_lines = []
                current_code_blocks = []
            else:
                stripped = line.strip()
                if stripped:
                    current_body_lines.append(stripped)

        # flush last section
        body = '\n'.join(current_body_lines).strip()
        if body or current_code_blocks:
            sections.append(self._make_entry(
                current_heading, body, current_code_blocks,
                tutorial_name, tutorial_url))

        return sections

    def _make_entry(self, heading, body, code_blocks, tutorial_name, tutorial_url):
        best_code = ''
        for cb in code_blocks:
            if cb['lang'] in ('python', 'py', ''):
                best_code = cb['code']
                break
        if not best_code and code_blocks:
            best_code = code_blocks[0]['code']

        keywords = self._extract_keywords(heading, body)
        content_type = 'code' if best_code else 'tutorial'

        return {
            'heading': heading,
            'description': body[:600],
            'tutorial_text': body[:1500],
            'code': best_code,
            'content_type': content_type,
            'source': 'slicermorph_tutorials',
            'tutorial_name': tutorial_name,
            'url': tutorial_url,
            'keywords': keywords,
        }

    def _extract_keywords(self, heading, body):
        combined = (heading + ' ' + body).lower()
        found = [term for term in self.DOMAIN_TERMS if term in combined]
        # also grab words from heading
        found += re.findall(r'[a-z]{3,}', heading.lower())
        return list(set(found))


def fetch_github_tutorials(verbose=True):
    """Fetch all SlicerMorph tutorial READMEs from GitHub and return parsed entries."""
    headers = {'User-Agent': 'Mozilla/5.0 Slicer DeveloperAgent RAG Indexer'}

    # Step 1: list top-level directories via GitHub API
    api_req = Request(SLICERMORPH_GITHUB_API, headers=headers)
    try:
        with urlopen(api_req, timeout=30) as resp:
            contents = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        if verbose:
            print(f"  ✗ Failed to list SlicerMorph/Tutorials: {e}")
        return []

    dirs = [entry['name'] for entry in contents if entry['type'] == 'dir']
    if verbose:
        print(f"  Found {len(dirs)} tutorial directories")

    parser = MarkdownParser()
    all_entries = []

    for dir_name in dirs:
        raw_url = f"{SLICERMORPH_GITHUB_RAW}/{dir_name}/README.md"
        tutorial_url = f"{SLICERMORPH_TUTORIAL_URL}/{dir_name}"
        req = Request(raw_url, headers=headers)
        try:
            with urlopen(req, timeout=20) as resp:
                md_text = resp.read().decode('utf-8')
        except Exception:
            continue  # no README.md in this directory

        entries = parser.parse(md_text, dir_name, tutorial_url)
        all_entries.extend(entries)
        if verbose:
            print(f"    ✓ {dir_name}: {len(entries)} sections")
        time.sleep(0.1)  # be polite to GitHub

    return all_entries


def build_tutorials_index(verbose=True):
    """Build a searchable index from SlicerMorph tutorial Markdown files."""
    if verbose:
        print('=' * 70)
        print('BUILDING SLICERMORPH TUTORIALS INDEX')
        print('=' * 70)

    entries = fetch_github_tutorials(verbose=verbose)
    if not entries:
        if verbose:
            print('  No tutorial entries extracted.')
        return []

    if verbose:
        print(f"\nTotal sections extracted: {len(entries)}")
        print("\nCreating search index...")

    # Try ML embeddings, fall back to keyword index
    indexed, has_ml = try_create_ml_embeddings(entries)

    # Ensure searchable text set for keyword fallback
    for entry in indexed:
        if 'searchable' not in entry:
            entry['searchable'] = ' '.join([
                entry.get('heading', ''),
                entry.get('description', ''),
                entry.get('tutorial_text', '')[:300],
                ' '.join(entry.get('keywords', [])),
            ]).lower()

    index_data = {
        'version': '1.0',
        'created_at': time.time(),
        'example_count': len(indexed),
        'has_ml_embeddings': has_ml,
        'source': 'slicermorph_tutorials',
        'examples': indexed,
    }

    with open(TUTORIALS_INDEX_FILE, 'w') as f:
        json.dump(index_data, f, indent=2)

    if verbose:
        print(f"\n{'=' * 70}")
        print(f"\u2713 Tutorials index saved to: {TUTORIALS_INDEX_FILE}")
        print(f"  Sections indexed: {len(indexed)}")
        print(f"  ML embeddings: {'Yes' if has_ml else 'No (keyword fallback)'}")
        print(f"  File size: {os.path.getsize(TUTORIALS_INDEX_FILE) / 1024:.1f} KB")
        print(f"{'=' * 70}")

    return indexed


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
    print()
    build_tutorials_index(verbose=True)
