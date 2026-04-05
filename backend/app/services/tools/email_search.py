"""Email search tool — hybridní vyhledávání v emailové databázi.

Strategie:
  1. Embeduj query → vektorové vyhledávání přes HNSW index (~14 ms, 508 indexovaných emailů)
  2. ILIKE search přes subject + body_text (~3 s, pokrývá všechny emaily)
  3. Merge výsledků: ILIKE má přednost (ORDER BY date DESC = nejnovější první),
     vektorové výsledky doplní zbývající sloty (bonus pro sémantické dotazy)

Pokud EMAIL_DB_URL není nastaven, tool se tiše přeskočí.
Read-only: každé spojení má SET TRANSACTION READ ONLY na úrovni session.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TypedDict

from app.core.config import settings

log = logging.getLogger("dautuu.tools.email_search")

# ---------------------------------------------------------------------------
# Connection pool — lazy init, read-only
# ---------------------------------------------------------------------------

_pool = None  # asyncpg.Pool | None


async def _get_pool():
    """Vrátí (nebo vytvoří) asyncpg pool. None pokud URL není nastaveno."""
    global _pool
    if _pool is not None:
        return _pool
    if not settings.email_db_url:
        return None
    try:
        import asyncpg

        url = settings.email_db_url
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

        _pool = await asyncpg.create_pool(
            dsn=url,
            min_size=1,
            max_size=3,
            command_timeout=12,
            init=_init_conn,
        )
        log.info("EMAIL_DB pool ready (%s)", url.split("@")[-1])
        return _pool
    except Exception as exc:
        log.error("EMAIL_DB pool FAILED: %s: %s", type(exc).__name__, exc)
        return None


async def _init_conn(conn) -> None:
    """Inicializace každého spojení v poolu: read-only + timeout."""
    await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    await conn.execute("SET statement_timeout = '11000'")  # 11 s


# ---------------------------------------------------------------------------
# Embedding query — sdílí model s dautuu
# ---------------------------------------------------------------------------

async def _embed_query(query: str) -> list[float] | None:
    """Embeduje query stejným modelem jako emailový klient. None při chybě."""
    try:
        from app.services.rag.embeddings import embed
        vec = await embed(query)
        return vec
    except Exception as exc:
        log.warning("EMAIL_EMBED_FAILED: %s: %s — použiju ILIKE fallback", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Tool definice pro LLM providery (OpenAI / Together formát + Anthropic)
# ---------------------------------------------------------------------------

EMAIL_SEARCH_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "search_emails",
        "description": (
            "Prohledá emailovou schránku uživatele a vrátí relevantní emaily. "
            "Použij kdykoliv uživatel zmiňuje emaily, zprávy, komunikaci, korespondenci, "
            "nebo chce najít konkrétní email — třeba od určité osoby nebo firmy, "
            "na určité téma nebo z určitého časového období. "
            "Hledej i přes jméno nebo část emailové adresy (např. 'ponechal' najde "
            "'vladimir.ponechal@vlapon.com'). Po nalezení emailů shrň jejich obsah "
            "srozumitelně — nejen metadata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Co hledat — klíčová slova, jméno osoby, firma, téma. "
                        "Např. 'Ponechal analytika', 'faktura Alza', 'schůzka projekt'."
                    ),
                },
                "from_filter": {
                    "type": "string",
                    "description": (
                        "Filtruj emaily od konkrétního odesílatele "
                        "(část jména nebo emailové adresy, case-insensitive). Volitelné."
                    ),
                },
                "folder": {
                    "type": "string",
                    "description": (
                        "Omez hledání na složku: 'INBOX', 'Sent', 'Odeslaná pošta' apod. "
                        "Volitelné — bez filtru se hledá ve všech složkách."
                    ),
                },
                "date_from": {
                    "type": "string",
                    "description": "Hledej jen emaily od tohoto data (YYYY-MM-DD). Volitelné.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Hledej jen emaily do tohoto data (YYYY-MM-DD). Volitelné.",
                },
            },
            "required": ["query"],
        },
    },
}

EMAIL_SEARCH_TOOL_ANTHROPIC = {
    "name": "search_emails",
    "description": (
        "Prohledá emailovou schránku uživatele a vrátí relevantní emaily. "
        "Použij kdykoliv uživatel zmiňuje emaily, zprávy, komunikaci, korespondenci, "
        "nebo chce najít konkrétní email — třeba od určité osoby nebo firmy, "
        "na určité téma nebo z určitého časového období. "
        "Hledej i přes jméno nebo část emailové adresy (např. 'ponechal' najde "
        "'vladimir.ponechal@vlapon.com'). Po nalezení emailů shrň jejich obsah "
        "srozumitelně — nejen metadata."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Co hledat — klíčová slova, jméno osoby, firma, téma. "
                    "Např. 'Ponechal analytika', 'faktura Alza', 'schůzka projekt'."
                ),
            },
            "from_filter": {
                "type": "string",
                "description": (
                    "Filtruj emaily od konkrétního odesílatele "
                    "(část jména nebo emailové adresy, case-insensitive). Volitelné."
                ),
            },
            "folder": {
                "type": "string",
                "description": (
                    "Omez hledání na složku: 'INBOX', 'Sent', 'Odeslaná pošta' apod. "
                    "Volitelné — bez filtru se hledá ve všech složkách."
                ),
            },
            "date_from": {
                "type": "string",
                "description": "Hledej jen emaily od tohoto data (YYYY-MM-DD). Volitelné.",
            },
            "date_to": {
                "type": "string",
                "description": "Hledej jen emaily do tohoto data (YYYY-MM-DD). Volitelné.",
            },
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Typy
# ---------------------------------------------------------------------------

class EmailRow(TypedDict):
    id: int
    subject: str
    from_address: str
    from_name: str
    to_addresses: str   # již naformátovaný string
    date: str
    body_excerpt: str   # body_text nebo ai_summary, zkráceno
    folder_name: str
    account_email: str
    source: str         # "vector" | "fulltext"


class EmailSearchMeta(TypedDict):
    query: str
    num_results: int
    success: bool
    used_vector: bool
    used_fulltext: bool


# ---------------------------------------------------------------------------
# Veřejné API
# ---------------------------------------------------------------------------

async def search_emails(
    query: str,
    from_filter: str | None = None,
    folder: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[EmailRow], EmailSearchMeta]:
    """Hybridní vyhledávání v emailové DB.

    Returns:
        (výsledky, metadata). Při chybě vrátí ([], meta) — nepadá chat.
    """
    meta: EmailSearchMeta = {
        "query": query,
        "num_results": 0,
        "success": False,
        "used_vector": False,
        "used_fulltext": False,
    }

    pool = await _get_pool()
    if pool is None:
        log.warning("EMAIL_SEARCH přeskočen — pool nedostupný")
        return [], meta

    try:
        limit = settings.email_search_max_results
        seen_ids: set[int] = set()
        results: list[EmailRow] = []

        # Obě větve spustíme paralelně
        vec = await _embed_query(query)

        vector_task = None
        fulltext_task = None

        if vec is not None:
            vector_task = asyncio.create_task(
                _search_vector(pool, vec, from_filter, folder, date_from, date_to, limit)
            )
        fulltext_task = asyncio.create_task(
            _search_fulltext(pool, query, from_filter, folder, date_from, date_to, limit, set())
        )

        # Počkáme na obě
        vector_rows: list[EmailRow] = []
        if vector_task is not None:
            try:
                vector_rows = await vector_task
                meta["used_vector"] = True
            except Exception as exc:
                log.warning("EMAIL_VECTOR_FAILED: %s: %s", type(exc).__name__, exc)

        fulltext_rows: list[EmailRow] = []
        try:
            fulltext_rows = await fulltext_task
            meta["used_fulltext"] = True
        except Exception as exc:
            log.warning("EMAIL_FULLTEXT_FAILED: %s: %s", type(exc).__name__, exc)

        # Merge: ILIKE výsledky mají přednost (jsou seřazeny DATE DESC = nejnovější),
        # vektorové výsledky doplní pokud ještě zbývá místo.
        # Důvod: HNSW pokrývá jen ~500 emailů a vrátí nejbližší bez ohledu na stáří.
        # ILIKE pokrývá všechny emaily a seřazením DESC zaručí nejnovější první.
        for row in fulltext_rows:
            if len(results) >= limit:
                break
            seen_ids.add(row["id"])
            results.append(row)

        for row in vector_rows:
            if len(results) >= limit:
                break
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(row)

        log.info("EMAIL_SEARCH_DONE query=%r total=%d (vector=%d, fulltext=%d)",
                 query, len(results), len(vector_rows), len(fulltext_rows))

        meta["success"] = True
        meta["num_results"] = len(results)
        return results, meta

    except Exception as exc:
        log.error("EMAIL_SEARCH_ERROR query=%r: %s: %s", query, type(exc).__name__, exc)
        return [], meta


# ---------------------------------------------------------------------------
# Interní search funkce
# ---------------------------------------------------------------------------

def _build_extra_conditions(
    from_filter: str | None,
    folder: str | None,
    date_from: str | None,
    date_to: str | None,
    start_param: int,
) -> tuple[list[str], list]:
    """Vrátí (podmínky WHERE, params) pro volitelné filtry."""
    conds: list[str] = []
    params: list = []
    p = start_param

    if from_filter:
        conds.append(
            f"(m.from_address ILIKE ${p} OR m.from_name ILIKE ${p})"
        )
        params.append(f"%{from_filter}%")
        p += 1

    if folder:
        conds.append(f"f.name ILIKE ${p}")
        params.append(f"%{folder}%")
        p += 1

    if date_from:
        from datetime import datetime
        try:
            conds.append(f"m.date >= ${p}")
            params.append(datetime.strptime(date_from, "%Y-%m-%d"))
            p += 1
        except ValueError:
            pass  # špatný formát — filtr přeskočíme

    if date_to:
        from datetime import datetime
        try:
            conds.append(f"m.date <= ${p}")
            params.append(datetime.strptime(date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
            p += 1
        except ValueError:
            pass

    return conds, params


def _parse_row(row, source: str) -> EmailRow:
    """Převede asyncpg Record na EmailRow."""
    # to_addresses je JSONB — deserializuj a extrahuj adresy
    to_raw = row.get("to_addresses")
    try:
        if isinstance(to_raw, str):
            to_list = json.loads(to_raw)
        elif to_raw is None:
            to_list = []
        else:
            to_list = to_raw  # asyncpg vrátí list přímo pro jsonb
        to_str = ", ".join(
            item.get("address", "") for item in to_list if item.get("address")
        ) or "—"
    except Exception:
        to_str = str(to_raw or "—")

    # Tělo: preferuj ai_summary (kratší, přesnější), jinak body_text zkrácený
    ai_summary = row.get("ai_summary") or ""
    body_text = row.get("body_text") or ""
    max_chars = settings.email_body_max_chars

    if ai_summary:
        body_excerpt = ai_summary[:max_chars]
        if len(ai_summary) > max_chars:
            body_excerpt += "… [zkráceno]"
    else:
        body_excerpt = body_text[:max_chars]
        if len(body_text) > max_chars:
            body_excerpt += "… [zkráceno]"

    return EmailRow(
        id=row["id"],
        subject=row.get("subject") or "(bez předmětu)",
        from_address=row.get("from_address") or "",
        from_name=row.get("from_name") or "",
        to_addresses=to_str,
        date=str(row.get("date") or ""),
        body_excerpt=body_excerpt,
        folder_name=row.get("folder_name") or "",
        account_email=row.get("account_email") or "",
        source=source,
    )


async def _search_vector(
    pool,
    vec: list[float],
    from_filter: str | None,
    folder: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> list[EmailRow]:
    """Vektorové vyhledávání přes HNSW index (14 ms)."""
    accounts = settings.email_accounts_list

    extra_conds, extra_params = _build_extra_conditions(
        from_filter, folder, date_from, date_to, start_param=3
    )

    account_clause = ""
    base_params: list = [vec, limit]

    if accounts:
        account_clause = "AND a.email = ANY($3)"
        base_params = [vec, limit, accounts]
        # posun extra params
        extra_conds2, extra_params2 = _build_extra_conditions(
            from_filter, folder, date_from, date_to, start_param=4
        )
        extra_conds = extra_conds2
        extra_params = extra_params2

    extra_where = (" AND " + " AND ".join(extra_conds)) if extra_conds else ""

    sql = f"""
        SELECT m.id, m.subject, m.from_address, m.from_name,
               m.to_addresses, m.date, m.body_text, m.preview,
               m.ai_summary, f.name AS folder_name, a.email AS account_email,
               me.embedding <=> $1 AS distance
        FROM message_embeddings me
        JOIN messages m ON m.id = me.message_id
        JOIN accounts a ON a.id = m.account_id
        JOIN folders f ON f.id = m.folder_id
        WHERE m.deleted_at IS NULL
          {account_clause}
          {extra_where}
        ORDER BY me.embedding <=> $1
        LIMIT $2
    """

    all_params = base_params + extra_params
    # asyncpg nepodporuje pgvector nativně — vektor předáme jako string s ::vector castem
    vec_str = "[" + ",".join(str(x) for x in vec) + "]"
    # Nahradit $1 za $1::vector všude v SQL
    sql_cast = sql.replace("$1", "$1::vector")
    all_params[0] = vec_str
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql_cast, *all_params)

    return [_parse_row(r, "vector") for r in rows]


async def _search_fulltext(
    pool,
    query: str,
    from_filter: str | None,
    folder: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    exclude_ids: set[int],
) -> list[EmailRow]:
    """ILIKE vyhledávání přes subject + body_text."""
    accounts = settings.email_accounts_list
    pattern = f"%{query}%"

    # Parametry: $1 = pattern, pak volitelně $2 = accounts[]
    if accounts:
        account_clause = "AND a.email = ANY($2)"
        base_params: list = [pattern, accounts]
        extra_conds, extra_params = _build_extra_conditions(
            from_filter, folder, date_from, date_to, start_param=3
        )
    else:
        account_clause = ""
        base_params = [pattern]
        extra_conds, extra_params = _build_extra_conditions(
            from_filter, folder, date_from, date_to, start_param=2
        )

    extra_where = (" AND " + " AND ".join(extra_conds)) if extra_conds else ""

    sql = f"""
        SELECT m.id, m.subject, m.from_address, m.from_name,
               m.to_addresses, m.date, m.body_text, m.preview,
               m.ai_summary, f.name AS folder_name, a.email AS account_email
        FROM messages m
        JOIN accounts a ON a.id = m.account_id
        JOIN folders f ON f.id = m.folder_id
        WHERE m.deleted_at IS NULL
          AND (m.subject ILIKE $1 OR m.body_text ILIKE $1)
          {account_clause}
          {extra_where}
        ORDER BY m.date DESC
        LIMIT {limit * 3}
    """
    # Fetchneme limit*3 abychom měli rezervu po vyloučení already-seen ID

    all_params = base_params + extra_params
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *all_params)

    results: list[EmailRow] = []
    for r in rows:
        if r["id"] not in exclude_ids:
            results.append(_parse_row(r, "fulltext"))
    return results[:limit]


# ---------------------------------------------------------------------------
# Formátování výsledků pro LLM
# ---------------------------------------------------------------------------

def format_email_results(results: list[EmailRow]) -> str:
    """Formátuje výsledky pro LLM kontext."""
    if not results:
        return "Vyhledávání v emailech nepřineslo žádné výsledky."

    lines = [f"Nalezeno emailů: {len(results)}\n"]
    for i, r in enumerate(results, 1):
        # Odesílatel
        if r["from_name"] and r["from_name"] != r["from_address"]:
            sender = f"{r['from_name']} <{r['from_address']}>"
        else:
            sender = r["from_address"]

        lines.append(f"[{i}] {r['subject']}")
        lines.append(f"    Od:    {sender}")
        lines.append(f"    Komu:  {r['to_addresses']}")
        lines.append(f"    Datum: {r['date']}")
        lines.append(f"    Schránka: {r['account_email']}  |  Složka: {r['folder_name']}")
        lines.append(f"    Obsah: {r['body_excerpt']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email memory — pasivní kontext pro system prompt
# ---------------------------------------------------------------------------

# Kolik emailů přidat do kontextu pasivně (méně než aktivní search)
_MEMORY_TOP_K = 3
# Max znaků z těla/summary v memory bloku (kratší než aktivní search)
_MEMORY_BODY_MAX = 300


async def retrieve_email_memory(query: str) -> str:
    """Vrátí relevantní emaily jako text pro system prompt (long-term memory).

    Rychlé vektorové vyhledávání přes HNSW index — pouze emailů které mají
    embedding. Výsledek je stručný blok textu připravený k vložení do system
    promptu, podobně jako retrieve_memory() pro konverzace.

    Vrátí "" pokud email DB není dostupná nebo nenajde nic relevantního.
    """
    pool = await _get_pool()
    if pool is None:
        return ""

    try:
        vec = await _embed_query(query)
        if vec is None:
            return ""

        accounts = settings.email_accounts_list
        vec_str = "[" + ",".join(str(x) for x in vec) + "]"

        account_clause = "AND a.email = ANY($3)" if accounts else ""
        params: list = [vec_str, _MEMORY_TOP_K]
        if accounts:
            params.append(accounts)

        sql = f"""
            SELECT m.subject, m.from_address, m.from_name,
                   m.to_addresses, m.date, m.body_text, m.ai_summary,
                   f.name AS folder_name, a.email AS account_email,
                   me.embedding <=> $1::vector AS distance
            FROM message_embeddings me
            JOIN messages m ON m.id = me.message_id
            JOIN accounts a ON a.id = m.account_id
            JOIN folders f ON f.id = m.folder_id
            WHERE m.deleted_at IS NULL
              {account_clause}
            ORDER BY me.embedding <=> $1::vector
            LIMIT $2
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        if not rows:
            return ""

        # Sestavíme stručný blok pro system prompt
        lines = ["## Relevantní emaily z emailové historie"]
        for row in rows:
            if row["from_name"] and row["from_name"] != row["from_address"]:
                sender = f"{row['from_name']} <{row['from_address']}>"
            else:
                sender = row["from_address"]

            ai_summary = row.get("ai_summary") or ""
            body_text = row.get("body_text") or ""
            excerpt = (ai_summary or body_text)[:_MEMORY_BODY_MAX]
            if len(ai_summary or body_text) > _MEMORY_BODY_MAX:
                excerpt += "…"

            date_str = str(row["date"])[:10] if row["date"] else ""
            lines.append(
                f"[{date_str}] {row['subject']}\n"
                f"Od: {sender} → {row['account_email']}\n"
                f"{excerpt}"
            )

        memory_block = "\n\n".join(lines)
        log.info("EMAIL_MEMORY retrieved %d emails for query '%s...'",
                 len(rows), query[:50])
        return memory_block

    except Exception as exc:
        log.warning("EMAIL_MEMORY_ERROR: %s: %s", type(exc).__name__, exc)
        return ""
