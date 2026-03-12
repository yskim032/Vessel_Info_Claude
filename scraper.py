"""
PORT-MIS 모선별관제현황 스크래퍼 (최종 버전)
"""
import asyncio
import logging
from typing import List, Dict, Any
from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

LOGIN_URL = "https://new.portmis.go.kr/"
USERNAME  = "mscbusops"
PASSWORD  = "MSCkorea1@"

PORT_CODES = {
    "busan":   {"code": "020", "name": "부산"},
    "incheon": {"code": "030", "name": "인천"},
}

# 폼 요소 ID (M0224 = 모선별관제현황)
PFX = "mf_tacMain_contents_M0224_body_"
ID = {
    "prtAgCd":          f"{PFX}prtAgCd",           # 청코드
    "prtAgNm":          f"{PFX}prtAgNm",           # 청코드 이름
    "btnPrtSch":        f"{PFX}btnPrtSch",          # 청코드 검색 아이콘
    "clsgn":            f"{PFX}clsgn",              # 호출부호
    "vsslKorNm":        f"{PFX}vsslKorNm",          # 선박명
    "etryptYear":       f"{PFX}etryptYear",         # 입항년도
    "etryptCo":         f"{PFX}etryptCo",           # 입항횟수
    "btnVsslSch":       f"{PFX}btnVsslSch",         # 호출부호 검색 아이콘
    "btnSearch":        f"{PFX}udcSearch_btnSearch", # 검색 버튼
    # 선박정보 표시 필드
    "vsslInnbNm":       f"{PFX}vsslInnbNm",         # 선박명(결과)
    "satmntEntrpsCd":   f"{PFX}satmntEntrpsCd",     # 선사코드
    "satmntEntrpsNm":   f"{PFX}satmntEntrpsNm",     # 선사명
    "vsslNltyCd":       f"{PFX}vsslNltyCd",         # 국적코드
    "vsslNltyNm":       f"{PFX}vsslNltyNm",         # 국적명
    "vsslKndCd":        f"{PFX}vsslKndCd",          # 선박종류코드
    "vsslKndNm":        f"{PFX}vsslKndNm",          # 선박종류명
    "intrlGrtg":        f"{PFX}intrlGrtg",          # 국제총톤수
    "grtg":             f"{PFX}grtg",               # 총톤수
}


async def _dismiss_popups(page: Page):
    for _ in range(5):
        try:
            btn = page.locator(
                "button:has-text('닫기'), button:has-text('확인'), .w2window_close"
            ).first
            if await btn.is_visible(timeout=600):
                await btn.click()
                await asyncio.sleep(0.3)
            else:
                break
        except Exception:
            break


async def _login(page: Page):
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)
    await _dismiss_popups(page)

    await page.locator("a:has-text('로그인')").first.click()
    await asyncio.sleep(1.5)

    await page.locator(f"#mf_frameLogin1_login1_id").fill(USERNAME, force=True)
    await page.locator(f"#mf_frameLogin1_login1_pw").fill(PASSWORD, force=True)
    await page.keyboard.press("Enter")

    await page.wait_for_url("**/index.xml**", timeout=20000)
    await asyncio.sleep(2)
    await _dismiss_popups(page)


async def _navigate_to_vessel_ctrl(page: Page):
    """정보이용 > 관제 > 모선별관제현황 이동"""
    await page.locator("a:has-text('정보이용'), span:has-text('정보이용')").first.click()
    await asyncio.sleep(1.5)
    await page.locator("text=관제").first.click()
    await asyncio.sleep(1.5)
    await page.locator("text=모선별관제현황").first.click()
    await asyncio.sleep(4)
    await _dismiss_popups(page)

    # 페이지 로드 확인
    if not await page.locator(f"#{ID['prtAgCd']}").is_visible(timeout=5000):
        raise RuntimeError("모선별관제현황 폼 로드 실패")


async def _fill_port_code(page: Page, code: str):
    """청코드 직접 입력 (Tab → 이름 자동완성)"""
    inp = page.locator(f"#{ID['prtAgCd']}")
    await inp.fill(code)
    await asyncio.sleep(0.3)
    await inp.press("Tab")
    await asyncio.sleep(0.8)


async def _open_vessel_popup_and_search(page: Page, vessel_name: str) -> List[Dict]:
    """호출부호 돋보기 클릭 → 팝업에서 선박명 검색 → 결과 목록 반환"""
    vssl_btn = page.locator(f"#{ID['btnVsslSch']}")

    try:
        async with page.expect_popup(timeout=5000) as popup_info:
            await vssl_btn.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(2)

        # 검색 입력
        search_input = popup.locator("#mf_ipt1")
        await search_input.fill(vessel_name)
        await search_input.press("Enter")
        await asyncio.sleep(2)

        # 결과 추출
        vessels = await _extract_popup_vessels(popup)
        await popup.close()
        return vessels

    except Exception as e:
        logger.error(f"선박 팝업 오류: {e}")
        # 팝업 방식 실패 시 직접 입력 (call_sign을 모를 경우엔 빈 list)
        return []


async def _extract_popup_vessels(popup) -> List[Dict]:
    """팝업 테이블에서 선박 목록 추출"""
    vessels = []
    try:
        rows = popup.locator("table tbody tr")
        count = await rows.count()

        for i in range(count):
            row = rows.nth(i)
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count < 4:
                continue

            texts = []
            for j in range(cell_count):
                t = (await cells.nth(j).inner_text()).strip()
                texts.append(t)

            # 첫 번째 셀이 검색폼 텍스트인 경우 스킵
            if any(k in texts[0] for k in ["선박명", "호출부호", "조회", "검색", "초기화"]):
                continue

            # 실제 선박 데이터
            vessel = {
                "row_index": i,
                "ship_name": texts[0] if len(texts) > 0 else "",
                "ship_type": texts[1] if len(texts) > 1 else "",
                "tonnage":   texts[2] if len(texts) > 2 else "",
                "call_sign": texts[3] if len(texts) > 3 else "",
                "ship_no":   texts[4] if len(texts) > 4 else "",
                "imo":       texts[5] if len(texts) > 5 else "",
                "company":   texts[6] if len(texts) > 6 else "",
            }
            if vessel["ship_name"]:
                vessels.append(vessel)

    except Exception as e:
        logger.error(f"팝업 테이블 추출 오류: {e}")

    return vessels


async def _select_vessel_in_popup(page: Page, vessel_name: str, call_sign: str, row_index: int):
    """호출부호 팝업에서 선박 선택"""
    vssl_btn = page.locator(f"#{ID['btnVsslSch']}")

    try:
        async with page.expect_popup(timeout=5000) as popup_info:
            await vssl_btn.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(2)

        # 선박명 검색
        search_input = popup.locator("#mf_ipt1")
        await search_input.fill(vessel_name)
        await search_input.press("Enter")
        await asyncio.sleep(2)

        # 올바른 행 선택
        rows = popup.locator("table tbody tr")
        count = await rows.count()

        target_row = None
        data_row_idx = 0
        SKIP_KEYWORDS = ["선박명", "호출부호", "조회", "검색", "초기화"]

        for i in range(count):
            row = rows.nth(i)
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count < 4:
                continue

            texts = [(await cells.nth(j).inner_text()).strip() for j in range(cell_count)]
            first_cell = texts[0]

            # 검색폼/헤더 행 스킵
            if not first_cell or any(k in first_cell for k in SKIP_KEYWORDS):
                continue

            # call_sign으로 매칭 (우선순위 1)
            if call_sign and call_sign.upper() in [t.upper() for t in texts]:
                target_row = row
                break

            # row_index로 매칭 (우선순위 2)
            if data_row_idx == row_index:
                target_row = row

            data_row_idx += 1

        if target_row is None and count > 0:
            # 첫번째 유효 데이터 행 사용
            for i in range(count):
                row = rows.nth(i)
                cells = row.locator("td")
                cell_count = await cells.count()
                if cell_count < 4:
                    continue
                first_cell = (await cells.nth(0).inner_text()).strip()
                if first_cell and not any(k in first_cell for k in SKIP_KEYWORDS):
                    target_row = row
                    break

        if target_row:
            await target_row.click()
            logger.info("선박 선택 완료")

        # 팝업이 자동으로 닫힐 때까지 대기
        try:
            await popup.wait_for_close(timeout=3000)
        except Exception:
            await popup.close()
        await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"선박 선택 오류: {e}")
        # 직접 호출부호 입력 폴백
        if call_sign:
            await page.locator(f"#{ID['clsgn']}").fill(call_sign)
            await asyncio.sleep(0.3)


async def _click_search(page: Page):
    """검색 버튼 클릭"""
    btn = page.locator(f"#{ID['btnSearch']}")
    await btn.click()
    await asyncio.sleep(4)
    await _dismiss_popups(page)


async def _extract_ship_info(page: Page) -> Dict:
    """선박정보 필드 추출"""
    info = {}
    field_map = {
        "ship_name":    ID["vsslInnbNm"],
        "agent":        ID["satmntEntrpsNm"],
        "nationality":  ID["vsslNltyNm"],
        "ship_type":    ID["vsslKndNm"],
        "intl_tonnage": ID["intrlGrtg"],
        "gross_tonnage":ID["grtg"],
    }
    for key, element_id in field_map.items():
        try:
            info[key] = await page.locator(f"#{element_id}").input_value()
        except Exception:
            info[key] = ""
    return info


async def _extract_control_records(page: Page) -> List[Dict]:
    """본선관제 내역 테이블 추출

    실제 td 구조 (헤더 colspan 때문에 td가 헤더보다 많음):
    pos 0: 입항횟수
    pos 1: 순번
    pos 2: 구분코드 (예: 03, 09)
    pos 3: 구분명   (예: 입항, 출항)
    pos 4: 교신시설_타입  (예: MSN)
    pos 5: 교신시설_번호  (예: 01)
    pos 6: 교신시설_이름  (예: 신항 1부두 1선석)
    pos 7: 교신시각  (예: 2026-03-08 20:43)
    pos 8: 교신     (예: PA8)
    pos 9: 도선
    pos10: 신청
    pos11: 부선호출부호1
    pos12: 부선호출부호2
    """
    records = []
    try:
        tables = page.locator(f"[id*='M0224'] table")
        table_count = await tables.count()

        target_table = None
        for i in range(table_count):
            tbl = tables.nth(i)
            header_texts = await tbl.locator("thead th, thead td").all_inner_texts()
            combined = " ".join(header_texts)
            if "입항횟수" in combined and "교신" in combined:
                target_table = tbl
                break

        if target_table is None:
            return []

        rows = target_table.locator("tbody tr")
        row_count = await rows.count()

        for i in range(row_count):
            row = rows.nth(i)
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count < 2:
                continue

            texts = [(await cells.nth(j).inner_text()).strip() for j in range(cell_count)]

            # 빈 행 필터링
            non_empty_cnt = sum(1 for t in texts if t)
            if non_empty_cnt < 2:
                continue

            # 교신시설 합치기 (타입 + 번호 + 이름)
            if len(texts) >= 7:
                facility = " ".join(filter(None, [texts[4], texts[5], texts[6]])) if cell_count > 6 else ""
                record = {
                    "입항횟수": texts[0] if len(texts) > 0 else "",
                    "순번":     texts[1] if len(texts) > 1 else "",
                    "구분":     texts[3] if len(texts) > 3 else (texts[2] if len(texts) > 2 else ""),
                    "교신시설": facility,
                    "교신시각": texts[7] if len(texts) > 7 else "",
                    "교신":     texts[8] if len(texts) > 8 else "",
                    "도선":     texts[9] if len(texts) > 9 else "",
                    "신청":     texts[10] if len(texts) > 10 else "",
                    "부선호출부호1": texts[11] if len(texts) > 11 else "",
                    "부선호출부호2": texts[12] if len(texts) > 12 else "",
                }
            else:
                # 예상 외 구조 fallback
                keys = ["입항횟수", "순번", "구분", "교신시설", "교신시각", "교신", "도선", "신청", "부선호출부호1", "부선호출부호2"]
                record = {keys[j]: texts[j] for j in range(min(len(keys), len(texts)))}

            records.append(record)

    except Exception as e:
        logger.error(f"관제 내역 추출 오류: {e}")

    return records


# ─────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────

async def search_vessels(vessel_name: str, port: str) -> List[Dict]:
    """선박명으로 선박 목록 조회"""
    port_info = PORT_CODES.get(port, PORT_CODES["busan"])

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR",
        )
        page = await context.new_page()

        try:
            logger.info(f"[search] 로그인")
            await _login(page)

            logger.info(f"[search] 모선별관제현황 이동")
            await _navigate_to_vessel_ctrl(page)

            logger.info(f"[search] 청코드 입력: {port_info['code']}")
            await _fill_port_code(page, port_info["code"])

            logger.info(f"[search] 선박 팝업 검색: {vessel_name}")
            vessels = await _open_vessel_popup_and_search(page, vessel_name)

            logger.info(f"[search] 결과: {len(vessels)}건")
            return vessels

        except Exception as e:
            logger.error(f"[search] 오류: {e}")
            raise
        finally:
            await browser.close()


async def get_vessel_details(
    vessel_name: str,
    port: str,
    call_sign: str,
    row_index: int = 0,
) -> Dict:
    """선택 선박의 본선관제 내역 조회"""
    port_info = PORT_CODES.get(port, PORT_CODES["busan"])

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR",
        )
        page = await context.new_page()

        try:
            logger.info(f"[details] 로그인")
            await _login(page)

            logger.info(f"[details] 모선별관제현황 이동")
            await _navigate_to_vessel_ctrl(page)

            logger.info(f"[details] 청코드 입력: {port_info['code']}")
            await _fill_port_code(page, port_info["code"])

            logger.info(f"[details] 선박 선택: {vessel_name} / {call_sign}")
            await _select_vessel_in_popup(page, vessel_name, call_sign, row_index)

            # 호출부호 폴백: 직접 입력
            clsgn_val = await page.locator(f"#{ID['clsgn']}").input_value()
            if not clsgn_val and call_sign:
                await page.locator(f"#{ID['clsgn']}").fill(call_sign)
                await asyncio.sleep(0.3)

            logger.info("[details] 검색 실행")
            await _click_search(page)

            logger.info("[details] 데이터 추출")
            ship_info = await _extract_ship_info(page)
            records   = await _extract_control_records(page)

            logger.info(f"[details] 관제 내역: {len(records)}건")
            return {"ship_info": ship_info, "records": records}

        except Exception as e:
            logger.error(f"[details] 오류: {e}")
            raise
        finally:
            await browser.close()
