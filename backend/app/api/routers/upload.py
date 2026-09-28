import os
import uuid
import shutil
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.db.session import get_db
from app.tasks.ingestion_task import process_document_task
from app.api.dependencies import get_current_tenant_id

router = APIRouter(prefix="/upload", tags=["upload"])


def compute_file_hash(file: UploadFile) -> str:
    """Compute SHA-256 hash of uploaded file."""
    hash_sha256 = hashlib.sha256()
    # Reset file position to beginning
    file.file.seek(0)
    for chunk in iter(lambda: file.file.read(4096), b""):
        hash_sha256.update(chunk)
    # Reset file position for later reading
    file.file.seek(0)
    return hash_sha256.hexdigest()


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_current_tenant_id),
    db=Depends(get_db),
):
    # 1. Compute file hash for deduplication
    file_hash = compute_file_hash(file)
    
    # 2. Check if document with this hash already exists for this tenant
    cur = db.cursor()
    try:
        cur.execute(
            """
            SELECT id FROM documents 
            WHERE tenant_id = %s AND content_hash = %s
            """,
            (tenant_id, file_hash),
        )
        existing = cur.fetchone()
        if existing:
            document_id = str(existing["id"])
            cur.close()
            return {
                "document_id": document_id,
                "status": "existing",
                "filename": file.filename,
                "message": "File already uploaded",
            }
    except Exception as e:
        cur.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    # 2b. Check if this tenant has a failed document with the same file hash
    cur = db.cursor()
    try:
        cur.execute(
            """
            SELECT d.id, d.status FROM documents d
            WHERE d.tenant_id = %s AND d.content_hash = %s
              AND d.status IN ('failed', 'fail_terminal')
            """,
            (tenant_id, file_hash),
        )
        failed_existing = cur.fetchone()
        if failed_existing:
            document_id = str(failed_existing["id"])
            cur.close()
            return {
                "document_id": document_id,
                "status": failed_existing["status"],
                "filename": file.filename,
                "message": "File already uploaded but processing failed. Use 'rag-cli retry' to retry.",
            }
    except Exception as e:
        cur.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    # 3. Generate document ID and resolve storage path
    document_id = str(uuid.uuid4())
    tenant_dir = f"/raw_uploads/{tenant_id}"
    os.makedirs(tenant_dir, exist_ok=True)
    file_path = f"{tenant_dir}/{document_id}_{file.filename}"

    # 4. Save the file to the volume
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 5. Insert document record with hash
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO documents (id, tenant_id, filename, storage_path, content_hash, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (document_id, tenant_id, file.filename, file_path, file_hash, "pending", datetime.now()),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        cur.close()
        # Clean up uploaded file on DB failure
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        cur.close()

    # 6. Fire Celery task
    process_document_task.delay(document_id, tenant_id)

    return {
        "document_id": document_id,
        "status": "pending",
        "filename": file.filename,
    }
