# 🍍 MyPineapple Bot — Bilan des corrections

Bot Discord **vitrine / commissions** pour MaxLananas (builder Minecraft + dev plugins).
Architecture `discord.py` en cogs, UI en **components v2** (type 17) via l'API REST.

---

## 🗄️ Réponse à ta question : la DB disparaît-elle sur bot-hosting.net ?

**OUI, en l'état ça disparaissait.** Un hébergeur type bot-hosting.net **re-clone le repo
à chaque restart** : le système de fichiers est réinitialisé. `data/bot.db` (et le WAL
`bot.db-wal`, qui contenait justement tes données non encore "pliéées") était perdu à
chaque redémarrage.

**Ce qui a été fait :**
1. **Checkpoint WAL automatique** — `PRAGMA wal_checkpoint(TRUNCATE)` régulier : le fichier
   `data/bot.db` est toujours à jour, et si tu continues de le versionner dans git, il
   sera correct.
2. **Support PostgreSQL** — si tu définis `DATABASE_URL=postgres://…`, le bot bascule
   automatiquement sur une base hébergée qui **survit à 100 % des restarts**. Gratuit chez
   [Neon](https://neon.tech), Supabase, Railway… C'est LA solution fiable.
3. `.env.example` fourni + `.gitignore` (les données ne seront plus commitées par erreur).

> **Recommandation** : branche une base Postgres gratuite (Neon) et mets `DATABASE_URL`
> dans les variables d'environnement de bot-hosting.net. Plus aucun risque de perdre
> l'XP, les warns, les tickets ou les daily.

---

## ✅ Bugs corrigés

| # | Bug | Correction |
|---|---|---|
| 1 | `REVIEW_TAG_3STARS` == `REVIEW_TAG_4STARS` | ID 3★ → `1540786007971070092` |
| 2 | `LEVEL_ROLES[20]` == `LEVEL_ROLES[30]` (Nemo = Medusa) | ID Medusa → `1525609578379608074` |
| 3 | Montée de niveau via `/daily` sans rôle ni message | `utils/leveling.py` partagé (`add_xp`) |
| 4 | `/xp-set` / `/xp-reset` ne synchronisent pas les rôles | `sync_level_roles()` appelé |
| 5 | `/announce` avec ping supprimé par `NO_MENTIONS` | `MENTIONS_ALL` quand un ping est fourni |
| 6 | Transcripts tickets perdus au restart | Stockés en DB (store `ticketlogs`) |
| 7 | Sondages perdus au restart | Sondages **persistants** (DB + vues persistantes) |
| 8 | Fuite de données git (`bot.db*`, `bot.log`) | `.gitignore` + `git rm --cached` |
| 9 | `data/*.json` morts | Retirés du suivi |
| 10 | Code mort (`flask`, `random_build_url`, doublons review) | Supprimé |
| 11 | `Intents.all()` sur-privilégié | `default()` + `members` + `message_content` |
| 12 | `tree.sync()` à chaque `on_ready` | Sync unique + gestion d'erreur |
| 13 | "toward level 101" au niveau max | Corrigé dans `utils/leveling.py` |
| 14 | Rating review non-numérique → 5★ silencieux | Validation 1–5 avec message d'erreur |

## ✨ Améliorations ajoutées (carte blanche)

- **Logs avec images** : les avatars changés, les photos supprimées et les pièces jointes
  sont maintenant **affichés en galerie** (component type 12) et en **vignette** (type 11),
  plus en lien texte.
- **Logs étendus** : purge en masse (`on_bulk_message_delete`), changement de pseudo global
  (display name), protection anti-boucle.
- **Montées multi-niveaux** : tous les rôles palier franchis sont attribués.
- **`purge`** : protège les messages épinglés + gère la limite des 14 jours.
- **`lock` / `unlock`** : fonctionnent aussi sur les threads.
- **Nettoyage des cooldowns XP** (le dict ne grossit plus indéfiniment).
- **Sanitisation des noms de tickets** (pas de crash sur pseudo invalide).
- **Fins de ligne normalisées LF** + `.gitattributes` (fini le mélange CRLF/LF).
- `asyncpg` ajouté à `requirements.txt` pour le support Postgres.

---

## 🚀 Pour déployer

```bash
pip install -r requirements.txt
export TOKEN=ton-token
export DATABASE_URL=postgres://user:pass@host:5432/db   # optionnel mais recommandé
python main.py
```

Sur bot-hosting.net : ajoute `TOKEN` (et idéalement `DATABASE_URL`) dans les variables
d'environnement, et le repo restera la source de vérité sans perte de données.
