# Documentation technique - BoardInterface

## 1. Objectif du projet

`BoardInterface` est un driver Python permettant de piloter une carte d'interface materielle depuis un PC.

Le besoin principal est de remplacer une action manuelle, comme appuyer sur un bouton d'alimentation d'une carte Toradex, par une commande logicielle envoyee automatiquement depuis un projet Python comme Toradex Flash Bench.

En pratique, le projet permet de :

- ouvrir une communication serie USB avec l'InterfaceBoard ;
- envoyer des commandes SCPI a la carte ;
- activer ou desactiver des sorties physiques ;
- faire un cycle d'alimentation automatique ;
- lire l'identite de la carte ;
- lire les erreurs SCPI ;
- piloter certaines commandes I2C, notamment le module RTC PCF8563.

Le projet Python est une reecriture du projet C# original `InterfaceBoard`.

## 2. Vue d'ensemble

Le principe general est le suivant :

```text
Toradex Flash Bench / script Python
        |
        | import board_interface
        v
BoardInterface Python
        |
        | port serie USB, commandes texte SCPI
        v
InterfaceBoard materielle
        |
        | sorties fixture / relais / signaux
        v
Carte Toradex ou alimentation a piloter
```

Le PC n'agit donc pas directement sur l'alimentation. Il envoie une commande a l'InterfaceBoard, et c'est l'InterfaceBoard qui active ou desactive une sortie physique.

## 3. Installation

Depuis le dossier du projet :

```powershell
cd C:\ClientHS\Dev\Python\BoardInterface
```

Creer un environnement virtuel :

```powershell
python -m venv .venv
```

Activer l'environnement :

```powershell
.\.venv\Scripts\Activate.ps1
```

Installer le projet en mode editable :

```powershell
pip install -e .
```

Le mode editable signifie que les modifications faites dans le code source sont immediatement prises en compte par Python, sans devoir reinstaller le package a chaque changement.

La dependance principale est :

```text
pyserial
```

Elle sert a communiquer avec le port serie USB.

## 4. Structure du projet

```text
BoardInterface/
|-- board_interface/
|   |-- __init__.py
|   |-- board.py
|   |-- commands.py
|   |-- errors.py
|   |-- pcf8563.py
|   |-- usb_comm.py
|
|-- examples/
|   |-- board_interface_gui.py
|   |-- toradex_flash_bench_power.py
|
|-- tests/
|   |-- test_commands.py
|   |-- test_interface_board.py
|
|-- docs/
|   |-- interface_board_functioning.md
|
|-- pyproject.toml
|-- README.md
```

## 5. Les modules principaux

### 5.1 `board_interface.board`

Ce fichier contient la classe principale :

```python
BoardInterface
```

C'est la classe que le reste du projet doit utiliser.

Exemple :

```python
from board_interface import BoardInterface

with BoardInterface("COM6", 115200) as board:
    print(board.id)
    board.power_cycle(0, off_time_s=1.0)
```

La classe `BoardInterface` expose des methodes de haut niveau :

```python
board.init()
board.close()
board.power_on(0)
board.power_off(0)
board.power_cycle(0, off_time_s=1.0)
board.reset()
board.clear_errors()
board.get_error()
```

Elle expose aussi des proprietes :

```python
board.id
board.fixture_outputs_mask
board.active_target
board.timeout_ms
board.rtc_module
```

### 5.2 `board_interface.usb_comm`

Ce fichier contient la couche de communication serie.

Son role est de :

- ouvrir le port serie ;
- envoyer une commande terminee par `\n` ;
- attendre une reponse ;
- detecter les timeouts ;
- lever une exception si la carte repond `-1`.

Cette couche utilise `pyserial`.

Exemple de commande envoyee :

```text
FIXT:ON 0\n
```

Exemple de reponse attendue :

```text
1
```

Dans le protocole :

```text
1  = commande acceptee
-1 = commande refusee ou echouee
```

### 5.3 `board_interface.commands`

Ce fichier centralise les constantes SCPI.

Exemples :

```python
IDN = "*IDN?"
RESET = "*RST"
CLEAR_STATUS = "*CLS"
FIXTURE_OUTPUT_ON = "FIXT:ON"
FIXTURE_OUTPUT_OFF = "FIXT:OFF"
QUERY_FIXTURE = "FIXT?"
TARGET = "TARG"
```

Cela evite d'ecrire les chaines de commande directement dans plusieurs fichiers.

### 5.4 `board_interface.errors`

Ce fichier contient :

```python
SCPICommandFailedError
SCPIError
```

`SCPICommandFailedError` est levee lorsque la carte retourne `-1`.

`SCPIError` transforme un code d'erreur SCPI en message lisible.

Exemple :

```python
error = board.get_error()
print(error.error_code)
print(error.message)
```

### 5.5 `board_interface.pcf8563`

Ce fichier pilote le module RTC PCF8563 via les commandes I2C exposees par l'InterfaceBoard.

Il permet de :

- assigner l'adresse I2C du composant ;
- regler la frequence SCL ;
- lire ou ecrire les registres de date/heure ;
- lire ou ecrire un objet `datetime` complet.

Exemple :

```python
from datetime import datetime
from board_interface import BoardInterface

with BoardInterface("COM6", 115200) as board:
    board.rtc_module.assign_to_i2c(100000)
    board.rtc_module.set_datetime(datetime.now())
    print(board.rtc_module.get_datetime())
```

## 6. Cycle de vie d'une connexion

Il y a deux facons d'utiliser la carte.

### 6.1 Avec `with`, recommande

```python
with BoardInterface("COM6", 115200) as board:
    print(board.id)
```

Cette forme appelle automatiquement :

```python
board.init()
```

au debut, puis :

```python
board.close()
```

a la fin, meme en cas d'erreur.

### 6.2 Sans `with`

```python
board = BoardInterface("COM6", 115200)
board.init()

try:
    print(board.id)
finally:
    board.close()
```

Cette forme est plus longue, mais permet un controle explicite.

## 7. Commandes principales

### 7.1 Lire l'identite de la carte

Code Python :

```python
print(board.id)
```

Commande envoyee :

```text
*IDN?
```

Role : verifier que la communication PC <-> InterfaceBoard fonctionne.

C'est le premier test a faire avec une vraie carte.

### 7.2 Lire le masque des sorties

Code Python :

```python
mask = board.fixture_outputs_mask
```

Commande envoyee :

```text
FIXT?
```

Le resultat est un nombre decimal representant les sorties actives sous forme de masque binaire.

Exemple :

```text
20 decimal = 00010100 binaire
```

Cela signifie que les sorties 2 et 4 sont actives si la numerotation commence a 0.

### 7.3 Activer une sortie

Code Python :

```python
board.enable_fixture_output(0)
```

ou :

```python
board.power_on(0)
```

Commande envoyee :

```text
FIXT:ON 0
```

Role : activer la sortie physique 0.

### 7.4 Desactiver une sortie

Code Python :

```python
board.disable_fixture_output(0)
```

ou :

```python
board.power_off(0)
```

Commande envoyee :

```text
FIXT:OFF 0
```

Role : desactiver la sortie physique 0.

### 7.5 Faire un cycle d'alimentation

Code Python :

```python
board.power_cycle(0, off_time_s=1.0)
```

Commandes envoyees :

```text
FIXT:OFF 0
FIXT:ON 0
```

Entre les deux commandes, Python attend `off_time_s` secondes.

C'est la methode la plus utile pour remplacer un appui manuel sur un bouton d'alimentation.

### 7.6 Lire la cible active

Code Python :

```python
target = board.active_target
```

Commande envoyee :

```text
TARG?
```

### 7.7 Changer la cible active

Code Python :

```python
board.active_target = 2
```

Commande envoyee :

```text
TARG 2
```

Les valeurs acceptees vont de 0 a 6.

### 7.8 Reset de la carte

Code Python :

```python
board.reset()
```

Commande envoyee :

```text
*RST
```

### 7.9 Effacer les erreurs

Code Python :

```python
board.clear_errors()
```

Commande envoyee :

```text
*CLS
```

### 7.10 Lire une erreur

Code Python :

```python
error = board.get_error()
print(error)
```

Commande envoyee :

```text
SYST:ERR?
```

Exemple de resultat :

```text
-102: Syntax error
```

## 8. Commandes brutes

Si une commande n'est pas encore encapsulee dans une methode Python, il est possible de l'envoyer directement.

### 8.1 Commande sans reponse metier

```python
board.write_scpi_command("FIXT:ON 0")
```

Cette methode attend quand meme que la carte retourne `1` pour confirmer la reussite.

### 8.2 Commande avec reponse

```python
response = board.query_scpi_command("*IDN?")
print(response)
```

Cette methode retourne directement la reponse texte de la carte.

## 9. Gestion des erreurs

### 9.1 Timeout

Si la carte ne repond pas dans le temps prevu, le driver leve :

```python
TimeoutError
```

Ca peut arriver si :

- le mauvais port COM est utilise ;
- la carte n'est pas branchee ;
- le baudrate est incorrect ;
- la carte est bloquee ;
- la commande envoyee ne provoque aucune reponse.

### 9.2 Commande refusee

Si la carte repond :

```text
-1
```

le driver leve :

```python
SCPICommandFailedError
```

Cela signifie que la carte a bien repondu, mais qu'elle a refuse la commande.

### 9.3 Parametres invalides cote Python

Certaines erreurs sont bloquees avant meme l'envoi serie.

Exemple :

```python
board.power_on(8)
```

Les sorties valides vont de 0 a 7. Le driver leve donc :

```python
ValueError
```

## 10. Tester le projet sans carte

Les tests unitaires utilisent un faux port serie appele `FakeSerial`.

Il permet de verifier que le code envoie les bonnes commandes sans avoir besoin de brancher la vraie carte.

Commande :

```powershell
python -m unittest discover -s tests -v
```

Les tests verifient notamment :

- `*IDN?`
- `*RST`
- `*CLS`
- `SYST:ERR?`
- `FIXT?`
- `FIXT:ON`
- `FIXT:OFF`
- `TARG?`
- `TARG`
- `I2C:SLAV`
- `I2C:FREQ`
- `I2C:WRIT`
- `I2C:WRIT:ALL`
- `I2C:READ?`
- `I2C:READ:ALL?`

## 11. Tester avec une vraie carte

### 11.1 Identifier le port COM

Sous PowerShell :

```powershell
Get-PnpDevice -Class Ports
```

Repere le port, par exemple :

```text
COM6
```

### 11.2 Tester l'identite

```powershell
python -c "from board_interface import BoardInterface; b=BoardInterface('COM6',115200); b.init(); print(b.id); b.close()"
```

Si cette commande fonctionne, la communication serie est valide.

### 11.3 Tester une sortie

Activer la sortie 0 :

```powershell
python -c "from board_interface import BoardInterface; b=BoardInterface('COM6',115200); b.init(); b.power_on(0); print(b.fixture_outputs_mask); b.close()"
```

Desactiver la sortie 0 :

```powershell
python -c "from board_interface import BoardInterface; b=BoardInterface('COM6',115200); b.init(); b.power_off(0); print(b.fixture_outputs_mask); b.close()"
```

### 11.4 Faire un power cycle

```powershell
python examples\toradex_flash_bench_power.py --port COM6 --power-output 0 --action cycle --off-time 1
```

## 12. Interface graphique de test

Une interface graphique est disponible :

```powershell
python examples\board_interface_gui.py
```

Elle permet de tester manuellement :

- la connexion ;
- `*IDN?` ;
- `FIXT?` ;
- `FIXT:ON` et `FIXT:OFF` pour les sorties 0 a 7 ;
- `TARG?` et `TARG` ;
- `*RST` ;
- `*CLS` ;
- `SYST:ERR?` ;
- une commande SCPI brute.

Le port par defaut dans l'interface est `COM6`.

## 13. Integration dans Toradex Flash Bench

Dans Toradex Flash Bench, l'objectif est de remplacer une etape manuelle comme :

```python
input("Appuyez sur le bouton d'alimentation puis Enter...")
```

par :

```python
from board_interface import BoardInterface

POWER_OUTPUT = 0

with BoardInterface("COM6", 115200) as board:
    board.power_cycle(POWER_OUTPUT, off_time_s=1.0)
```

Le point important est de connaitre la sortie physique reliee au controle d'alimentation.

Si la sortie 0 commande le relais d'alimentation :

```python
POWER_OUTPUT = 0
```

Si c'est la sortie 3 :

```python
POWER_OUTPUT = 3
```

## 14. Sequence recommandee pour valider le materiel

1. Brancher l'InterfaceBoard en USB.
2. Identifier le port COM.
3. Lancer l'interface graphique.
4. Cliquer sur `Connecter`.
5. Cliquer sur `Lire ID (*IDN?)`.
6. Lire `FIXT?`.
7. Tester `ON` puis `OFF` sur une sortie non critique.
8. Verifier physiquement le changement d'etat.
9. Tester `Power cycle` sur la sortie reliee a la carte Toradex.
10. Integrer l'appel dans Toradex Flash Bench.

## 15. Resume court

`BoardInterface` est une couche Python qui transforme des appels simples :

```python
board.power_on(0)
board.power_off(0)
board.power_cycle(0)
```

en commandes SCPI envoyees sur le port serie :

```text
FIXT:ON 0
FIXT:OFF 0
```

C'est cette traduction qui permet d'automatiser l'alimentation d'une carte Toradex depuis un banc de test logiciel.
