from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator
import uuid
import json
from datetime import datetime

from app.db.session import get_db
from app.db.models import Document, User
from app.api.deps import get_current_user
from app.services.llm.router import chat, ChatMessage, stream_with_usage
from pydantic import BaseModel

router = APIRouter(prefix="/documents", tags=["documents"])

class DocumentCreate(BaseModel):
    title: str = "Nový dokument"
    project_id: uuid.UUID | None = None
    source_text: str = ""
    content: str = ""

class DocumentUpdate(BaseModel):
    title: str | None = None
    project_id: uuid.UUID | None = None
    source_text: str | None = None
    content: str | None = None

class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    project_id: uuid.UUID | None
    source_text: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DocumentGenerateRequest(BaseModel):
    prompt: str
    model: str
    provider: str
    
@router.post("", response_model=DocumentResponse)
async def create_document(
    doc: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    new_doc = Document(
        user_id=user.id,
        title=doc.title,
        project_id=doc.project_id,
        source_text=doc.source_text,
        content=doc.content,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)
    return new_doc

@router.get("", response_model=list[DocumentResponse])
async def get_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.user_id == user.id).order_by(Document.updated_at.desc())
    )
    return result.scalars().all()

@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dokument nenalezen")
    return doc

@router.put("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: uuid.UUID,
    update_data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dokument nenalezen")
    
    if update_data.title is not None:
        doc.title = update_data.title
    if update_data.project_id is not None:
        doc.project_id = update_data.project_id
    if update_data.source_text is not None:
        doc.source_text = update_data.source_text
    if update_data.content is not None:
        doc.content = update_data.content

    await db.commit()
    await db.refresh(doc)
    return doc

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dokument nenalezen")
    
    await db.delete(doc)
    await db.commit()
    return {"status": "ok"}

@router.post("/{doc_id}/generate")
async def generate_document(
    doc_id: uuid.UUID,
    req: DocumentGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Vygeneruje/upraví obsah dokumentu na základě source_text a existujícího obsahu, 
    podle uživatelského promptu.
    """
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dokument nenalezen")

    system_prompt = (
        "Jsi expertní copywriter a editor. Tvojí úlohou je upravit stávající text "
        "na základě Východiska (podkladů) a pokynů uživatele. "
        "Vrať POUZE nový upravený text ve formátu Markdown. Zcela vynechej jakékoli "
        "úvody, pozdravy, vysvětlení nebo meta komentáře. Výstup musí obsahovat pouze samotný text."
    )
    
    user_msg = f"VÝCHODISKO (Podklady):\n{doc.source_text}\n\n"
    if doc.content.strip():
        user_msg += f"AKTUÁLNÍ VÝSLEDEK (K úpravě):\n{doc.content}\n\n"
        
    user_msg += f"POŽADAVEK NA ÚPRAVU:\n{req.prompt}"

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_msg)
    ]

    async def stream_generator() -> AsyncGenerator[str, None]:
        full_content = ""
        try:
            async for delta, usage in stream_with_usage(
                messages=messages,
                model=req.model,
                provider=req.provider,
                temperature=0.7,
                max_tokens=4000,
            ):
                if delta:
                    full_content += delta
                    chunk_obj = {
                        "type": "delta",
                        "delta": delta,
                        "done": False
                    }
                    yield f"data: {json.dumps(chunk_obj)}\n\n"
                
                if usage is not None:
                    chunk_obj = {
                        "type": "done",
                        "done": True,
                        "delta": "",
                        "usage": {
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens
                        }
                    }
                    yield f"data: {json.dumps(chunk_obj)}\n\n"
        except Exception as e:
            err_obj = {
                "type": "error",
                "error": str(e)
            }
            yield f"data: {json.dumps(err_obj)}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
