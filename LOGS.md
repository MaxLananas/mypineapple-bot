# 🕵️ Système de logs « Big Brother » — MyPineapple Bot

Surveillance complète du serveur : chaque événement part dans un salon dédié,
dans une catégorie **privée** que **seul le rôle d'accès aux logs** peut voir.

---

## 1. Installation (une seule commande)

```
/logssetup
```

La commande crée (si besoin) :

- une **catégorie `logs`** privée ;
- **18 salons** de logs, chacun avec ses permissions verrouillées.

Options :

| Option | Effet |
|--------|-------|
| `nom_categorie` | Nom de la catégorie (défaut : `logs`) |
| `recreer` | **Supprime** les salons de logs existants et les recrée proprement (l'historique des logs est perdu) |

> ⚠️ La commande est réservée au rôle d'accès aux logs (ou à un administrateur),
> et le bot doit avoir la permission **Gérer les salons**.

### Permissions appliquées

| Cible | Voir le salon | Écrire | Historique |
|-------|---------------|--------|------------|
| `@everyone` | ❌ | ❌ | ❌ |
| **Rôle de logs** (`LOG_ACCESS_ROLE_ID`) | ✅ | ❌ | ✅ |
| Le bot | ✅ | ✅ | ✅ |

Le rôle de logs est défini dans `config.py` :

```python
LOG_ACCESS_ROLE_ID = 1518719020084236378   # SEUL rôle autorisé à voir les logs
```

> ⚠️ **Limite Discord** : un membre portant la permission *Administrateur* voit
> **tous** les salons, quoi qu'on fasse. C'est impossible à contourner
> côté API : la seule solution est de ne donner *Administrateur* à personne.

---

## 2. Les 18 salons

| Salon | Ce qui est enregistré |
|-------|-----------------------|
| 📥・messages | **Tout** message envoyé : auteur, ID, salon, contenu, pièces jointes (vignettes), stickers, embeds, réponses |
| ✏️・éditions | Messages modifiés — **avant / après** (+ alimente `/editsnipe`) |
| 🗑️・suppressions | Messages supprimés (+ suppressions en masse, + alimente `/snipe`) |
| 👥・membres | Arrivées, départs (avec durée de séjour et rôles), changements de pseudo |
| 🖼️・profils | Avatar (**ancien + nouveau**), bannière (**avant / après**), bio, couleur d'accent, nom d'utilisateur / nom global |
| 🟢・statuts | Statut (en ligne / inactif / ne pas déranger / hors ligne), statut personnalisé, activité (jeu, stream, musique…) |
| 🚪・invitations | Création/suppression d'invitations + **d'où vient chaque nouveau membre** (code utilisé, parrain, utilisations, âge du compte) |
| ⌨️・commandes | Chaque slash-command utilisée : qui, où, quelles options, durée + commandes en erreur |
| 🔨・modération | Bans, débans, kicks, timeouts, avertissements, purges, slowmode, verrouillage de salon |
| 🎭・rôles | Création, suppression, modification ; rôles ajoutés/retirés à un membre ; **permissions sensibles** mises en évidence |
| 📺・salons | Création, suppression, renommage, sujet, slowmode, NSFW, **changements de permissions** |
| 🔊・vocal | Entrées, sorties (avec durée), changements de salon, mute/demute, sourdine, stream, caméra |
| ⚙️・serveur | Nom, icône, bannière, description, niveau de vérification, boosts, webhooks, émojis, stickers |
| 🧵・fils | Création, suppression, renommage, archivage, verrouillage des threads |
| 🚨・sécurité | Comptes de moins de 24 h (avec ping du rôle support), sanctions anti-spam |
| 🕵️・audit | **Journal d'audit Discord** : qui a fait quoi, sur qui, avec quelle raison |
| 📊・statistiques | Rapport automatique toutes les 6 h + tableau de bord `/logstats` |
| 🤖・bot | Démarrages, reconnexions, erreurs non gérées, installation des logs |

---

## 3. Commandes

| Commande | Description |
|----------|-------------|
| `/logssetup` | Installe / répare la catégorie et les 18 salons |
| `/logstats` | Tableau de bord : messages, éditions, suppressions, commandes, arrivées, départs, invitations, vocal, top salons, top membres, top parrains, tendance 7 jours |
| `/logtoggle` | Active/désactive un type de log (18 choix possibles) |

Toutes ces commandes sont **réservées au rôle de logs** (ou aux administrateurs).

---

## 4. Statistiques conservées

Compteurs journaliers (30 jours d'historique) :

- messages, éditions, suppressions, commandes (par membre et par salon) ;
- arrivées, départs, invitations ;
- secondes de vocal (du jour) ;
- actions de modération, alertes de sécurité.

Les compteurs sont stockés dans `db.config()["log_stats"]` → ils **survivent aux
redémarrages** (comme le reste de la base).

---

## 5. Mode de secours (sans `/logssetup`)

Tant que la commande n'a pas été lancée, chaque type de log part dans un
**thread** créé dans le salon `LOG_HUB_CHANNEL_ID` (comportement historique).
Aucun événement n'est perdu avant l'installation — mais les threads n'ont pas
les permissions verrouillées de la catégorie `logs`.

Ces threads sont **mémorisés** (en DB) et reconnus comme canaux de logs : le bot
ne reloggue donc jamais ses propres logs, même dans ce mode de secours
(c'était la cause de la boucle de spam).

---

## 6. Ce qu'il est **techniquement impossible** de capturer

- **La bio / le « à propos » des autres membres** : l'API Discord ne l'expose
  pas aux bots (elle n'est disponible que pour son propre compte). Le code la
  récupère si Discord la renvoie un jour (`/users/{id}` → puis
  `/guilds/{gid}/members/{uid}`), mais il ne faut pas compter dessus.
- **Les messages supprimés par un autre bot ou par Discord** : l'événement
  `on_message_delete` ne contient le contenu que si le message était en cache.
- **Les messages hors des salons où le bot n'a pas accès**.
- **Les messages supprimés *avant* l'arrivée du bot** (ou avant un redémarrage,
  tant que le cache est vide).

---

## 7. Anti-spam / anti-boucle (protections permanentes)

Le risque n°1 d'un système de logs, c'est de **logger ses propres logs** :
le message de log est un message → il est relogué → boucle infinie.
Quatre protections indépendantes empêchent ça :

1. **Reconnaissance totale des canaux de logs** — sont ignorés : les 18 salons,
   la catégorie `logs`, **tout thread dont le parent est un salon de logs ou le
   salon hub**, tout thread créé par le hub (mémorisé en DB), et tout salon rangé
   dans la catégorie `logs`. Un salon/thread de logs ne produit donc **jamais**
   de log, même si son ID a été perdu.
2. **Le bot ne logge jamais ses propres messages** (`message.author.id == bot.user.id`)
   pour les messages, éditions, suppressions et suppressions en masse.
   Les actions du bot ne polluent pas non plus le 🕵️・audit (elles sont déjà
   journalisées à la source par `/logssetup`, `mod_action`, etc.).
3. **Déduplication** : un contenu identique vers le même salon à moins de 3 s
   d'intervalle est ignoré — casse instantanément une boucle serrée.
4. **Coupe-circuit** : au-delà de **25 envois en 10 secondes** sur un serveur,
   l'écriture des logs est **suspendue 5 minutes** (erreur écrite dans les logs
   du bot) puis reprend automatiquement. Même un bug futur ne pourra pas
   transformer le bot en spammeur.

Pendant `/logssetup`, les logs sont mis **en pause** : la création/édition des
18 salons ne génère pas des dizaines de messages « salon créé / modifié ».

---

## 8. Technique

| Fichier | Rôle |
|---------|------|
| `utils/loghub.py` | Le hub : registre des 18 salons, permissions, résolution des salons, écriture des payloads (components v2), compteurs, toggles |
| `cogs/logs.py` | Les **30 listeners** Discord qui alimentent le hub + les commandes `/logssetup`, `/logstats`, `/logtoggle` |
| `cogs/moderation.py` | Appelle `loghub.mod_action()` après chaque sanction (le but n'est pas seulement passif) |
| `utils/antispam.py` | Journalise les sanctions anti-spam dans 🚨・sécurité |
| `cogs/invites.py` | Journalise la **source** de chaque arrivée dans 🚪・invitations |
| `main.py` | Annonce démarrages/reconnexions/erreurs dans 🤖・bot ; applique le mode « serveur uniquement » |

Les envois à fort volume (messages, éditions, suppressions) passent par la
**file d'attente** interne (`api_send_queued`) : le bot n'est jamais ralenti par
ses propres logs, et le rate-limit Discord est absorbé automatiquement.
