# Specification d'integration - BoardInterface dans Toradex Flash Bench

## 1. Objectif

Cette specification decrit comment integrer le package Python `BoardInterface` dans un autre projet Python, notamment `Toradex Flash Bench`, afin de piloter automatiquement l'alimentation des cartes Toradex.

L'objectif fonctionnel est de remplacer une action manuelle de l'utilisateur, par exemple appuyer sur un bouton d'alimentation, par une commande logicielle envoyee a l'InterfaceBoard.

Le projet appelant, ici Toradex Flash Bench, doit pouvoir :

- ouvrir une connexion avec l'InterfaceBoard ;
- couper l'alimentation d'une carte Toradex ;
- remettre l'alimentation ;
- faire un cycle OFF/ON automatique ;
- gerer les erreurs de communication ;
- continuer ou arreter le processus de flash selon le resultat.

## 2. Principe d'integration

`BoardInterface` est un package Python externe au projet Toradex Flash Bench.

Il doit etre installe dans l'environnement Python utilise par Toradex Flash Bench, puis importe comme n'importe quelle dependance Python.

Schema logique :

```text
Toradex Flash Bench
        |
        | import board_interface
        v
BoardInterface
        |
        | pyserial / COM6 / 115200 bauds
        v
InterfaceBoard materielle
        |
        | sortie fixture 0..7
        v
Alimentation carte Toradex
```

## 3. Prerequis

### 3.1 Prerequis logiciel

- Python 3.10 ou superieur
- `pip`
- acces au projet `BoardInterface`
- dependance `pyserial`

Le projet `BoardInterface` se trouve actuellement ici :

```text
C:\ClientHS\Dev\Python\BoardInterface
```

### 3.2 Prerequis materiel

- InterfaceBoard branchee au PC en USB
- Port COM connu, par exemple `COM6`
- Une sortie fixture de l'InterfaceBoard cablee vers le relais ou circuit de controle d'alimentation Toradex

Exemple :

```text
Sortie fixture 0 -> relais alimentation carte Toradex
```

Dans ce cas, la configuration devra utiliser :

```python
POWER_OUTPUT = 0
```

## 4. Installation dans l'environnement de Toradex Flash Bench

### 4.1 Cas recommande : installation locale editable

Activer l'environnement virtuel du projet Toradex Flash Bench, puis installer `BoardInterface` depuis son chemin local.

Exemple :

```powershell
cd C:\ClientHS\Dev\ToradexFlashBench
.\.venv\Scripts\Activate.ps1
pip install -e C:\ClientHS\Dev\Python\BoardInterface
```

Avantage : les modifications faites dans `BoardInterface` sont directement visibles depuis Toradex Flash Bench.

### 4.2 Verifier l'installation

Depuis l'environnement Python de Toradex Flash Bench :

```powershell
python -c "from board_interface import BoardInterface; print(BoardInterface)"
```

Si l'import fonctionne, l'installation est correcte.

### 4.3 Verifier la dependance pyserial

```powershell
python -c "import serial; print(serial.VERSION)"
```

Si cette commande echoue, installer la dependance :

```powershell
pip install pyserial
```

## 5. Configuration recommandee

Il est recommande de ne pas coder le port COM et l'index de sortie directement partout dans le code.

Creer une configuration centralisee dans Toradex Flash Bench.

Exemple simple :

```python
BOARD_INTERFACE_PORT = "COM6"
BOARD_INTERFACE_BAUDRATE = 115200
BOARD_INTERFACE_TIMEOUT_MS = 10000
TORADEX_POWER_OUTPUT = 0
TORADEX_POWER_OFF_TIME_S = 1.0
```

Ces valeurs peuvent ensuite etre deplacees dans :

- un fichier `.json` ;
- un fichier `.ini` ;
- un fichier `.yaml` ;
- des variables d'environnement ;
- une configuration deja existante dans Toradex Flash Bench.

## 6. Utilisation minimale

Exemple minimal pour faire un cycle d'alimentation :

```python
from board_interface import BoardInterface

with BoardInterface("COM6", 115200) as board:
    board.power_cycle(0, off_time_s=1.0)
```

Cette sequence effectue :

```text
1. ouverture du port COM6
2. envoi de FIXT:OFF 0
3. attente de 1 seconde
4. envoi de FIXT:ON 0
5. fermeture du port COM6
```

## 7. Wrapper recommande pour Toradex Flash Bench

Pour eviter de disperser le code `BoardInterface` dans tout le projet Toradex Flash Bench, il est recommande de creer un petit wrapper dedie.

Exemple de fichier :

```text
ToradexFlashBench/power_control.py
```

Contenu propose :

```python
from __future__ import annotations

from board_interface import BoardInterface


class ToradexPowerController:
    def __init__(
        self,
        port: str = "COM6",
        baudrate: int = 115200,
        output_index: int = 0,
        timeout_ms: int = 10000,
        off_time_s: float = 1.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.output_index = output_index
        self.timeout_ms = timeout_ms
        self.off_time_s = off_time_s

    def power_on(self) -> None:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            board.power_on(self.output_index)

    def power_off(self) -> None:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            board.power_off(self.output_index)

    def power_cycle(self) -> None:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            board.power_cycle(self.output_index, self.off_time_s)

    def check_connection(self) -> str:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            return board.id
```

Utilisation :

```python
power = ToradexPowerController(
    port="COM6",
    output_index=0,
    off_time_s=1.0,
)

print(power.check_connection())
power.power_cycle()
```

## 8. Integration dans un workflow de flash

### 8.1 Avant integration

Un workflow manuel peut ressembler a ceci :

```python
print("Veuillez eteindre puis rallumer la carte Toradex.")
input("Appuyez sur Enter lorsque c'est fait...")

start_flash()
```

### 8.2 Apres integration

Le workflow peut devenir :

```python
from power_control import ToradexPowerController

power = ToradexPowerController(port="COM6", output_index=0)

power.power_cycle()
start_flash()
```

### 8.3 Integration avec verification

Version plus robuste :

```python
from power_control import ToradexPowerController

power = ToradexPowerController(port="COM6", output_index=0)

try:
    board_id = power.check_connection()
    print(f"InterfaceBoard detectee: {board_id}")
    power.power_cycle()
except Exception as exc:
    print(f"Erreur pendant le pilotage alimentation: {exc}")
    raise

start_flash()
```

## 9. Gestion des erreurs attendues

### 9.1 Port COM incorrect

Symptome probable :

```text
could not open port 'COM6'
```

Action : verifier le port avec :

```powershell
Get-PnpDevice -Class Ports
```

### 9.2 Carte qui ne repond pas

Symptome probable :

```text
TimeoutError: Interface board has not responded in time
```

Ca signifie que le port est peut-etre ouvert, mais qu'aucune reponse n'arrive.

Verifier :

- le baudrate ;
- le firmware de la carte ;
- le cable USB ;
- le fait qu'un autre logiciel n'utilise pas deja le port ;
- le timeout configure.

### 9.3 Commande refusee

Symptome probable :

```text
SCPICommandFailedError
```

Cela signifie que la carte a repondu `-1`.

Ca peut arriver si :

- la commande est invalide ;
- l'index de sortie est incorrect ;
- la carte est dans un etat d'erreur ;
- le firmware ne supporte pas cette commande.

### 9.4 Sortie incorrecte

Si `power_cycle(0)` fonctionne logiciellement mais ne coupe pas la carte Toradex, le probleme est probablement materiel ou de configuration.

Verifier quelle sortie physique controle reellement l'alimentation.

Tester les sorties via l'interface graphique :

```powershell
python C:\ClientHS\Dev\Python\BoardInterface\examples\board_interface_gui.py
```

## 10. Strategie de retry recommandee

Dans un banc de flash, une erreur de communication peut etre temporaire. Il peut etre utile de faire une ou deux tentatives avant d'abandonner.

Exemple :

```python
import time

from power_control import ToradexPowerController


def power_cycle_with_retry(power: ToradexPowerController, retries: int = 2) -> None:
    last_error: Exception | None = None

    for attempt in range(1, retries + 2):
        try:
            power.power_cycle()
            return
        except Exception as exc:
            last_error = exc
            print(f"Power cycle failed, attempt {attempt}: {exc}")
            time.sleep(1)

    raise RuntimeError("Unable to power cycle Toradex board") from last_error
```

Utilisation :

```python
power = ToradexPowerController(port="COM6", output_index=0)
power_cycle_with_retry(power)
```

## 11. Mode simulation pour developpement

Pour ne pas dependre du materiel pendant le developpement de Toradex Flash Bench, il est recommande de prevoir un mode simulation.

Exemple :

```python
class SimulatedPowerController:
    def power_on(self) -> None:
        print("[SIMU] power_on")

    def power_off(self) -> None:
        print("[SIMU] power_off")

    def power_cycle(self) -> None:
        print("[SIMU] power_cycle")

    def check_connection(self) -> str:
        return "SIMULATED-BOARD"
```

Puis choisir l'implementation selon la configuration :

```python
if config.use_simulated_power:
    power = SimulatedPowerController()
else:
    power = ToradexPowerController(port="COM6", output_index=0)
```

Cela permet de tester le workflow logiciel sans brancher l'InterfaceBoard.

## 12. Interface graphique comme outil de validation

Avant d'utiliser `BoardInterface` dans Toradex Flash Bench, il faut valider le comportement avec l'interface graphique.

Commande :

```powershell
cd C:\ClientHS\Dev\Python\BoardInterface
.\.venv\Scripts\Activate.ps1
python examples\board_interface_gui.py
```

Sequence de validation :

1. Selectionner `COM6`.
2. Cliquer sur `Connecter`.
3. Cliquer sur `Lire ID (*IDN?)`.
4. Cliquer sur `Lire sorties (FIXT?)`.
5. Tester `ON` puis `OFF` sur une sortie non critique.
6. Identifier la sortie qui controle l'alimentation Toradex.
7. Tester `Power cycle` sur cette sortie.
8. Reporter l'index de sortie dans la configuration Toradex Flash Bench.

## 13. Tests automatises

Les tests de `BoardInterface` peuvent etre lances independamment :

```powershell
cd C:\ClientHS\Dev\Python\BoardInterface
python -m unittest discover -s tests -v
```

Ces tests ne necessitent pas la carte. Ils verifient que les appels Python generent les bonnes commandes SCPI.

Dans Toradex Flash Bench, il est recommande d'ajouter des tests unitaires autour du wrapper `ToradexPowerController`, en mockant `BoardInterface`.

Exemple de test conceptuel :

```python
from unittest.mock import Mock, patch

from power_control import ToradexPowerController


def test_power_cycle_calls_board_interface():
    with patch("power_control.BoardInterface") as board_cls:
        board = board_cls.return_value.__enter__.return_value

        power = ToradexPowerController(port="COM6", output_index=0)
        power.power_cycle()

        board.power_cycle.assert_called_once_with(0, 1.0)
```

## 14. Regles d'utilisation recommandees

- Ne pas ouvrir plusieurs connexions serie en parallele sur le meme port COM.
- Toujours fermer la connexion apres utilisation.
- Preferer `with BoardInterface(...) as board:`.
- Centraliser le port COM et l'index de sortie dans une configuration.
- Tester la sortie physique avant de l'utiliser dans un workflow automatique.
- En cas d'erreur, lire `SYST:ERR?` si la carte repond encore.
- Garder un mode simulation pour developper sans materiel.

## 15. Exemple complet d'utilisation dans Toradex Flash Bench

```python
from __future__ import annotations

from board_interface import BoardInterface


class ToradexPowerController:
    def __init__(
        self,
        port: str,
        output_index: int,
        baudrate: int = 115200,
        timeout_ms: int = 10000,
        off_time_s: float = 1.0,
    ) -> None:
        self.port = port
        self.output_index = output_index
        self.baudrate = baudrate
        self.timeout_ms = timeout_ms
        self.off_time_s = off_time_s

    def verify(self) -> str:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            return board.id

    def power_cycle(self) -> None:
        with BoardInterface(self.port, self.baudrate, self.timeout_ms) as board:
            board.power_cycle(self.output_index, self.off_time_s)


def flash_toradex_board() -> None:
    power = ToradexPowerController(
        port="COM6",
        output_index=0,
        off_time_s=1.0,
    )

    print(f"InterfaceBoard: {power.verify()}")
    power.power_cycle()

    # Lancer ensuite le processus existant de flash Toradex.
    # start_flash()
```

## 16. Critere d'acceptation

L'integration est consideree valide si :

1. Toradex Flash Bench importe correctement `board_interface`.
2. Le port COM configure permet de lire `board.id`.
3. La sortie configuree coupe et remet bien l'alimentation de la carte Toradex.
4. Le workflow de flash n'a plus besoin d'une action manuelle utilisateur pour l'alimentation.
5. Les erreurs de communication sont visibles et n'echouent pas silencieusement.
