"""
RAG Retriever for Slicer Documentation

Retrieves relevant code examples at runtime based on user queries.
"""

import json
import os
import re


INDEX_FILE = os.path.join(os.path.dirname(__file__), 'slicer_rag_index.json')
CURATED_FILE = os.path.join(os.path.dirname(__file__), 'curated_examples.json')
TUTORIALS_INDEX_FILE = os.path.join(os.path.dirname(__file__), 'slicermorph_tutorials_index.json')


class SlicerRAG:
    """Retrieve relevant Slicer code examples using RAG"""
    
    def __init__(self):
        self.index = None
        self.curated = []
        self.tutorials = []
        self.has_ml = False
        self.model = None
        self.load_index()
        self.load_curated()
        self.load_tutorials()
    
    def load_curated(self):
        """Load curated examples (prioritized over auto-indexed)"""
        if not os.path.exists(CURATED_FILE):
            return
        
        with open(CURATED_FILE, 'r') as f:
            data = json.load(f)
        
        self.curated = data.get('examples', [])
        
        # Add searchable text for keyword search
        for example in self.curated:
            searchable = ' '.join([
                example.get('heading', ''),
                example.get('description', ''),
                ' '.join(example.get('keywords', [])),
                example['code'][:500]
            ]).lower()
            example['searchable'] = searchable
    
    def load_index(self):
        """Load the pre-built index"""
        if not os.path.exists(INDEX_FILE):
            print(f"Warning: RAG index not found at {INDEX_FILE}")
            print("Run rag_indexer.py to build the index first.")
            return False
        
        with open(INDEX_FILE, 'r') as f:
            data = json.load(f)
        
        self.index = data.get('examples', [])
        self.has_ml = data.get('has_ml_embeddings', False)
        
        # Load ML model if index has embeddings
        if self.has_ml:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                print("Warning: sentence-transformers not available, falling back to keyword search")
                self.has_ml = False
        
        return True

    def load_tutorials(self):
        """Load the SlicerMorph tutorials index if available"""
        if not os.path.exists(TUTORIALS_INDEX_FILE):
            return False
        try:
            with open(TUTORIALS_INDEX_FILE, 'r') as f:
                data = json.load(f)
            self.tutorials = data.get('examples', [])
            # Ensure searchable field exists
            for entry in self.tutorials:
                if 'searchable' not in entry:
                    entry['searchable'] = ' '.join([
                        entry.get('heading', ''),
                        entry.get('description', ''),
                        entry.get('tutorial_text', '')[:300],
                        ' '.join(entry.get('keywords', [])),
                    ]).lower()
            return True
        except Exception as e:
            print(f"Warning: Could not load tutorials index: {e}")
            return False
    
    def retrieve_ml(self, query, top_k=5):
        """Retrieve using ML embeddings (cosine similarity)"""
        import numpy as np
        
        # Encode query
        query_embedding = self.model.encode(query)
        
        # Calculate similarities
        scores = []
        for example in self.index:
            if 'embedding' not in example:
                continue
            
            example_embedding = np.array(example['embedding'])
            similarity = np.dot(query_embedding, example_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(example_embedding)
            )
            scores.append((similarity, example))
        
        # Sort by similarity
        scores.sort(reverse=True, key=lambda x: x[0])
        
        return [ex for score, ex in scores[:top_k]]
    
    def retrieve_keyword(self, query, top_k=5):
        """Retrieve using keyword matching (fallback)"""
        query_lower = query.lower()
        query_terms = set(re.findall(r'\w+', query_lower))
        
        scores = []
        
        # Search curated examples first (with priority boost)
        for example in self.curated:
            searchable = example.get('searchable', '')
            priority = example.get('priority', 50)
            
            # Count matching terms
            matches = sum(1 for term in query_terms if term in searchable)
            
            # Bonus for exact phrase matches
            if query_lower in searchable:
                matches += 5
            
            # Bonus for matching keywords
            keywords = example.get('keywords', [])
            keyword_matches = sum(1 for term in query_terms if any(term in kw.lower() for kw in keywords))
            matches += keyword_matches * 2
            
            # Apply priority boost
            score = matches * (priority / 50)
            
            if matches > 0:
                scores.append((score, example))
        
        # Then search indexed examples
        for example in self.index:
            searchable = example.get('searchable', '')
            
            matches = sum(1 for term in query_terms if term in searchable)
            
            if query_lower in searchable:
                matches += 5
            
            keywords = example.get('keywords', [])
            keyword_matches = sum(1 for term in query_terms if any(term in kw.lower() for kw in keywords))
            matches += keyword_matches * 2
            
            if matches > 0:
                scores.append((matches, example))

        # Also search SlicerMorph tutorials
        for example in self.tutorials:
            searchable = example.get('searchable', '')

            matches = sum(1 for term in query_terms if term in searchable)

            if query_lower in searchable:
                matches += 5

            keywords = example.get('keywords', [])
            keyword_matches = sum(1 for term in query_terms if any(term in kw.lower() for kw in keywords))
            matches += keyword_matches * 2

            if matches > 0:
                scores.append((matches, example))
        
        # Sort by score
        scores.sort(reverse=True, key=lambda x: x[0])
        
        return [ex for score, ex in scores[:top_k]]
    
    def retrieve_examples(self, user_query, top_k=5):
        """Find most relevant examples for user's request"""
        if not self.index:
            return []
        
        # Use ML if available, otherwise keyword search
        if self.has_ml and self.model:
            return self.retrieve_ml(user_query, top_k)
        else:
            return self.retrieve_keyword(user_query, top_k)
    
    def format_for_prompt(self, examples, max_chars=3000):
        """Format retrieved examples for inclusion in AI prompt"""
        if not examples:
            return ""
        
        sections = ["=== RELEVANT SLICER CODE EXAMPLES ==="]
        sections.append("These examples show the correct way to use Slicer APIs:\n")
        
        total_chars = 0
        included_count = 0
        
        for example in examples:
            code = example.get('code', '').strip()
            heading = example.get('heading', '').strip()
            source = example.get('source', '')
            content_type = example.get('content_type', 'code')

            # For tutorial entries show prose; for code entries show the code block
            if content_type == 'tutorial':
                body = example.get('tutorial_text', example.get('description', '')).strip()
                if not body:
                    continue
                entry_size = len(body) + len(heading) + 60
                if total_chars + entry_size > max_chars:
                    break
                if heading:
                    sections.append(f"\n## SlicerMorph Tutorial: {heading}")
                sections.append(f"{body}\n")
                total_chars += entry_size
                included_count += 1
            else:
                # Skip if empty or too large
                if not code or len(code) < 20:
                    continue
                entry_size = len(code) + len(heading) + 50
                if total_chars + entry_size > max_chars:
                    break
                if heading:
                    sections.append(f"\n## Example: {heading}")
                else:
                    sections.append(f"\n## Example from {source}")
                sections.append(f"{code}\n")
                total_chars += entry_size
                included_count += 1
        
        if included_count == 0:
            return ""
        
        sections.append(f"\n--- {included_count} relevant examples provided ---")
        
        return '\n'.join(sections)


def get_rag_retriever():
    """Get a RAG retriever instance"""
    return SlicerRAG()


if __name__ == '__main__':
    # Test the retriever
    print("Testing RAG retriever...\n")
    
    rag = SlicerRAG()
    
    test_queries = [
        "segment a volume using threshold",
        "load data from URL",
        "create 3D rendering",
    ]
    
    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)
        
        examples = rag.retrieve_examples(query, top_k=3)
        
        if examples:
            print(f"Found {len(examples)} relevant examples:")
            for i, ex in enumerate(examples, 1):
                heading = ex.get('heading', 'Untitled')
                source = ex.get('source', 'unknown')
                code_preview = ex.get('code', '')[:100].replace('\n', ' ')
                print(f"  {i}. [{source}] {heading}")
                print(f"     {code_preview}...")
        else:
            print("  No examples found")
