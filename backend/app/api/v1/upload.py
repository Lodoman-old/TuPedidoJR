from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.api.deps import get_current_user
from app.models.user import User
from app.services.file_service import save_upload

router = APIRouter()


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    if not file:
        raise HTTPException(status_code=400, detail="No se envió ningún archivo")
    try:
        url = await save_upload(file)
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
