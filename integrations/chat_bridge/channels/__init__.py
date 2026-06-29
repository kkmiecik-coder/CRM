# -*- coding: utf-8 -*-
# Rejestr kanalow. Dodanie nowego kanalu = nowy modul z poller()/send() + jedna linia tutaj.
from channels import olx, allegro_msg, allegro_dispute

REGISTRY = {
    olx.name: olx,
    allegro_msg.name: allegro_msg,
    allegro_dispute.name: allegro_dispute,
}
