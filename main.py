"""
PORT-MIS 모선별관제현황 조회 API 서버
"""
import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

from scraper import search_vessels, get_vessel_details

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="PORT-MIS 모선별관제현황 API")


# ─── 요청 모델 ───────────────────────────────────────────

class SearchRequest(BaseModel):
    vessel_name: str
    port: str = "busan"   # "busan" | "incheon"


class DetailsRequest(BaseModel):
    vessel_name: str
    port: str = "busan"
    call_sign: str
    row_index: int = 0


# ─── 엔드포인트 ───────────────────────────────────────────

@app.post("/api/search")
async def api_search(req: SearchRequest):
    """선박명으로 선박 목록 조회"""
    if not req.vessel_name.strip():
        raise HTTPException(status_code=400, detail="선박명을 입력하세요.")
    try:
        vessels = await search_vessels(req.vessel_name.strip(), req.port)
        return {"success": True, "vessels": vessels, "count": len(vessels)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/details")
async def api_details(req: DetailsRequest):
    """선택 선박의 본선관제 내역 조회"""
    if not req.vessel_name.strip() or not req.call_sign.strip():
        raise HTTPException(status_code=400, detail="선박명과 호출부호를 입력하세요.")
    try:
        result = await get_vessel_details(
            req.vessel_name.strip(),
            req.port,
            req.call_sign.strip(),
            req.row_index,
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─── 정적 파일 서비스 ─────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ─── 실행 ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
