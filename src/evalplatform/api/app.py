from fastapi import FastAPI
from pydantic import BaseModel

from evalplatform.api.routes.evals import router as evals_router

app = FastAPI(title="LLM Eval Platform", version="0.1.0")
app.include_router(evals_router)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")
