import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.async_session import get_async_db
from app.api.dependencies import get_current_tenant_id
from app.tasks.ingestion_task import process_document_task

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@router.get("/")
async def list_documents(
    db: AsyncSession = Depends(get_async_db),
    tenant_id: str = Depends(get_current_tenant_id),
):
    sql = text("""
        SELECT d.id, d.filename, d.status, d.created_at, d.retry_count,
               COUNT(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        WHERE d.tenant_id = :tenant_id
        GROUP BY d.id, d.filename, d.status, d.created_at, d.retry_count
        ORDER BY d.created_at DESC
    """)
    result = await db.execute(sql, {"tenant_id": tenant_id})
    rows = result.fetchall()

    documents = []
    for row in rows:
        documents.append(
            {
                "id": str(row[0]),
                "filename": row[1],
                "status": row[2],
                "created_at": row[3].isoformat() if isinstance(row[3], datetime) else str(row[3]),
                "retry_count": row[4],
                "chunk_count": row[5],
            }
        )

    return documents


@router.post("/{document_id}/retry")
async def retry_document(
    document_id: str,
    db: AsyncSession = Depends(get_async_db),
    tenant_id: str = Depends(get_current_tenant_id),
):
    sql = text("""
        SELECT status, retry_count FROM documents
        WHERE id = :document_id AND tenant_id = :tenant_id
    """)
    result = await db.execute(sql, {"document_id": document_id, "tenant_id": tenant_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    status = row[0]
    retry_count = row[1]

    if status == "completed":
        raise HTTPException(status_code=400, detail="Document is already completed")
    if status == "fail_terminal":
        raise HTTPException(status_code=400, detail="Document has exhausted retries. Contact an admin.")
    if status == "processing":
        raise HTTPException(status_code=400, detail="Document is currently being processed")

    if retry_count >= MAX_RETRIES:
        await db.execute(
            text("UPDATE documents SET status = 'fail_terminal' WHERE id = :document_id"),
            {"document_id": document_id},
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="Maximum retries exceeded. Document marked as fail_terminal.")

    await db.execute(text("DELETE FROM chunks WHERE document_id = :document_id"), {"document_id": document_id})
    await db.execute(text("DELETE FROM parsed_documents WHERE document_id = :document_id"), {"document_id": document_id})
    await db.execute(
        text("""
            UPDATE documents
            SET status = 'pending', retry_count = retry_count + 1
            WHERE id = :document_id
        """),
        {"document_id": document_id},
    )
    await db.commit()

    process_document_task.delay(document_id, tenant_id)

    return {
        "document_id": document_id,
        "status": "pending",
        "retry_count": retry_count + 1,
        "message": "Retry scheduled",
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_async_db),
    tenant_id: str = Depends(get_current_tenant_id),
):
    sql = text("""
        SELECT id FROM documents
        WHERE id = :document_id AND tenant_id = :tenant_id
    """)
    result = await db.execute(sql, {"document_id": document_id, "tenant_id": tenant_id})
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Document not found")

    await db.execute(text("DELETE FROM chunks WHERE document_id = :document_id"), {"document_id": document_id})
    await db.execute(text("DELETE FROM parsed_documents WHERE document_id = :document_id"), {"document_id": document_id})
    await db.execute(text("DELETE FROM documents WHERE id = :document_id"), {"document_id": document_id})
    await db.commit()

    return {"document_id": document_id, "status": "deleted"}
