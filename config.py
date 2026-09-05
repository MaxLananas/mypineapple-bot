import os

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set.")

LOGO_URL       = "https://i.ibb.co/WWbL1v1k/7391989548e4747ad18756fa467b74da.webp"
DISCORD_INVITE = "https://discord.gg/pnJhKuU2QK"
INSTAGRAM_URL  = "https://www.instagram.com/maxlananas.builds/"
WEBSITE_URL    = "https://maxlananas.is-a.dev/"
YOUTUBE_URL    = "https://www.youtube.com/@MaxLanana"

TICKET_CATEGORY_ID    = 1518728726421180676
TICKET_LOG_CHANNEL_ID = 1525589088969822300
NO_XP_CHANNEL_ID      = 1525598251015868466
WELCOME_CHANNEL_ID    = 1518717925144526980
REVIEW_FORUM_ID       = 1540774649347186789
LOG_HUB_CHANNEL_ID    = 1521230854007951500

SUPPORT_ROLE_ID = 1186432110752448574
AUTOROLE_ID     = 1518723809082085588
CLIENT_ROLE_ID  = 1540771567938568303

REVIEW_TAG_5STARS     = 1540784140386050088
REVIEW_TAG_4STARS     = 1540785959140982845
REVIEW_TAG_3STARS     = 1540786007971070092
REVIEW_TAG_2STARS     = 1540786052371980319
REVIEW_TAG_1STAR      = 1540786083585982504
REVIEW_TAG_BUILD      = 1540786428466831460
REVIEW_TAG_PLUGIN     = 1540786610189107220
REVIEW_TAG_PARTNER    = 1540786675033047151
REVIEW_TAG_VERIFIED   = 1540786776866557963
REVIEW_TAG_FEATURED   = 1540786829740212376

LEVEL_ROLES: dict[int, int] = {
    10:  1525609032499466270,
    20:  1525609413556174970,
    30:  1525609578379608074,
    40:  1525611768507007127,
    50:  1525611938283913267,
    60:  1525612127421726791,
    70:  1525612488916467712,
    80:  1525612683854876713,
    90:  1525613027918090350,
    100: 1525613203990773830,
}

LEVEL_ROLE_NAMES: dict[int, str] = {
    10:  "🦀 Mr. Krabs",
    20:  "🐟 Nemo",
    30:  "🪼 Medusa",
    40:  "🐬 Flipper",
    50:  "🦑 Davy Jones",
    60:  "🐙 Ursula",
    70:  "🧜 Ariel",
    80:  "🌊 Aquaman",
    90:  "🐋 Moby Dick",
    100: "🍍 Pineapple Lord",
}

RELEASE_BASE = "https://github.com/MaxLananas/Asset-Portfolio/releases/download/images-v1/"

CREDITS: dict[str, dict] = {
    "bte":         {"label": "BuildTheEarth France", "url": None},
    "endorah":     {"label": "Endorah",              "url": "https://endorah.net/"},
    "fight4glory": {"label": "Fight4Glory",          "url": None},
    "mrbeast":     {"label": "MrBeast",              "url": "https://www.youtube.com/watch?v=qTMKHZelGAs"},
}

PORTFOLIO_FILES: list[dict] = [
    {"name": "2025-01-27_20.55.35.png",    "credit": None},
    {"name": "2025-04-13_12.19.39.png",    "credit": None},
    {"name": "2025-04-17_21.24.15.png",    "credit": None},
    {"name": "2025-04-17_21.24.28.png",    "credit": None},
    {"name": "2025-04-17_21.24.35.png",    "credit": None},
    {"name": "2025-04-27_15.00.38.png",    "credit": None},
    {"name": "2025-05-26_17.29.47.png",    "credit": None},
    {"name": "2025-06-04_15.53.50.png",    "credit": "bte"},
    {"name": "2025-06-10_19.05.39.png",    "credit": "bte"},
    {"name": "2025-06-10_19.09.43.png",    "credit": "bte"},
    {"name": "2025-06-13_11.07.58.png",    "credit": "bte"},
    {"name": "2025-06-30_21.09.22.png",    "credit": None},
    {"name": "2025-06-30_22.06.58.png",    "credit": None},
    {"name": "2025-07-09_19.07.32.png",    "credit": None},
    {"name": "2025-07-14_17.18.52.png",    "credit": None},
    {"name": "2025-07-14_17.21.46.png",    "credit": None},
    {"name": "2025-07-14_17.26.17.png",    "credit": None},
    {"name": "2025-07-15_13.03.23.png",    "credit": None},
    {"name": "2025-07-18_15.18.06.png",    "credit": None},
    {"name": "2025-07-19_22.41.22.png",    "credit": "endorah"},
    {"name": "2025-07-21_18.17.35.png",    "credit": None},
    {"name": "2025-09-13_19.31.36.png",    "credit": None},
    {"name": "2025-09-13_20.22.36.png",    "credit": None},
    {"name": "2025-09-18_13.23.02.png",    "credit": None},
    {"name": "2025-09-18_13.23.25.png",    "credit": None},
    {"name": "2025-09-18_13.23.41.png",    "credit": None},
    {"name": "2025-09-18_13.26.41.png",    "credit": None},
    {"name": "2025-09-18_13.27.22.png",    "credit": None},
    {"name": "2025-09-18_13.27.54.png",    "credit": None},
    {"name": "2025-09-18_13.31.06.png",    "credit": None},
    {"name": "2025-09-20_18.52.59.png",    "credit": "bte"},
    {"name": "2025-09-25_21.45.27.png",    "credit": None},
    {"name": "2025-10-19_13.50.46.png",    "credit": None},
    {"name": "2025-10-19_13.51.00.png",    "credit": None},
    {"name": "2025-10-19_13.51.24.png",    "credit": None},
    {"name": "2025-10-23_17.38.26.png",    "credit": None},
    {"name": "2025-10-23_17.38.40.png",    "credit": None},
    {"name": "2025-10-24_23.07.50.png",    "credit": None},
    {"name": "2025-10-25_01.04.04.png",    "credit": None},
    {"name": "2025-10-25_01.04.17.png",    "credit": None},
    {"name": "2025-10-25_02.01.55.png",    "credit": None},
    {"name": "2025-10-25_02.02.23.png",    "credit": None},
    {"name": "2025-10-27_17.32.34.png",    "credit": None},
    {"name": "2025-10-27_17.56.40.png",    "credit": None},
    {"name": "2025-10-27_17.56.53.png",    "credit": None},
    {"name": "2025-10-29_17.00.15.png",    "credit": "mrbeast"},
    {"name": "2025-10-29_17.47.57.png",    "credit": "mrbeast"},
    {"name": "2025-10-30_21.38.03.png",    "credit": None},
    {"name": "2025-10-31_17.24.05.png",    "credit": None},
    {"name": "2025-11-02_21.24.44.png",    "credit": None},
    {"name": "2025-11-02_21.24.53.png",    "credit": None},
    {"name": "2025-11-02_22.00.18.png",    "credit": None},
    {"name": "2025-11-16_14.56.40.png",    "credit": "mrbeast"},
    {"name": "2025-11-16_15.08.49.png",    "credit": "mrbeast"},
    {"name": "2025-11-22_11.02.49.png",    "credit": None},
    {"name": "2025-11-22_11.04.22.png",    "credit": None},
    {"name": "2025-12-09_18.58.54.png",    "credit": None},
    {"name": "2025-12-09_18.59.03.png",    "credit": None},
    {"name": "2025-12-24_13.51.44.png",    "credit": None},
    {"name": "2025-12-24_13.51.51.png",    "credit": None},
    {"name": "2026-01-03_01.34.48.png",    "credit": "bte"},
    {"name": "2026-01-03_01.35.07.png",    "credit": "bte"},
    {"name": "2026-01-03_01.35.57.png",    "credit": "bte"},
    {"name": "2026-01-03_01.37.11.png",    "credit": "bte"},
    {"name": "2026-04-01_21.07.14.png",    "credit": "bte"},
    {"name": "2026-04-01_21.07.28.png",    "credit": "bte"},
    {"name": "2026-05-30_15.23.36.png",    "credit": None},
    {"name": "2026-07-02_16.20.56.png",    "credit": None},
    {"name": "2026-07-06_21.59.15_4K.png", "credit": None},
    {"name": "2026-07-06_21.59.35_4K.png", "credit": "bte"},
    {"name": "chateau_loire.png",          "credit": "endorah"},
    {"name": "circuit24hdumans.jpg",       "credit": "bte"},
    {"name": "larresingle.jpg",            "credit": "bte"},
    {"name": "little-bridge.png",          "credit": "bte"},
    {"name": "maisonbois.png",             "credit": None},
    {"name": "Mt_Blanc_cut.png",           "credit": None},
    {"name": "Ocapiat-01.png",             "credit": "endorah"},
    {"name": "Parentis.png",               "credit": None},
    {"name": "pontneufv1.png",             "credit": None},
    {"name": "potfleur.png",               "credit": None},
    {"name": "sans_nom-2-1.jpg",           "credit": "bte"},
    {"name": "Shot_01.jpg",                "credit": "endorah"},
    {"name": "Shot_03.1.jpg",              "credit": "endorah"},
    {"name": "Shot_03.jpg",                "credit": "endorah"},
    {"name": "Shot_06.2.png",              "credit": "endorah"},
    {"name": "Slide_1.png",                "credit": "mrbeast"},
    {"name": "Slide_2.png",                "credit": "mrbeast"},
    {"name": "spawnfight4glory.jpg",       "credit": "fight4glory"},
    {"name": "Streaming-768x432.jpg",      "credit": "endorah"},
    {"name": "untitled-2.jpg",             "credit": "bte"},
    {"name": "untitled.jpg",               "credit": None},
    {"name": "untitled3-2.jpg",            "credit": "bte"},
    {"name": "untitled3.jpg",              "credit": None},
    {"name": "CIRCUITxDIRIGEABLE.jpg",    "credit": "bte"},
    {"name": "Larressingle.png",           "credit": "bte"},
    {"name": "Lemans_-_france5.jpg",       "credit": "bte"},
    {"name": "Lemans_-_large.png",         "credit": "bte"},
    {"name": "Occi.png",                   "credit": "bte"},
    {"name": "untitled11.jpg",             "credit": "bte"},
    {"name": "untitled13.jpg",             "credit": "bte"},
    {"name": "untitled18.jpg",             "credit": "bte"},
]