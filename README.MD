## About Endfield Mod Manager

- Mod manager for **Arknights: Endfield**
- Enable and disable mods safely
- Uses asset replacement instead of injection
- **Does not currently inject DLLs**

**An open-source launcher and mod manager for Arknights: Endfield**

## For Users (Run Without an EXE)

1. **Install Python**
   - Install Python 3.10+ from https://www.python.org/
   - Make sure **“Add Python to PATH”** is checked during install.

2. **Install dependencies**
   ```powershell
   pip install -r requirements.txt

### Developer setup

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pyinstaller launcher\__main__.py

## Goals
- Provide a safe, extendable mod manager
- Encourage cosmetic and UI-based mods
- Allow community contributions
- **Working On Injecting DLLs**

## Limitations

- This mod manager uses **file-based asset replacement only**
- **No runtime code injection** is performed
- **Does not currently inject DLLs**
- Does not modify or hook game executables or memory
- Limited to assets that the game already loads (models, textures, configs, etc.)
- Script-based or logic-changing mods are **not supported**
- Mod compatibility depends on the game’s asset loading behavior
- Conflicting mods that replace the same files may overwrite each other

This design is intentional to remain compatible with **IL2CPP-based games** and to reduce the risk of crashes or anti-cheat issues.

- Note: You Can Use This Free Of Permission Either For Learning Or Usage!

## License
MIT

## Other
This project is a community-driven mod manager.
It does not support cheating, exploits, or violation of game terms.
Users are responsible for compliance with the game's EULA.

