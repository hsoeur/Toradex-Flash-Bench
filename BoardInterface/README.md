# BoardInterface

This folder contains a Python port of the original C# InterfaceBoard driver.

It talks to the board through the same serial SCPI protocol:

- `*IDN?`
- `FIXT:ON <index>`
- `FIXT:OFF <index>`
- `FIXT?`
- `TARG <index>`
- `SYST:ERR?`
- `I2C:*` commands for the PCF8563 RTC

## Install

From this repository:

```powershell
pip install -e .
```

The only runtime dependency is `pyserial`.

## Power control example

```python
from board_interface import InterfaceBoard

POWER_OUTPUT = 0

with BoardInterface("COM3", 115200) as board:
    board.power_off(POWER_OUTPUT)
    board.power_on(POWER_OUTPUT)
```

For a full power cycle:

```python
from board_interface import InterfaceBoard

with BoardInterface("COM3", 115200) as board:
    board.power_cycle(output_index=0, off_time_s=1.0)
```

## CLI example

```powershell
python examples/toradex_flash_bench_power.py --port COM3 --power-output 0 --action cycle
```

Use the `--power-output` value that matches the InterfaceBoard output wired to the
Toradex board power relay.


## Interface graphique de test

Une petite interface Tkinter est disponible pour tester la carte en reel avec des boutons.

Depuis ce dossier, avec l'environnement virtuel active :

```powershell
python examples\board_interface_gui.py
```

Le port par defaut est `COM6`. L'interface permet de :

- connecter / deconnecter la carte
- lire `*IDN?`
- lire le masque `FIXT?`
- activer ou desactiver les sorties 0 a 7
- faire un power cycle sur une sortie choisie
- lire et ecrire `TARG`
- envoyer une commande SCPI brute
- lire et effacer les erreurs SCPI
