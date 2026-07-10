# -*- coding: utf-8 -*-
# Jednolite logowanie automatu blogowego (stdout, od razu flush — widoczne w logach crona).
def log(*a):
    print("[blog]", *a, flush=True)
