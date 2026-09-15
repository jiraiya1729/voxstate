"""Health-check API route used by smoke tests and the frontend readiness check."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight readiness response for clients and smoke tests."""
    return {"status": "ok"}
