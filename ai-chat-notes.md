# Osobní AI Chat s pamětí - Průzkum a plán

## Cíl projektu

Nahradit Grok (X.ai) který nemá paměť mezi sezeními. Chci mít vlastního AI asistenta s kterým mohu:
- Chatovat o čemkoliv (svět, technologie, cokoliv)
- Který si pamatuje kontext z minulých týdnů
- Přepínat mezi různými LLM modely
- Mít plnou kontrolu nad daty a soukromím

---

## Tech Stack

| Vrstva | Technologie |
|--------|-------------|
| Mobilní app | Flutter + Riverpod |
| Backend | Python + FastAPI |
| Databáze | PostgreSQL + pgvector |
| Embeddingy | OpenAI `text-embedding-3-small` nebo lokální `nomic-embed-text` |
| Auth | JWT (python-jose) |
| Lokální LLM | Ollama (Llama3, Mistral, Gemma...) |
| Komerční LLM | OpenAI (GPT-4o), Anthropic (Claude), Grok (X.ai) |
| Agent framework | Vlastní implementace (pro učení), případně LangChain/LlamaIndex |

---

## Architektura

```
Flutter App (iOS/Android)
        ↕ HTTPS/WebSocket
FastAPI Backend (lokální PC)
    ├── RAG Engine (PostgreSQL + pgvector)
    ├── LLM Router (Claude / OpenAI / Ollama / Grok)
    ├── Agent Engine
    │       ├── search_web (Brave Search API)
    │       ├── get_weather (OpenWeatherMap)
    │       ├── get_news (RSS / NewsAPI)
    │       ├── read_url (stáhne a shrne webovou stránku)
    │       ├── search_memory ← dotaz do RAG
    │       └── save_memory ← uložení do RAG
    └── Auth (JWT)
```

---

## Jak funguje RAG (paměť)

```
Uživatel píše zprávu
        ↓
1. Embedding zprávy
        ↓
2. Vyhledání relevantního kontextu v pgvector
        ↓
3. Sestavení promptu: [System] + [RAG kontext] + [Historie] + [Zpráva]
        ↓
4. LLM odpovídá
        ↓
5. Uložení zprávy do DB + nový embedding
```

---

## Jak fungují Agent Tools

```
Uživatel: "Co se dnes děje ve světě?"
        ↓
LLM rozhodne zavolat: search_web("world news today")
        ↓
Backend zavolá Brave Search API
        ↓
LLM dostane výsledky, případně zavolá read_url() pro detail
        ↓
LLM sestaví odpověď + uloží do RAG pro budoucí kontext
```

---

## Typy paměti - srovnání

| Typ | Popis | Příklad |
|-----|-------|---------|
| Kontextové okno | Paměť jen v rámci jedné konverzace | Grok |
| Persistentní paměť | Ukládání faktů mezi sezeními | ChatGPT Memory |
| RAG | Vyhledávání v uložených dokumentech/konverzacích | Claude Projects |
| Fine-tuning | Naučení modelu na vlastních datech | Méně běžné |

---

## Srovnání modelů

| | Grok (X.ai) | Claude (Anthropic) |
|---|---|---|
| Témata | Obecná | Obecná |
| Paměť mezi sezeními | Žádná | Žádná (bez Projects) |
| Kontext okno | 131k tokenů | 200k tokenů |
| Real-time data | Ano (X/Twitter) | Ne |
| Cena API | ~$3/M tokenů | ~$3/M tokenů |
| Vhodný pro konverzaci | Dobrý | Velmi dobrý |

Claude nemá omezení jen na technická témata - funguje výborně pro obecnou konverzaci.

---

## Fáze implementace

### Fáze 1 - Backend základ
- FastAPI projekt setup
- PostgreSQL + pgvector
- JWT autentizace (register/login)
- Základní chat endpoint (bez RAG)
- Integrace OpenAI + Ollama

### Fáze 2 - RAG a paměť
- Embedding pipeline
- Vyhledávání kontextu při každém dotazu
- Sumarizace starých konverzací
- Extrakce faktů o uživateli ("paměť entit")

### Fáze 3 - Přepínání modelů
- LLM Router abstrakce
- OpenAI, Anthropic, Grok, Ollama pod jednotným rozhraním

### Fáze 4 - Flutter app
- Chat UI s Markdown renderingem
- Výběr modelu v nastavení
- Historie konverzací
- Streaming odpovědí

### Fáze 5 - Externí zdroje + Agenti
- Upload dokumentů (PDF, text)
- Gmail integrace (OAuth)
- Agent tools: web search, počasí, news, read_url
- Automatický embedding nových dat

---

## Proč to má smysl stavět (vs. komerční platformy)

- Plná kontrola nad daty a soukromím
- Platíš jen za API tokeny, ne $20-50/měsíc za platformu
- Flexibilita - vlastní zdroje dat, vlastní tools
- Pochopíš jak RAG a agenti fungují zevnitř
- Možnost napojit nestandardní zdroje dat

---

## Zdroje dat do RAG (plán)

- Chat historie (automaticky)
- Vlastní poznámky a dokumenty (upload)
- Emaily (Gmail OAuth)
- RSS feedy / news
- Kalendář (Google Calendar)
