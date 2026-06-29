# -*- coding: utf-8 -*-
# Jednolite logowanie mostka (stdout, od razu flush — widoczne w `docker logs`).
def log(*a):
    print("[bridge]", *a, flush=True)
