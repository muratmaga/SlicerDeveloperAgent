"""
Slicer Documentation Fetcher and Cacher

Fetches live documentation from official Slicer docs and caches it locally.
This ensures the AI agent always has access to current API patterns.
"""

import os
import json
import time

# Official Slicer documentation sources
DOC_SOURCES = {
    'script_repository': 'https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html',
    'segmentations': 'https://slicer.readthedocs.io/en/latest/developer_guide/modules/segmentations.html',
    'api_reference': 'https://slicer.readthedocs.io/en/latest/developer_guide/api.html',
}

# Cache settings
CACHE_DURATION_DAYS = 7  # Refresh cache after 7 days
CACHE_FILE = os.path.join(os.path.dirname(__file__), 'slicer_docs_cache.json')


def fetch_documentation(verbose=True):
    """Fetch documentation from Slicer's official docs"""
    # Always use requests-based approach for reliability
    return fetch_documentation_external(verbose)


def fetch_documentation_external(verbose=True):
    """Fallback for running outside Slicer using urllib"""
    from urllib.request import urlopen, Request
    from urllib.error import URLError
    
    docs = {}
    if verbose:
        print("Fetching Slicer documentation from official sources...")
    
    # User agent to avoid getting blocked
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Slicer DeveloperAgent/1.0'}
    
    for source_name, url in DOC_SOURCES.items():
        if verbose:
            print(f"  Fetching {source_name}...")
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=30) as response:
                content = response.read().decode('utf-8')
            
            docs[source_name] = {
                'url': url,
                'content': content,
                'content_length': len(content),
                'fetch_time': time.time()
            }
            if verbose:
                print(f"    ✓ Fetched {len(content):,} characters")
        except Exception as e:
            if verbose:
                print(f"    ✗ Failed: {e}")
            docs[source_name] = {
                'url': url,
                'content': '',
                'content_length': 0,
                'fetch_time': time.time(),
                'error': str(e)
            }
    return docs


def save_cache(docs):
    """Save documentation cache to disk"""
    cache_data = {
        'version': '1.0',
        'cached_at': time.time(),
        'docs': docs
    }
    
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
        print(f"✓ Cache saved to {CACHE_FILE}")
        return True
    except Exception as e:
        print(f"✗ Failed to save cache: {e}")
        return False


def load_cache():
    """Load documentation cache from disk"""
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        # Check if cache is still valid
        cached_at = cache_data.get('cached_at', 0)
        age_days = (time.time() - cached_at) / (24 * 3600)
        
        if age_days > CACHE_DURATION_DAYS:
            print(f"Cache is {age_days:.1f} days old, needs refresh")
            return None
        
        print(f"✓ Loaded cache from {CACHE_FILE} (age: {age_days:.1f} days)")
        return cache_data
    except Exception as e:
        print(f"✗ Failed to load cache: {e}")
        return None


def get_documentation(force_refresh=False):
    """Get documentation from cache or fetch if needed"""
    if not force_refresh:
        cache = load_cache()
        if cache:
            return cache['docs']
    
    # Fetch fresh documentation
    docs = fetch_documentation()
    save_cache(docs)
    return docs


def format_docs_for_prompt(docs, max_chars=8000):
    """Format documentation content for inclusion in AI prompt
    
    Extracts code examples and important API patterns from documentation.
    """
    import re
    from html.parser import HTMLParser
    
    class CodeExtractor(HTMLParser):
        """Extract clean code from HTML"""
        def __init__(self):
            super().__init__()
            self.in_code = False
            self.code_blocks = []
            self.current_block = []
        
        def handle_starttag(self, tag, attrs):
            if tag in ('pre', 'code'):
                self.in_code = True
                self.current_block = []
        
        def handle_endtag(self, tag):
            if tag in ('pre', 'code'):
                self.in_code = False
                if self.current_block:
                    code = ''.join(self.current_block).strip()
                    # Include if it has slicer references or looks like Python
                    if code and (('slicer' in code.lower()) or ('import' in code) or ('def ' in code)):
                        self.code_blocks.append(code)
                    self.current_block = []
        
        def handle_data(self, data):
            if self.in_code:
                self.current_block.append(data)
    
    sections = []
    sections.append("=== SLICER API CODE EXAMPLES (FROM OFFICIAL DOCS) ===")
    sections.append("Study these patterns for correct API usage:\n")
    
    total_chars = 0
    example_count = 0
    
    # Priority keywords for finding useful examples
    priority_keywords = ['segment', 'threshold', 'AddEmptySegment', 'SetSelectedSegmentID', 
                        'downloadFromURL', 'SampleData', 'GetSegmentation']
    
    for source_name, source_data in docs.items():
        content = source_data.get('content', '')
        if not content or total_chars >= max_chars:
            continue
        
        # Extract clean code from HTML
        parser = CodeExtractor()
        try:
            parser.feed(content)
        except:
            pass  # Ignore HTML parsing errors
        
        # Sort code blocks - prioritize those with important keywords
        def priority_score(code):
            score = 0
            for keyword in priority_keywords:
                if keyword.lower() in code.lower():
                    score += 10
            return score + len(code)  # Longer is slightly better
        
        parser.code_blocks.sort(key=priority_score, reverse=True)
        
        if parser.code_blocks:
            url = source_data['url']
            sections.append(f"\n## Examples from {source_name}:")
            
            for code in parser.code_blocks[:25]:  # Check up to 25 examples
                code = code.strip()
                
                # Skip if too short or no newlines (not really code)
                if len(code) < 15:
                    continue
                
                # Skip if adding this would exceed limit
                if total_chars + len(code) + 20 > max_chars:
                    continue
                
                sections.append(f"\n{code}\n")
                total_chars += len(code) + 20
                example_count += 1
                
                if total_chars >= max_chars * 0.9:  # Stop at 90% to leave room
                    break
        
        if total_chars >= max_chars * 0.9:
            break
    
    if example_count == 0:
        sections.append("\n(No code examples found in documentation)")
    else:
        sections.append(f"\n--- {example_count} examples loaded ---")
    
    result = '\n'.join(sections)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n..."
    
    return result


if __name__ == '__main__':
    # Test the fetcher
    print("Testing Slicer Documentation Fetcher...")
    docs = get_documentation(force_refresh=True)
    
    total_content = sum(d.get('content_length', 0) for d in docs.values())
    print(f"\nTotal content fetched: {total_content} characters")
    
    for name, data in docs.items():
        print(f"  {name}: {data.get('content_length', 0)} characters")
    
    if total_content > 0:
        print("\nFormatted prompt preview:")
        print("=" * 80)
        prompt_text = format_docs_for_prompt(docs, max_chars=2000)
        print(prompt_text[:1000] + "...")
