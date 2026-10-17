from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.features.google_login.user import User
from app.features.google_login import accounts as account_service
from app.features.google_login.repository import user_repository
from app.features.profile.schemas import ProfileUpdateRequest

router = APIRouter(prefix="/gmail", tags=["profile"])

@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = account_service.find_account(db, current_user)
    return {
        "email": current_user.email,
        "name": current_user.name,
        "signature": current_user.signature,
        "preferences": current_user.preferences,
        "bio": current_user.bio,
        "is_connected": bool(account and account.encrypted_credentials and not account.requires_reauth),
        "requires_reauth": bool(account and account.requires_reauth),
    }




@router.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    if request.name is not None: current_user.name = request.name
    if request.signature is not None: current_user.signature = request.signature
    if request.preferences is not None: current_user.preferences = request.preferences
    if request.bio is not None: current_user.bio = request.bio
    user_repository.update(db, current_user)
    return {"message": "Profile updated successfully"}

