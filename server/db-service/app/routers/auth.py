"""Auth endpoint — validate a token and return user info."""

from fastapi import APIRouter, Depends

from app.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/validate")
async def validate_token(user: CurrentUser = Depends(get_current_user)):
    """Validate Bearer token and return user info."""
    return {
        "azure_oid": user.azure_oid,
        "email": user.email,
        "display_name": user.display_name,
    }
