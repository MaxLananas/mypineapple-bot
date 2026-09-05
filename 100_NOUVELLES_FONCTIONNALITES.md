# 🍍 MyPineapple Bot — 100 nouvelles fonctionnalités + optimisation

> Carte blanche. Classées par thème, avec la complexité estimée (🟢 simple /
> 🟡 moyen / 🔴 gros) et l'impact. Les plus rentables sont marquées ⭐.

---

## A. Économie (système de monnaie « ananas ») — 1 à 12

1. 🟡⭐ **Monnaie interne** : `🍍` (pineapple coins) gagnés en parlant, vocal, tickets, events.
2. 🟡 **`/balance`** : voir son solde (+ celui d'un autre membre).
3. 🟡 **`/daily` étendu** : bonus en monnaie en plus de l'XP.
4. 🟡 **Shop** (`/shop`) : acheter des rôles cosmétiques, couleurs, badges.
5. 🟡 **`/pay @membre 100`** : transférer des coins.
6. 🟡 **`/leaderboard money`** : top des plus riches.
7. 🔴 **Casino** : `/blackjack`, `/slots`, `/roulette` (avec limite anti-addiction).
8. 🟡 **`/steal`** : tenter de voler (avec risque d'amende).
9. 🟢 **`/work`** : petits jobs RP pour gagner des coins (cooldown).
10. 🔴 **Marché** : achat/vente entre membres (enchères).
11. 🟡 **Récompenses de streak** : streak quotidien = bonus coins.
12. 🟢 **`/grant @membre 500`** (admin) : créditer manuellement.

## B. Leveling / XP avancé — 13 à 20

13. 🟢⭐ **Cartes de rang en image** (Pillow) : `/rank` génère une vraie image stylée.
14. 🟢 **XP par palier d'activité** : multiplicateur selon le nombre de messages/semaine.
15. 🟡 **Système de titres** : titres débloqués (Chatty, Builder, Night Owl…).
16. 🟡 **`/stats` en graphe** : courbe d'XP sur 7 jours (matplotlib).
17. 🟢 **Bonus XP à l'heure du serveur** (golden hour).
18. 🟡 **XP de groupe** : bonus quand on est plusieurs en vocal.
19. 🟢 **`/reset-level all`** avec confirmation en 2 étapes.
20. 🟡 **Achievements** : badges permanents (1er message, 100 messages, 1er ticket…).

## C. Tickets améliorés — 21 à 28

21. 🟢⭐ **Bouton « Claim »** : le support s'attribue un ticket (affiché dans le nom).
22. 🟢 **Priorité P1/P2/P3** sur les tickets bug.
23. 🟡 **SLA/rappel auto** : ping si un ticket n'a pas eu de réponse staff > 24h.
24. 🟢 **Tag auto du forum** selon le type de ticket (déjà partiel).
25. 🟡 **`/ticket-stats`** : ouverts/fermés/temps moyen de résolution.
26. 🟢 **Note interne** : commande `/note` visible uniquement par le support.
27. 🟡 **Satisfaction auto** : mini-sondage étoiles à la fermeture.
28. 🟢 **Archivage des transcripts en PDF** (ReportLab) en plus du HTML/TXT.

## D. Modération intelligente — 29 à 38

29. 🔴⭐ **Anti-raid** : N joins en M secondes → verrouillage auto + alerte.
30. 🔴 **Auto-mod** : filtre liens/mots interdits configurable (`/automod`).
31. 🟡 **Anti-spam global** : limite de messages par seconde (avec timeout auto).
32. 🟢 **`/warn` avec expiration** : les warns s'expirent après X jours.
33. 🟢 **`/history`** : historique de modération d'un membre (audit log).
34. 🟡 **`/softban`** : ban + unban immédiat (purge les messages).
35. 🟢 **Seuils de sanction configurables** (3/5 → paramétrables).
36. 🔴 **Captcha/verification** : bouton « je ne suis pas un robot » à l'arrivée.
37. 🟡 **Anti-alt** : détecter les comptes récents qui rejoignent en masse.
38. 🟢 **`/lockdown`** : verrouiller tout le serveur en 1 commande.

## E. Logs avancés — 39 à 45

39. 🟢⭐ **Recherche dans les logs** (`/log-search @membre`) : historique d'un membre.
40. 🟡 **Rétention** : purge auto des logs > 30 jours (option).
41. 🟡 **Sauvegarde des logs en DB** (pas seulement les threads Discord).
42. 🟢 **Log des statuts en ligne/hors ligne** (avec debounce).
43. 🟢 **Log des rôles de niveau attribués** (qui a monté quel palier).
44. 🟡 **Dashboard de logs** : résumé quotidien (X messages, Y joins…).
45. 🟢 **Log des webhooks supprimés** avec nom (déjà partiel, enrichir).

## F. Fun & jeux Minecraft — 46 à 56

46. 🟢⭐ **`/trivia`** : quiz Minecraft (questions/réponses tournantes).
47. 🟢 **`/rps`** : pierre-papier-ciseaux.
48. 🟢 **`/roll`** : dés (`2d6`, `1d20`).
49. 🟡 **`/minecraft`** : info serveur, ping d'un serveur MC (API).
50. 🟢 **`/wouldyourather`** : dilemmes aléatoires.
51. 🟢 **`/truth` `/dare`** : vérité/défi.
52. 🟡 **`/meme`** : memes Minecraft (via API ou dossier local).
53. 🟢 **`/quote`** : citations de membres (message aléatoire).
54. 🟡 **`/hangman`** : pendu avec mots Minecraft.
55. 🟢 **`/ship`** : compatibilité fun entre 2 membres.
56. 🔴 **Mini-RPG** : combats de tour par tour entre membres.

## G. Portfolio / showcase — 57 à 63

57. 🟢⭐ **Portfolio par catégorie** : builds / plugins / maps / collabs.
58. 🟡 **Galerie paginée publique** (boutons, pas seulement DM).
59. 🟢 **`/build @pseudo`** : afficher un build précis.
60. 🟡 **Système de tags** : médiéval, moderne, spawn, redstone…
61. 🟢 **Compteur de vues** par build (quels builds sont les plus consultés).
62. 🟡 **`/showcase`** : poster un nouveau build via formulaire (auto ajout à la liste).
63. 🔴 **Site vitrine auto-généré** : portfolio synchronisé avec le bot.

## H. Commerce / commandes — 64 à 70

64. 🟡⭐ **Suivi de commande** : statut (en attente / en cours / livré) affiché dans le ticket.
65. 🟢 **`/invoice`** : générer une facture simple (montant, description).
66. 🟡 **Rappels de livraison** : ping auto si une commission dépasse la deadline.
67. 🟢 **`/prices` personnalisé** : devis rapide via formulaire.
68. 🟡 **Historique client** : nombre de commandes, total dépensé.
69. 🟢 **Badge « client fidèle »** après N commandes.
70. 🔴 **Paiements intégrés** (lien Stripe/PayPal) — à discuter (légal).

## I. Communauté & social — 71 à 80

71. 🟡⭐ **Système d'invites** : traquer qui invite qui + récompenses.
72. 🟢 **`/reputation`** : +rep / -rep entre membres.
73. 🟡 **Système de suggestions** : les membres votent (👍/👎) sur les idées.
74. 🟢 **`/birthday`** : enregistrer son anniversaire + message le jour J.
75. 🟡 **Rôle auto par réaction** (reaction roles).
76. 🟢 **`/serverinfo` enrichi** : membres en vocal, boosts, boosters.
77. 🟡 **Événements récurrents** : annonces programmées (streams, events).
78. 🟢 **`/feedback`** : retour anonyme vers les admins.
79. 🟡 **Message d'au revoir** quand un membre quitte (salon arrivées).
80. 🔴 **Mini-bot de comptage** (counting channel) pour la communauté.

## J. Welcome / onboarding — 81 à 86

81. 🟢⭐ **Onboarding guidé** : message de bienvenue + boutons (lire règles, choisir rôles).
82. 🟢 **`/rules`** : afficher les règles stylées.
83. 🟡 **Vérification par bouton** : rôle « Membre » après acceptation.
84. 🟢 **Welcome DM personnalisé** en plus du salon.
85. 🟡 **Message de bienvenue en image** (bannière générée avec le pseudo).
86. 🟢 **Alerte staff** sur les comptes < 24h (déjà fait — l'étendre à un ping).

## K. Admin / config / utilitaires — 87 à 94

87. 🟡⭐ **Web dashboard** : configurer le bot depuis un site (Flask/FastAPI).
88. 🟢 **`/config`** : voir/modifier les réglages (IDs, seuils) en commande.
89. 🟡 **Backup auto quotidien** de la DB vers un fichier (déjà partiel via Discord).
90. 🟢 **`/ping` enrichi** : latence API + DB + temps de traitement.
91. 🟡 **Mode maintenance** (`/maintenance on`) : bloque les commandes.
92. 🟢 **`/uptime`** dédié + statut des cogs.
93. 🟡 **Healthcheck HTTP** : endpoint pour uptime monitoring (UptimeRobot).
94. 🟢 **`/sync`** : re-synchroniser les slash commands à la demande.

## L. Divers / polish — 95 à 100

95. 🟢⭐ **Localisation FR** : traduire toutes les commandes (ou bilingue).
96. 🟢 **Cooldowns globaux** sur les commandes fun (anti-spam).
97. 🟡 **Thème saisonnier** : couleurs d'accent qui changent (été/halloween/noël).
98. 🟢 **`/help` avec sous-menus** (boutons par catégorie).
99. 🟡 **Son d'ambiance** : effet « océan » dans les cards (gifs/palette).
100. 🔴 **Système de plugins maison** : mini-framework pour ajouter des cogs sans toucher au cœur.

---

# ⚡ Optimisation, librairies & technologies

## Ce que je recommande (impact réel, sans exploser la complexité)

| Priorité | Changement | Pourquoi |
|---|---|---|
| ⭐⭐⭐ | **Config via `.env` + validation `pydantic`** | Les IDs en dur dans `config.py` sont fragiles. Pydantic valide tout au démarrage et donne des erreurs claires. |
| ⭐⭐⭐ | **Tests unitaires (`pytest`)** | `xp_for_level`, `parse_duration`, le flush DB… sont testables. Évite les régressions. |
| ⭐⭐⭐ | **CI GitHub Actions** | Lint + tests à chaque push. Gratuit, direct. |
| ⭐⭐ | **`uv` au lieu de pip** | Installation ~10× plus rapide, lockfile reproductible (`uv.lock`). Parfait pour bot-hosting.net. |
| ⭐⭐ | **Type hints complets + `mypy`** | Attrape des bugs avant la prod. Ton code est déjà typé, on peut passer au niveau supérieur. |
| ⭐⭐ | **Cartes de rang en image (`Pillow`)** | Gros gain visuel pour `/rank` et `/profile`. |
| ⭐⭐ | **Graphes (`matplotlib`)** | `/stats` avec courbe d'XP = effet waouh. |
| ⭐⭐ | **Scheduler dédié (`apscheduler`)** | Giveaways, rappels, backups : plus propre que des `tasks.loop` maison. |
| ⭐ | **Redis** | Cache/cooldowns partagés. **Surcharge pour ton échelle** — seulement si tu multi-instanciés. |
| ⭐ | **Docker** | Reproductible, mais bot-hosting.net gère déjà le déploiement. |
| ⭐ | **asyncpg pool tuning** | Déjà en place. Juste ajuster `min_size/max_size` selon la charge. |

## Ce que je NE recommande PAS (pour ton échelle)

- ❌ **Base NoSQL (Mongo…)** : ton modèle est un simple key-value, Postgres/SQLite suffisent largement.
- ❌ **ORM lourd (SQLAlchemy async)** : sur-ingénierie pour une table `kv_store`.
- ❌ **Framework type `discord.py` alternatif (nextcord/pycord)** : migration risquée sans gain pour toi.
- ❌ **Microservices / message queues** : sur-dimensionné pour un bot de serveur communautaire.
- ❌ **IA/LLM** : tu as explicitement dit « pas IA » — et c'est coûteux + lent. On reste déterministe.

## Améliorations de code « sans librairie » (gratuites et rentables)

1. **Centraliser les IDs** dans un seul endroit + les rendre configurables par guild.
2. **Retry + backoff exponentiel** sur les appels API Discord (au lieu des 3 tentatives fixes).
3. **Queue d'envoi** pour respecter le rate-limit global (bufferiser les bursts de logs).
4. **Lazy-loading des cogs** au premier besoin (réduit le démarrage).
5. **Découper `cogs/tickets.py`** (~940 lignes) en modules plus petits.
6. **Logging structuré JSON** pour un monitoring externe éventuel.
7. **Gestion propre du SIGTERM** (flush DB à la fermeture, déjà partiel).
8. **Healthcheck `/ping` qui inclut la latence DB** (détecte une DB morte).

---

## Ma suggestion : par où commencer ?

Si tu me dis « go », je m'attaque dans cet ordre (impact décroissant) :

1. **Économie ananas** (A) — énorme valeur d'engagement.
2. **Cartes de rang en image** (B13) + **graphes** (B16).
3. **Anti-raid + auto-mod** (D) — sécurité.
4. **Système d'invites + réputation** (I) — croissance.
5. **Onboarding guidé** (J) — accueil pro.
6. **CI + tests + pydantic** (optimisation).

Dis-moi « oui » et je commence, ou choisis les numéros précis que tu veux.
