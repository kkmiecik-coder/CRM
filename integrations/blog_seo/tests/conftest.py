# -*- coding: utf-8 -*-
# Wspolne przygotowanie srodowiska testow: ustawiamy minimalne zmienne, aby importy nie
# zalezaly od realnych sekretow. Config i tak uzywa os.environ.get z domyslnymi wartosciami.
import os
os.environ.setdefault("BLOG_LLM_PROVIDER", "openai")
os.environ.setdefault("BLOG_OPENAI_API_KEY", "sk-test")
os.environ.setdefault("BLOG_ANTHROPIC_API_KEY", "sk-ant-test")
