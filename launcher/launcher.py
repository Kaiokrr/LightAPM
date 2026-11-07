"""
Lanceur de lightAPM (compilé en lightAPM.exe à la racine du projet).

1. Trouve Python 3.9+ (et propose de l'installer avec winget s'il manque).
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
import threading

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


def installer_python():
    if message(T("Python isn't installed on this PC, and lightAPM needs it.\n\n"
                 "Install it now (Python 3.12, no administrator rights needed)?",
                 "Python n'est pas installé sur ce PC, et lightAPM en a besoin.\n\n"
                 "L'installer maintenant (Python 3.12, sans droits administrateur) ?"), style=0x24) != 6:
        return None
    if not shutil.which("winget"):
        message(T("Install Python from https://www.python.org/downloads/ "
                  "(tick \"Add python.exe to PATH\"), then run lightAPM.exe again.",
                  "Installe Python depuis https://www.python.org/downloads/ "
                  "(coche « Add python.exe to PATH »), puis relance lightAPM.exe."))
        return None
    ok = Progression(T("Installing Python 3.12…", "Installation de Python 3.12…")).lancer(
        ["winget", "install", "-e", "--id", "Python.Python.3.12", "--scope", "user",
         "--accept-package-agreements", "--accept-source-agreements", "--silent"])
    return trouver_python() if ok else None


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
    """Petite fenêtre « installation en cours » pendant une commande longue."""

    def __init__(self, texte):
        self.texte, self.ok, self.sortie = texte, False, ""

    def lancer(self, cmd):
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
        tk.Label(w, text=self.texte, bg="#07060a", fg="#f4f1fa", font=("Segoe UI", 11), justify="left").pack(
            padx=28, pady=(24, 12), anchor="w")
        st = ttk.Style(w)
        st.theme_use("clam")
        st.configure("L.Horizontal.TProgressbar", troughcolor="#1a1524", background="#a855f7",
                     bordercolor="#07060a", lightcolor="#a855f7", darkcolor="#a855f7")
        barre = ttk.Progressbar(w, mode="indeterminate", length=340, style="L.Horizontal.TProgressbar")
        barre.pack(padx=28, pady=(0, 26))
        barre.start(12)
        w.update_idletasks()
        w.geometry(f"+{(w.winfo_screenwidth() - w.winfo_reqwidth()) // 2}"
                   f"+{(w.winfo_screenheight() - w.winfo_reqheight()) // 3}")

        def job():
            try:
                r = executer(cmd, timeout=1800)
                self.ok, self.sortie = r.returncode == 0, (r.stdout + r.stderr)[-1500:]
            except Exception as e:
                self.sortie = str(e)
            w.after(0, w.destroy)

        threading.Thread(target=job, daemon=True).start()
        w.mainloop()
        return self.ok


def main():
    if not os.path.exists(APP):
        message(T(f"File not found:\n{APP}\n\nKeep lightAPM.exe at the root of the lightAPM folder.",
                  f"Fichier introuvable :\n{APP}\n\nGarde lightAPM.exe à la racine du dossier lightAPM."),
                style=0x10)
        return
    python = trouver_python() or installer_python()
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
