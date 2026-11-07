<div align="center">

<img src="app/assets/lightapm_tile.png" alt="Logo lightAPM" width="96">

# lightAPM

**Ton APM en direct par-dessus tes jeux, et tes stats par jeu, session après session.**

![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-a855f7?style=flat-square)
![Version](https://img.shields.io/badge/version-1.5.0-a855f7?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.9%2B-2a2140?style=flat-square)
![Gratuit](https://img.shields.io/badge/prix-gratuit-2a2140?style=flat-square)

### [Télécharger lightAPM](https://github.com/Kaiokrr/lightAPM/archive/refs/heads/main.zip)

<sub>Décompresse le ZIP, double-clique sur <code>lightAPM.exe</code>. C'est tout.</sub>

</div>

<br>

<table>
  <tr>
    <td align="center" width="33%"><img src="docs/stats.png" alt="Onglet Stats : moyenne et peak record de chaque jeu"><br><sub><b>Tes jeux</b> · moyenne et peak de chacun</sub></td>
    <td align="center" width="33%"><img src="docs/detail.png" alt="Détail d'un jeu : moyenne, peak, low, tendance, courbe et sessions"><br><sub><b>Détail d'un jeu</b> · courbe et historique</sub></td>
    <td align="center" width="33%"><img src="docs/options.png" alt="Options rangées par catégorie avec aperçu de l'overlay"><br><sub><b>Options</b> · aperçu de l'overlay en direct</sub></td>
  </tr>
</table>

## Ce que fait lightAPM

| | |
| --- | --- |
| **Overlay discret** | Un simple chiffre, fond transparent, où tu veux sur l'écran. Verrouillé, les clics le traversent : il ne gêne jamais en jeu. |
| **Stats par jeu** | Le jeu ouvert est détecté tout seul. Chaque session enregistre ta moyenne, ton peak et ton low, et tes stats se cumulent au fil des parties. |
| **Courbe d'évolution** | Pour chaque jeu : ta moyenne session après session, la plage entre ton low et ton peak, et ta tendance récente. |
| **Pause AFK** | Tu lâches le clavier ? Les APM se figent. Tu reprends ? Ils repartent exactement où ils en étaient. |
| **Résumé de fin de partie** | Une petite carte en bas de l'écran avec la moyenne, le peak et le low de la session. |
| **Installation en un clic** | `lightAPM.exe` installe tout ce qu'il faut au premier lancement, puis te guide pour les réglages. |
| **Démarrage avec Windows** | En option, dans la zone de notification, sans droits administrateur. |
| **Mises à jour** | Proposées au démarrage, jamais installées sans ton accord. |

## Installation

1. **[Télécharge le ZIP](https://github.com/Kaiokrr/lightAPM/archive/refs/heads/main.zip)** et décompresse-le où tu veux (par exemple dans `Documents`).
2. Double-clique sur **`lightAPM.exe`**.
3. Suis l'assistant : thème, ce qui compte comme une action, démarrage. Une minute, montre en main.

Au premier lancement, `lightAPM.exe` vérifie que Python est installé (et propose de l'installer s'il manque),
puis installe les composants nécessaires. Ça prend environ une minute et n'arrive qu'une fois.

> [!NOTE]
> Windows peut afficher **« Windows a protégé votre ordinateur »** : l'exe n'est pas signé (un certificat
> coûte cher pour un projet gratuit). Clique sur **Informations complémentaires**, puis **Exécuter quand même**.
> Le code du lanceur est lisible dans [`launcher/launcher.py`](launcher/launcher.py).

Avec Git : `git clone https://github.com/Kaiokrr/lightAPM.git`

## Comment sont calculées les stats

- **APM en direct** : tes actions des 60 dernières secondes (réglable), ramenées à une minute. Pendant la première
  minute, l'en-tête affiche « Calibrage » et le chiffre monte progressivement, sans faux pic au lancement.
- **Une action** = une touche pressée, un clic ou un cran de molette (chacun peut être désactivé). Maintenir
  une touche ne compte qu'une fois.
- **Moyenne** d'une session : toutes tes actions divisées par ton temps de jeu réel (pauses AFK exclues).
- **Peak** : ta meilleure minute de jeu complète.
- **Low** : ta pire minute de jeu active (les minutes AFK ne comptent pas).
- **Session** : elle commence quand le jeu passe au premier plan sur ton écran principal, et se termine quand
  tu le fermes ou le quittes plus de 5 minutes (réglable). Les sessions de moins d'une minute sont ignorées.

Les navigateurs (Chrome, Edge, Firefox, Opera, Brave…) ne sont jamais comptés.

## 7 thèmes

<img src="docs/themes.png" alt="Les 7 thèmes : Violet, Glace, Braise, Néon, Ambre, Sakura, Mono">

Au choix dans l'assistant ou dans **Options › Apparence**.

## Raccourcis

| Touche | Action |
| :---: | --- |
| <kbd>F8</kbd> | Verrouiller / déverrouiller l'overlay. Déverrouillé, glisse-le où tu veux : sa position est gardée. |
| <kbd>F9</kbd> | Afficher / masquer l'overlay |

Modifiables dans **Options › Raccourcis**.

## Questions fréquentes

<details>
<summary><b>Est-ce que lightAPM enregistre ce que je tape ?</b></summary>
<br>
Non. Il compte les actions, il ne garde pas les touches. Tout reste sur ton PC, dans le dossier <code>data/</code>.
La seule connexion à Internet sert à vérifier s'il existe une nouvelle version (désactivable dans <b>Options › Mises à jour</b>).
</details>

<details>
<summary><b>Est-ce que ça peut poser problème avec un anti-cheat ?</b></summary>
<br>
lightAPM ne touche pas au jeu : il ne lit ni ne modifie sa mémoire et n'injecte rien. Il écoute le clavier et la
souris au niveau de Windows et regarde quelle fenêtre est au premier plan, comme un logiciel d'overlay classique.
</details>

<details>
<summary><b>Où sont mes stats ? Comment repartir de zéro ?</b></summary>
<br>
Dans <code>data/stats.json</code> (et tes réglages dans <code>data/config.json</code>), à côté de l'exe.
Pour effacer un seul jeu : ouvre-le dans l'onglet Stats, puis <b>Supprimer</b>. Pour tout effacer : supprime le dossier <code>data/</code>.
</details>

<details>
<summary><b>Un jeu est rangé dans « Apps » au lieu de « Jeux »</b></summary>
<br>
Ouvre-le dans l'onglet Stats et change sa catégorie avec le menu en haut à droite. Tu peux aussi le renommer.
</details>

<details>
<summary><b>Comment désinstaller ?</b></summary>
<br>
Si tu as activé <b>Lancer avec Windows</b>, désactive-le d'abord dans <b>Options › Démarrage</b>. Ensuite, supprime simplement le dossier.
</details>

<details>
<summary><b>Pour les développeurs</b></summary>
<br>

```
lightAPM.exe          lanceur : installe ce qu'il faut et démarre l'app
app/lightapm.py       l'application (customtkinter, pynput, pystray, Pillow)
app/assets/           logo et icônes
launcher/             code source du lanceur + build.bat pour le compiler
requirements.txt      dépendances Python
version.json          dernière version publiée, lue par l'app pour proposer les mises à jour
data/                 réglages et stats de l'utilisateur (créé au lancement, ignoré par Git)
```

**Lancer depuis le code**

```
pip install -r requirements.txt
pythonw app/lightapm.py
```

**Recompiler le lanceur** : `pip install pyinstaller`, puis `launcher\build.bat`.

**Publier une mise à jour**

1. Dans `app/lightapm.py`, augmente `VERSION` et ajoute les nouveautés dans `NOUVEAUTES`.
2. Reporte le même numéro et les notes dans `version.json`.
3. Pousse sur `main`.

Au démarrage suivant, les utilisateurs se voient proposer la mise à jour. L'app télécharge le nouveau
`app/lightapm.py`, vérifie qu'il est valide, garde une copie `.bak`, puis redémarre et affiche « Quoi de neuf ».
</details>

<br>

<div align="center">
<sub>Fait par <a href="https://github.com/Kaiokrr">Kaiokrr</a></sub>
</div>
