# -*- coding: utf-8 -*-
"""
EPIC PDF 초록 생성 핵심 로직 (노트북 summary_project_0212.ipynb 기반)
- PDF 텍스트 추출: PyMuPDF(fitz) 사용
- OpenAI GPT로 정부 보도자료 형식 초록 생성
"""
import os
import re
import io
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from openai import OpenAI


# 기본 프롬프트 (노트북 summary_project_0212.ipynb와 동일)
DEFAULT_PROMPT = """
정부 보도자료의 초록을 작성할거야. 아래 지침을 반드시 따라줘.

1. 문단 구성
 - 문단은 개요 1문단, 본문 2~5문단, 마무리 1문단, (조건부) 참고/별첨/첨부 문단 순서로 작성한다.
 - 문단 사이는 반드시 빈 줄 1줄로만 구분한다(즉 '\n\n' 형태).
 - 최종 출력은 오직 완성된 초록만 출력한다.

2. 개요 문단은 한 문장으로 작성한다.
 - 형식: A(부처)는 MM.DD.(day) ~~한다고 밝혔다. 또는 ~~했다.
 - 날짜 표기는 예: 7월 30일(월) → 7.30.(월), 10월 26일 → 10.26. 형태로 변경하며, 초록 전체에 동일하게 적용한다.

3. 본문 문단
 - 어미는 모두 음슴체로 끝내고 마지막에 "." 를 찍는다.
 - 한 문단은 한 문장으로만 구성하며, 절대로 두 문장으로 작성하지 않는다.
 - 개요를 제외한 모든 본문 문단 앞에는 "-"를 붙인다.
 - 주요 내용을 간결하게 요약하되, 해당 자료에서 말하고자 하는 바와 강조점은 명확히 포함한다.
 - 본문은 가급적 3~5문단 이내로 요약하며, 문서에 따라 유연하게 적용하되 7~8문단은 최소화한다.
 - <참고><별첨><첨부> 등 추가 자료의 내용은 본문 초록 작성에 사용하지 않는다.
 - 각 문단은 반드시 빈 줄 1줄로만 구분한다(즉 '\n\n' 형태).
 
4. 마무리 문단은 A가 향후 ~~할 계획이거나 ~~하겠다고 밝혔다는 내용을 포함한 음슴체 문장으로 작성.
 - A(부처)의 직책과 개인 이름은 쓰지 않고 A(부처)만 작성한다.

5. <참고>/<별첨>/<첨부>
 - 원문에 '<참고>' '<별첨>' '<첨부>'가 존재하는 경우에만 작성한다.
 - 원문에 사용된 표기(<참고>, <별첨>, <첨부>)와 번호를 변경 없이 그대로 유지한다.
 - 여러 개가 있는 경우에도 하나의 문단으로 작성한다.
 - 작성 형식은 아래와 같다.

   <참고>
   1. 원문에 사용된 제목 1
   2. 원문에 사용된 제목 2

 - 표제(<참고>/<별첨>/<첨부>)는 한 번만 작성한다.
 - 하위 항목은 숫자 번호(1., 2., …)만 사용한다.
 - 해당 블록 전체 앞뒤로만 문단 구분(빈 줄 1줄)을 둔다.

6. 작성 원칙
 - 모든 문장은 말이 되어야 하며 맥락상 어색하지 않아야 한다.
 - 모든 단어 및 문장은 제공된 보도자료 텍스트만을 활용해야 한다.
 - 보도자료에 없는 내용을 임의로 생성하거나 외부 정보를 포함하면 안 된다.
 - 위 문단 구조와 형식을 어긴 출력은 잘못된 결과이므로, 반드시 형식을 먼저 맞춘 후 내용을 작성한다.

7. 이곳에 첨부한 PDF 자료(정부 보도자료)를 활용해 위 지침을 모두 따른 하나의 완성된 초록을 작성한다.

보도자료는 다음과 같습니다:
"""

# EPTS 대책자료용 시스템 규칙 (main_notebook_EPTS_rev_0210.ipynb의 SYSTEM_RULES)
SYSTEM_RULES_EPTS = """

## System message

당신은 정부 부처 정책/대책 보도자료를 “이용자 페이지 입력 규격”에 맞춰 요약·정리하는 시니어 에디터다.
입력 문서(본문·표·그림·붙임·별첨·요약본·인포그래픽)에 근거하지 않은 사실·수치·일정·기관·법령·평가·해석을 절대 추가하지 않는다.

### [최상위 원칙]
- 본 작업은 요약(summarization)이 아니라  입력 문서의 구조를 유지한 채 재배치·정렬하는 편집 작업이다.
- 모든 내용은 원문 표현을 최우선으로 사용한다. (핵심 수치·날짜·목표·정책수단은 문서 표현)
- 문서에 없는 정보는 “문서에 명시 없음” 으로 표기한다.
- 원문에 존재하는 문장·구·항목을 더 짧은 표현으로 줄이거나 여러 항목을 하나의 문장으로 합치는 행위를 금지한다.

### [환각 방지·검증]
- 수치·단위·기간·목표연도는 문서 기준 그대로 사용한다. : 조/억/%/만명 등 단위, 기준시점(연/분기/월), 목표연도(’26/’30/’45 등)를 그대로 확인해 정확히 적는다(추정 금지)
- 반복 내용은 가장 구체적인 근거를 우선 채택한다.
- 근거 표기가 가능한 경우 (근거: 본문/표/캡션) 형태로 표시한다.

### [비전·목표]
- 입력 문서에 ‘비전’, ‘목표’, ‘추진목표’, ‘4대 목표’ 등으로 명시된 항목이 있는 경우에만 해당 문구를 포함할 수 있다.
- ‘비전’, ‘목표’ 등은 요약·재서술·의미 변경을 금지한다.(추정 금지)
- 문서에 기재된 표현을 그대로 사용한다.(생성 변경 금지)
- 정책 내용 영역에 상위 항목으로 배치한다.

### [<세부 추진계획> 정보 레벨]
- 정책 내용은 L1 → L2 → L3 → L4의 위계를 따른다.
- L1: 정책 대분류(분야·축·과제명)
  (예: 민생경제 회복)
- L2: 정책 방향과 지원 대상·목적을 포괄하는 정책 축(추진과제, 정책 방향 문장)
  (예: 소상공인 3대 부담 경감과 함께 매출회복 및 경쟁력 강화 지원)
- L3: L2를 구성하는 정책 묶음 단위(세부 추진과제)
  (패키지, 지원군, ○○ 지원, ○○ 제고, ○○ 확대 등)
- L4: 집행 수단·사업·제도·예산·수치:  개별 지원사업, 세제·금융 수단, 예산 규모, 제도명 등 : 문단 서두에 "(...)"가 있으면 "..."를 원문과 같이 입력한다.
  (L2 하위에 L4를 직접 배치하는 것을 금지)
- 동일 블록 내에서 서로 다른 정보 레벨를 혼용하지 않는다.
- L1, L2, L3의 번호체계 단계가 넘어갈 때는 1줄 공백을 넣어서 작성한다.

### [세부 추진계획 문장 우선]
- 정책 내용에서 하위 항목을 구성할때, 원문에 굵은 문장, 숫자 네모 박스 등은 상위 정책 축을 나타내는 경우가 많으므로 우선적으로 L2 후보로 검토한다.
- 다만, 해당 문장이 정책 방향이 아닌 단순 열거 또는 설명에 해당하는 경우에는 하위 레벨(L3 또는 L4)로 조정할 수 있다.
- 방향 문장이 있는 경우, 세부 수단을 새 과제나 중간 제목으로 재구성하지 않는다.

### [집행 수단·예시]
- 원문에 이미 나열된 항목만 사용한다.
- 순서·표현을 그대로 유지하며 요약·통합·재분류를 금지한다.
- 집행 수단·예시는 원문에 동일 문단 또는 동일 항목 묶음 내에서 ‘-’, ‘·’, ‘○’, ‘①’ 등으로 이미 나열된 경우에만 포함할 수 있다.
- 집행수단 및 예시의 문장 앞에 '(...)'이 있는 경우 '...'을 원문과 같이 L4로 작성한다.

### [서식·기호]
- 볼드는 제목과 정책 내용의 번호 항목에만 사용한다.
- 번호 체계는 ‘1. → 1) → - → ·’만 사용한다.
- 번호체계 뒤에는 뒤는 공백없이 붙여쓰기
- L1, L2, L3 번호체계가 바꿀때는 1줄 공백을 넣어서 작성한다.
- 정책 내용에는 마침표를 사용하지 않는다.
- 「 」 앞에는 반드시 띄어쓴다.

### [최종 출력 구조(순서 고정)]

1. 정책 관련 정보: 문서 제목 사용. 제목이 없으면 “문서에 명시 없음”
 -관련부처(예시: 관계부처합동, 재정경제부)
 -발행일자(예시: 2026. 1. 26)

2. 정책배경: 1~4단락(기본 3단락)으로 서술하고, 추진배경, 문제인식, 정책필요성, 대책 개요, 기대효과를 중심으로 작성한다. 
   * (1단락) 추진 배경: 세계·국내 동향 / 시대적 상황 / 문제점
   * (2단락) 대책 개요: 목적 / 전략 / 기본방향 / 추진체계 큰 틀(문서 범위)
   * (3단락) 기대효과: 기대효과 / 향후 전망(문서 표현 기반)
   * 단락당 입력화면 2줄 분량 목표, 장문 금지
   * 필요 시 문장 말미 근거 표기: (근거: 본문 p.x)
   * 문장은 음슴체를 사용하고 문장 끝에 마침표를 찍는다.(예:~하였음. ~임)

3. 정책 내용: 향후 추진과제 중심, 반드시 명사형, 마침표 금지
   * 필요 시 문장 말미 근거 표기: (근거: 본문 p.x)

< 비전 및 목표 > 
 ① 비전 : 비전 문구 (문서 표현 그대로)
 ② 목표 : 목표 (문서에 명시된 항목 그대로, 요약·재구성 금지)

< 추진체계/추진방향/추진과제 >
 ① 문서에 명시된 추진과제 축 또는 체계 명칭 그대로 사용
   - (세부 내용이 있는 경우 작성)
 ② 문서에 명시된 추진방향 또는 최근 추진 성과 등 작성
   - (세부 내용이 있는 경우 작성)

4. 주요 내용: 향후 추진과제 중심, 반드시 명사형, 마침표 금지.

< 세부 추진계획 > (분류 기호 앞 들여쓰기는 양식과 동일하게 맞춤)

1. 정책 대분류: 분야/축/과제명
 1)정책 방향과 지원 대상·목적을 포괄하는 정책 축(추진과제, 정책 방향 문장)
  -상위 추진과제를 구성하는 정책 묶음 단위(세부 추진과제)
   ·집행 수단·사업·제도·예산·수치: 문장 앞에 '(집행수단)'이 있는 경우 '집행수단'을 원문과 같이 L4로 작성한다.

### [최종 점검]

출력 직전 아래를 자체 점검해 위반 시 수정한다

* 오타/깨짐/‘?’ 문자
* 내용 중 사용되는 전각은 ‘·’를 사용한다.(‘⋅’ 사용 금지)
* 정책 내용 영역 마침표
* 「 」 앞 띄어쓰기
* 번호체계 `1. → 1) → - → ·`  
* 불필요한 표 사용 여부
* 문서 외 정보 혼입 여부(삭제 또는 “문서에 명시 없음/추가자료 필요”)
""".strip()


# def get_client(api_key_path: str = "openai_api_key.txt") -> OpenAI:
#     """API 키 파일에서 읽어 OpenAI 클라이언트 반환."""
#     path = Path(api_key_path)
#     if not path.exists():
#         raise FileNotFoundError(f"API 키 파일을 찾을 수 없습니다: {api_key_path}")
#     with open(path, "r", encoding="utf-8") as f:
#         api_key = f.read().strip()
#     return OpenAI(api_key=api_key)
def get_client() -> OpenAI:
    """Streamlit Secrets에서 API 키를 읽어 OpenAI 클라이언트 반환."""
    api_key = st.secrets["OPENAI_API_KEY"]
    return OpenAI(api_key=api_key)

def extract_text_from_pdf(pdf_path_or_bytes):
    """
    PDF에서 텍스트 추출.
    pdf_path_or_bytes: 파일 경로(str/Path) 또는 bytes (업로드 파일)
    """
    if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
        doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
    else:
        doc = fitz.open(pdf_path_or_bytes)
    text = ""
    try:
        for page in doc:
            text += page.get_text("text")
    finally:
        doc.close()
    return text.strip()


def summarize_text_with_gpt(
    client: OpenAI,
    text: str,
    model: str = "gpt-4.1",
    max_chunk_size: int = 10000,
    prompt: str | None = None,
):
    """텍스트 앞부분을 GPT로 요약."""
    if not (text or "").strip():
        return "⚠️ 텍스트 없음 (스캔본 또는 추출 불가)"

    head_text = text[:max_chunk_size]
    if prompt is None:
        prompt = "다음 내용을 5줄 이내로 핵심만 요약해줘."

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "당신은 정부·경제 정책 보고서를 공식 문체로 요약하는 분석가입니다."},
            {"role": "user", "content": f"{prompt}\n\n{head_text}"},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def admin_url_from_filename(pdf_filename: str, is_epts: bool = False) -> str:
    """파일명에서 관리자 경로 생성."""
    base = os.path.splitext(os.path.basename(pdf_filename))[0]
    base = re.sub(r"^[A-Za-z]+", "", base)
    m = re.match(r"(\d+)", base)
    n_str = m.group(1) if m else ""
    if not n_str:
        return ""
    if is_epts:
        return "https://epts.kdi.re.kr/kdicmsAuth/"
    return (
        "https://eiec.kdi.re.kr/aoslwj9584/epic/masterList.do"
        f"?pg=1&pp=20&skey=symbol&svalue={n_str}"
    )


def generate_epic_abstract_from_pdf_bytes(
    client: OpenAI,
    pdf_bytes: bytes,
    pdf_filename: str,
    prompt: str | None = None,
    model: str = "gpt-4.1",
) -> str:
    """
    EPIC 정부 보도자료용: PDF 원본 파일을 OpenAI 파일로 업로드 후 DEFAULT_PROMPT에 따라 초록 생성.
    """
    prompt = prompt or DEFAULT_PROMPT
    # 파일명이 .pdf로 끝나지 않으면 확장자 추가
    if not pdf_filename.lower().endswith('.pdf'):
        pdf_filename = pdf_filename + '.pdf'
    
    uploaded = client.files.create(
        file=(pdf_filename, io.BytesIO(pdf_bytes)),
        purpose="assistants",
    )
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "당신은 정부·경제 정책 보고서를 공식 문체로 요약하는 분석가입니다."}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                        {
                            "type": "input_file",
                            "file_id": uploaded.id,
                        },
                    ],
                },
            ],
            timeout=180,
        )
        return resp.output_text
    finally:
        try:
            client.files.delete(uploaded.id)
        except Exception:
            pass


def process_one_pdf(client, pdf_name: str, pdf_content: bytes, prompt: str | None = None, model: str = "gpt-4.1"):
    """
    EPIC 정부 보도자료용 PDF 하나 처리:
    - (선택) 텍스트 미리보기
    - OpenAI 파일 업로드 + DEFAULT_PROMPT 기반 초록 생성
    """
    prompt = prompt or DEFAULT_PROMPT
    try:
        # 미리보기용 텍스트 (있으면 좋고, 없어도 기능에는 영향 없음)
        try:
            text = extract_text_from_pdf(pdf_content)
            text_preview = (text[:3000] + "...") if len(text) > 3000 else text
        except Exception:
            text_preview = ""

        summary = generate_epic_abstract_from_pdf_bytes(
            client=client,
            pdf_bytes=pdf_content,
            pdf_filename=pdf_name,
            prompt=prompt,
            model=model,
        )
        admin_url = admin_url_from_filename(pdf_name, is_epts=False)
        return {
            "파일명": pdf_name,
            "텍스트파싱 결과": text_preview,
            "요약 결과": summary,
            "관리자 경로": admin_url,
            "오류": None,
        }
    except Exception as e:
        return {
            "파일명": pdf_name,
            "텍스트파싱 결과": "",
            "요약 결과": "",
            "관리자 경로": "",
            "오류": str(e),
        }


def process_pdfs_from_folder(client, folder_path: str, prompt: str | None = None, model: str = "gpt-4.1"):
    """
    폴더 내 모든 PDF를 처리해 결과 리스트 반환.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return []
    prompt = prompt or DEFAULT_PROMPT
    results = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() != ".pdf":
            continue
        try:
            text = extract_text_from_pdf(str(f))
            text_preview = (text[:3000] + "...") if len(text) > 3000 else text
            summary = summarize_text_with_gpt(client, text, model=model, prompt=prompt)
            admin_url = admin_url_from_filename(f.name)
            results.append({
                "파일명": f.name,
                "텍스트파싱 결과": text_preview,
                "요약 결과": summary,
                "관리자 경로": admin_url,
                "오류": None,
            })
        except Exception as e:
            results.append({
                "파일명": f.name,
                "텍스트파싱 결과": "",
                "요약 결과": "",
                "관리자 경로": "",
                "오류": str(e),
            })
    return results


def generate_policy_abstract_from_pdf_bytes(
    client: OpenAI,
    pdf_bytes: bytes,
    pdf_filename: str,
    title: str,
    model: str = "gpt-4.1",
) -> str:
    """
    EPTS 대책자료용: PDF 원본 파일을 OpenAI 파일로 업로드 후 SYSTEM_RULES_EPTS에 따라 초록 생성.
    (main_notebook_EPTS_rev_0210.ipynb의 generate_file_abstract를 참고)
    """
    # 파일명이 .pdf로 끝나지 않으면 확장자 추가
    if not pdf_filename.lower().endswith('.pdf'):
        pdf_filename = pdf_filename + '.pdf'
    
    uploaded = client.files.create(
        file=(pdf_filename, io.BytesIO(pdf_bytes)),
        purpose="assistants",
    )
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content":[{"type": "input_text", "text": SYSTEM_RULES_EPTS}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"제목: {title}\n\n아래 파일을 참고하여 정책배경/주요내용을 작성하세요.",
                        },
                        {
                            "type": "input_file",
                            "file_id": uploaded.id,
                        },
                    ],
                },
            ],
            timeout=180,
        )
        # openai-python 최신 버전에서 제공하는 편의 프로퍼티
        return resp.output_text
    finally:
        # 불필요한 파일은 정리 (실패하더라도 무시)
        try:
            client.files.delete(uploaded.id)
        except Exception:
            pass


def process_one_pdf_epts(
    client: OpenAI,
    pdf_name: str,
    pdf_content: bytes,
    model: str = "gpt-4.1",
):
    """
    EPTS 대책자료용 PDF 하나 처리:
    - (선택) 텍스트 미리보기
    - OpenAI 파일 업로드 + SYSTEM_RULES_EPTS 기반 초록 생성
    """
    try:
        # 미리보기용 텍스트 (있으면 좋고, 없어도 기능에는 영향 없음)
        try:
            text = extract_text_from_pdf(pdf_content)
            text_preview = (text[:3000] + "...") if len(text) > 3000 else text
        except Exception:
            text_preview = ""

        title = os.path.splitext(os.path.basename(pdf_name))[0]
        summary = generate_policy_abstract_from_pdf_bytes(
            client=client,
            pdf_bytes=pdf_content,
            pdf_filename=pdf_name,
            title=title,
            model=model,
        )
        admin_url = admin_url_from_filename(pdf_name, is_epts=True)
        return {
            "파일명": pdf_name,
            "텍스트파싱 결과": text_preview,
            "요약 결과": summary,
            "관리자 경로": admin_url,
            "오류": None,
        }
    except Exception as e:
        return {
            "파일명": pdf_name,
            "텍스트파싱 결과": "",
            "요약 결과": "",
            "관리자 경로": "",
            "오류": str(e),
        }





