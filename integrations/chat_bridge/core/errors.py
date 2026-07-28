# -*- coding: utf-8 -*-
# Wyjatki wspolne dla kanalow.


class PermanentSendError(Exception):
    """Wysylka, ktorej ponawianie nic nie da (np. format zalacznika odrzucany przez kanal).

    Worker konczy taka pozycje od razu — bez 5 prob i backoffu — a tresc wyjatku
    trafia do agenta jako powod w notatce i w czerwonym dymku Chatwoota.
    """
