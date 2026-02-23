# -*- coding: utf-8 -*-
"""
EPIC 초록 작성 앱 (Streamlit)
- PDF 파일 업로드 또는 폴더 선택으로 1개/여러 개 동시 처리
- 초록 확인 후 개별·일괄 txt 다운로드
"""
import re
import zipfile
import io
from pathlib import Path

import streamlit as st

from summary_core import (
    get_client,
    DEFAULT_PROMPT,
    process_one_pdf,
    process_pdfs_from_folder,
    process_one_pdf_epts,
)


def sanitize_filename(text: str, max_len: int = 80) -> str:
    """파일명에 사용할 수 없는 문자 제거."""
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text))
    return text.strip()[:max_len]


def extract_title_from_summary(summary: str, task_mode: str) -> str:
    """초록에서 대책명/정책명 추출."""
    if not summary:
        return ""
    
    if task_mode == "ETPS 대책자료 초록":
        # ETPS: "1. 정책 관련 정보: 문서 제목 사용" 부분에서 제목 추출
        lines = summary.split('\n')
        for i, line in enumerate(lines):
            if '정책 관련 정보' in line or '관련부처' in line:
                # 다음 줄들에서 제목 찾기
                for j in range(i, min(i + 5, len(lines))):
                    if lines[j].strip() and not lines[j].strip().startswith('-') and '관련부처' not in lines[j] and '발행일자' not in lines[j]:
                        title = lines[j].strip()
                        # 불필요한 접두사 제거
                        title = re.sub(r'^[0-9]+\.\s*', '', title)
                        title = re.sub(r'^정책 관련 정보:\s*', '', title)
                        if title and len(title) > 3:
                            return sanitize_filename(title, 50)
        # 찾지 못하면 첫 줄 사용
        first_line = lines[0].strip() if lines else ""
        return sanitize_filename(first_line[:50], 50) if first_line else ""
    else:
        # EPIC: 첫 줄에서 부처명과 주요 내용 추출
        lines = summary.split('\n')
        first_line = lines[0].strip() if lines else ""
        if first_line:
            # "A(부처)는 MM.DD.(day) ~~한다고 밝혔다" 형식에서 주요 내용 추출
            match = re.search(r'는\s+[0-9.]+\([^)]+\)\s+(.+?)(?:라고|한다고|했다고)', first_line)
            if match:
                title = match.group(1).strip()
                return sanitize_filename(title[:50], 50)
            # 패턴이 없으면 첫 줄의 일부 사용
            return sanitize_filename(first_line[:50], 50)
    return ""


def summary_to_txt_content(row: dict) -> str:
    """결과 한 건을 txt 본문 문자열로."""
    base = Path(row["파일명"]).stem
    return (
        f"[제목]\n{row['파일명']}\n\n"
        f"[파일명]\n{base}\n\n"
        "[초록]\n"
        f"{str(row.get('요약 결과', '')).strip()}"
    )


st.set_page_config(page_title="EPIC 초록 작성", page_icon="📄", layout="wide")

st.title("📄 EPIC/ETPS 초록 작성 도구")
st.caption("PDF를 업로드하거나 폴더를 선택하면 정해진 규칙에 따라 초록을 생성합니다. 결과를 확인·수정한 뒤 txt로 받을 수 있습니다.")

# 작업 유형 선택 (꼭지 선택)
task_mode = st.radio(
    "작업 유형",
    ["EPIC 정부 보도자료 초록", "ETPS 대책자료 초록"],
    horizontal=True,
    key="task_mode_radio",
)

# 작업 유형이나 입력이 변경되면 이전 결과 초기화
current_task_key = f"task_mode_{task_mode}"
if "last_task_mode" not in st.session_state or st.session_state["last_task_mode"] != task_mode:
    # 작업 유형이 변경되면 이전 결과 및 편집 내용 모두 초기화
    if "summary_results" in st.session_state:
        del st.session_state["summary_results"]
    # 해당 작업 유형의 편집 내용도 초기화
    for key in list(st.session_state.keys()):
        if key.startswith("summary_edit_"):
            del st.session_state[key]
    st.session_state["last_task_mode"] = task_mode

# API 키 경로 (앱 기준 상대 경로)
app_dir = Path(__file__).resolve().parent
api_key_path = app_dir / "openai_api_key.txt"
with st.sidebar:
    st.subheader("설정")
    api_key_custom = st.text_input(
        "API 키 파일 경로 (비우면 openai_api_key.txt 사용)",
        value="",
        placeholder="openai_api_key.txt",
    )
    if api_key_custom:
        api_key_path = Path(api_key_custom)
    model = st.selectbox("모델", ["gpt-4.1", "gpt-4o", "gpt-4o-mini"], index=0)

st.subheader("📎 PDF 파일 업로드 (여러 개 가능)")

uploaded = st.file_uploader(
    "PDF 파일을 선택하세요 (다중 선택 가능)",
    type=["pdf"],
    accept_multiple_files=True,
)

## 중복 방지 기능 추가
# 업로드 파일 변경 감지
current_file_names = sorted([f.name for f in uploaded]) if uploaded else []

if "last_uploaded_files" not in st.session_state:
    st.session_state["last_uploaded_files"] = current_file_names

# 업로드 목록이 이전과 다르면 결과 초기화
if st.session_state["last_uploaded_files"] != current_file_names:
    if "summary_results" in st.session_state:
        del st.session_state["summary_results"]
    for key in list(st.session_state.keys()):
        if key.startswith("summary_edit_"):
            del st.session_state[key]
    st.session_state["last_uploaded_files"] = current_file_names
####

pdf_items = []  # (파일명, bytes) 리스트

if uploaded:
    for f in uploaded:
        pdf_items.append((f.name, f.read()))

if not pdf_items:
    st.info("PDF 파일을 업로드하세요.")
    st.stop()
    

    if folder_path_input:
        folder_path = Path(folder_path_input)
        if not folder_path.exists():
            st.error(f"경로가 존재하지 않습니다: {folder_path_input}")
        elif not folder_path.is_dir():
            st.error(f"폴더가 아닙니다: {folder_path_input}")
        else:
            pdf_files = sorted([p for p in folder_path.iterdir() if p.suffix.lower() == ".pdf"])
            if not pdf_files:
                st.warning(f"'{folder_path_input}' 폴더에 PDF 파일이 없습니다.")
            else:
                pdf_items = [(p.name, None) for p in pdf_files]
                st.success(f"총 {len(pdf_items)}개 PDF 파일을 찾았습니다.")
# 실행
if not pdf_items:
    st.stop()

run_label = "🚀 초록 생성 실행"
if st.button(run_label, type="primary"):
    try:
        client = get_client()
        # client = get_client(str(api_key_path))
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    results = []
    progress = st.progress(0, text="처리 중...")
    total = len(pdf_items)

    for i, (name, pdf_bytes) in enumerate(pdf_items):
        if task_mode == "EPIC 정부 보도자료 초록":
            r = process_one_pdf(client, name, pdf_bytes, prompt=DEFAULT_PROMPT, model=model)
        else:
            r = process_one_pdf_epts(client, name, pdf_bytes, model=model)

        results.append(r)
        progress.progress((i + 1) / total, text=f"처리 중... ({i + 1}/{total})")

    progress.empty()
    # 작업 유형과 함께 결과 저장 (작업 유형별로 분리)
    st.session_state["summary_results"] = results
    st.session_state["results_task_mode"] = task_mode
    st.rerun()


# -------------------------------------------------
# 🔵 세션 기본 초기화 추가
# -------------------------------------------------
if "summary_results" not in st.session_state:
    st.session_state["summary_results"] = []

if "regen_results" not in st.session_state:   # 🔵 수정
    st.session_state["regen_results"] = {}

if "pdf_items" not in st.session_state:      # 🔵 수정
    st.session_state["pdf_items"] = []

# 작업 유형이 일치하는지 확인 (다른 작업 유형의 결과가 남아있으면 무시)
if st.session_state.get("results_task_mode") != task_mode:
    st.info("새로운 작업을 시작하세요. 이전 결과는 다른 작업 유형의 결과입니다.")
    st.stop()

results = st.session_state["summary_results"]
st.success(f"총 {len(results)}건 처리 완료.")



# 결과 테이블 + 초록 확인(편집 가능) + txt 다운로드


# 🔵 재생성 결과 저장용 초기화 (루프 위쪽에 추가)
if "regen_results" not in st.session_state:
    st.session_state["regen_results"] = {}

BASE_ADMIN_URL = "https://eiec.kdi.re.kr/aoslwj9584/epic/masterList.do"

for i, row in enumerate(results):

    with st.expander(
        f"📄 {row['파일명']}" + (f" — 오류: {row['오류']}" if row.get("오류") else ""),
        expanded=(i == 0)
    ):

        if row.get("오류"):
            st.error(row["오류"])
        else:
            st.markdown("### 📝 기존 초록")

            original_abstract = row.get("요약 결과", "")

            st.text_area(
                "기존 초록",
                value=original_abstract,
                height=350,
                key=f"orig_{task_mode}_{i}",
                disabled=False,
                label_visibility="collapsed",
            )

            filename = row["파일명"]
            col1, col2 = st.columns(2)

            # 관리자 링크
            with col1:
                match = re.search(r'\d+', filename)
                if match:
                    key_value = match.group()
                    admin_url = (
                        f"{BASE_ADMIN_URL}"
                        f"?pg=1&pp=20&skey=symbol"
                        f"&svalue={key_value}&sdatetp=reg&sdate="
                    )
                    st.link_button("🔎 관리자 경로 열기", admin_url)

            # 🔄 재생성 버튼
            with col2:
                if st.button("🔄 초록 재생성", key=f"regen_btn_{task_mode}_{i}"):

                    with st.spinner("재생성 중..."):

                        client = get_client()

                        pdf_bytes = None
                        for name, content in pdf_items:
                            if name == filename:
                                pdf_bytes = content
                                break

                        if task_mode == "EPIC 정부 보도자료 초록":
                            new_result = process_one_pdf(
                                client,
                                filename,
                                pdf_bytes,
                                prompt=DEFAULT_PROMPT,
                                model=model
                            )
                        else:
                            new_result = process_one_pdf_epts(
                                client,
                                filename,
                                pdf_bytes,
                                model=model
                            )

                        # 🔵 재생성 결과만 따로 저장
                        st.session_state["regen_results"][i] = new_result.get("요약 결과", "")

                        st.rerun()

            # 🔵 재생성 결과가 있으면 아래에 추가 표시
            if i in st.session_state["regen_results"]:
                st.markdown("---")
                st.markdown("### 🔄 재생성 초록 (NEW)")

                st.text_area(
                    "재생성 초록",
                    value=st.session_state["regen_results"][i],
                    height=350,
                    key=f"regen_text_{task_mode}_{i}",
                    disabled=False,
                    label_visibility="collapsed",
                )


# # 🔵 재생성 결과 저장용 초기화 (루프 위쪽에 추가)
# if "regen_results" not in st.session_state:
#     st.session_state["regen_results"] = {}
    
# BASE_ADMIN_URL = "https://eiec.kdi.re.kr/aoslwj9584/epic/masterList.do"

# for i, row in enumerate(results):
#     with st.expander(f"📄 {row['파일명']}" + (f" — 오류: {row['오류']}" if row.get("오류") else ""), expanded=(i == 0)):
#         if row.get("오류"):
#             st.error(row["오류"])
#         else:
#             st.markdown("**요약 결과 (초록)** — 아래에서 수정 후 다운로드하면 수정본이 저장됩니다.")
#             abstract = row.get("요약 결과", "")
#             # 결과 길이에 맞춰 높이 설정 (최소 350px, 최대 700px)
#             line_approx = max(1, len(abstract) // 40)
#             area_height = min(700, max(350, 120 + line_approx * 22))

#             # 🔵 수정 시작
#             regen_ver = st.session_state["regen_counter"].get(i, 0)
#             edit_key = f"summary_edit_{task_mode}_{i}_{regen_ver}"
#             # 🔵 수정 끝

            
#             # 작업 유형별로 고유한 키 사용 (EPIC/ETPS 분리)
#             edit_key = f"summary_edit_{task_mode}_{i}"
#             edited = st.text_area(
#                 "초록",
#                 value=abstract,
#                 height=int(area_height),
#                 key=edit_key,
#                 disabled=False,
#                 label_visibility="collapsed",
#             )
            
#             # ------------------------------------
#             # 🔎 관리자 경로 자동 생성 (파일명 기반)
#             # ------------------------------------
#             filename = row["파일명"]

#             col1, col2 = st.columns(2)
            
#             with col1:
#                 match = re.search(r'\d+', filename)
#                 if match:
#                     key_value = match.group()
#                     admin_url = (
#                         f"{BASE_ADMIN_URL}"
#                         f"?pg=1&pp=20"
#                         f"&skey=symbol"
#                         f"&svalue={key_value}"
#                         f"&sdatetp=reg&sdate="
#                     )
#                     st.link_button("🔎 관리자 경로 열기", admin_url)
#                 else:
#                     st.warning("파일명에서 관리자 키 값을 찾을 수 없습니다.")
            
#             with col2:
#                 if st.button("🔄 초록 재생성", key=f"regen_{task_mode}_{i}_{row['파일명']}"):
            
#                     with st.spinner("해당 파일 초록을 재생성 중..."):
            
#                         client = get_client()
            
#                         pdf_bytes = None
#                         for name, content in pdf_items:
#                             if name == filename:
#                                 pdf_bytes = content
#                                 break
            
#                         if task_mode == "EPIC 정부 보도자료 초록":
#                             new_result = process_one_pdf(
#                                 client,
#                                 filename,
#                                 pdf_bytes,
#                                 prompt=DEFAULT_PROMPT,
#                                 model=model
#                             )
#                         else:
#                             new_result = process_one_pdf_epts(
#                                 client,
#                                 filename,
#                                 pdf_bytes,
#                                 model=model
#                             )
#                         # 🔵 수정 시작
#                         st.session_state["summary_results"][i] = new_result
#                         st.session_state["regen_counter"][i] = regen_ver + 1
#                         # 🔵 수정 끝
#                         st.rerun()


            

                        
        # 개별 txt 다운로드 (수정된 내용 반영)
        edit_key = f"summary_edit_{task_mode}_{i}"
        row_for_dl = {**row, "요약 결과": st.session_state.get(edit_key, row.get("요약 결과", ""))}
        txt_content = summary_to_txt_content(row_for_dl)
        base_name = Path(row["파일명"]).stem
        
        # 대책명/정책명 추출하여 파일명 생성
        summary_text = row_for_dl.get("요약 결과", "")
        title_prefix = extract_title_from_summary(summary_text, task_mode)
        if title_prefix:
            txt_name = f"{title_prefix}_{base_name}.txt"
        else:
            txt_name = f"{base_name}.txt"
        txt_name = sanitize_filename(txt_name, 100)
        
        st.download_button(
            label=f"📥 {txt_name} 다운로드",
            data=txt_content,
            file_name=txt_name,
            mime="text/plain; charset=utf-8",
            key=f"dl_{i}",
        )

# 일괄 다운로드 (zip) — 수정된 초록 반영
st.divider()
st.subheader("📦 전체 초록 한 번에 받기 (ZIP)")
zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
    for i, row in enumerate(results):
        if row.get("오류"):
            continue
        edit_key = f"summary_edit_{task_mode}_{i}"
        row_for_zip = {**row, "요약 결과": st.session_state.get(edit_key, row.get("요약 결과", ""))}
        base = Path(row["파일명"]).stem
        
        # 대책명/정책명 추출하여 파일명 생성
        summary_text = row_for_zip.get("요약 결과", "")
        title_prefix = extract_title_from_summary(summary_text, task_mode)
        if title_prefix:
            name = f"{title_prefix}_{base}.txt"
        else:
            name = f"{base}.txt"
        name = sanitize_filename(name, 100)
        
        zf.writestr(name, summary_to_txt_content(row_for_zip))
zip_buffer.seek(0)
st.download_button(
    label="ZIP 파일로 전체 초록 다운로드",
    data=zip_buffer,
    file_name="epic_summary_txt.zip",
    mime="application/zip",
    key="dl_zip",
)























