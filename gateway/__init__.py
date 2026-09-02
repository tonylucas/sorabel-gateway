"""Gouvernance de la gateway : matrice d'accès, journal, catalogue de tools.

Les canaux (`mcp_server/`) traduisent un protocole ; c'est ici que se décide
qui a le droit d'appeler quoi, et ici que tout appel est tracé. Un second canal
importerait `gateway.tools` et hériterait des deux sans rien réimplémenter.
"""
