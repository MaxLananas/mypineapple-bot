# 🍍 MyPineapple Bot — Guide Neon + 100 suggestions

---

## PARTIE 1 — Migrer tes données vers Neon (sans rien perdre)

### Étape 1 : Récupérer ta connexion Neon
1. Sur [console.neon.tech](https://console.neon.tech), ouvre ton **project**.
2. Va dans **Connect** (ou "Connection Details" / le bouton "Connect" en haut à droite).
3. Copie la **connection string** (format « pooled » ou « direct », peu importe). Elle ressemble à :
   ```
   postgresql://neondb_owner:XXXXXXXX@ep-muddy-forest-a1b2c3d4.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

### Étape 2 : Transférer tes données actuelles (SQLite → Neon)
Ton bot utilise actuellement `data/bot.db`. J'ai ajouté un script de migration :
`scripts/migrate_db.py`.

**Depuis la machine où se trouve ta DB actuelle** (ton hébergement bot-hosting.net,
dans la console si dispo, ou en local si tu as le fichier), lance :

```bash
# Option A — transfert direct (recommandé)
export DATABASE_URL='postgresql://neondb_owner:XXXX@ep-...aws.neon.tech/neondb?sslmode=require'
python scripts/migrate_db.py direct --source data/bot.db

# Option B — via un fichier de sauvegarde
python scripts/migrate_db.py export --source data/bot.db --out backup.json
export DATABASE_URL='...'
python scripts/migrate_db.py import --in backup.json
```

Le script crée la table `kv_store` automatiquement et y copie **levels, tickets,
daily, warns, config, ticketlogs**. Rien n'est perdu.

> ⚠️ **Important** : fais la migration **AVANT** le prochain redémarrage de ton bot.
> bot-hosting.net re-clone le repo à chaque restart et efface `data/` — donc si ton
> bot redémarre avant la migration, la progression non sauvegardée ailleurs est perdue.
>
> J'ai aussi généré une sauvegarde de secours `migration_export.json` (35 joueurs,
> 2 daily, 2 tickets) à partir du repo — mais elle reflète l'état **au moment du commit**,
> pas forcément ta progression la plus récente.

### Étape 3 : Configurer le bot
Dans les **variables d'environnement** de bot-hosting.net, ajoute :
```
TOKEN=ton-token-discord
DATABASE_URL=postgresql://neondb_owner:XXXX@ep-....neon.tech/neondb?sslmode=require
```
Au prochain démarrage, le bot détecte `DATABASE_URL` et bascule automatiquement sur
PostgreSQL (le code est déjà en place dans `utils/db.py`). Ta progression est alors
**définitivement à l'abri des restarts**.

---

## PARTIE 2 — 100 suggestions pour le bot

### A. Leveling / XP / Daily (1–15)
1. **Palier « abysse » négatif** : XP bonus la nuit, malus dans les canaux off-topic.
2. **Double XP week-end** automatisé (vendredi 18h → dimanche 23h59).
3. **XP par activité vocale** : +X XP toutes les 10 min en vocal.
4. **XP pour les réactions** : récompenser les membres actifs dans les annonces.
5. **Anti-spam XP** : détecter les copier-coller répétés pour neutraliser le farm.
6. **Palier de rôle manquant** : ajouter des niveaux intermédiaires (5, 15, 25…).
7. **`/level-rewards`** : commande listant tous les rôles palier et leurs seuils.
8. **Badge de progression** : barre animée qui se remplit (progress bar plus longue).
9. **Message de bienvenue de niveau** : customiser le texte de level-up par serveur.
10. **Streak leaderboard** : top des streaks quotidiens.
11. **Streak gel** (« freeze ») : conserver son streak une fois par semaine.
12. **XP en récompense de ticket fermé** (commission = bonus XP client).
13. **Désactivation XP par rôle** (rôle « muted XP »).
14. **Statistiques perso** (`/stats`) : messages envoyés, XP gagné, temps de vocal.
15. **Réinitialisation XP globale** sécurisée avec confirmation en 2 étapes.

### B. Tickets / Support (16–28)
16. **Bouton « Claim »** : un support s'attribue un ticket (affiché dans le topic).
17. **Numéro unique de ticket** (#0001…) affiché dans le nom du channel.
18. **Limite de tickets ouverts** (1 par type par utilisateur, déjà partiel — l'étendre).
19. **Fermeture avec motif** : Résolu / Abandonné / Dupliqué (menu au close).
20. **Réouverture** d'un ticket fermé (bouton dans le transcript).
21. **Rappel automatique** des tickets inactifs > 48h (ping support).
22. **Transcription enrichie** : inclure les images uploadées dans le transcript.
23. **Transcription en PDF/HTML** plutôt que `.txt` (plus lisible).
24. **Priorité** : P1/P2/P3 sur les tickets bug.
25. **Tag auto** du forum selon le type de ticket.
26. **Note interne** : messages staff invisibles au client dans le ticket.
27. **Statistiques tickets** (`/ticket-stats`) : ouverts/fermés/temps moyen.
28. **Sondage de satisfaction** automatique à la fermeture d'un ticket.

### C. Modération (29–40)
29. **`/history`** : historique de modération d'un membre (audit log).
30. **Softban** (ban + unban immédiat pour purger les messages).
31. **`/warn` avec durée d'expiration** (warn auto-expiré après X jours).
32. **Seuils de sanction configurables** (3/5 hardcodés → paramétrables).
33. **Afficher « émis par »** dans `/warnings`.
34. **`/slowmode` sur threads**.
35. **`/purge` par utilisateur** (purge les messages d'un membre précis).
36. **`/purge` par mot-clé / regex**.
37. **Anti-raid** : détection de N joins en M secondes → verrouillage auto.
38. **Anti-lien** : filtre de liens externes (whitelist de domaines).
39. **Mute vocal** (mute + mute de la voix) dans une seule commande.
40. **Journal de modération** dans un channel dédié (déjà des threads logs — le lier).

### D. Logs (41–50)
41. **Log des messages supprimés avec images** (fait — l'étendre aux vidéos).
42. **Log des changements de bio** Discord (nécessite fetch de l'utilisateur).
43. **Log des changements de bannière** (banner).
44. **Log des statuts custom / activités** (si tu réactives les presences).
45. **Log des invitations** créées (tracking des invites).
46. **Log des webhooks** créés/modifiés/supprimés.
47. **Log des permissions de channel modifiées**.
48. **Recherche dans les logs** (`/log-search`) par utilisateur.
49. **Rétention** : purge automatique des logs > 30 jours (option).
50. **Sauvegarde des logs** en base (pas seulement des threads Discord).

### E. Fun (51–58)
51. **`/rps`** (pierre-papier-ciseaux).
52. **`/roll`** (dés : `2d6`, `1d20`…).
53. **Giveaways** (`/giveaway create`) avec tirage au sort.
54. **`/8ball` cooldown** pour éviter le spam.
55. **Trivia quiz** sur Minecraft.
56. **`/meme`** : memes aléatoires (API ou dossier).
57. **`/quote`** : citations de membres (message aléatoire sauvegardé).
58. **`/ship`** : compatibilité entre deux membres (fun).

### F. Reviews / Portfolio / Commerce (59–68)
59. **Vérifier que l'utilisateur a un rôle client** avant `/review`.
60. **Cooldown `/review`** + limite de reviews par utilisateur.
61. **Validation stricte de l'URL image** (domaines whitelist : imgur, cdn…).
62. **Portfolio paginé** (boutons ← →, pas 8 images fixes).
63. **Portfolio par catégorie** (builds / plugins / maps / collabs).
64. **Bouton « Voir le build »** avec lien direct dans le portfolio.
65. **`/portfolio` publique** (pas seulement en DM).
66. **Galerie par tags** (médiéval, moderne, spawn, redstone…).
67. **Compteur de reviews** (moyenne étoiles affichée).
68. **`/prices` avec devis automatique** (formulaire → estimation).

### G. Welcome / Onboarding (69–75)
69. **Message de bienvenue personnalisé** avec pseudo + rang (déjà riche, l'enrichir).
70. **Système d'invites** : traquer qui a invité qui, récompenses.
71. **Vérification** (captcha / bouton « Je ne suis pas un robot »).
72. **Message de règles** + acceptation via bouton (rôle accordé).
73. **Welcome DM** en plus du message dans le salon.
74. **Détection des comptes récents** (< 24h) → alerte staff.
75. **Message d'au revoir** quand un membre quitte (dans le salon arrivées).

### H. Info / UI (76–82)
76. **`/help` dynamique** listant toutes les commandes par catégorie.
77. **Emojis dynamiques** dans les cards (niveau → émoji adapté).
78. **`/serverinfo` enrichi** : membres en vocal, boosts, boosters.
79. **`/avatar` avec bouton** pour télécharger l'image en pleine résolution.
80. **Thème saisonnier** (couleurs d'accent qui changent selon la saison).
81. **Localisation FR** : traduire les commandes en français (ou bilingue).
82. **Timestamps relatifs** partout (déjà bien — standardiser).

### I. Infra / DB / Sécurité / Perf (83–95)
83. **PostgreSQL** (fait — le documenter pour ton hébergeur).
84. **`.env`** sécurisé : ne jamais commit de token (fait via `.gitignore`).
85. **Rate-limit global** : éviter les 429 de l'API Discord.
86. **Queue des messages** : bufferiser les envois pour respecter les limites.
87. **Health check** : endpoint ou commande `/ping` enrichie (fait).
88. **Restart propre** : flush DB à la fermeture (fait via `close_db`).
89. **Reconnexion auto** : gérer les coupures de gateway (discord.py le fait).
90. **Tests unitaires** sur les helpers (`xp_for_level`, `parse_duration`…).
91. **CI GitHub** (Actions) : lint + tests à chaque push.
92. **Logs structurés JSON** pour un monitoring externe.
93. **Config par guild** : rendre les IDs configurables (pas hardcodés).
94. **Mode maintenance** (`/maintenance on`) pour bloquer les commandes.
95. **Backup automatique** quotidien de la DB vers un fichier/drive.

### I-bis. Divers / Communauté (96–100)
96. **Annonce auto des nouveaux builds** (poster dans un salon showcase).
97. **Système de suggestion** : les membres votent via réactions.
98. **Calendrier des streams** / annonces de lives.
99. **Rôle « booster »** avec avantages (XP bonus).
100. **`/roadmap`** : afficher les projets en cours de MaxLananas.
