# mobile/

Dossier **réservé au futur accès iPhone** au briefing MIA.

Aucune application mobile n'existe encore. Le point d'appui prévu côté serveur
est l'API structurée `GET /api/briefing/` (agenda + mails iCloud, lecture
seule), protégée par `BRIEFING_API_KEY` et **jamais exposée directement sur
Internet** — un client iPhone passerait par un reverse proxy TLS.

Voir `backend/briefing/README.md` pour la marche à suivre d'accès depuis un
appareil mobile.
