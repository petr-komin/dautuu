"""File tools — čtení a zápis souborů v AI pracovním adresáři (/workspace).

Všechny cesty jsou sandboxované do AGENT_WORKSPACE (výchozí /workspace).
Path traversal (../../etc/passwd apod.) je zakázán — vrátí chybu.

Dostupné tools:
  - read_file(path)                  — přečte soubor
  - write_file(path, content)        — zapíše / přepíše soubor
  - list_files(path=".")             — vypíše obsah adresáře
  - create_directory(path)           — vytvoří adresář
  - delete_file(path)                — smaže soubor (ne adresář)
"""
from __future__ import annotations

import os
import logging
from pathlib import Path

log = logging.getLogger("dautuu.tools.files")

# ---------------------------------------------------------------------------
# Workspace root — konfigurovatelný přes env proměnnou
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/workspace")).resolve()


def _safe_path(relative: str) -> Path:
    """Převede relativní cestu na absolutní uvnitř workspace.

    Raises ValueError při pokusu o path traversal mimo workspace.
    """
    # Odstraň leading slash — chceme relativní cestu vůči workspace
    relative = relative.lstrip("/")
    # Pokud model poslal absolutní cestu začínající workspace rootem (např. "workspace/foo.txt"),
    # odstraň ten prefix také aby nedošlo k dvojitému workspace/workspace/
    workspace_prefix = str(WORKSPACE_ROOT).lstrip("/") + "/"
    if relative.startswith(workspace_prefix):
        relative = relative[len(workspace_prefix):]
    target = (WORKSPACE_ROOT / relative).resolve()
    if not str(target).startswith(str(WORKSPACE_ROOT)):
        raise ValueError(
            f"Přístup mimo workspace není povolen: {relative!r}. "
            f"Použij relativní cestu bez lomítka na začátku, např. 'soubor.txt' nebo 'slozka/soubor.txt'."
        )
    return target


# ---------------------------------------------------------------------------
# Tool definice — OpenAI/Together/Ollama formát
# ---------------------------------------------------------------------------

FILE_TOOLS_OPENAI: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Přečte obsah souboru z pracovního adresáře. "
                "Použij když potřebuješ zjistit obsah existujícího souboru."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relativní cesta k souboru v pracovním adresáři, např. 'notes.txt' nebo 'projekt/main.py'.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Zapíše nebo přepíše soubor v pracovním adresáři. "
                "Vytvoří soubor i potřebné adresáře pokud neexistují."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relativní cesta k souboru, např. 'output.txt' nebo 'src/script.py'.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Obsah který se zapíše do souboru.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "Vypíše obsah adresáře v pracovním adresáři. "
                "Použij pro zjištění jaké soubory a složky existují."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relativní cesta k adresáři. Výchozí je '.' (kořen workspace).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Vytvoří adresář (včetně rodičovských) v pracovním adresáři.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relativní cesta k adresáři který se má vytvořit.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Smaže soubor z pracovního adresáře. Adresáře nesmaže.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relativní cesta k souboru který se má smazat.",
                    }
                },
                "required": ["path"],
            },
        },
    },
]

# Anthropic formát
FILE_TOOLS_ANTHROPIC: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Přečte obsah souboru z pracovního adresáře. "
            "Použij když potřebuješ zjistit obsah existujícího souboru."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relativní cesta k souboru v pracovním adresáři.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Zapíše nebo přepíše soubor v pracovním adresáři. "
            "Vytvoří soubor i potřebné adresáře pokud neexistují."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativní cesta k souboru."},
                "content": {"type": "string", "description": "Obsah souboru."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "Vypíše obsah adresáře v pracovním adresáři.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relativní cesta k adresáři. Výchozí '.'.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "create_directory",
        "description": "Vytvoří adresář (včetně rodičovských) v pracovním adresáři.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativní cesta k adresáři."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Smaže soubor z pracovního adresáře.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativní cesta k souboru."}
            },
            "required": ["path"],
        },
    },
]

# Sada názvů tool pro rychlé lookupování
FILE_TOOL_NAMES = {"read_file", "write_file", "list_files", "create_directory", "delete_file"}


# ---------------------------------------------------------------------------
# Implementace tools
# ---------------------------------------------------------------------------

def read_file(path: str) -> str:
    """Přečte soubor a vrátí jeho obsah jako string."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return f"[CHYBA] Soubor neexistuje: {path}"
        if not target.is_file():
            return f"[CHYBA] Cesta není soubor: {path}"
        content = target.read_text(encoding="utf-8", errors="replace")
        log.info("FILE_READ path=%r size=%d", path, len(content))
        return content
    except ValueError as e:
        return f"[CHYBA] {e}"
    except Exception as e:
        log.error("FILE_READ_ERROR path=%r: %s", path, e)
        return f"[CHYBA] Nelze přečíst soubor: {e}"


def write_file(path: str, content: str) -> str:
    """Zapíše content do souboru. Vytvoří adresáře pokud neexistují."""
    try:
        target = _safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        log.info("FILE_WRITE path=%r size=%d", path, len(content))
        return f"Soubor úspěšně zapsán: {path} ({len(content)} znaků)"
    except ValueError as e:
        return f"[CHYBA] {e}"
    except Exception as e:
        log.error("FILE_WRITE_ERROR path=%r: %s", path, e)
        return f"[CHYBA] Nelze zapsat soubor: {e}"


def list_files(path: str = ".") -> str:
    """Vypíše obsah adresáře."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return f"[CHYBA] Adresář neexistuje: {path}"
        if not target.is_dir():
            return f"[CHYBA] Cesta není adresář: {path}"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        if not entries:
            return f"Adresář je prázdný: {path}"
        lines = [f"Obsah adresáře: {path}/"]
        for entry in entries:
            rel = entry.relative_to(WORKSPACE_ROOT)
            if entry.is_dir():
                lines.append(f"  [dir]  {rel}/")
            else:
                size = entry.stat().st_size
                lines.append(f"  [file] {rel}  ({size} B)")
        log.info("FILE_LIST path=%r entries=%d", path, len(entries))
        return "\n".join(lines)
    except ValueError as e:
        return f"[CHYBA] {e}"
    except Exception as e:
        log.error("FILE_LIST_ERROR path=%r: %s", path, e)
        return f"[CHYBA] Nelze vypsat adresář: {e}"


def create_directory(path: str) -> str:
    """Vytvoří adresář včetně rodičovských."""
    try:
        target = _safe_path(path)
        target.mkdir(parents=True, exist_ok=True)
        log.info("DIR_CREATE path=%r", path)
        return f"Adresář vytvořen: {path}"
    except ValueError as e:
        return f"[CHYBA] {e}"
    except Exception as e:
        log.error("DIR_CREATE_ERROR path=%r: %s", path, e)
        return f"[CHYBA] Nelze vytvořit adresář: {e}"


def delete_file(path: str) -> str:
    """Smaže soubor."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return f"[CHYBA] Soubor neexistuje: {path}"
        if not target.is_file():
            return f"[CHYBA] Cesta není soubor (adresáře nemažu): {path}"
        target.unlink()
        log.info("FILE_DELETE path=%r", path)
        return f"Soubor smazán: {path}"
    except ValueError as e:
        return f"[CHYBA] {e}"
    except Exception as e:
        log.error("FILE_DELETE_ERROR path=%r: %s", path, e)
        return f"[CHYBA] Nelze smazat soubor: {e}"


def dispatch_file_tool(name: str, args: dict) -> str:
    """Zavolá správnou file tool funkci podle názvu."""
    if name == "read_file":
        return read_file(args.get("path", ""))
    if name == "write_file":
        return write_file(args.get("path", ""), args.get("content", ""))
    if name == "list_files":
        return list_files(args.get("path", "."))
    if name == "create_directory":
        return create_directory(args.get("path", ""))
    if name == "delete_file":
        return delete_file(args.get("path", ""))
    return f"[CHYBA] Neznámý file tool: {name}"
