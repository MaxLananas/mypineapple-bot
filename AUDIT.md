# 🔍 Audit complet — MyPineapple Bot

**Date :** 2026-10-03
**Périmètre :** `main.py`, `config.py`, `cogs/*` (10 cogs), `cogs/tickets/*`, `utils/*`, `scripts/*`
**Méthode :** lecture intégrale du code + `pyflakes` + compilation de tous les fichiers +
chargement réel des 10 cogs (discord.py 2.7.1) + simulations des flux critiques.

---

## 🔴 Bugs critiques corrigés

### 1. `/daily` → `404 Not Found (10062): Unknown interaction` *(bug signalé)*
**Cause :** la commande faisait tout le travail **avant** d'accuser réception de
l'interaction : `add_xp()` → `sync_level_roles()` (jusqu'à **20 appels REST** pour
aligner les rôles palier) + message de level-up. Au-delà de **3 secondes**,
Discord invalide le token de l'interaction → le `defer()` qui suivait plantait.

**Correctifs :**
- `interaction.response.defer(ephemeral=True)` est désormais **la première ligne**
  de `/daily` ; le chemin « reviens dans Xh » et la carte de récompense passent par
  `followup` / `edit`.
- `add_xp()` ne resynchronise plus les rôles que si un **palier est franchi**
  (`milestone_roles_crossed`) : le cas courant ne fait plus aucun appel REST.

### 2. Même bug latent dans d'autres commandes/boutons
Le même schéma (ACK après un appel REST lent) existait dans :
`/ban`, `/kick`, `/mute`, `/unmute`, `/slowmode`, `/lock`, `/unlock`
et le bouton **« Reopen Ticket »** (création de salon avant la réponse).
→ ACK immédiat + `followup` + gestion `discord.HTTPException` (avant, seule
`Forbidden` était attrapée : une erreur 400/500 remontait en « Unknown interaction »).

### 3. Anti-spam : le rôle « muted » restait appliqué à vie après un restart
Le retrait du rôle (et du rôle d'avertissement) était une `asyncio.Task` **en mémoire** :
un redémarrage du bot la perdait → le timeout Discord expirait mais le rôle restait.
→ Les mutes en cours sont **persistés en base** (`antispam_timeouts`) et
`restore_pending_releases()` les replanifie au démarrage (`main.py`).

### 4. Perte de données à l'arrêt (backend « salon Discord »)
`close_db()` / `db.flush()` appelaient `_flush_all()` qui respecte un intervalle
minimum de 30 s entre deux snapshots : si un flush venait d'avoir lieu, les
changements des 30 dernières secondes étaient **silencieusement perdus** à l'arrêt.
→ Nouvel argument `force=True`, utilisé au shutdown.

### 5. Le bouton « Close » pouvait supprimer un salon qui n'est pas un ticket
`_do_close_ticket()` supprimait le salon même si la base ne le connaissait pas
(base restaurée, vieux bouton, salon renommé…). → Garde : salon non suivi = refus.

### 6. Bouton « Reopen » : crash si l'auteur du ticket a quitté le serveur
`await guild.fetch_member(opener_id)` non protégé → `NotFound` non géré, et la
réponse arrivait après la création du salon (timeout d'interaction).
→ `defer` d'abord, `fetch_member` protégé, message d'erreur clair.

---

## 🟠 Bugs cachés corrigés

| # | Où | Bug | Effet |
|---|----|-----|-------|
| 7 | `main.py` | `tree.sync()` global à **chaque** connexion (`on_ready` est rappelé à chaque reconnexion) | peut épuiser le quota de commandes Discord |
| 8 | `cogs/invites.py` | `add_xp(member=inviter)` avec un `discord.User` si l'inviteur a quitté | `AttributeError` sur `.roles`, récompense perdue en silence |
| 9 | `cogs/invites.py` | cache des invitations **global** (pas par serveur) | collisions de codes entre serveurs → mauvais parrain |
| 10 | `cogs/logs.py` | cache bio/bannière vide au 1er passage | faux « Bio/Banner Changed » à **chaque restart** |
| 11 | `cogs/logs.py` | ping staff des nouveaux comptes | ne pingait **jamais** (`NO_MENTIONS` par défaut) |
| 12 | `utils/images.py` | `_codepoint()` supprimait le VS16 dans les séquences ZWJ | URL Twemoji invalide → emoji absent de la carte (ex. 🧜‍♂️ Triton) |
| 13 | `cogs/moderation.py` | `/warn` sans borne de longueur | > 4000 car. = erreur 400 côté Discord |
| 14 | `cogs/moderation.py` | `/announce` (titre/message) idem | idem |
| 15 | `cogs/fun.py` | `/poll` (question/options) idem | idem |
| 16 | `cogs/moderation.py` | `/warnings` : liste non bornée + `fromisoformat` non protégé | erreur 400 / `ValueError` sur donnée corrompue |
| 17 | `cogs/profile.py` | `/streak` + `/daily` : `fromisoformat` non protégé, streak non numérique | crash sur donnée corrompue |
| 18 | `cogs/info.py` | `/rank`, `/userinfo`, `/stats`, `/leaderboard` : accès `ud["level"]` | `KeyError` si une entrée DB est corrompue |
| 19 | `cogs/leveling.py` | `voice_xp_loop` : un seul `try` pour tous les serveurs | une erreur sur un serveur privait **tous** les autres de l'XP vocal |
| 20 | `cogs/fun.py` | tirage des giveaways : entrée corrompue | la boucle plantait → plus aucun giveaway terminé |
| 21 | `cogs/tickets/views.py` | l'éphémère « réfléchit… » restait bloqué après fermeture | mauvaise UX |
| 22 | `cogs/tickets/modals.py` | erreur à la création d'un ticket | « Interaction failed » sans explication → message d'erreur ajouté |
| 23 | `scripts/migrate_db.py` | liste de stores incomplète (`stats`, `closedtickets`) | **perte de données** lors d'une migration SQLite/Postgres |
| 24 | `cogs/tickets/core.py` | `/commission-close` : `fetch_member` non protégé + message non borné | crash si le client a quitté / erreur 400 |

---

## 🧹 Nettoyage (qualité)

- `pyflakes` : **19 signalements → 0** (imports inutilisés, `f"..."` sans
  placeholder, variables mortes, `global _session` inutile, variable `dr` inutile).
- Nouveau helper `utils.helpers.parse_iso()` : parsing ISO tolérant (naïf → UTC,
  `None`/valeur corrompue → `None` au lieu d'une exception).
- Bornes de longueur documentées aux endroits sensibles (limite Discord : 4000 car. par bloc).

---

## ✅ Vérifications effectuées

```
pyflakes ................. 0 finding
py_compile ............... tous les .py OK
chargement des cogs ...... 10/10, 48 commandes, 0 doublon
```

Simulations exécutées (hors ligne, sans Discord) :

- `/daily` 1ᵉʳ claim : ordre `defer → add_xp → delete_original` ✔
- `/daily` en cooldown : `defer → followup` (plus de double ACK) ✔
- `/warnings` avec 41 avertissements corrompus : 2 526 car. affichés, pas d'erreur ✔
- `/leaderboard`, `/userinfo` avec entrées DB corrompues ✔
- Tirage de giveaway avec entrées corrompues (nettoyées) ✔
- `on_user_update` : 0 faux positif, vrai changement détecté ✔
- Anti-spam : escalade + restauration après restart (rôle retiré, entrée purgée) ✔
- `parse_iso`, `_codepoint` (VS16 / ZWJ), `progress_bar(50, 0)`, `parse_duration` ✔

---

## ⚠️ Points de conception à trancher (pas des bugs techniques)

1. **`/warn` automatique** : 3 avertissements → *kick*, 5 → *ban*. Les
   avertissements ne sont **pas remis à zéro** après l'action : un membre banni
   qui revient est banni à nouveau dès 1 nouvel avertissement. À confirmer.
2. **`utils/settings.py`** n'est importé nulle part : les réglages par serveur
   (`overrides`) sont du code mort. Soit on le branche, soit on le supprime.
3. **`/level-rewards` et `/emojis`** n'ont pas de restriction de permission
   (volontaire ? `/emojis` est réservé aux admins, `/level-rewards` non).
4. **Intent privilégié `presences`** activé dans le code : il doit l'être aussi
   dans le portail développeur, sinon le bot refuse de démarrer (erreur 4014).
5. **Mode DB « salon Discord »** : un snapshot complet est réécrit à chaque flush
   (max 1 / 30 s) et l'ancien message est supprimé — pense à garder le salon propre.
