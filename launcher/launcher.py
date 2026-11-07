"""
Lanceur de lightAPM (compilé en lightAPM.exe à la racine du projet).

1. Trouve Python 3.9+. S'il manque : télécharge l'installeur officiel de python.org, vérifie son empreinte
   SHA-256, l'installe sans console ni droits admin (winget en secours), avec l'accord de l'utilisateur.
2. Installe les dépendances de requirements.txt si elles manquent (une seule fois).
3. Lance app/lightapm.py sans console, en lui passant les arguments reçus (ex. --autostart).

Compiler : launcher\\build.bat
"""
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request

NOM = "lightAPM"
if getattr(sys, "frozen", False):  # lightAPM.exe : posé à la racine du projet
    RACINE = os.path.dirname(os.path.abspath(sys.executable))
else:  # launcher/launcher.py
    RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RACINE, "app", "lightapm.py")
REQ = os.path.join(RACINE, "requirements.txt")
DATA = os.path.join(RACINE, "data")
MARQUEUR = os.path.join(DATA, "deps.ok")
MODULES = "import customtkinter, pynput, pystray, PIL"
SANS_CONSOLE = 0x08000000  # CREATE_NO_WINDOW
# Python installé si l'utilisateur n'en a pas : installeurs officiels python.org (signés par la
# Python Software Foundation), vérifiés par leur empreinte SHA-256 avant d'être lancés.
PY_VERSION = "3.13.17"
PY_SHA256 = {"amd64": "5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190",
             "arm64": "3089a1977c32b26f5078e5a7d0285b7a861b8c96250c5dac3b6af59fbe9e9a75"}


def _langue():
    """Langue choisie dans l'app (data/config.json), anglais par défaut."""
    try:
        import json
        with open(os.path.join(DATA, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("language", "en")
    except Exception:
        return "en"


LANGUE = _langue()


def T(en, fr):
    return fr if LANGUE == "fr" else en


def message(texte, titre=NOM, style=0x40):
    """Boîte de message Windows (0x40 info, 0x10 erreur, 0x24 question oui/non). Renvoie 6 pour Oui."""
    return ctypes.windll.user32.MessageBoxW(None, texte, titre, style)


def env_propre():
    """Environnement sans les variables du lanceur compilé (PyInstaller pointe TCL_LIBRARY, etc. vers
    un dossier temporaire qui disparaît à sa fermeture : l'app ne pourrait plus démarrer Tk)."""
    retirer = ("TCL_LIBRARY", "TK_LIBRARY", "PYTHONHOME", "PYTHONPATH")
    return {k: v for k, v in os.environ.items() if k not in retirer and not k.startswith(("_PYI", "_MEI"))}


def executer(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=SANS_CONSOLE, env=env_propre(),
                          **kw)


def tester_python(cmd):
    """Renvoie le chemin de python.exe si `cmd` lance un Python 3.9+ fonctionnel."""
    try:
        r = executer(cmd + ["-c", "import sys; print(sys.version_info >= (3, 9)); print(sys.executable)"],
                     timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    lignes = r.stdout.strip().splitlines()
    if r.returncode == 0 and len(lignes) == 2 and lignes[0] == "True":
        return lignes[1]
    return None


def trouver_python():
    candidats = []
    if shutil.which("py"):
        candidats.append([shutil.which("py"), "-3"])
    for nom in ("python", "python3"):
        if shutil.which(nom):
            candidats.append([shutil.which(nom)])
    base = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
    if os.path.isdir(base):  # installé par winget / python.org mais PATH pas encore rechargé
        for d in sorted(os.listdir(base), reverse=True):
            candidats.append([os.path.join(base, d, "python.exe")])
    for c in candidats:
        exe = tester_python(c)
        if exe:
            return exe
    return None


def architecture():
    a = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    return "arm64" if "ARM" in a else "amd64"


def telecharger(url, dest, progres):
    """Télécharge `url` dans `dest` en signalant l'avancement (0 à 1). Renvoie l'empreinte SHA-256."""
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": f"{NOM}-launcher"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total, lu = int(r.headers.get("Content-Length") or 0), 0
        while True:
            bloc = r.read(256 * 1024)
            if not bloc:
                break
            f.write(bloc)
            h.update(bloc)
            lu += len(bloc)
            if total:
                progres(lu / total)
    return h.hexdigest()


def installer_python():
    """Installe Python pour l'utilisateur courant, sans droits admin. Renvoie le chemin de python.exe."""
    if message(T("lightAPM needs Python, which isn't installed on this PC.\n\n"
                 f"Download and install it automatically now?\n(Python {PY_VERSION} from python.org, about "
                 "30 MB, no administrator rights needed)",
                 "lightAPM a besoin de Python, qui n'est pas installé sur ce PC.\n\n"
                 f"Le télécharger et l'installer automatiquement maintenant ?\n(Python {PY_VERSION} depuis "
                 "python.org, environ 30 Mo, sans droits administrateur)"), style=0x24) != 6:
        return None
    arch = architecture()
    url = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-{arch}.exe"
    dest = os.path.join(tempfile.gettempdir(), f"lightapm-python-{PY_VERSION}-{arch}.exe")

    def job(etat):
        etat(T("Downloading Python…", "Téléchargement de Python…"), 0.0)
        empreinte = telecharger(url, dest, lambda x: etat(None, x))
        if empreinte != PY_SHA256[arch]:
            raise RuntimeError(T("the downloaded file doesn't match (SHA-256)",
                                 "le fichier téléchargé ne correspond pas (SHA-256)"))
        etat(T("Installing Python…\nThis can take a minute.", "Installation de Python…\nÇa peut prendre une minute."),
             None)
        r = executer([dest, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=0",
                      "Include_test=0", "Include_doc=0", "Shortcuts=0", "AssociateFiles=0"], timeout=1200)
        if r.returncode != 0:
            raise RuntimeError(T(f"the Python installer stopped (code {r.returncode})",
                                 f"l'installeur de Python s'est arrêté (code {r.returncode})"))

    prog = Progression(T("Preparing the Python installation…", "Préparation de l'installation de Python…"))
    ok = prog.lancer_tache(job)
    try:
        os.remove(dest)
    except OSError:
        pass
    python = trouver_python() if ok else None
    if not python and shutil.which("winget"):  # secours : winget
        Progression(T("Installing Python with winget…", "Installation de Python avec winget…")).lancer(
            ["winget", "install", "-e", "--id", "Python.Python.3.13", "--scope", "user",
             "--accept-package-agreements", "--accept-source-agreements", "--silent"])
        python = trouver_python()
    if not python:
        message(T("Python couldn't be installed automatically"
                  + (f" ({prog.sortie})" if prog.sortie else "") + ".\n\n"
                  "Install it from https://www.python.org/downloads/ (tick \"Add python.exe to PATH\"), "
                  "then run lightAPM.exe again.",
                  "Python n'a pas pu être installé automatiquement"
                  + (f" ({prog.sortie})" if prog.sortie else "") + ".\n\n"
                  "Installe-le depuis https://www.python.org/downloads/ (coche « Add python.exe to PATH »), "
                  "puis relance lightAPM.exe."), style=0x10)
    return python


def signature(python):
    try:
        with open(REQ, "rb") as f:
            req = f.read()
    except OSError:
        req = b""
    return hashlib.sha256(python.encode() + req).hexdigest()


def deps_ok(python):
    try:
        with open(MARQUEUR, encoding="utf-8") as f:
            if f.read() == signature(python):
                return True  # déjà vérifié avec ce Python et ces dépendances
    except OSError:
        pass
    return executer([python, "-c", MODULES], timeout=60).returncode == 0


def installer_deps(python):
    if executer([python, "-m", "pip", "--version"]).returncode != 0:
        executer([python, "-m", "ensurepip", "--user"], timeout=300)
    cmd = [python, "-m", "pip", "install", "--user", "--disable-pip-version-check", "-r", REQ]
    return Progression(T("Installing lightAPM components…\nThis only happens once.",
                          "Installation des composants de lightAPM…\nÇa n'arrive qu'une fois.")).lancer(cmd)


class Progression:
    """Petite fenêtre « installation en cours » pendant une opération longue."""

    def __init__(self, texte):
        self.texte, self.ok, self.sortie = texte, False, ""

    def lancer(self, cmd):
        """Exécute une commande (succès = code de retour 0)."""
        def job(etat):
            r = executer(cmd, timeout=1800)
            self.sortie = (r.stdout + r.stderr)[-1500:]
            if r.returncode != 0:
                raise RuntimeError(f"code {r.returncode}")
        ok = self.lancer_tache(job)
        return ok

    def lancer_tache(self, tache):
        """Exécute tache(etat) en arrière-plan ; etat(texte ou None, avancement 0-1 ou None = indéterminé).
        Succès si la tâche ne lève pas d'exception (son message est gardé dans self.sortie)."""
        import tkinter as tk
        from tkinter import ttk
        w = tk.Tk()
        w.title(NOM)
        w.configure(bg="#07060a")
        w.resizable(False, False)
        ico = os.path.join(RACINE, "app", "assets", "lightapm_icon.ico")
        if os.path.exists(ico):
            try:
                w.iconbitmap(ico)
            except tk.TclError:
                pass
        label = tk.Label(w, text=self.texte, bg="#07060a", fg="#f4f1fa", font=("Segoe UI", 11), justify="left",
                         width=38, anchor="w")
        label.pack(padx=28, pady=(24, 12), anchor="w")
        st = ttk.Style(w)
        st.theme_use("clam")
        st.configure("L.Horizontal.TProgressbar", troughcolor="#1a1524", background="#a855f7",
                     bordercolor="#07060a", lightcolor="#a855f7", darkcolor="#a855f7")
        barre = ttk.Progressbar(w, mode="indeterminate", length=340, style="L.Horizontal.TProgressbar",
                                maximum=100)
        barre.pack(padx=28, pady=(0, 26))
        barre.start(12)
        w.update_idletasks()
        w.geometry(f"+{(w.winfo_screenwidth() - w.winfo_reqwidth()) // 2}"
                   f"+{(w.winfo_screenheight() - w.winfo_reqheight()) // 3}")
        etat_ui = {"texte": None, "avance": None, "fini": False, "mode": "indeterminate"}

        def etat(texte, avance):  # appelé depuis la tâche : l'interface est mise à jour par rafraichir()
            if texte is not None:
                etat_ui["texte"] = texte
            etat_ui["avance"] = avance

        def rafraichir():
            if etat_ui["texte"] is not None:
                label.configure(text=etat_ui["texte"])
                etat_ui["texte"] = None
            mode = "determinate" if etat_ui["avance"] is not None else "indeterminate"
            if mode != etat_ui["mode"]:
                etat_ui["mode"] = mode
                barre.stop()
                barre.configure(mode=mode)
                if mode == "indeterminate":
                    barre.start(12)
            if mode == "determinate":
                barre["value"] = etat_ui["avance"] * 100
            if etat_ui["fini"]:
                w.destroy()
                return
            w.after(100, rafraichir)

        def job():
            try:
                tache(etat)
                self.ok = True
            except Exception as e:
                self.sortie = self.sortie or str(e)
            etat_ui["fini"] = True

        threading.Thread(target=job, daemon=True).start()
        w.after(100, rafraichir)
        w.mainloop()
        return self.ok


def main():
    if not os.path.exists(APP):
        message(T(f"File not found:\n{APP}\n\nKeep lightAPM.exe at the root of the lightAPM folder.",
                  f"Fichier introuvable :\n{APP}\n\nGarde lightAPM.exe à la racine du dossier lightAPM."),
                style=0x10)
        return
    force = os.environ.get("LIGHTAPM_TEST_INSTALL_PYTHON") == "1"  # test : simule un PC sans Python
    python = (None if force else trouver_python()) or installer_python()
    if not python:
        return
    os.makedirs(DATA, exist_ok=True)
    if not deps_ok(python):
        if not installer_deps(python) or executer([python, "-c", MODULES]).returncode != 0:
            message(T("Installing the components failed.\n\nOpen a terminal and run:\n",
                      "L'installation des composants a échoué.\n\nOuvre un terminal et lance :\n")
                    + f'"{python}" -m pip install -r "{REQ}"', style=0x10)
            return
    with open(MARQUEUR, "w", encoding="utf-8") as f:
        f.write(signature(python))
    pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = python
    subprocess.Popen([pythonw, APP] + sys.argv[1:], cwd=os.path.dirname(APP), creationflags=SANS_CONSOLE,
                     close_fds=True, env=env_propre())


if __name__ == "__main__":
    main()
