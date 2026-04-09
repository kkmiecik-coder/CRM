"""Ładowanie bazy wiedzy z plików Markdown z hybrid matching"""

import os
import re
import yaml


class KnowledgeSection:
    def __init__(self, title, keywords, synonyms, content, filepath):
        self.title = title
        self.keywords = [k.lower() for k in keywords]
        self.synonyms = {}
        for key, values in synonyms.items():
            self.synonyms[key.lower()] = [v.lower() for v in values]
        self.content = content
        self.filepath = filepath
        self.all_keywords = set(self.keywords)
        for values in self.synonyms.values():
            self.all_keywords.update(values)


class KnowledgeLoader:
    _instance = None

    STOP_WORDS = {
        'czy', 'jest', 'są', 'jak', 'co', 'to', 'w', 'na', 'do', 'z', 'i',
        'a', 'lub', 'albo', 'o', 'po', 'za', 'od', 'nie', 'tak', 'ten',
        'ta', 'te', 'tego', 'tej', 'tym', 'tych', 'dla', 'jaki', 'jaka',
        'jakie', 'mam', 'mamy', 'masz', 'proszę', 'prosze', 'hej', 'cześć',
        'czesc', 'witam', 'dzięki', 'dzieki', 'dziekuje', 'może', 'moze',
    }

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sections = []
            cls._instance._loaded = False
        return cls._instance

    def load(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), 'data')
        self._sections = []
        if not os.path.isdir(data_dir):
            return
        for filename in sorted(os.listdir(data_dir)):
            if not filename.endswith('.md'):
                continue
            filepath = os.path.join(data_dir, filename)
            section = self._parse_md_file(filepath)
            if section:
                self._sections.append(section)
        self._loaded = True

    def _parse_md_file(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            raw = f.read()
        if not raw.startswith('---'):
            return None
        parts = raw.split('---', 2)
        if len(parts) < 3:
            return None
        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None
        content = parts[2].strip()
        return KnowledgeSection(
            title=meta.get('title', os.path.basename(filepath)),
            keywords=meta.get('keywords', []),
            synonyms=meta.get('synonyms', {}),
            content=content,
            filepath=filepath
        )

    def get_relevant_context(self, message):
        if not self._loaded:
            self.load()
        message_lower = message.lower()
        matched = []
        for section in self._sections:
            if any(kw in message_lower for kw in section.all_keywords):
                matched.append(section)
        if matched:
            return '\n\n'.join(s.content for s in matched)
        words = [w for w in re.split(r'\s+', message_lower) if len(w) > 3 and w not in self.STOP_WORDS]
        if not words:
            return ''
        scored = []
        for section in self._sections:
            content_lower = section.content.lower()
            score = sum(1 for w in words if w in content_lower)
            if score > 0:
                scored.append((score, section))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:2]
        if top:
            return '\n\n'.join(s.content for _, s in top)
        return ''
