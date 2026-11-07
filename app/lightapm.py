"""
lightAPM : compteur d'APM léger (overlay + stats par jeu).

Lancement normal : lightAPM.exe à la racine du projet (installe les dépendances si besoin).
Lancement manuel : pythonw app/lightapm.py
Dépendances : pip install -r requirements.txt

Dossiers :
  app/          ce fichier (remplacé par les mises à jour)
  app/assets/   logo (light_1.png) et icônes générées automatiquement à partir du logo
  data/         tes réglages (config.json), tes stats (stats.json) et le journal d'erreurs

- L'overlay (chiffre seul, fond transparent) se place où tu veux : déverrouillé,
  clic gauche + glisser ; verrouillé, il est click-through.
- Onglet Stats : l'app au premier plan sur l'écran principal est détectée et les APM lui sont
  attribués. Une session se termine quand le jeu est fermé ou quitté depuis plus de N minutes :
  moyenne, peak (meilleure minute) et low (pire minute active) sont cumulés session après session.
- Onglet Options : tous les réglages, rangés par catégorie.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import subprocess
import threading
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from collections import deque
from tkinter import colorchooser

import customtkinter as ctk
from PIL import Image, ImageDraw
from pynput import keyboard, mouse

NOM = "lightAPM"
DOSSIER = os.path.dirname(os.path.abspath(__file__))  # app/
RACINE = os.path.dirname(DOSSIER)  # racine du projet (lightAPM.exe, README…)
ASSETS = os.path.join(DOSSIER, "assets")
DATA = os.path.join(RACINE, "data")  # données perso : jamais publiées sur GitHub
os.makedirs(DATA, exist_ok=True)
CONFIG = os.path.join(DATA, "config.json")
STATS = os.path.join(DATA, "stats.json")
LOG = os.path.join(DATA, "lightapm.log")
ICO = os.path.join(ASSETS, "lightapm_icon.ico")
TILE = os.path.join(ASSETS, "lightapm_tile.png")
LOGO = os.path.join(ASSETS, "lightapm_logo.png")
LANCEUR = os.path.join(RACINE, "lightAPM.exe")


def _langue_config():
    """Langue choisie (config.json), anglais par défaut."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            l = json.load(f).get("language", "en")
        return l if l in ("en", "fr") else "en"
    except Exception:
        return "en"


LANGUE = _langue_config()


def T(en, fr):
    """Texte dans la langue de l'app : T("English", "Français")."""
    return fr if LANGUE == "fr" else en

KEY = "#010101"  # couleur rendue transparente (overlay)
MIN_FENETRE = 30.0  # au lancement, on divise par au moins 30 s : pas de pic artificiel les premières secondes
MIN_MOY_LIVE = 60  # la moyenne d'une session en cours n'est affichée qu'après 1 min de jeu
MIN_SESSION = 60  # secondes au premier plan en dessous desquelles une session est ignorée
AFK_APM = 5  # minute sous ce seuil = AFK, ignorée pour le "low"
APP_ID = "kaio.lightapm"
WIN = sys.platform == "win32"
VERSION = "1.6.0"
# Mises à jour : URL d'un petit fichier JSON {"version": "1.5.0", "url": "<lien du .py>", "notes": [...]}
# (ex. sur GitHub : https://raw.githubusercontent.com/<toi>/lightAPM/main/version.json).
# Peut aussi être mise dans apm_counter.json, clé "update_url".
UPDATE_URL = "https://raw.githubusercontent.com/Kaiokrr/lightAPM/main/version.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOUVEAUTES = {  # version: {"en": [...], "fr": [...]}
    "1.6.0": {
        "en": ["lightAPM is now in English, with French available in Options > Appearance",
               "Language choice in the setup assistant"],
        "fr": ["lightAPM est maintenant en anglais, avec le français au choix dans Options > Apparence",
               "Choix de la langue dans l'assistant de configuration"],
    },
    "1.5.0": {
        "en": ["Options organized by category, with a sidebar",
               "Live overlay preview while you adjust it",
               "A single lightAPM.exe installs and launches everything",
               "Your settings and stats now live in the data/ folder"],
        "fr": ["Options rangées par catégorie, avec une barre latérale",
               "Aperçu de l'overlay en direct pendant que tu le règles",
               "Un seul lightAPM.exe pour tout installer et lancer",
               "Tes réglages et tes stats sont maintenant dans le dossier data/"],
    },
    "1.4.0": {
        "en": ["Setup assistant on first launch",
               "7 color themes, in Options > Appearance",
               "Automatic APM pause when you're AFK, resumes as soon as you play again",
               "Start with Windows (minimized to tray if you like)",
               "Update checks and a \"What's new\" screen",
               "The window keeps its size and position"],
        "fr": ["Écran de configuration au premier démarrage",
               "7 thèmes de couleur, au choix dans Options > Apparence",
               "Pause automatique des APM quand tu es AFK, reprise dès que tu rejoues",
               "Lancement avec Windows (réduit dans le tray si tu veux)",
               "Vérification des mises à jour et écran « Quoi de neuf »",
               "La fenêtre garde sa taille et sa position"],
    },
}

# Thèmes : fond noir minimaliste + une couleur d'accent (maquette Claude Design "lightAPM Redesign")
THEMES = {  # clé: (nom, accent, accent clair, accent foncé)
    "violet": ("Violet", "#a855f7", "#c084fc", "#7e22ce"),
    "glace": (T("Ice", "Glace"), "#22d3ee", "#67e8f9", "#0e7490"),
    "braise": (T("Ember", "Braise"), "#f43f5e", "#fb7185", "#be123c"),
    "neon": (T("Neon", "Néon"), "#22c55e", "#4ade80", "#15803d"),
    "ambre": (T("Amber", "Ambre"), "#f59e0b", "#fbbf24", "#b45309"),
    "sakura": ("Sakura", "#ec4899", "#f472b6", "#be185d"),
    "mono": ("Mono", "#d4d4d8", "#ffffff", "#71717a"),
}
ON_ACC = "#0b0712"  # texte posé sur l'accent
DANGER = "#f0a3b5"


def _mix(a, b, t):
    """Mélange deux couleurs hex : t = part de b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def appliquer_palette(cle):
    """Définit toutes les couleurs de l'interface à partir de l'accent du thème."""
    global BG, PANEL, FIELD, BORDER, BORDER2, TRACK, BAND, ACC, ACC_H, ACC_D, TXT, TXT2, MUTED, DIM
    _, ACC, ACC_H, ACC_D = THEMES.get(cle, THEMES["violet"])
    BG = _mix("#060609", ACC, 0.012)  # fond
    PANEL = _mix("#0c0c11", ACC, 0.022)  # cartes
    FIELD = _mix("#0c0c11", ACC, 0.06)  # carte mise en avant
    BORDER = _mix("#18181f", ACC, 0.06)  # bordure discrète
    BORDER2 = _mix("#1c1c25", ACC, 0.17)  # bordure accentuée
    TRACK = _mix("#141419", ACC, 0.06)  # rail des barres
    BAND = _mix("#0c0c11", ACC, 0.26)  # bande low→peak du graphe
    TXT = _mix("#f5f5f7", ACC, 0.04)
    TXT2 = _mix("#c8c7cf", ACC, 0.08)
    MUTED = _mix("#8b8a97", ACC, 0.1)
    DIM = _mix("#6c6b78", ACC, 0.1)


appliquer_palette("violet")
CATEGORIES = (("jeux", T("Games", "Jeux")), ("apps", "Apps"))
NAVIGATEURS = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "arc.exe",
               "zen.exe", "librewolf.exe", "waterfox.exe", "iexplore.exe", "thorium.exe", "floorp.exe"}
LANCEURS = {"steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "riotclientux.exe",
            "riotclientservices.exe", "battle.net.exe", "galaxyclient.exe", "eadesktop.exe", "upc.exe",
            "ubisoftconnect.exe", "xboxpcapp.exe", "playnite.desktopapp.exe"}
DOSSIERS_JEUX = ("steamapps", "riot games", "epic games", "\\games\\", "gog galaxy", "ubisoft game launcher",
                 "ea games", "xboxgames", "battle.net", "blizzard", "-shipping.exe", "roblox", "minecraft",
                 "overwatch", "\\game\\", "\\jeux\\")

DEFAUT = {
    "x": 30, "y": 30, "placed": False,
    "size": 22, "font": "Consolas", "bold": True,
    "color": "#c084fc", "outline_on": True, "outline_color": "#000000",
    "opacity": 0.7, "suffix": "",
    "window": 60, "refresh": 100,
    "count_keys": True, "count_clicks": True, "count_scroll": True,
    "hk_lock": "f8", "hk_toggle": "f9",
    "start_locked": True, "tray_on_minimize": True,
    "logo_path": "",
    "track_apps": True, "session_gap": 5, "session_popup": True,
    "afk_delay": 10,
    "theme": "violet", "setup_done": False, "win_geom": "", "last_version": "",
    "autostart": False, "start_minimized": True, "overlay_on_start": True,
    "check_updates": True, "update_url": "",
    "language": "en",
}


def log_err(*exc):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(*exc)) + "\n")
    except Exception:
        pass


def charger():
    c = dict(DEFAUT)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if k in DEFAUT and type(v) is type(DEFAUT[k]):
                    c[k] = v
    except Exception:
        pass
    return c


DEJA_INSTALLE = os.path.exists(CONFIG)  # pour afficher "Quoi de neuf" aux anciens utilisateurs
cfg = charger()
appliquer_palette(cfg["theme"])
AUTOSTART_LANCE = "--autostart" in sys.argv  # lancé par Windows au démarrage du PC

# ---------- Logo / icônes ----------
def trouver_logo():
    for n in ("logo.png", "light_1.png"):
        p = os.path.join(ASSETS, n)
        if os.path.exists(p):
            return p
    return None


def _recadrer(im, marge):
    """Carré centré sur le motif lumineux, agrandi de `marge`."""
    bb = im.convert("L").point(lambda p: 255 if p > 50 else 0).getbbox() or (0, 0) + im.size
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    cote = min(max(bb[2] - bb[0], bb[3] - bb[1]) * marge, min(im.size))
    x0 = max(0, min(im.width - cote, cx - cote / 2))
    y0 = max(0, min(im.height - cote, cy - cote / 2))
    return im.crop((int(x0), int(y0), int(x0 + cote), int(y0 + cote)))


def build_assets(src):
    im = Image.open(src).convert("RGB")
    # tuile arrondie (icône fenêtre + tray)
    tile = _recadrer(im, 1.5).resize((256, 256), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 255, 255), radius=56, fill=255)
    tile.putalpha(mask)
    tile.save(TILE)
    tile.save(ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
              bitmap_format="bmp")
    # logo à fond transparent (en-tête) : alpha = luminosité du pixel
    petit = _recadrer(im, 1.15).resize((160, 160), Image.LANCZOS)
    px = petit.load()
    out = Image.new("RGBA", petit.size)
    o = out.load()
    for y in range(petit.height):
        for x in range(petit.width):
            r, g, b = px[x, y]
            a = max(r, g, b)
            if a < 6:
                o[x, y] = (0, 0, 0, 0)
            else:
                k = 255 / a
                o[x, y] = (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)), a)
    out.save(LOGO)


MARQUEUR = os.path.join(DATA, "icones.src")  # signature du logo ayant servi à générer les icônes
LOGO_ERR = [""]


def preparer_assets():
    """Génère les icônes depuis l'image source (si elle a changé). Renvoie True si un logo est dispo."""
    LOGO_ERR[0] = ""
    src = trouver_logo()
    if not src:
        return False
    try:
        sig = f"v2|{src}|{os.path.getmtime(src)}"
        ok = all(os.path.exists(p) for p in (ICO, TILE, LOGO))
        if ok:
            try:
                with open(MARQUEUR, encoding="utf-8") as f:
                    ok = f.read() == sig
            except OSError:
                ok = False
        if not ok:
            build_assets(src)
            with open(MARQUEUR, "w", encoding="utf-8") as f:
                f.write(sig)
        return True
    except Exception as e:
        LOGO_ERR[0] = str(e)
        log_err(*sys.exc_info())
        return False


def image_defaut(taille=160):
    im = Image.new("RGBA", (taille, taille), (0, 0, 0, 0))
    m = taille // 6
    ImageDraw.Draw(im).ellipse((m, m, taille - m, taille - m), fill=ACC)
    return im


HAS_LOGO = preparer_assets()

# ---------- Capture des inputs ----------
events = deque()
pressed = set()
actions = deque()  # demandes venant des threads pynput/pystray, traitées par le thread tk
capture = {"target": None}
compteur = [0]  # total des actions comptées (lu par le suivi par app)


verrou = threading.Lock()
derniere_act = [time.time()]  # dernier input (y compris mouvement de souris)
debut = time.time()


def est_afk(now=None):
    return (now or time.time()) - derniere_act[0] > cfg["afk_delay"]


def activite():
    """Appelé à chaque input. En revenant d'AFK, on décale l'historique de la durée de la pause :
    les APM reprennent exactement où ils s'étaient figés, comme si la pause n'avait pas existé."""
    global debut
    t = time.time()
    if t - derniere_act[0] > cfg["afk_delay"]:
        gap = t - derniere_act[0] - cfg["afk_delay"]
        with verrou:
            decale = [e + gap for e in events]
            events.clear()
            events.extend(decale)
            debut += gap
    derniere_act[0] = t


def compter():
    with verrou:
        events.append(time.time())
    compteur[0] += 1


def key_to_str(k):
    if isinstance(k, keyboard.Key):
        return k.name
    c = getattr(k, "char", None)
    return c.lower() if c else f"vk{getattr(k, 'vk', None)}"


def on_press(key):
    activite()
    if key in pressed:  # auto-repeat -> ignoré
        return
    pressed.add(key)
    s = key_to_str(key)
    if capture["target"]:
        actions.append(("captured", capture["target"], s))
        capture["target"] = None
        return
    if s == cfg["hk_lock"]:
        actions.append(("lock",))
        return
    if s == cfg["hk_toggle"]:
        actions.append(("toggle",))
        return
    if cfg["count_keys"]:
        compter()


def on_release(key):
    pressed.discard(key)


def on_click(x, y, button, down):
    activite()
    if down and cfg["count_clicks"]:
        compter()


def on_scroll(x, y, dx, dy):
    activite()
    if cfg["count_scroll"]:
        compter()


keyboard.Listener(on_press=on_press, on_release=on_release, daemon=True).start()
mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=lambda x, y: activite(), daemon=True).start()

# ---------- App au premier plan (écran principal) ----------
# Fenêtres du système qu'on ne compte pas comme une "app" (bureau, barre des tâches, menu…)
IGNORER = {"explorer.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
           "shellexperiencehost.exe", "lockapp.exe", "textinputhost.exe", "applicationframehost.exe",
           "systemsettings.exe", "screenclippinghost.exe", "snippingtool.exe"}

if WIN:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ver = ctypes.WinDLL("version")
    _u32.GetForegroundWindow.restype = wt.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _u32.MonitorFromWindow.restype = wt.HANDLE
    _u32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    _u32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.c_void_p]
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    _k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _ver.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.c_void_p]
    _ver.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    _ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(ctypes.c_uint)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def chemin_process(pid):
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        return buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
    finally:
        _k32.CloseHandle(h)


def process_vivant(pid):
    h = _k32.OpenProcess(0x1000, False, pid)
    if not h:
        return ctypes.get_last_error() == 5  # accès refusé (anti-cheat…) = il tourne encore
    try:
        code = wt.DWORD()
        return not _k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
    finally:
        _k32.CloseHandle(h)


def nom_lisible(path):
    """Nom affiché : description du .exe (ex. "VALORANT"), sinon nom du fichier."""
    try:
        taille = _ver.GetFileVersionInfoSizeW(path, None)
        if taille:
            data = ctypes.create_string_buffer(taille)
            if _ver.GetFileVersionInfoW(path, 0, taille, data):
                p, n = ctypes.c_void_p(), ctypes.c_uint()
                langs = []
                if _ver.VerQueryValueW(data, r"\VarFileInfo\Translation", ctypes.byref(p), ctypes.byref(n)) \
                        and n.value >= 4:
                    w = ctypes.cast(p, ctypes.POINTER(ctypes.c_ushort))
                    langs.append(f"{w[0]:04x}{w[1]:04x}")
                langs += ["040904b0", "040904e4", "000004b0"]
                for champ in ("FileDescription", "ProductName"):
                    for lc in langs:
                        if _ver.VerQueryValueW(data, f"\\StringFileInfo\\{lc}\\{champ}", ctypes.byref(p),
                                               ctypes.byref(n)) and n.value:
                            s = ctypes.wstring_at(p.value, n.value).strip("\x00 ").strip()
                            if s:
                                return s[:40]
    except Exception:
        log_err(*sys.exc_info())
    return os.path.splitext(os.path.basename(path))[0]


def app_premier_plan():
    """(exe, chemin, pid) de l'app au premier plan si elle est sur l'écran principal, sinon None."""
    hwnd = _u32.GetForegroundWindow()
    if not hwnd:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    mon = _u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    if not mon or not _u32.GetMonitorInfoW(mon, ctypes.byref(mi)) or not (mi.dwFlags & 1):
        return None  # pas sur l'écran principal
    pid = wt.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in (0, os.getpid()):
        return None
    path = chemin_process(pid.value)
    if not path:
        return None
    exe = os.path.basename(path).lower()
    if exe in IGNORER or exe in NAVIGATEURS:  # navigateurs : jamais comptés dans les stats
        return None
    r = wt.RECT()
    m = mi.rcMonitor
    plein = bool(_u32.GetWindowRect(hwnd, ctypes.byref(r))) and r.left <= m.left and r.top <= m.top \
        and r.right >= m.right and r.bottom >= m.bottom
    return exe, path, pid.value, plein


def deviner_categorie(exe, path="", plein_ecran=False):
    """Jeux ou Apps, deviné au premier lancement (modifiable dans le détail)."""
    if exe in LANCEURS:
        return "apps"
    p = (path or "").lower()
    if plein_ecran or any(d in p for d in DOSSIERS_JEUX):
        return "jeux"
    return "apps"


# ---------- Stats par app ----------
def charger_stats():
    try:
        with open(STATS, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d.get("apps"), dict):
            for exe in [e for e in d["apps"] if e in NAVIGATEURS]:  # navigateurs : plus suivis
                del d["apps"][exe]
            for exe, a in d["apps"].items():
                for x in a.get("sessions", []):  # anciennes sessions : peak >= moyenne >= low
                    x["peak"] = max(x["peak"], x["avg"])
                    x["low"] = min(x["low"], x["avg"])
                if a.get("cat") not in dict(CATEGORIES):
                    a["cat"] = deviner_categorie(exe, a.get("path", ""))
            return d
    except Exception:
        pass
    return {"apps": {}}


stats = charger_stats()


class Session:
    def __init__(self, exe, pid):
        self.exe, self.pid = exe, pid
        self.debut = self.vu = time.time()
        self.duree = 0.0  # secondes passées au premier plan
        self.actions = 0
        self.minutes = []  # APM de chaque minute complète au premier plan
        self.min_t, self.min_n = 0.0, 0

    def ajouter(self, dt, n):
        self.duree += dt
        self.actions += n
        self.min_t += dt
        self.min_n += n
        if self.min_t >= 60:
            self.minutes.append(self.min_n * 60 / self.min_t)
            self.min_t, self.min_n = 0.0, 0

    def resume(self):
        mins = list(self.minutes)
        # Peak et low : uniquement des minutes complètes de jeu. Une minute incomplète (ex. 20 s à la fin)
        # extrapolée à 60 s fausserait le peak ; elle compte quand même dans la moyenne (actions / temps).
        avg = self.actions * 60 / self.duree if self.duree else 0
        actives = [m for m in mins if m >= AFK_APM]
        return {"start": round(self.debut), "end": round(self.vu), "duration": round(self.duree),
                "actions": self.actions, "avg": round(avg),
                "peak": round(max(mins + [avg])),  # jamais sous la moyenne
                "low": round(min(min(actives), avg)) if actives else 0}


suivi = {"ouvertes": {}, "actuel": None, "t": time.time(), "vu": 0, "save": time.time()}


def snapshot_stats():
    """Stats sur disque = sessions terminées + sessions en cours (en cas de crash, rien n'est perdu)."""
    out = {"apps": {}}
    for exe, a in stats["apps"].items():
        ss = list(a["sessions"])
        s = suivi["ouvertes"].get(exe)
        if s and s.duree >= MIN_SESSION:
            ss.append(s.resume())
        out["apps"][exe] = dict(a, sessions=ss)
    return out


def sauver_stats():
    suivi["save"] = time.time()
    try:
        tmp = STATS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot_stats(), f, indent=1, ensure_ascii=False)
        os.replace(tmp, STATS)
    except Exception:
        log_err(*sys.exc_info())


def agreger(a):
    ss = a["sessions"]
    t = sum(s["duration"] for s in ss)
    n = sum(s["actions"] for s in ss)
    lows = [s["low"] for s in ss if s["low"] > 0]
    der5 = ss[-5:]
    t5 = sum(s["duration"] for s in der5)
    return {
        "n": len(ss), "temps": t,
        "avg": round(n * 60 / t) if t else 0,
        "avg5": round(sum(s["actions"] for s in der5) * 60 / t5) if t5 else 0,
        "peak_max": max((s["peak"] for s in ss), default=0),
        "peak_moy": round(sum(s["peak"] for s in ss) / len(ss)) if ss else 0,
        "low_moy": round(sum(lows) / len(lows)) if lows else 0,
    }


def fmt_duree(sec):
    m = int(sec // 60)
    if m < 1:
        return "<1 min"
    return f"{m} min" if m < 60 else (f"{m // 60}h{m % 60:02d}" if LANGUE == "en" else f"{m // 60} h {m % 60:02d}")


def fmt_chrono(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_date(ts):
    return time.strftime(T("%m/%d %H:%M", "%d/%m %H:%M"), time.localtime(ts))


# ---------- Thème violet ----------
def appliquer_theme():
    T = ctk.ThemeManager.theme

    def S(widget, **kv):
        for k, v in kv.items():
            if widget in T and k in T[widget]:
                T[widget][k] = [v, v]

    S("CTk", fg_color=BG)
    S("CTkToplevel", fg_color=BG)
    S("CTkFrame", fg_color=PANEL, top_fg_color=PANEL, border_color=BORDER)
    S("CTkLabel", text_color=TXT)
    S("CTkButton", fg_color=ACC, hover_color=ACC_H, border_color=BORDER2, text_color=ON_ACC)
    S("CTkEntry", fg_color=PANEL, border_color=BORDER2, text_color=TXT)
    S("CTkCheckBox", fg_color=ACC, hover_color=ACC_H, border_color=MUTED, checkmark_color="#ffffff",
      text_color=TXT2)
    S("CTkSwitch", fg_color=TRACK, progress_color=ACC, button_color="#e9ddff",
      button_hover_color="#ffffff", text_color=TXT)
    S("CTkSlider", fg_color=TRACK, progress_color=ACC, button_color=ACC_H, button_hover_color="#ffffff")
    S("CTkComboBox", fg_color=PANEL, border_color=BORDER2, button_color=BORDER2, button_hover_color=ACC_D,
      text_color=TXT)
    S("CTkOptionMenu", fg_color=PANEL, button_color=PANEL, button_hover_color=TRACK, text_color=ACC_H)
    S("DropdownMenu", fg_color=FIELD, hover_color=ACC_D, text_color=TXT)
    S("CTkScrollbar", button_color=BORDER2, button_hover_color=ACC_D)
    S("CTkSegmentedButton", fg_color=FIELD, selected_color=ACC, selected_hover_color=ACC_H,
      unselected_color=FIELD, unselected_hover_color=TRACK, text_color=TXT)


if WIN:  # sinon Windows regroupe la fenêtre sous l'icône de Python
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")
appliquer_theme()

# ---------- Une seule instance ----------
APPEL = os.path.join(DATA, "afficher.flag")  # un 2e lancement demande à l'instance ouverte de se montrer


def instance_unique():
    """Empêche deux lightAPM en même temps (deux overlays, APM comptés deux fois).
    Après un redémarrage (--restart), on attend que l'ancienne instance se ferme."""
    if not WIN:
        return
    limite = time.time() + (8 if "--restart" in sys.argv else 0)
    while True:
        h = _k32.CreateMutexW(None, False, r"Local\lightAPM_instance")
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            globals()["_MUTEX"] = h  # gardé ouvert tant que l'app tourne
            return
        _k32.CloseHandle(h)
        if time.time() > limite:
            try:
                open(APPEL, "w").close()
            except OSError:
                pass
            sys.exit(0)
        time.sleep(0.25)


if WIN:
    _k32.CreateMutexW.restype = wt.HANDLE
    _k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
instance_unique()

# ---------- Fenêtre principale + overlay ----------
root = ctk.CTk()
root.title(NOM)
root.geometry("720x820")


def restaurer_geometrie():
    """Reprend la taille/position de la dernière fois, si elle tient encore à l'écran."""
    m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", cfg["win_geom"])
    if not m:
        return
    w, h, x, y = map(int, m.groups())
    if WIN:
        u = ctypes.windll.user32
        vx, vy, vw, vh = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))  # écran virtuel
        if not (vx - 50 <= x <= vx + vw - 100 and vy - 10 <= y <= vy + vh - 100):
            root.geometry(f"{w}x{h}")
            return
    root.geometry(f"{w}x{h}+{x}+{y}")


restaurer_geometrie()
root.resizable(True, True)
root.minsize(660, 580)
root.report_callback_exception = log_err


def set_icon():
    """Icône de la fenêtre + barre des tâches. Plusieurs méthodes en cascade, car Tk et
    customtkinter n'en acceptent pas toujours une seule (version, format du .ico...)."""
    try:
        root.iconbitmap(ICO)
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=TILE)
        root.iconphoto(True, img)
        root._icone = img  # garder une référence
    except Exception:
        log_err(*sys.exc_info())
    if WIN:  # dernier recours : message Windows direct, qui force l'icône de la barre des tâches
        try:
            u = ctypes.WinDLL("user32")
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.GetParent.restype = ctypes.c_void_p
            u.GetParent.argtypes = [ctypes.c_void_p]
            u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
            hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
            for metrique, grande in ((11, 1), (49, 0)):  # SM_CXICON / SM_CXSMICON
                t = u.GetSystemMetrics(metrique)
                h = u.LoadImageW(None, ICO, 1, t, t, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    u.SendMessageW(hwnd, 0x80, grande, h)  # WM_SETICON
            identite_fenetre(hwnd)
        except Exception:
            log_err(*sys.exc_info())


def pythonw_exe():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    if "\\program files\\windowsapps\\" in exe.lower():  # dossier du Store, non lançable directement
        import shutil
        exe = shutil.which("pythonw") or "pythonw.exe"
    return exe


def commande_lancement():
    if os.path.exists(LANCEUR):  # le lanceur vérifie aussi les dépendances
        return f'"{LANCEUR}"'
    return f'"{pythonw_exe()}" "{os.path.abspath(__file__)}"'


def regler_autostart(actif):
    """Lancer lightAPM avec Windows (clé Run de l'utilisateur, sans droits admin)."""
    if not WIN:
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if actif:
                winreg.SetValueEx(k, NOM, 0, winreg.REG_SZ, commande_lancement() + " --autostart")
            else:
                try:
                    winreg.DeleteValue(k, NOM)
                except FileNotFoundError:
                    pass
    except OSError:
        log_err(*sys.exc_info())


def redemarrer():
    """Relance l'app (thème changé, mise à jour installée, assistant relancé)."""
    subprocess.Popen([pythonw_exe(), os.path.abspath(__file__), "--restart"], cwd=DOSSIER, close_fds=True)
    quitter()


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


def verifier_maj(manuel=False):
    """Vérifie en arrière-plan ; le résultat revient au thread tk via `actions`."""
    url = cfg["update_url"] or UPDATE_URL

    def job():
        if not url:
            actions.append(("maj", None, T("Update source not configured.", "Source des mises à jour non configurée."), manuel))
            return
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": f"{NOM}/{VERSION}"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            nouvelle = version_tuple(data["version"]) > version_tuple(VERSION)
            actions.append(("maj", data if nouvelle else False, None, manuel))
        except Exception as e:
            actions.append(("maj", None, T(f"Could not check ({e.__class__.__name__}).", f"Vérification impossible ({e.__class__.__name__})."), manuel))

    threading.Thread(target=job, daemon=True).start()


def installer_maj(data):
    """Télécharge la nouvelle version, vérifie qu'elle est valide, garde une copie .bak puis relance."""
    def job():
        try:
            import hashlib
            import urllib.request
            req = urllib.request.Request(data["url"], headers={"User-Agent": f"{NOM}/{VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                brut = r.read()
            if data.get("sha256") and hashlib.sha256(brut).hexdigest() != data["sha256"].lower():
                raise ValueError(T("sha256 mismatch", "empreinte sha256 différente"))
            compile(brut.decode("utf-8"), "lightapm.py", "exec")  # refuse un fichier cassé
            moi = os.path.abspath(__file__)
            with open(moi, "rb") as f, open(moi + ".bak", "wb") as b:
                b.write(f.read())
            with open(moi + ".new", "wb") as f:
                f.write(brut)
            os.replace(moi + ".new", moi)
            actions.append(("maj_ok",))
        except Exception as e:
            log_err(*sys.exc_info())
            actions.append(("maj_err", T(f"Update failed ({e})", f"Échec de la mise à jour ({e})")))

    threading.Thread(target=job, daemon=True).start()


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def de(cls, s):
        import uuid
        g = cls()
        ctypes.memmove(ctypes.addressof(g), uuid.UUID(s).bytes_le, 16)
        return g


class _PROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


def identite_fenetre(hwnd):
    """Donne à la fenêtre sa propre identité dans la barre des tâches. Indispensable avec le Python
    du Microsoft Store : sans ça, Windows affiche l'icône de Python au lieu du logo. Permet aussi
    d'épingler lightAPM (clic droit > Épingler) avec le bon logo et la bonne commande."""
    try:
        ctypes.OleDLL("ole32").CoInitialize(None)
    except OSError:
        pass
    ps = ctypes.c_void_p()
    ctypes.OleDLL("shell32").SHGetPropertyStoreForWindow(
        ctypes.c_void_p(hwnd), ctypes.byref(_GUID.de("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")), ctypes.byref(ps))
    vt = ctypes.cast(ctypes.cast(ps, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PROPKEY),
                                   ctypes.POINTER(_PROPVARIANT))(vt[6])
    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vt[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
    bufs = []
    try:
        # 2 RelaunchCommand, 4 RelaunchDisplayName, 3 RelaunchIcon, puis 5 AppUserModel ID
        for pid, val in ((2, commande_lancement()), (4, NOM), (3, ICO + ",0"), (5, APP_ID)):
            b = ctypes.create_unicode_buffer(val)
            bufs.append(b)
            v = _PROPVARIANT(31, 0, 0, 0, ctypes.cast(b, ctypes.c_void_p), None)  # VT_LPWSTR
            set_value(ps, ctypes.byref(_PROPKEY(_GUID.de("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid)),
                      ctypes.byref(v))
        commit(ps)
    finally:
        release(ps)


if HAS_LOGO:  # customtkinter remet son icône ~200 ms après l'ouverture : on réapplique après
    root.after(400, set_icon)
    root.after(1200, set_icon)

lock_txt = tk.StringVar()
locked = False
overlay_visible = True

ov = tk.Toplevel(root)
ov.overrideredirect(True)
ov.attributes("-topmost", True)
ov.configure(bg=KEY)
if WIN:
    ov.attributes("-transparentcolor", KEY)

canvas = tk.Canvas(ov, width=10, height=10, bg=KEY, highlightthickness=0)
canvas.pack()
cadre = canvas.create_rectangle(0, 0, 0, 0, fill=KEY, outline=KEY, width=2)
OFFS = ((-1, 0), (1, 0), (0, -1), (0, 1))
ombres = [canvas.create_text(0, 0, text="0") for _ in OFFS]
texte = canvas.create_text(0, 0, text="0")


def restyle():
    try:
        police = tkfont.Font(family=cfg["font"], size=cfg["size"],
                             weight="bold" if cfg["bold"] else "normal")
    except tk.TclError:
        return
    w = police.measure("0000" + cfg["suffix"]) + 24
    h = police.metrics("linespace") + 14
    canvas.config(width=w, height=h)
    canvas.coords(cadre, 1, 1, w - 1, h - 1)
    for it, (dx, dy) in zip(ombres, OFFS):
        canvas.coords(it, w // 2 + dx, h // 2 + dy)
        canvas.itemconfig(it, font=police, fill=cfg["outline_color"],
                          state="normal" if cfg["outline_on"] else "hidden")
    canvas.coords(texte, w // 2, h // 2)
    canvas.itemconfig(texte, font=police, fill=cfg["color"])
    ov.attributes("-alpha", cfg["opacity"])
    for f in APRES_RESTYLE:
        f()


APRES_RESTYLE = []  # ex. l'aperçu de l'overlay dans Options


def click_through(actif):
    if not WIN:
        return
    ov.update_idletasks()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(ov.winfo_id()) or ov.winfo_id()
    style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    style |= 0x80000  # WS_EX_LAYERED
    style = (style | 0x20) if actif else (style & ~0x20)  # WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, -20, style)


def save():
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


_job = [None]


def save_later():
    if _job[0]:
        root.after_cancel(_job[0])
    _job[0] = root.after(500, save)


def set_lock(etat):
    global locked
    locked = etat
    if etat:
        canvas.itemconfig(cadre, fill=KEY, outline=KEY)
        cfg["placed"] = True
        save()
    else:
        canvas.itemconfig(cadre, fill="#1d1330", outline=ACC)
    click_through(etat)
    lock_txt.set(T("Unlock overlay", "Déverrouiller l'overlay") if etat else T("Lock overlay", "Verrouiller l'overlay"))


def toggle_overlay():
    global overlay_visible
    overlay_visible = not overlay_visible
    if overlay_visible:
        ov.deiconify()
        ov.attributes("-topmost", True)
        click_through(locked)
    else:
        save()
        ov.withdraw()


_drag = {}


def start_drag(e):
    # point de départ : souris (coordonnées écran) et position mémorisée de l'overlay
    _drag.update(mx=e.x_root, my=e.y_root, wx=cfg["x"], wy=cfg["y"])


def do_drag(e):
    if not locked and "mx" in _drag:
        cfg["x"] = _drag["wx"] + e.x_root - _drag["mx"]
        cfg["y"] = _drag["wy"] + e.y_root - _drag["my"]
        ov.geometry(f"+{cfg['x']}+{cfg['y']}")


def fin_drag(e):
    """Overlay lâché : sa position est enregistrée tout de suite (survit à un arrêt brutal du PC)."""
    if not locked and "mx" in _drag:
        cfg["placed"] = True
        _drag.clear()
        save()


canvas.bind("<Button-1>", start_drag)
canvas.bind("<B1-Motion>", do_drag)
canvas.bind("<ButtonRelease-1>", fin_drag)

# ---------- Tray (chargé seulement quand on réduit) ----------
tray = {"icon": None, "dispo": True}


def to_tray():
    if tray["icon"] or not tray["dispo"]:
        return
    try:
        import pystray
    except ImportError:
        tray["dispo"] = False
        root.iconify()
        return
    try:
        img = Image.open(TILE).convert("RGBA").resize((64, 64), Image.LANCZOS)
    except Exception:
        img = image_defaut(64)

    def push(*a):
        return lambda icon, item: actions.append(a)

    menu = pystray.Menu(
        pystray.MenuItem(T("Open", "Ouvrir"), push("open"), default=True),
        pystray.MenuItem(T("Lock / unlock overlay", "Verrouiller / déverrouiller"), push("lock")),
        pystray.MenuItem(T("Show / hide overlay", "Afficher / masquer l'overlay"), push("toggle")),
        pystray.MenuItem(T("Quit", "Quitter"), push("quit")),
    )
    icon = pystray.Icon("lightapm", img, NOM, menu)
    tray["icon"] = icon
    root.withdraw()
    icon.run_detached()


def from_tray():
    ic = tray["icon"]
    tray["icon"] = None
    if ic:
        ic.stop()
    root.deiconify()
    root.lift()
    if HAS_LOGO:
        root.after(100, set_icon)


def on_unmap(e):
    if e.widget is root and cfg["tray_on_minimize"] and root.state() == "iconic":
        root.after(0, to_tray)


root.bind("<Unmap>", on_unmap)


def quitter():
    if cfg["setup_done"] and root.state() == "normal":
        cfg["win_geom"] = root.geometry()
    save()
    for s in list(suivi["ouvertes"].values()):
        fermer_session(s, popup=False)
    sauver_stats()
    if tray["icon"]:
        try:
            tray["icon"].stop()
        except Exception:
            pass
    root.destroy()


root.protocol("WM_DELETE_WINDOW", quitter)


def extinction_windows():
    """Windows s'éteint ou ferme la session : on enregistre tout avant d'être coupé."""
    if cfg["setup_done"] and root.state() == "normal":
        cfg["win_geom"] = root.geometry()
    save()
    sauver_stats()


root.protocol("WM_SAVE_YOURSELF", extinction_windows)

# ---------- UI ----------
loading = False
CW = 190  # largeur commune des contrôles : tout s'aligne à droite
PAD = 18  # marge extérieure commune

_FAMILLES = {f.lower() for f in tkfont.families()}
F_UI = next((f for f in ("Segoe UI", "Inter") if f.lower() in _FAMILLES), "TkDefaultFont")
F_MONO = next((f for f in ("JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas")
               if f.lower() in _FAMILLES), "Courier New")
SC = ctk.ScalingTracker.get_widget_scaling(root)  # pour dessiner aux bonnes dimensions sur les Canvas


def police(size, bold=False, mono=False):
    return ctk.CTkFont(family=F_MONO if mono else F_UI, size=size, weight="bold" if bold else "normal")


def legende(parent, txt, **kw):
    """Petit titre de section : majuscules, gris."""
    return ctk.CTkLabel(parent, text=txt.upper(), text_color=MUTED, font=police(11, True), anchor="w", **kw)


# ---------- Boîtes de dialogue ----------
def boite(titre, sous_titre="", lignes=(), boutons=(("OK", None, True),), largeur=400):
    """Dialogue minimaliste centré sur l'app. boutons = (texte, action(w) ou None pour fermer, principal)."""
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg=BORDER2)
    f = ctk.CTkFrame(w, corner_radius=0, fg_color=PANEL, width=largeur)
    f.pack(padx=1, pady=1)
    wrap = largeur - 44
    ctk.CTkLabel(f, text=titre, font=police(17, True), anchor="w", justify="left", wraplength=wrap).pack(
        fill="x", padx=22, pady=(20, 0))
    if sous_titre:
        ctk.CTkLabel(f, text=sous_titre, font=police(12), text_color=MUTED, anchor="w", justify="left",
                     wraplength=wrap).pack(fill="x", padx=22, pady=(2, 0))
    if lignes:
        liste = ctk.CTkFrame(f, fg_color=BG, corner_radius=10, border_width=1, border_color=BORDER)
        liste.pack(fill="x", padx=22, pady=(14, 0))
        for l in lignes:
            r = ctk.CTkFrame(liste, fg_color="transparent", corner_radius=0)
            r.pack(fill="x", padx=14, pady=(8, 0))
            ctk.CTkLabel(r, text="●", font=police(8), text_color=ACC, width=12, height=18).pack(side="left",
                                                                                              anchor="n")
            ctk.CTkLabel(r, text=l, font=police(12), text_color=TXT2, anchor="w", justify="left",
                         wraplength=wrap - 60).pack(side="left", fill="x", padx=(6, 0))
        ctk.CTkFrame(liste, fg_color="transparent", height=10, corner_radius=0).pack()
    w.statut = ctk.CTkLabel(f, text="", font=police(12), text_color=MUTED, anchor="w", height=16)
    w.statut.pack(fill="x", padx=22, pady=(10, 0))
    bas = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
    bas.pack(fill="x", padx=22, pady=(6, 20))
    for texte, action, principal in reversed(boutons):
        ctk.CTkButton(bas, text=texte, height=36, width=110, corner_radius=10, font=police(13, principal),
                      fg_color=ACC if principal else "transparent", hover_color=ACC_H if principal else TRACK,
                      text_color=ON_ACC if principal else TXT2, border_width=0 if principal else 1,
                      border_color=BORDER2,
                      command=(lambda a=action: a(w)) if action else w.destroy).pack(side="right", padx=(8, 0))
    w.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - w.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - w.winfo_reqheight()) // 3
    w.geometry(f"+{max(0, x)}+{max(0, y)}")
    try:
        w.grab_set()
    except tk.TclError:
        pass
    return w


etat_maj = {"boite": None, "texte": ""}


def quoi_de_neuf(version=VERSION):
    notes = NOUVEAUTES.get(version)
    if isinstance(notes, dict):
        notes = notes.get(LANGUE) or notes.get("en")
    boite(T(f"What's new · v{version}", f"Quoi de neuf · v{version}"),
          T("What changed in this version", "Les nouveautés de cette version"),
          notes or [T("Fixes and improvements.", "Corrections et améliorations.")], ((T("Great!", "Super !"), None, True),))


def resultat_maj(data, err, manuel):
    if err:
        texte = err
    elif data is False:
        texte = T(f"You're up to date (v{VERSION}).", f"Tu es à jour (v{VERSION}).")
    else:
        texte = T(f"Version {data['version']} available.", f"Version {data['version']} disponible.")
    etat_maj["texte"] = texte
    try:
        maj_statut.configure(text=texte)
    except NameError:
        pass
    if data:
        def lancer(w):
            w.statut.configure(text=T("Downloading and installing…", "Téléchargement et installation…"),
                               text_color=ACC_H)
            etat_maj["boite"] = w
            installer_maj(data)

        notes = (data.get("notes_fr") if LANGUE == "fr" else None) or data.get("notes") or []
        etat_maj["boite"] = boite(T(f"Update {data['version']} available", f"Mise à jour {data['version']} disponible"),
                                  T(f"You have version {VERSION}. The app restarts by itself after installing.",
                                    f"Tu as la version {VERSION}. L'app redémarre toute seule après l'installation."),
                                  notes, ((T("Later", "Plus tard"), None, False),
                                          (T("Update", "Mettre à jour"), lancer, True)))
    elif manuel and err:
        boite(T("Updates", "Mises à jour"), err)


# ---------- Assistant du premier démarrage ----------
def assistant():
    """Écran de configuration au premier lancement (relançable depuis Options > Application).
    Bloque la suite du démarrage jusqu'à « C'est parti »."""
    ov.withdraw()
    root.deiconify()  # customtkinter ne montre la fenêtre qu'au mainloop() : on la montre dès maintenant
    root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    cles = ("count_keys", "count_clicks", "count_scroll", "track_apps", "session_popup", "overlay_on_start",
            "autostart", "start_minimized", "check_updates")
    v = {k: tk.IntVar(value=int(cfg[k])) for k in cles}
    choix = {"theme": cfg["theme"], "window": cfg["window"], "afk_delay": cfg["afk_delay"]}
    etape, fini, cadre = [0], tk.BooleanVar(value=False), [None]
    try:
        im = Image.open(LOGO).convert("RGBA") if HAS_LOGO else image_defaut()
    except Exception:
        im = image_defaut()
    logo = ctk.CTkImage(light_image=im, dark_image=im, size=(26, 26))
    ETAPES = (
        (T("Welcome to lightAPM", "Bienvenue sur lightAPM"),
         T("Pick your language and theme. You can change them anytime in Options.",
           "Choisis ta langue et ton thème. Tu pourras les changer à tout moment dans Options.")),
        (T("What counts as an action", "Ce qui compte comme une action"),
         T("Choose which inputs count toward your APM.", "Choisis les inputs pris en compte dans tes APM.")),
        (T("Your game sessions", "Tes sessions de jeu"),
         T("lightAPM detects the game in focus and keeps your stats, session after session.",
           "lightAPM détecte le jeu au premier plan et garde tes stats session après session.")),
        (T("Startup", "Démarrage"),
         T("How lightAPM starts. Everything can be changed later in Options.",
           "Comment lightAPM se lance. Tout reste modifiable dans Options.")),
    )

    def choisir_langue(nom):
        l = "fr" if nom == "Français" else "en"
        if l != LANGUE:  # tous les textes changent : on relance l'assistant dans la nouvelle langue
            cfg["language"] = l
            cfg["theme"] = choix["theme"]
            save()
            subprocess.Popen([pythonw_exe(), os.path.abspath(__file__), "--restart"], cwd=DOSSIER,
                             close_fds=True)
            os._exit(0)

    def aller(d):
        etape[0] += d
        construire()

    def choisir_theme(k):
        choix["theme"] = k
        construire()

    def carte_switch(parent, row, titre, desc, cle):
        c = ctk.CTkFrame(parent, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
        c.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        c.columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=titre, font=police(14, True), anchor="w", height=20).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(c, text=desc, font=police(12), text_color=MUTED, anchor="w", justify="left",
                     wraplength=330).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        ctk.CTkSwitch(c, text="", variable=v[cle], width=46).grid(row=0, column=1, rowspan=2, padx=(8, 8))

    def carte_choix(parent, row, titre, desc, cle, options, fmt):
        c = ctk.CTkFrame(parent, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
        c.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        c.columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=titre, font=police(14, True), anchor="w", height=20).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(c, text=desc, font=police(12), text_color=MUTED, anchor="w", justify="left",
                     wraplength=250).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        noms = [fmt(o) for o in options]
        seg = ctk.CTkSegmentedButton(c, values=noms, font=police(12, True), height=30, text_color=TXT2,
                                     selected_color=ACC, selected_hover_color=ACC_H, unselected_color=BG,
                                     unselected_hover_color=TRACK, fg_color=BG,
                                     command=lambda n: choix.__setitem__(cle, options[noms.index(n)]))
        seg.set(fmt(min(options, key=lambda o: abs(o - choix[cle]))))
        choix[cle] = options[noms.index(seg.get())]
        seg.grid(row=0, column=1, rowspan=2, padx=(8, 14))

    def carte_theme(parent, i, k):
        nom, acc, acc_h, acc_d = THEMES[k]
        sel = k == choix["theme"]
        c = ctk.CTkFrame(parent, fg_color=FIELD if sel else PANEL, border_width=2 if sel else 1,
                         border_color=ACC if sel else BORDER, corner_radius=12, height=58)
        c.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 5, 5 if i % 2 == 0 else 0),
               pady=(0, 10))
        c.grid_propagate(False)
        c.columnconfigure(1, weight=1)
        fond = FIELD if sel else PANEL
        cv = tk.Canvas(c, width=int(58 * SC), height=int(24 * SC), bg=fond, highlightthickness=0)
        cv.grid(row=0, column=0, padx=(14, 6), pady=16)
        for j, coul in enumerate((acc_d, acc, acc_h)):
            x = j * 17 * SC
            cv.create_oval(x, 0, x + 23 * SC, 23 * SC, fill=coul, outline=fond, width=2 * SC)
        ctk.CTkLabel(c, text=nom, font=police(14, sel), text_color=TXT if sel else TXT2, anchor="w").grid(
            row=0, column=1, sticky="w")
        if sel:
            ctk.CTkLabel(c, text="✓", font=police(15, True), text_color=ACC_H, width=20).grid(
                row=0, column=2, padx=(0, 14))
        cliquable(c, lambda: choisir_theme(k))

    def construire():
        appliquer_palette(choix["theme"])
        appliquer_theme()
        root.configure(fg_color=BG)
        if cadre[0]:
            cadre[0].destroy()
        f = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
        f.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        cadre[0] = f
        n = etape[0]
        haut = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        haut.pack(fill="x")
        ctk.CTkLabel(haut, text="", image=logo).pack(side="left")
        ctk.CTkLabel(haut, text=NOM, font=police(14, True)).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(haut, text=f"{n + 1} / {len(ETAPES)}", font=police(12, mono=True), text_color=MUTED).pack(
            side="right")
        prog = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        prog.pack(fill="x", pady=(14, 22))
        for i in range(len(ETAPES)):
            prog.columnconfigure(i, weight=1, uniform="p")
            ctk.CTkFrame(prog, height=4, corner_radius=2, fg_color=ACC if i <= n else TRACK).grid(
                row=0, column=i, sticky="ew", padx=(0 if i == 0 else 3, 0 if i == len(ETAPES) - 1 else 3))
        titre, sous = ETAPES[n]
        ctk.CTkLabel(f, text=titre, font=police(24, True), anchor="w").pack(fill="x")
        ctk.CTkLabel(f, text=sous, font=police(13), text_color=MUTED, anchor="w", justify="left",
                     wraplength=440).pack(fill="x", pady=(2, 18))
        corps = ctk.CTkScrollableFrame(f, fg_color="transparent", corner_radius=0)
        corps.pack(fill="both", expand=True)
        corps.columnconfigure((0, 1), weight=1, uniform="c")
        if n == 0:
            lg = ctk.CTkFrame(corps, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
            lg.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
            lg.columnconfigure(0, weight=1)
            ctk.CTkLabel(lg, text=T("Language", "Langue"), font=police(14, True), anchor="w", height=20).grid(
                row=0, column=0, sticky="w", padx=16, pady=14)
            seg = ctk.CTkSegmentedButton(lg, values=["English", "Français"], font=police(12, True), height=30,
                                         text_color=TXT2, selected_color=ACC, selected_hover_color=ACC_H,
                                         unselected_color=BG, unselected_hover_color=TRACK, fg_color=BG,
                                         command=choisir_langue)
            seg.set("Français" if LANGUE == "fr" else "English")
            seg.grid(row=0, column=1, padx=14)
            for i, k in enumerate(THEMES):
                carte_theme(corps, i + 2, k)
        elif n == 1:
            carte_switch(corps, 0, T("Keyboard", "Clavier"),
                         T("Every key press (the app's own hotkeys don't count).",
                           "Chaque touche pressée (les raccourcis de l'app ne comptent pas)."), "count_keys")
            carte_switch(corps, 1, T("Mouse clicks", "Clics souris"),
                         T("Left, right and middle clicks.", "Clic gauche, droit et molette cliquée."), "count_clicks")
            carte_switch(corps, 2, T("Mouse wheel", "Molette"),
                         T("Every wheel notch.", "Chaque cran de molette."), "count_scroll")
            carte_choix(corps, 3, T("Measured over", "Calcul sur"),
                        T("Time window used for the live number.", "Durée prise en compte pour le chiffre en direct."),
                        "window", (30, 60, 120), lambda o: f"{o} s")
        elif n == 2:
            carte_switch(corps, 0, T("Track the game in focus", "Suivre le jeu au premier plan"),
                         T("Stats per game: average, peak and low of every session. Browsers are ignored.",
                           "Stats par jeu : moyenne, peak et low de chaque session. Navigateurs ignorés."),
                         "track_apps")
            carte_choix(corps, 1, T("AFK pause after", "Pause AFK après"),
                        T("With no input, APM freezes and resumes as soon as you play again.",
                          "Sans input, les APM se figent et reprennent dès que tu rejoues."),
                        "afk_delay", (5, 10, 30), lambda o: f"{o} s")
            carte_switch(corps, 2, T("End-of-session summary", "Résumé en fin de session"),
                         T("A small card with your average, peak and low.",
                           "Une petite carte avec ta moyenne, ton peak et ton low."), "session_popup")
            carte_switch(corps, 3, T("Show overlay on startup", "Overlay visible au démarrage"),
                         T("The number on top of your games (F9 to show or hide it).",
                           "Le chiffre par-dessus tes jeux (F9 pour l'afficher ou le masquer)."), "overlay_on_start")
        else:
            carte_switch(corps, 0, T("Start with Windows", "Lancer avec Windows"),
                         T("lightAPM starts by itself when you turn on your PC.",
                           "lightAPM démarre tout seul quand tu allumes ton PC."), "autostart")
            carte_switch(corps, 1, T("Start minimized to tray", "Démarrer réduit dans le tray"),
                         T("When starting with Windows, the app stays quietly in the notification area.",
                           "Au lancement avec Windows, l'app reste discrète dans la zone de notification."),
                         "start_minimized")
            carte_switch(corps, 2, T("Check for updates", "Vérifier les mises à jour"),
                         T("On every startup. Nothing installs without your OK.",
                           "À chaque démarrage. Rien ne s'installe sans ton accord."), "check_updates")
        bas = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        bas.pack(fill="x", pady=(14, 0))
        style = dict(height=40, corner_radius=10, font=police(14, True))
        if n == 0:
            ctk.CTkButton(bas, text=T("Skip", "Passer"), width=100, fg_color="transparent", hover_color=PANEL,
                          text_color=MUTED, command=lambda: fini.set(True), **style).pack(side="left")
        else:
            ctk.CTkButton(bas, text=T("Back", "Retour"), width=100, fg_color="transparent", hover_color=PANEL, border_width=1,
                          border_color=BORDER2, text_color=TXT2, command=lambda: aller(-1), **style).pack(
                side="left")
        derniere = n == len(ETAPES) - 1
        ctk.CTkButton(bas, text=T("Let's go", "C'est parti") if derniere else T("Next", "Suivant"), width=150, fg_color=ACC,
                      hover_color=ACC_H, text_color=ON_ACC,
                      command=(lambda: fini.set(True)) if derniere else (lambda: aller(1)), **style).pack(
            side="right")

    construire()
    root.wait_variable(fini)
    for k in cles:
        cfg[k] = bool(v[k].get())
    cfg.update(choix)
    cfg["setup_done"] = True
    regler_autostart(cfg["autostart"])
    appliquer_palette(cfg["theme"])
    appliquer_theme()
    root.configure(fg_color=BG)
    cadre[0].destroy()
    save()
    ov.deiconify()
    root.protocol("WM_DELETE_WINDOW", quitter)


def cliquable(widget, action):
    """Rend un cadre et tout son contenu cliquable."""
    widget.bind("<Button-1>", lambda e: action())
    widget.configure(cursor="hand2")
    for w in widget.winfo_children():
        cliquable(w, action)


if not cfg["setup_done"]:
    assistant()


# En-tête : logo | titre | APM en direct
header = ctk.CTkFrame(root, fg_color="transparent", corner_radius=0)
header.pack(fill="x", padx=PAD, pady=(PAD, 14))
header.columnconfigure(1, weight=1)


def creer_logo_ctk():
    try:
        im = Image.open(LOGO).convert("RGBA") if HAS_LOGO else image_defaut()
    except Exception:
        im = image_defaut()
    return ctk.CTkImage(light_image=im, dark_image=im, size=(28, 28))


logo_box = ctk.CTkFrame(header, width=42, height=42, corner_radius=11, fg_color=FIELD, border_width=1,
                        border_color=BORDER2)
logo_box.grid(row=0, column=0, rowspan=2, padx=(0, 12))
logo_box.grid_propagate(False)
logo_ctk = creer_logo_ctk()
logo_lbl = ctk.CTkLabel(logo_box, text="", image=logo_ctk)
logo_lbl.place(relx=0.5, rely=0.5, anchor="center")
ctk.CTkLabel(header, text=NOM, font=police(18, True), anchor="w").grid(row=0, column=1, sticky="sw")
ctk.CTkLabel(header, text=T("APM counter", "Compteur d'APM"), text_color=MUTED, anchor="w", font=police(12)).grid(
    row=1, column=1, sticky="nw")
live_val = tk.StringVar(value="0")
ctk.CTkLabel(header, textvariable=live_val, text_color=ACC_H, font=police(30, True, mono=True), anchor="e",
             height=34).grid(row=0, column=2, sticky="se")
live_lbl = ctk.CTkLabel(header, text="APM LIVE", text_color=MUTED, font=police(10, True), anchor="e", height=14)
live_lbl.grid(row=1, column=2, sticky="ne")

# Action principale : verrouiller / déverrouiller l'overlay
ctk.CTkButton(root, textvariable=lock_txt, height=36, corner_radius=10, fg_color=PANEL, hover_color=TRACK,
              border_width=1, border_color=BORDER2, text_color=TXT, font=police(13, True),
              command=lambda: set_lock(not locked)).pack(fill="x", padx=PAD, pady=(0, 10))
tray_v = tk.IntVar(value=int(cfg["tray_on_minimize"]))  # réglé dans Options > Application


class Onglets:
    """Barre d'onglets minimaliste : texte + soulignement violet sous l'onglet actif."""

    def __init__(self, parent):
        self.barre = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self.barre.pack(fill="x", padx=PAD)
        ctk.CTkFrame(parent, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x", padx=PAD)
        self.corps = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self.corps.pack(fill="both", expand=True, padx=PAD, pady=(14, PAD))
        self.pages, self.btns, self.actif = {}, {}, None

    def add(self, nom):
        i = len(self.pages)
        b = ctk.CTkButton(self.barre, text=nom, width=10, height=34, corner_radius=6, fg_color="transparent",
                          hover_color=PANEL, text_color=MUTED, font=police(13),
                          command=lambda: self.set(nom))
        b.grid(row=0, column=i, padx=(0, 4))
        trait = ctk.CTkFrame(self.barre, height=2, width=10, corner_radius=0, fg_color=BG)
        trait.grid(row=1, column=i, sticky="ew", padx=(8, 12))
        page = ctk.CTkFrame(self.corps, fg_color="transparent", corner_radius=0)
        self.pages[nom], self.btns[nom] = page, (b, trait)
        if self.actif is None:
            self.set(nom)
        return page

    def set(self, nom):
        if self.actif:
            self.pages[self.actif].pack_forget()
        self.actif = nom
        self.pages[nom].pack(fill="both", expand=True)
        for n, (b, trait) in self.btns.items():
            on = n == nom
            b.configure(text_color=TXT if on else MUTED, font=police(13, on))
            trait.configure(fg_color=ACC if on else BG)


tabs = Onglets(root)


def tab(nom):
    f = tabs.add(nom)
    f.columnconfigure(0, weight=1)
    return f

class Groupe:
    """Carte de réglages : petit titre en capitales, puis des lignes séparées par un filet."""

    def __init__(self, page, titre):
        self.c = ctk.CTkFrame(page, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
        self.c.pack(fill="x", padx=(0, 6), pady=(0, 12))
        self.c.columnconfigure(0, weight=1)
        ctk.CTkLabel(self.c, text=titre.upper(), font=police(10, True), text_color=DIM, anchor="w",
                     height=14).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(12, 0))
        self.r = 1

    def ligne(self, label, widget, aide=None, marge=18):
        """Ajoute une ligne « libellé (+ aide) ... contrôle ». Renvoie le label d'aide (modifiable)."""
        if self.r > 1:
            ctk.CTkFrame(self.c, fg_color=BORDER, height=1, corner_radius=0).grid(
                row=self.r, column=0, columnspan=2, sticky="ew", padx=18)
            self.r += 1
        txt = ctk.CTkFrame(self.c, fg_color="transparent", corner_radius=0)
        txt.grid(row=self.r, column=0, sticky="w", padx=(18, 12), pady=10)
        ctk.CTkLabel(txt, text=label, font=police(13), text_color=TXT, anchor="w", height=18).pack(anchor="w")
        lbl_aide = None
        if aide is not None:
            lbl_aide = ctk.CTkLabel(txt, text=aide, font=police(11), text_color=DIM, anchor="w", justify="left",
                                    height=14, wraplength=300)
            lbl_aide.pack(anchor="w")
        widget.grid(row=self.r, column=1, sticky="e", padx=(0, marge), pady=10)
        self.r += 1
        return lbl_aide


size_v = tk.DoubleVar(value=cfg["size"])
font_v = tk.StringVar(value=cfg["font"])
bold_v = tk.IntVar(value=int(cfg["bold"]))
outline_v = tk.IntVar(value=int(cfg["outline_on"]))
opac_v = tk.DoubleVar(value=cfg["opacity"])
suffix_v = tk.StringVar(value=cfg["suffix"])
win_v = tk.DoubleVar(value=min(cfg["window"], 180))
ref_v = tk.DoubleVar(value=min(cfg["refresh"], 500))
ck_v = tk.IntVar(value=int(cfg["count_keys"]))
cc_v = tk.IntVar(value=int(cfg["count_clicks"]))
cs_v = tk.IntVar(value=int(cfg["count_scroll"]))
sl_v = tk.IntVar(value=int(cfg["start_locked"]))
track_v = tk.IntVar(value=int(cfg["track_apps"]))
gap_v = tk.DoubleVar(value=max(1, min(30, cfg["session_gap"])))
popup_v = tk.IntVar(value=int(cfg["session_popup"]))
afk_v = tk.DoubleVar(value=max(3, min(60, cfg["afk_delay"])))
auto_v = tk.IntVar(value=int(cfg["autostart"]))
smin_v = tk.IntVar(value=int(cfg["start_minimized"]))
ovs_v = tk.IntVar(value=int(cfg["overlay_on_start"]))
chk_v = tk.IntVar(value=int(cfg["check_updates"]))


def clamp(v, a, b):
    return max(a, min(b, v))


def sync(*_):
    if loading:
        return
    try:
        cfg["size"] = clamp(int(round(size_v.get())), 6, 200)
        cfg["window"] = clamp(int(round(win_v.get())), 5, 600)
        cfg["refresh"] = clamp(int(round(ref_v.get() / 10)) * 10, 20, 1000)
        cfg["opacity"] = round(clamp(opac_v.get(), 0.1, 1.0), 2)
        cfg["session_gap"] = clamp(int(round(gap_v.get())), 1, 30)
        cfg["afk_delay"] = clamp(int(round(afk_v.get())), 3, 60)
    except (tk.TclError, ValueError):
        return
    cfg["font"] = font_v.get() or DEFAUT["font"]
    cfg["bold"] = bool(bold_v.get())
    cfg["outline_on"] = bool(outline_v.get())
    cfg["suffix"] = suffix_v.get()
    cfg["count_keys"] = bool(ck_v.get())
    cfg["count_clicks"] = bool(cc_v.get())
    cfg["count_scroll"] = bool(cs_v.get())
    cfg["start_locked"] = bool(sl_v.get())
    cfg["tray_on_minimize"] = bool(tray_v.get())
    cfg["track_apps"] = bool(track_v.get())
    cfg["session_popup"] = bool(popup_v.get())
    cfg["start_minimized"] = bool(smin_v.get())
    cfg["overlay_on_start"] = bool(ovs_v.get())
    cfg["check_updates"] = bool(chk_v.get())
    if bool(auto_v.get()) != cfg["autostart"]:
        cfg["autostart"] = bool(auto_v.get())
        regler_autostart(cfg["autostart"])
    restyle()
    save_later()


for v in (size_v, font_v, bold_v, outline_v, opac_v, suffix_v, win_v, ref_v, ck_v, cc_v, cs_v, sl_v, tray_v,
          track_v, gap_v, popup_v, afk_v, auto_v, smin_v, ovs_v, chk_v):
    v.trace_add("write", sync)


def slider(g, label, var, a, b, steps, fmt, aide=None):
    box = ctk.CTkFrame(g.c, fg_color="transparent", width=CW, height=28)
    box.grid_propagate(False)
    box.columnconfigure(0, weight=1)
    s = ctk.CTkSlider(box, from_=a, to=b, number_of_steps=steps, variable=var)
    s.grid(row=0, column=0, sticky="ew", pady=5)
    lbl = ctk.CTkLabel(box, width=54, anchor="e", text=fmt(var.get()), text_color=ACC_H,
                       font=police(12, True, mono=True))
    lbl.grid(row=0, column=1, padx=(8, 0))
    g.ligne(label, box, aide)

    def maj(*_):
        try:
            lbl.configure(text=fmt(var.get()))
        except tk.TclError:
            pass

    var.trace_add("write", maj)


def switch(g, label, var, aide=None):
    # l'interrupteur a une marge interne à droite : on la compense pour aligner les bords
    return g.ligne(label, ctk.CTkSwitch(g.c, text="", variable=var, width=46), aide, marge=10)


def contraste(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return "black" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "white"


couleur_btn = {}


def maj_couleur_btn(nom):
    couleur_btn[nom].configure(text=cfg[nom].upper(), fg_color=cfg[nom], hover_color=cfg[nom],
                               text_color=contraste(cfg[nom]))


def choisir(nom):
    c = colorchooser.askcolor(color=cfg[nom], parent=root)
    if c and c[1]:
        cfg[nom] = c[1]
        maj_couleur_btn(nom)
        restyle()
        save_later()


def bouton_couleur(f, nom):
    b = ctk.CTkButton(f, width=CW, height=30, corner_radius=8, border_width=1, border_color=BORDER2,
                      font=police(12, True, mono=True), command=lambda: choisir(nom))
    couleur_btn[nom] = b
    maj_couleur_btn(nom)
    return b


# Stats : catégories, graphiques, détail par app
t = tab("Stats")
vue = {"cat": "jeux", "detail": None}
NOMS_CAT = dict(CATEGORIES)


def il_y_a(ts):
    d = time.time() - ts
    if d < 3600:
        m = max(1, int(d // 60))
        return T(f"{m} min ago", f"il y a {m} min")
    if d < 86400:
        return T(f"{int(d // 3600)}h ago", f"il y a {int(d // 3600)} h")
    if d < 2 * 86400:
        return T("yesterday", "hier")
    return T(f"{int(d // 86400)} days ago", f"il y a {int(d // 86400)} j")


def legende_canvas(cv, s, w, items):
    """Légende alignée à droite d'un graphique : items = [(dessin(x_droite) -> largeur, texte), ...]."""
    f = tkfont.Font(family=F_UI, size=8)
    x = w
    for dessin, texte in reversed(items):
        cv.create_text(x, 8 * s, anchor="e", fill=MUTED, font=(F_UI, 8), text=texte)
        x -= f.measure(texte) + 6 * s
        x -= dessin(x) + 14 * s


def couper(txt, n):
    return txt if len(txt) <= n else txt[:n - 1] + "…"


def apps_de(cat):
    out = [(exe, a) for exe, a in stats["apps"].items() if a.get("cat") == cat and a["sessions"]]
    out.sort(key=lambda x: x[1]["sessions"][-1]["end"], reverse=True)  # dernier joué en haut
    return out


# Bandeau "en cours"
live = ctk.CTkFrame(t, fg_color=FIELD, border_width=1, border_color=BORDER2, corner_radius=12)
live.pack(fill="x", pady=(0, 12))
live.columnconfigure(2, weight=1)
live_dot = tk.Canvas(live, width=int(8 * SC), height=int(8 * SC), bg=FIELD, highlightthickness=0)
live_dot.grid(row=0, column=0, padx=(14, 8), pady=12)
live_dot_id = live_dot.create_oval(0, 0, int(8 * SC) - 1, int(8 * SC) - 1, fill=ACC, outline="")
live_etat = ctk.CTkLabel(live, text="", font=police(11, True), text_color=ACC, height=20)
live_etat.grid(row=0, column=1, padx=(0, 10))
live_nom = ctk.CTkLabel(live, text="", font=police(14, True), anchor="w", height=20)
live_nom.grid(row=0, column=2, sticky="ew")
live_chrono = ctk.CTkLabel(live, text="", font=police(13, mono=True), text_color=MUTED, height=20)
live_chrono.grid(row=0, column=3, padx=(8, 10))
live_moy = ctk.CTkLabel(live, text="", font=police(13, True, mono=True), text_color=ACC_H, height=20)
live_moy.grid(row=0, column=4, padx=(0, 14))

vue_liste = ctk.CTkFrame(t, fg_color="transparent", corner_radius=0)
vue_detail = ctk.CTkScrollableFrame(t, fg_color="transparent", corner_radius=0)
vue_liste.pack(fill="both", expand=True)

# --- Vue liste : puces de catégories + graphique en barres + lignes ---
puces_row = ctk.CTkFrame(vue_liste, fg_color="transparent", corner_radius=0)
puces_row.pack(fill="x", pady=(0, 12))
puces = {}
for _k, _n in CATEGORIES:
    puces[_k] = ctk.CTkButton(puces_row, text=_n, height=32, width=10, corner_radius=16, border_width=1,
                              font=police(13), command=lambda k=_k: choisir_cat(k))
    puces[_k].pack(side="left", padx=(0, 8))
liste_scroll = ctk.CTkScrollableFrame(vue_liste, fg_color="transparent", corner_radius=0)
liste_scroll.pack(fill="both", expand=True)
liste_scroll.columnconfigure(0, weight=1)
carte_barres = ctk.CTkFrame(liste_scroll, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
carte_barres.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 16))
barres = tk.Canvas(carte_barres, bg=PANEL, highlightthickness=0, height=int(80 * SC))
barres.pack(fill="x", padx=16, pady=14)
titre_liste = legende(liste_scroll, "")
titre_liste.grid(row=1, column=0, sticky="w", pady=(0, 6))
lignes_box = ctk.CTkFrame(liste_scroll, fg_color="transparent", corner_radius=0)
lignes_box.grid(row=2, column=0, sticky="ew", padx=(0, 6))
lignes_box.columnconfigure(0, weight=1)


def dessiner_barres(*_):
    cv, s = barres, SC
    cv.delete("all")
    w = max(cv.winfo_width(), int(200 * s))
    cat = vue["cat"]
    items = []
    for exe, a in apps_de(cat):
        g = agreger(a)
        items.append((a["name"], g["avg"], g["peak_max"]))
    items.sort(key=lambda x: x[1], reverse=True)
    items = items[:8]
    cv.create_text(0, 8 * s, anchor="w", fill=MUTED, font=(F_UI, 8, "bold"),
                   text=(T("AVERAGE PER GAME", "MOYENNE PAR JEU") if cat == "jeux"
                         else T("AVERAGE PER APP", "MOYENNE PAR APP")))
    # légende à droite : rail violet = moyenne, trait blanc = peak record
    legende_canvas(cv, s, w, [
        (lambda x: cv.create_line(x - 10 * s, 8 * s, x, 8 * s, fill=ACC, width=6 * s, capstyle="round") and 10 * s,
         T("average", "moyenne")),
        (lambda x: cv.create_line(x, 2 * s, x, 14 * s, fill=TXT, width=max(1, 2 * s)) and 2 * s,
         T("best peak", "peak record")),
    ])
    top, row = 30 * s, 30 * s
    if not items:
        cv.create_text(0, top + 12 * s, anchor="w", fill=DIM, font=(F_UI, 10),
                       text=T("No sessions in this category yet.", "Pas encore de session dans cette catégorie."))
        cv.configure(height=int(top + 30 * s))
        return
    vmax = max(max(p, a) for _, a, p in items) or 1
    lab_w, val_w = 130 * s, 46 * s
    x0, x1 = lab_w + 6 * s, w - val_w
    for i, (nom, avg, peak) in enumerate(items):
        y = top + i * row + row / 2
        cv.create_text(0, y, anchor="w", fill=TXT, font=(F_UI, 10), text=couper(nom, 17))
        cv.create_line(x0, y, x1, y, width=10 * s, fill=TRACK, capstyle="round")
        xa = x0 + (x1 - x0) * avg / vmax
        if avg > 0:
            cv.create_line(x0, y, max(xa, x0 + 1), y, width=10 * s, fill=ACC, capstyle="round")
        xp = x0 + (x1 - x0) * peak / vmax
        cv.create_line(xp, y - 8 * s, xp, y + 8 * s, width=max(1, 2 * s), fill=TXT)
        cv.create_text(w, y, anchor="e", fill=TXT, font=(F_MONO, 10, "bold"), text=str(avg))
    cv.configure(height=int(top + len(items) * row + 4 * s))


barres.bind("<Configure>", dessiner_barres)


def ligne_app(i, exe, a):
    g = agreger(a)
    c = ctk.CTkFrame(lignes_box, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
    c.grid(row=i, column=0, sticky="ew", pady=(0, 8))
    c.columnconfigure(0, weight=1)
    ctk.CTkLabel(c, text=a["name"], font=police(15, True), anchor="w", height=22).grid(
        row=0, column=0, sticky="w", padx=(16, 8), pady=(12, 0))
    ctk.CTkLabel(c, text=f"{g['n']} session{'s' if g['n'] > 1 else ''} · {fmt_duree(g['temps'])} · "
                         + T(f"last {il_y_a(a['sessions'][-1]['end'])}", f"dernière {il_y_a(a['sessions'][-1]['end'])}"),
                 font=police(12), text_color=MUTED, anchor="w", height=18).grid(
        row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 12))
    for col, (val, lib, coul) in enumerate(((g["avg"], T("avg", "moy"), ACC_H), (g["peak_max"], "peak", TXT)), start=1):
        ctk.CTkLabel(c, text=str(val), font=police(20, True, mono=True), text_color=coul, anchor="e",
                     width=58, height=24).grid(row=0, column=col, sticky="e", padx=(4, 0), pady=(10, 0))
        ctk.CTkLabel(c, text=lib, font=police(11), text_color=MUTED, anchor="e", width=58, height=16).grid(
            row=1, column=col, sticky="ne", padx=(4, 0), pady=(0, 12))
    ctk.CTkLabel(c, text="›", font=police(22), text_color=MUTED, width=20).grid(
        row=0, column=3, rowspan=2, padx=(8, 14))
    cliquable(c, lambda: ouvrir_detail(exe))
    for w in [c] + c.winfo_children():
        w.bind("<Enter>", lambda e: c.configure(border_color=ACC_D), add="+")
        w.bind("<Leave>", lambda e: c.configure(border_color=BORDER), add="+")


def choisir_cat(k):
    vue["cat"] = k
    rafraichir_liste()


def rafraichir_liste():
    for k, b in puces.items():
        n = len(apps_de(k))
        on = k == vue["cat"]
        b.configure(text=f"{NOMS_CAT[k]} · {n}", fg_color=ACC if on else BG, hover_color=ACC_H if on else PANEL,
                    border_color=ACC if on else BORDER2, text_color="#0b0712" if on else TXT2,
                    font=police(13, on))
    for w in lignes_box.winfo_children():
        w.destroy()
    apps = apps_de(vue["cat"])
    titre_liste.configure(text=NOMS_CAT[vue["cat"]].upper())
    if not apps:
        ctk.CTkLabel(lignes_box, text=T("Launch a game or an app on your main screen: the session is saved "
                                        "when you leave it.",
                                        "Lance un jeu ou une app sur ton écran principal : la session est "
                                        "enregistrée quand tu la quittes."), text_color=DIM, font=police(12),
                     justify="left", anchor="w", wraplength=int(420)).grid(row=0, column=0, sticky="w")
    for i, (exe, a) in enumerate(apps):
        ligne_app(i, exe, a)
    dessiner_barres()


# --- Vue détail d'une app ---
def ouvrir_detail(exe):
    vue["detail"] = exe
    vue_liste.pack_forget()
    vue_detail.pack(fill="both", expand=True)
    construire_detail()


def fermer_detail():
    vue["detail"] = None
    vue_detail.pack_forget()
    vue_liste.pack(fill="both", expand=True)
    rafraichir_liste()


def dessiner_courbe(cv, sessions):
    s = SC
    cv.delete("all")
    w = max(cv.winfo_width(), int(200 * s))
    h, top, left, right = 200 * s, 34 * s, 34 * s, w - 10 * s
    bot = h - 20 * s
    cv.create_text(0, 8 * s, anchor="w", fill=MUTED, font=(F_UI, 8, "bold"),
                   text=T("PROGRESS PER SESSION", "ÉVOLUTION PAR SESSION"))
    legende_canvas(cv, s, w, [
        (lambda x: cv.create_line(x - 12 * s, 8 * s, x, 8 * s, fill=ACC_H, width=max(1, 2 * s)) and 12 * s,
         T("average", "moyenne")),
        (lambda x: cv.create_rectangle(x - 10 * s, 4 * s, x, 12 * s, fill=BAND, outline="") and 10 * s,
         "low → peak"),
    ])
    ss = sessions[-30:]
    if not ss:
        return
    avgs = [x["avg"] for x in ss]
    peaks = [max(x["peak"], x["avg"]) for x in ss]
    lows = [min(x["low"], x["avg"]) if x["low"] > 0 else x["avg"] for x in ss]
    lo, hi = min(lows), max(peaks)
    pas = next((p for p in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if (hi - lo) / p <= 3), 2000)
    vmin = max(0, int(lo // pas) * pas)
    vmax = (int(hi // pas) + 1) * pas

    def Y(v):
        return bot - (v - vmin) / (vmax - vmin) * (bot - top)

    n = len(ss)

    def X(i):
        return left + (right - left) * (i / (n - 1) if n > 1 else 0.5)

    for v in range(vmin, vmax + 1, pas):
        cv.create_line(left, Y(v), right, Y(v), fill=TRACK)
        cv.create_text(left - 6 * s, Y(v), anchor="e", fill=DIM, font=(F_MONO, 8), text=str(v))
    if n > 1:
        pts = [c for i in range(n) for c in (X(i), Y(peaks[i]))]
        pts += [c for i in reversed(range(n)) for c in (X(i), Y(lows[i]))]
        cv.create_polygon(*pts, fill=BAND, outline="")
        cv.create_line(*[c for i in range(n) for c in (X(i), Y(avgs[i]))], fill=ACC_H, width=2.5 * s,
                       joinstyle="round", capstyle="round")
    else:
        cv.create_rectangle(X(0) - 6 * s, Y(peaks[0]), X(0) + 6 * s, Y(lows[0]), fill=BAND, outline="")
    r = 4.5 * s
    cv.create_oval(X(n - 1) - r, Y(avgs[-1]) - r, X(n - 1) + r, Y(avgs[-1]) + r, fill=PANEL, outline=ACC_H,
                   width=2.5 * s)
    cv.create_text(left, h - 6 * s, anchor="w", fill=DIM, font=(F_UI, 8), text=fmt_date(ss[0]["start"])[:5])
    if n > 1:
        cv.create_text(right, h - 6 * s, anchor="e", fill=DIM, font=(F_UI, 8), text=fmt_date(ss[-1]["start"])[:5])
    cv.configure(height=int(h))


def tuile(parent, col, titre, valeur, fort=False):
    f = ctk.CTkFrame(parent, fg_color=FIELD if fort else PANEL, border_width=1,
                     border_color=BORDER2 if fort else BORDER, corner_radius=12)
    f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 0 if col == 3 else 5))
    legende(f, titre, height=16).pack(anchor="w", padx=14, pady=(12, 2))
    ctk.CTkLabel(f, text=str(valeur), font=police(24, True, mono=True), text_color=ACC_H if fort else TXT,
                 anchor="w", height=30).pack(anchor="w", padx=14, pady=(0, 12))


def changer_cat(exe, nom):
    k = next(k for k, n in CATEGORIES if n == nom)
    stats["apps"][exe]["cat"] = k
    vue["cat"] = k
    sauver_stats()


def renommer(exe):
    d = ctk.CTkInputDialog(text=T(f"New name for {stats['apps'][exe]['name']}:",
                                  f"Nouveau nom pour {stats['apps'][exe]['name']} :"), title=T("Rename", "Renommer"))
    nom = (d.get_input() or "").strip()
    if nom:
        stats["apps"][exe]["name"] = nom[:40]
        sauver_stats()
        construire_detail()


def supprimer(exe, bouton):
    if bouton.cget("text") != T("Confirm?", "Confirmer ?"):  # 2 clics pour éviter les accidents
        bouton.configure(text=T("Confirm?", "Confirmer ?"), fg_color="#3a1220", hover_color="#4c1729")
        root.after(3000, lambda: bouton.winfo_exists() and bouton.configure(
            text=T("Delete", "Supprimer"), fg_color="transparent", hover_color=PANEL))
        return
    stats["apps"].pop(exe, None)
    sauver_stats()
    fermer_detail()


def construire_detail():
    exe = vue["detail"]
    a = stats["apps"].get(exe)
    for w in vue_detail.winfo_children():
        w.destroy()
    if not a:
        fermer_detail()
        return
    g = agreger(a)
    box = ctk.CTkFrame(vue_detail, fg_color="transparent", corner_radius=0)
    box.pack(fill="x", padx=(0, 6))
    box.columnconfigure(0, weight=1)

    haut = ctk.CTkFrame(box, fg_color="transparent", corner_radius=0)
    haut.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    haut.columnconfigure(1, weight=1)
    ctk.CTkButton(haut, text="‹", width=36, height=36, corner_radius=10, fg_color="transparent", hover_color=PANEL,
                  border_width=1, border_color=BORDER2, text_color=TXT, font=police(18),
                  command=fermer_detail).grid(row=0, column=0, rowspan=2, padx=(0, 12))
    ctk.CTkLabel(haut, text=a["name"], font=police(19, True), anchor="w", height=24).grid(
        row=0, column=1, sticky="sw")
    ctk.CTkLabel(haut, text=f"{g['n']} session{'s' if g['n'] > 1 else ''} · {fmt_duree(g['temps'])} " + T("total", "au total"),
                 font=police(12), text_color=MUTED, anchor="w", height=18).grid(row=1, column=1, sticky="nw")
    m = ctk.CTkOptionMenu(haut, values=[n for _, n in CATEGORIES], width=124, height=30, corner_radius=15,
                          font=police(12, True), dropdown_font=police(12),
                          command=lambda nom: changer_cat(exe, nom))
    m.set(NOMS_CAT.get(a.get("cat"), "Apps"))
    m.grid(row=0, column=2, rowspan=2, sticky="e")

    tuiles = ctk.CTkFrame(box, fg_color="transparent", corner_radius=0)
    tuiles.grid(row=1, column=0, sticky="ew", pady=(0, 12))
    for i in range(4):
        tuiles.columnconfigure(i, weight=1, uniform="t")
    tend = g["avg5"] - g["avg"]
    tuile(tuiles, 0, T("Average", "Moyenne"), g["avg"], fort=True)
    tuile(tuiles, 1, "Peak", g["peak_max"])
    tuile(tuiles, 2, T("Avg low", "Low moy"), g["low_moy"])
    tuile(tuiles, 3, T("Trend", "Tendance"), f"{'+' if tend >= 0 else '−'}{abs(tend)}")

    carte = ctk.CTkFrame(box, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
    carte.grid(row=2, column=0, sticky="ew", pady=(0, 16))
    cv = tk.Canvas(carte, bg=PANEL, highlightthickness=0, height=int(200 * SC))
    cv.pack(fill="x", padx=16, pady=14)
    cv.bind("<Configure>", lambda e: dessiner_courbe(cv, a["sessions"]))

    legende(box, "Sessions").grid(row=3, column=0, sticky="w", pady=(0, 4))
    table = ctk.CTkFrame(box, fg_color="transparent", corner_radius=0)
    table.grid(row=4, column=0, sticky="ew")
    largeurs = (0, 70, 52, 52, 52)
    for j, lw in enumerate(largeurs):
        table.columnconfigure(j, weight=1 if j == 0 else 0, minsize=lw)
    entete = ("DATE", T("LENGTH", "DURÉE"), T("AVG", "MOY"), "PEAK", "LOW")
    for j, txt in enumerate(entete):
        ctk.CTkLabel(table, text=txt, font=police(10, True), text_color=DIM, anchor="w" if j == 0 else "e",
                     height=22).grid(row=0, column=j, sticky="ew", padx=(12 if j == 0 else 0, 12 if j == 4 else 0))
    for i, s in enumerate(reversed(a["sessions"][-30:]), start=1):
        bg = PANEL if i % 2 else BG
        fond = ctk.CTkFrame(table, fg_color=bg, corner_radius=8, height=34)
        fond.grid(row=i, column=0, columnspan=5, sticky="nsew")
        vals = (fmt_date(s["start"]), fmt_duree(s["duration"]), s["avg"], s["peak"], s["low"])
        for j, v in enumerate(vals):
            ctk.CTkLabel(table, text=str(v), font=police(12, j == 2, mono=True), fg_color=bg, height=26,
                         text_color=ACC_H if j == 2 else (MUTED if j == 1 else TXT),
                         anchor="w" if j == 0 else "e").grid(
                row=i, column=j, sticky="ew", padx=(12 if j == 0 else 0, 12 if j == 4 else 0), pady=4)

    bas = ctk.CTkFrame(box, fg_color="transparent", corner_radius=0)
    bas.grid(row=5, column=0, sticky="w", pady=(16, 4))
    style = dict(height=36, width=110, corner_radius=10, fg_color="transparent", hover_color=PANEL,
                 border_width=1, border_color=BORDER2, font=police(13))
    ctk.CTkButton(bas, text=T("Rename", "Renommer"), text_color=TXT2, command=lambda: renommer(exe), **style).pack(
        side="left", padx=(0, 8))
    b = ctk.CTkButton(bas, text=T("Delete", "Supprimer"), text_color=DANGER, **style)
    b.configure(command=lambda: supprimer(exe, b))
    b.pack(side="left")
    vue_detail._parent_canvas.yview_moveto(0)


def rafraichir_jeux():
    if vue["detail"]:
        construire_detail()
    else:
        rafraichir_liste()


def toast_session(nom, r):
    """Résumé en bas à droite de l'écran principal, se ferme seul (ou au clic)."""
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg=ACC_D)
    f = ctk.CTkFrame(w, corner_radius=0, fg_color=PANEL)
    f.pack(padx=1, pady=1)
    ctk.CTkLabel(f, text=T("SESSION OVER", "SESSION TERMINÉE"), font=police(10, True), text_color=ACC, anchor="w", height=16).pack(
        fill="x", padx=16, pady=(12, 0))
    ctk.CTkLabel(f, text=nom, font=police(15, True), anchor="w", height=22).pack(fill="x", padx=16)
    ctk.CTkLabel(f, text=f"{fmt_duree(r['duration'])} · {r['actions']} actions", text_color=MUTED,
                 font=police(12), anchor="w", height=18).pack(fill="x", padx=16)
    row = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
    row.pack(fill="x", padx=16, pady=(10, 14))
    for titre, v, fort in ((T("AVG", "MOY"), r["avg"], True), ("PEAK", r["peak"], False), ("LOW", r["low"], False)):
        c = ctk.CTkFrame(row, fg_color=FIELD if fort else BG, border_width=1, border_color=BORDER2 if fort else BORDER,
                         corner_radius=10)
        c.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(c, text=titre, font=police(10, True), text_color=MUTED, height=14).pack(
            anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(c, text=str(v), font=police(20, True, mono=True), text_color=ACC_H if fort else TXT,
                     height=26, width=64, anchor="w").pack(anchor="w", padx=12, pady=(0, 8))
    w.update_idletasks()
    rect = wt.RECT()
    if WIN and ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        droite, bas_ = rect.right, rect.bottom
    else:
        droite, bas_ = root.winfo_screenwidth(), root.winfo_screenheight()
    w.geometry(f"+{droite - w.winfo_reqwidth() - 16}+{bas_ - w.winfo_reqheight() - 16}")
    cliquable(f, lambda: w.destroy())
    w.after(12000, lambda: w.winfo_exists() and w.destroy())


def fermer_session(s, popup=True):
    suivi["ouvertes"].pop(s.exe, None)
    if s.duree < MIN_SESSION or s.exe not in stats["apps"]:
        return
    r = s.resume()
    stats["apps"][s.exe]["sessions"].append(r)
    sauver_stats()
    rafraichir_jeux()
    if popup and cfg["session_popup"]:
        toast_session(stats["apps"][s.exe]["name"], r)


_live_prec = [None]


def maj_live_jeu():
    ouv = suivi["ouvertes"]
    s = ouv.get(suivi["actuel"])
    if s:
        etat = (T("PLAYING", "EN COURS"), ACC, stats["apps"][s.exe]["name"], fmt_chrono(s.duree),
                (f"{round(s.actions * 60 / s.duree)} " + T("avg", "moy") if s.duree >= MIN_MOY_LIVE
                 else T("measuring…", "calcul…")))
    elif ouv:
        s = max(ouv.values(), key=lambda x: x.vu)
        etat = (T("PAUSED", "EN PAUSE"), MUTED, stats["apps"][s.exe]["name"], fmt_chrono(s.duree),
                (f"{round(s.actions * 60 / s.duree)} " + T("avg", "moy") if s.duree >= MIN_MOY_LIVE
                 else T("measuring…", "calcul…")))
    elif not cfg["track_apps"]:
        etat = (T("OFF", "INACTIF"), DIM, T("Tracking disabled (Options)", "Suivi désactivé (Options)"), "", "")
    else:
        etat = (T("WAITING", "EN ATTENTE"), DIM, T("No app in focus", "Aucune app au premier plan"), "", "")
    if etat == _live_prec[0]:
        return
    _live_prec[0] = etat
    txt, coul, nom, chrono, moy = etat
    live_etat.configure(text=txt, text_color=coul)
    live_dot.itemconfig(live_dot_id, fill=coul)
    live_nom.configure(text=couper(nom, 26), text_color=TXT if moy else MUTED)
    live_chrono.configure(text=chrono)
    live_moy.configure(text=moy)


def tick_suivi():
    """Toutes les secondes : attribue les actions à l'app au premier plan, gère les sessions."""
    try:
        now = time.time()
        dt = min(now - suivi["t"], 5.0)  # pas de saut énorme après une mise en veille
        suivi["t"] = now
        n = compteur[0] - suivi["vu"]
        suivi["vu"] = compteur[0]
        app = app_premier_plan() if (WIN and cfg["track_apps"]) else None
        ouv = suivi["ouvertes"]
        if app:
            exe, path, pid, plein = app
            s = ouv.get(exe)
            if s and s.pid != pid:  # le jeu a été relancé : nouvelle session
                fermer_session(s)
                s = None
            if not s:
                a = stats["apps"].get(exe)
                if a is None:
                    a = stats["apps"][exe] = {"name": nom_lisible(path), "sessions": [],
                                              "cat": deviner_categorie(exe, path, plein), "path": path}
                elif not a.get("path"):
                    a["path"] = path
                    if not a["sessions"]:
                        a["cat"] = deviner_categorie(exe, path, plein)
                s = ouv[exe] = Session(exe, pid)
            elif plein and stats["apps"][exe].get("cat") == "apps" and not stats["apps"][exe]["sessions"] \
                    and exe not in LANCEURS:
                stats["apps"][exe]["cat"] = "jeux"  # passé en plein écran : sûrement un jeu
            s.ajouter(0 if est_afk(now) else dt, n)  # AFK : le temps de session est en pause
            s.vu = now
        suivi["actuel"] = app[0] if app else None
        for exe, s in list(ouv.items()):
            if exe != suivi["actuel"] and (now - s.vu > cfg["session_gap"] * 60 or not process_vivant(s.pid)):
                fermer_session(s)
        if root.winfo_viewable():
            maj_live_jeu()
        if os.path.exists(APPEL):  # quelqu'un a relancé lightAPM.exe : on se montre
            os.remove(APPEL)
            if tray["icon"]:
                from_tray()
            else:
                root.deiconify()
                root.lift()
                root.focus_force()
        if ouv and now - suivi["save"] > 30:
            sauver_stats()
    except Exception:
        log_err(*sys.exc_info())
    root.after(1000, tick_suivi)


# catégorie affichée au démarrage : la première qui a des données (Jeux en priorité)
vue["cat"] = next((k for k, _ in CATEGORIES if apps_de(k)), "jeux")
rafraichir_liste()
maj_live_jeu()

# Options : barre latérale de catégories + une page par catégorie (maquette "Options · par catégorie")
t = tab("Options")
t.columnconfigure(0, weight=0)  # la barre latérale garde sa largeur
t.columnconfigure(1, weight=1)
t.rowconfigure(0, weight=1)
cote = ctk.CTkFrame(t, fg_color="transparent", corner_radius=0, width=172)
cote.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
cote.pack_propagate(False)  # largeur fixe : le contenu prend tout le reste
contenu = ctk.CTkFrame(t, fg_color="transparent", corner_radius=0)
contenu.grid(row=0, column=1, sticky="nsew")
BTN = dict(height=30, corner_radius=8, fg_color=BG, hover_color=TRACK, border_width=1, border_color=BORDER2,
           text_color=TXT2, font=police(12))


def icone(cle, couleur, taille=16):
    """Petite icône au trait, dessinée en 4x puis réduite (nette sur tous les écrans)."""
    k = 4
    n = taille * k
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = int(1.8 * k)
    u = n / 24  # repère 24x24 comme les icônes de la maquette

    def P(*pts):
        return [(x * u, y * u) for x, y in pts]

    if cle == "apparence":
        d.ellipse(P((4, 4), (20, 20)), outline=couleur, width=w)
        d.pieslice(P((4, 4), (20, 20)), 90, 270, fill=couleur)
    elif cle == "overlay":
        d.rounded_rectangle(P((3, 5), (21, 19)), radius=2 * u, outline=couleur, width=w)
        d.rectangle(P((13, 9), (18, 13)), fill=couleur)
    elif cle == "calcul":
        d.line(P((4, 18), (9, 12), (13, 15), (20, 6)), fill=couleur, width=w, joint="curve")
    elif cle == "raccourcis":
        d.rounded_rectangle(P((3, 7), (21, 18)), radius=2 * u, outline=couleur, width=w)
        for x in (7, 11, 15):
            d.rectangle(P((x, 10.5), (x + 1.6, 12)), fill=couleur)
        d.line(P((8, 14.5), (16, 14.5)), fill=couleur, width=w)
    elif cle == "sessions":
        d.rounded_rectangle(P((3, 8), (21, 18)), radius=4 * u, outline=couleur, width=w)
        d.line(P((8, 11), (8, 15)), fill=couleur, width=w)
        d.line(P((6, 13), (10, 13)), fill=couleur, width=w)
        d.ellipse(P((15, 11), (17, 13)), fill=couleur)
    elif cle == "demarrage":
        d.arc(P((5, 5), (19, 19)), 300, 240, fill=couleur, width=w)
        d.line(P((12, 3), (12, 12)), fill=couleur, width=w)
    elif cle == "maj":
        d.line(P((12, 4), (12, 15)), fill=couleur, width=w)
        d.line(P((7, 10), (12, 15), (17, 10)), fill=couleur, width=w, joint="curve")
        d.line(P((5, 20), (19, 20)), fill=couleur, width=w)
    else:  # application : engrenage simplifié
        d.ellipse(P((9, 9), (15, 15)), outline=couleur, width=w)
        for a, b2 in (((12, 3), (12, 6)), ((12, 18), (12, 21)), ((3, 12), (6, 12)), ((18, 12), (21, 12)),
                      ((5.6, 5.6), (7.7, 7.7)), ((16.3, 16.3), (18.4, 18.4)), ((5.6, 18.4), (7.7, 16.3)),
                      ((16.3, 7.7), (18.4, 5.6))):
            d.line(P(a, b2), fill=couleur, width=w)
    im = im.resize((taille * 2, taille * 2), Image.LANCZOS)
    return ctk.CTkImage(light_image=im, dark_image=im, size=(taille, taille))


CATS_OPT = (("apparence", T("Appearance", "Apparence"), T("Language and color theme", "Langue et thème de couleur")),
            ("overlay", "Overlay", T("The counter shown on top of your games", "Le compteur affiché par-dessus tes jeux")),
            ("calcul", T("Calculation", "Calcul"),
             T("What counts as an action, and over how long", "Ce qui compte comme une action, et sur quelle durée")),
            ("raccourcis", T("Hotkeys", "Raccourcis"),
             T("Keys to control the overlay in game", "Touches pour piloter l'overlay en jeu")),
            ("sessions", "Sessions", T("Game detection and per-game stats", "Détection du jeu au premier plan et stats par jeu")),
            ("demarrage", T("Startup", "Démarrage"), T("How lightAPM starts", "Comment lightAPM se lance")),
            ("maj", T("Updates", "Mises à jour"), T("Nothing installs without your OK", "Rien ne s'installe sans ton accord")),
            ("application", "Application", T("Window, assistant and reset", "Fenêtre, assistant et remise à zéro")))
pages_opt, boutons_opt, icones_opt = {}, {}, {}
opt_actif = [None]


def montrer_opt(cle):
    if opt_actif[0]:
        pages_opt[opt_actif[0]].pack_forget()
    opt_actif[0] = cle
    pages_opt[cle].pack(fill="both", expand=True)
    for k, b in boutons_opt.items():
        on = k == cle
        b.configure(fg_color=FIELD if on else "transparent", text_color=TXT if on else TXT2,
                    font=police(13, on), image=icones_opt[k][on])


for _k, _nom, _desc in CATS_OPT:
    icones_opt[_k] = (icone(_k, MUTED), icone(_k, ACC_H))
    boutons_opt[_k] = ctk.CTkButton(cote, text=_nom, image=icones_opt[_k][0], compound="left", anchor="w",
                                    width=168, height=36, corner_radius=9, fg_color="transparent",
                                    hover_color=PANEL, text_color=TXT2, font=police(13),
                                    command=lambda k=_k: montrer_opt(k))
    boutons_opt[_k].pack(fill="x", pady=1)
    _p = ctk.CTkScrollableFrame(contenu, fg_color="transparent", corner_radius=0)
    ctk.CTkLabel(_p, text=_nom, font=police(22, True), anchor="w", height=28).pack(fill="x")
    ctk.CTkLabel(_p, text=_desc, font=police(13), text_color=MUTED, anchor="w", height=18).pack(
        fill="x", pady=(0, 14))
    pages_opt[_k] = _p
ctk.CTkLabel(cote, text=f"v{VERSION}", font=police(11, mono=True), text_color=DIM, anchor="w").pack(
    side="bottom", fill="x", padx=12, pady=(0, 4))


# --- Apparence ---
P = pages_opt["apparence"]
g = Groupe(P, T("Language", "Langue"))
LANGUE_ACTIVE = LANGUE


def choisir_langue_opt(nom):
    cfg["language"] = "fr" if nom == "Français" else "en"
    save()
    maj_bouton_redemarrer()


langue_seg = ctk.CTkSegmentedButton(g.c, values=["English", "Français"], font=police(12, True), height=30,
                                    text_color=TXT2, selected_color=ACC, selected_hover_color=ACC_H,
                                    unselected_color=BG, unselected_hover_color=TRACK, fg_color=BG,
                                    command=choisir_langue_opt)
langue_seg.set("Français" if LANGUE == "fr" else "English")
g.ligne(T("App language", "Langue de l'app"), langue_seg)
g = Groupe(P, T("Theme", "Thème"))
theme_box = ctk.CTkFrame(g.c, fg_color="transparent", corner_radius=0)
theme_btns = {}
THEME_ACTIF = cfg["theme"]
for _k, (_nom, _acc, _h, _d) in THEMES.items():
    theme_btns[_k] = ctk.CTkButton(theme_box, text="", width=30, height=30, corner_radius=15, fg_color=_acc,
                                   hover_color=_h, border_width=3, border_color=PANEL,
                                   command=lambda k=_k: choisir_theme_opt(k))
    theme_btns[_k].pack(side="left", padx=(6, 0))
theme_aide = g.ligne(T("Accent color", "Couleur d'accent"), theme_box, "")
g = Groupe(P, T("Apply", "Appliquer"))
theme_go = ctk.CTkButton(g.c, text=T("Restart to apply", "Redémarrer pour appliquer"), width=CW,
                         **dict(BTN, fg_color=ACC, hover_color=ACC_H, text_color=ON_ACC, border_width=0,
                                font=police(12, True)), command=lambda: redemarrer())
theme_go_aide = g.ligne(T("Language and theme", "Langue et thème"), theme_go,
                        T("Your stats are kept", "Tes stats sont gardées"))


def maj_bouton_redemarrer():
    change = cfg["theme"] != THEME_ACTIF or cfg["language"] != LANGUE_ACTIVE
    theme_go.configure(state="normal" if change else "disabled", fg_color=ACC if change else TRACK,
                       text_color=ON_ACC if change else DIM)


def choisir_theme_opt(k):
    cfg["theme"] = k
    save()
    for c, b in theme_btns.items():
        b.configure(border_color=TXT if c == k else PANEL)
    theme_aide.configure(text=THEMES[k][0] + ("" if k == THEME_ACTIF else T(" · not applied yet",
                                                                            " · pas encore appliqué")))
    maj_bouton_redemarrer()


choisir_theme_opt(cfg["theme"])

# --- Overlay ---
P = pages_opt["overlay"]
apercu_box = ctk.CTkFrame(P, fg_color=FIELD, border_width=1, border_color=BORDER2, corner_radius=14, height=96)
apercu_box.pack(fill="x", padx=(0, 6), pady=(0, 12))
apercu_box.pack_propagate(False)
_ap_txt = ctk.CTkFrame(apercu_box, fg_color="transparent", corner_radius=0)
_ap_txt.pack(side="left", padx=20)
legende(_ap_txt, T("Preview", "Aperçu")).pack(anchor="w")
ctk.CTkLabel(_ap_txt, text=T("Updates live", "Mis à jour en direct"), font=police(12), text_color=DIM, anchor="w", height=16).pack(
    anchor="w")
apercu = tk.Canvas(apercu_box, bg=FIELD, highlightthickness=0, width=int(150 * SC), height=int(80 * SC))
apercu.pack(side="right", padx=16)


def maj_apercu():
    try:
        apercu.delete("all")
    except (NameError, tk.TclError):
        return
    try:
        f = (cfg["font"], min(cfg["size"], 34), "bold" if cfg["bold"] else "normal")
        txt = live_val.get() + cfg["suffix"]
        x, y = int(apercu.cget("width")) - 4, int(apercu.cget("height")) // 2
        if cfg["outline_on"]:
            for dx, dy in OFFS:
                apercu.create_text(x + dx, y + dy, text=txt, font=f, fill=cfg["outline_color"], anchor="e")
        apercu.create_text(x, y, text=txt, font=f, fill=cfg["color"], anchor="e")
    except tk.TclError:
        pass


APRES_RESTYLE.append(maj_apercu)

g = Groupe(P, T("Text", "Texte"))
slider(g, T("Size", "Taille"), size_v, 8, 120, 112, lambda v: f"{int(round(v))}")
installees = {f.lower() for f in tkfont.families()}
candidates = ["Consolas", "Segoe UI", "Segoe UI Semibold", "Bahnschrift", "Cascadia Mono", "Arial",
              "Verdana", "Tahoma", "Trebuchet MS", "Courier New", "Lucida Console", "Impact", "Calibri"]
polices = [f for f in candidates if f.lower() in installees] or [cfg["font"]]
if cfg["font"] not in polices:
    polices.insert(0, cfg["font"])
combo = ctk.CTkComboBox(g.c, values=polices, width=CW, height=30, corner_radius=8, border_width=1,
                        font=police(12), dropdown_font=police(12), command=lambda v: font_v.set(v))
combo.set(cfg["font"])
combo.bind("<Return>", lambda e: font_v.set(combo.get()))
g.ligne(T("Font", "Police"), combo)
switch(g, T("Bold", "Gras"), bold_v)
g.ligne(T("Text after the number", "Texte après le chiffre"), ctk.CTkEntry(g.c, textvariable=suffix_v, width=CW, height=30, corner_radius=8,
                                              border_width=1, font=police(12), placeholder_text=T("e.g. APM", "ex. APM")))

g = Groupe(P, T("Colors", "Couleurs"))
g.ligne(T("Number", "Chiffre"), bouton_couleur(g.c, "color"))
switch(g, T("Outline", "Contour"), outline_v, T("Readable on any background", "Lisible sur tous les fonds"))
g.ligne(T("Outline color", "Couleur du contour"), bouton_couleur(g.c, "outline_color"))
slider(g, T("Opacity", "Opacité"), opac_v, 0.1, 1.0, 90, lambda v: f"{int(round(v * 100))}%")

g = Groupe(P, "Placement")
switch(g, T("Locked on startup", "Verrouillé au démarrage"), sl_v,
       T("Click-through: never gets in the way in game", "Clics traversants : ne gêne pas en jeu"))

# --- Calcul ---
P = pages_opt["calcul"]
g = Groupe(P, T("Counted actions", "Actions comptées"))
switch(g, T("Keyboard keys", "Touches clavier"), ck_v,
       T("The app's own hotkeys don't count", "Les raccourcis de l'app ne comptent pas"))
switch(g, T("Mouse clicks", "Clics souris"), cc_v)
switch(g, T("Mouse wheel", "Molette"), cs_v)
g = Groupe(P, T("Calculation", "Calcul"))
slider(g, T("Rolling window", "Fenêtre glissante"), win_v, 5, 180, 175, lambda v: f"{int(round(v))} s",
       T("Time window used for the live number", "Durée prise en compte pour le chiffre en direct"))
slider(g, T("Refresh rate", "Rafraîchissement"), ref_v, 20, 500, 48, lambda v: f"{int(round(v / 10)) * 10} ms")
g = Groupe(P, "Pause AFK")
slider(g, T("Pause after", "Pause après"), afk_v, 3, 60, 57, lambda v: f"{int(round(v))} s",
       T("With no input, APM freezes and resumes as soon as you play again",
         "Sans input, les APM se figent et reprennent dès que tu rejoues"))

# --- Raccourcis ---
P = pages_opt["raccourcis"]
g = Groupe(P, T("Keys", "Touches"))
hk_btn = {}


def hk_text(nom):
    return cfg[nom].upper()


def start_capture(nom):
    capture["target"] = nom
    hk_btn[nom].configure(text=T("Press a key…", "Appuie sur une touche…"), text_color=ACC_H, border_color=ACC)


for nom, lib in (("hk_lock", T("Lock / unlock overlay", "Verrouiller / déverrouiller")),
                 ("hk_toggle", T("Show / hide overlay", "Afficher / masquer l'overlay"))):
    hk_btn[nom] = ctk.CTkButton(g.c, text=hk_text(nom), width=CW, command=lambda n=nom: start_capture(n),
                                **dict(BTN, font=police(12, True, mono=True)))
    g.ligne(lib, hk_btn[nom], T("Click, then press a key", "Clique, puis appuie sur une touche"))

# --- Sessions ---
P = pages_opt["sessions"]
g = Groupe(P, T("Tracking", "Suivi"))
switch(g, T("Track the game in focus", "Suivre le jeu au premier plan"), track_v,
       T("On the main screen · browsers ignored", "Sur l'écran principal · navigateurs ignorés"))
slider(g, T("End after a break of", "Fin après une pause de"), gap_v, 1, 30, 29, lambda v: f"{int(round(v))} min",
       T("Come back before that and the session continues", "Si tu reviens avant, la session continue"))
switch(g, T("End-of-session summary", "Résumé en fin de session"), popup_v,
       T("Average, peak and low in a small card", "Moyenne, peak et low dans une petite carte"))

# --- Démarrage ---
P = pages_opt["demarrage"]
g = Groupe(P, T("Launch", "Lancement"))
switch(g, T("Start with Windows", "Lancer avec Windows"), auto_v,
       T("No administrator rights needed", "Sans droits administrateur"))
switch(g, T("Minimized to tray", "Réduit dans le tray"), smin_v,
       T("When the app starts with Windows", "Quand l'app se lance avec Windows"))
switch(g, T("Show overlay on startup", "Overlay visible au démarrage"), ovs_v)

# --- Mises à jour ---
P = pages_opt["maj"]
g = Groupe(P, "Version")
g.ligne(T("Installed version", "Version installée"), ctk.CTkLabel(g.c, text=f"v{VERSION}", font=police(13, True, mono=True),
                                         text_color=ACC_H, anchor="e"))
switch(g, T("Check on startup", "Vérifier au démarrage"), chk_v)


def verifier_clic():
    maj_statut.configure(text=T("Checking…", "Vérification…"))
    verifier_maj(manuel=True)


maj_statut = g.ligne(T("Check now", "Rechercher maintenant"),
                     ctk.CTkButton(g.c, text=T("Check for updates", "Rechercher une mise à jour"), width=CW,
                                                            command=verifier_clic, **BTN), etat_maj["texte"])
g = Groupe(P, T("What's new", "Nouveautés"))
g.ligne(T("Recent changes", "Ce qui a changé"),
        ctk.CTkButton(g.c, text=T("What's new", "Quoi de neuf"), width=CW, command=quoi_de_neuf, **BTN),
        f"Version {VERSION}")

# --- Application ---
P = pages_opt["application"]
g = Groupe(P, T("Window", "Fenêtre"))
switch(g, T("Minimize to tray", "Réduire dans le tray"), tray_v,
       T("The minimize button sends the app to the notification area",
         "Le bouton réduire envoie l'app dans la zone de notification"))
GARDER = ("x", "y", "placed", "logo_path", "theme", "setup_done", "win_geom", "last_version", "update_url",
          "autostart", "language")


def reset_all():
    global loading
    cfg.update({k: v for k, v in DEFAUT.items() if k not in GARDER})
    loading = True
    size_v.set(cfg["size"]); font_v.set(cfg["font"]); bold_v.set(int(cfg["bold"]))
    outline_v.set(int(cfg["outline_on"])); opac_v.set(cfg["opacity"]); suffix_v.set(cfg["suffix"])
    win_v.set(cfg["window"]); ref_v.set(cfg["refresh"]); ck_v.set(int(cfg["count_keys"]))
    cc_v.set(int(cfg["count_clicks"])); cs_v.set(int(cfg["count_scroll"])); sl_v.set(int(cfg["start_locked"]))
    tray_v.set(int(cfg["tray_on_minimize"])); track_v.set(int(cfg["track_apps"]))
    gap_v.set(cfg["session_gap"]); popup_v.set(int(cfg["session_popup"])); afk_v.set(cfg["afk_delay"])
    smin_v.set(int(cfg["start_minimized"])); ovs_v.set(int(cfg["overlay_on_start"]))
    chk_v.set(int(cfg["check_updates"]))
    loading = False
    combo.set(cfg["font"])
    for n in couleur_btn:
        maj_couleur_btn(n)
    for n in hk_btn:
        hk_btn[n].configure(text=hk_text(n))
    restyle()
    save_later()


def relancer_assistant():
    cfg["setup_done"] = False
    save()
    redemarrer()


g = Groupe(P, "Configuration")
g.ligne(T("Setup assistant", "Écran de configuration"),
        ctk.CTkButton(g.c, text=T("Run the assistant again", "Relancer l'assistant"), width=CW,
                      command=relancer_assistant, **BTN),
        T("Language, theme, inputs, startup…", "Langue, thème, inputs, démarrage…"))
reset_btn = ctk.CTkButton(g.c, text=T("Reset everything", "Tout réinitialiser"), width=CW,
                          **dict(BTN, text_color=DANGER))


def reset_confirme():
    if reset_btn.cget("text") != T("Confirm?", "Confirmer ?"):  # 2 clics pour éviter les accidents
        reset_btn.configure(text=T("Confirm?", "Confirmer ?"), fg_color="#3a1220")
        root.after(3000, lambda: reset_btn.configure(text=T("Reset everything", "Tout réinitialiser"), fg_color=BG))
        return
    reset_btn.configure(text=T("Reset everything", "Tout réinitialiser"), fg_color=BG)
    reset_all()


reset_btn.configure(command=reset_confirme)
g.ligne(T("Default settings", "Réglages par défaut"), reset_btn,
        T("Your stats, language and theme are kept", "Tes stats, ta langue et ton thème sont gardés"))

montrer_opt("overlay" if cfg["setup_done"] else "apparence")
maj_apercu()

# ---------- Boucle ----------
def place_defaut():
    """Coin haut-droit de l'écran."""
    ov.update_idletasks()
    return max(0, root.winfo_screenwidth() - ov.winfo_reqwidth() - 40), 40


_dernier = [None]
_afk_ov = [False]


def update():
    while actions:
        a = actions.popleft()
        if a[0] == "lock":
            set_lock(not locked)
        elif a[0] == "toggle":
            toggle_overlay()
        elif a[0] == "open":
            from_tray()
        elif a[0] == "quit":
            quitter()
            return
        elif a[0] == "maj":
            resultat_maj(*a[1:])
        elif a[0] == "maj_ok":
            redemarrer()
            return
        elif a[0] == "maj_err":
            etat_maj["texte"] = a[1]
            maj_statut.configure(text=a[1])
            if etat_maj["boite"] and etat_maj["boite"].winfo_exists():
                etat_maj["boite"].statut.configure(text=a[1], text_color=DANGER)
        elif a[0] == "captured":
            if a[2] != "esc":
                cfg[a[1]] = a[2]
                save_later()
            hk_btn[a[1]].configure(text=hk_text(a[1]), text_color=TXT2, border_color=BORDER2)
    fenetre_visible = root.winfo_viewable()
    if overlay_visible or fenetre_visible:
        now = time.time()
        fen = cfg["window"]
        afk = est_afk(now)
        ref = derniere_act[0] + cfg["afk_delay"] if afk else now  # AFK : valeur figée
        with verrou:
            while events and events[0] < ref - fen:
                events.popleft()
            n = len(events)
        ecoule = ref - debut
        duree = max(min(ecoule, fen), min(MIN_FENETRE, fen))
        val = round(n * 60 / duree)
        calibrage = ecoule < fen  # la fenêtre glissante n'est pas encore pleine
        if overlay_visible:
            txt = str(val) + cfg["suffix"]
            for it in ombres + [texte]:
                canvas.itemconfig(it, text=txt)
            if afk != _afk_ov[0]:  # en pause : chiffre atténué
                _afk_ov[0] = afk
                canvas.itemconfig(texte, fill=_mix(cfg["color"], "#6b6b6b", 0.65) if afk else cfg["color"])
        if fenetre_visible and (val, afk, calibrage) != _dernier[0]:
            _dernier[0] = (val, afk, calibrage)
            live_val.set(str(val))
            maj_apercu()
            live_lbl.configure(text=T("PAUSED · AFK", "EN PAUSE · AFK") if afk else (T("CALIBRATING…", "CALIBRAGE…") if calibrage
                                                                    else "APM LIVE"),
                               text_color=DIM if (afk or calibrage) else MUTED)
    root.after(cfg["refresh"], update)


restyle()
def overlay_visible_a_lecran(x, y):
    """L'overlay est-il sur un écran branché ? (sinon, ex. 2e écran débranché, il serait introuvable)"""
    if not WIN:
        return True
    u = ctypes.windll.user32
    vx, vy, vw, vh = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))  # écran virtuel (tous les écrans)
    return vx - 20 <= x <= vx + vw - 30 and vy - 10 <= y <= vy + vh - 30


# L'overlay reprend sa dernière position ; en haut à droite au premier lancement ou s'il est hors écran
if (not cfg["placed"] and (cfg["x"], cfg["y"]) == (DEFAUT["x"], DEFAUT["y"]))         or not overlay_visible_a_lecran(cfg["x"], cfg["y"]):
    cfg["x"], cfg["y"] = place_defaut()
ov.geometry(f"+{cfg['x']}+{cfg['y']}")
set_lock(cfg["start_locked"] and cfg["placed"])  # 1er lancement : déverrouillé pour le placer
update()
tick_suivi()
if cfg["autostart"]:
    regler_autostart(True)  # garde la commande à jour si le dossier a bougé
if not cfg["overlay_on_start"]:
    toggle_overlay()
if AUTOSTART_LANCE and cfg["start_minimized"]:
    root.after(300, to_tray if cfg["tray_on_minimize"] else root.iconify)
ancienne = cfg["last_version"] or ("1.3.0" if DEJA_INSTALLE else "")
if ancienne and version_tuple(ancienne) < version_tuple(VERSION):
    root.after(900, quoi_de_neuf)
cfg["last_version"] = VERSION
save()
if cfg["check_updates"]:
    root.after(4000, verifier_maj)
root.mainloop()
