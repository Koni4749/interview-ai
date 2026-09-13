import streamlit as st
from openai import OpenAI
import pdfplumber
import io
import json
import os
import base64
import random

st.set_page_config(page_title="학생부 모의면접", page_icon="🎓", layout="wide")

# --- Secrets 검증 및 모델 설정 ---
if "API_KEY" not in st.secrets:
    st.error("⚠️ `.streamlit/secrets.toml`에 API_KEY가 설정되지 않았습니다.")
    st.stop()

api_key = st.secrets["API_KEY"]
base_url = st.secrets.get("BASE_URL", None)
MODEL_ID = st.secrets.get("MODEL_NAME", "google/gemma-4-31B-it")

client = OpenAI(api_key=api_key, base_url=base_url)

# --- 대학별 평가표 데이터 로드 ---
@st.cache_data
def load_university_rubrics():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "universities.json")
    
    if not os.path.exists(json_path):
        st.error(f"⚠️ `universities.json` 파일을 찾을 수 없습니다. (경로: {json_path})")
        return {}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"⚠️ `universities.json` 파일 파싱 오류: {e}")
        return {}

UNIV_DATA = load_university_rubrics()
UNIV_CHOICES = list(UNIV_DATA.keys())

# --- PDF 파싱 함수 ---
def extract_text_from_pdf(file_bytes) -> str:
    text_content = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if page_text:
                text_content.append(f"--- [Page {idx}] ---\n{page_text.strip()}")
    return "\n\n".join(text_content)

# --- 사진(이미지) 텍스트 추출 함수 (Vision API 호출) ---
def extract_text_from_images(uploaded_images, client, model_id) -> str:
    extracted_pages = []
    for idx, img in enumerate(uploaded_images, start=1):
        img_bytes = img.read()
        img.seek(0)
        b64_str = base64.b64encode(img_bytes).decode("utf-8")
        mime_type = img.type if img.type else "image/jpeg"

        prompt = """
이 이미지는 고등학교 학교생활기록부 사진입니다.
사진 속 텍스트를 누락 없이 그대로 전사해 주세요. 사족이나 분석은 절대 쓰지 마세요.
"""
        try:
            res = client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_str}"}}
                        ]
                    }
                ],
                temperature=0.2
            )
            text = res.choices[0].message.content
            if text:
                extracted_pages.append(f"--- [사진 {idx} 추출 내용] ---\n{text.strip()}")
        except Exception as e:
            st.error(f"사진 {idx}번 텍스트 추출 중 오류 발생: {e}")
    return "\n\n".join(extracted_pages)

# --- 세션 상태 초기화 ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "interview_active" not in st.session_state:
    st.session_state.interview_active = False
if "turn_count" not in st.session_state:
    st.session_state.turn_count = 0
if "max_turns" not in st.session_state:
    st.session_state.max_turns = 3
if "evaluation_result" not in st.session_state:
    st.session_state.evaluation_result = None
if "parsed_record" not in st.session_state:
    st.session_state.parsed_record = ""
if "last_uploaded_file" not in st.session_state:
    st.session_state.last_uploaded_file = None
# 중복 질문 방지용 누적 질문 보관소 (새 면접을 해도 유지됨)
if "history_of_all_questions" not in st.session_state:
    st.session_state.history_of_all_questions = []

# --- 사이드바 설정 ---
with st.sidebar:
    st.header("⚙️ 모의면접 설정")
    
    target_univ = st.selectbox("지원 대학 선택", UNIV_CHOICES, index=0)
    current_rubric = UNIV_DATA[target_univ]
    target_major = st.text_input("지원 학과", value="환경공학과")
    
    # 질문 중복 탈피를 위한 면접 유형 선택
    interview_focus = st.selectbox(
        "🎯 이번 세션 면접 검증 초점",
        [
            "랜덤 종합 면접 (균형 검증)",
            "기초 교과(수학/과학/사회) 교과서 기본 원리 검증",
            "전공 심화 탐구 및 진위 확인 (프로젝트/실험 위주)",
            "공동체 역량 및 인성 (갈등 해결, 협업, 소통 위주)"
        ],
        index=0,
        help="새로운 면접을 볼 때마다 초점을 변경하면 생기부의 다양한 영역을 고르게 대비할 수 있습니다."
    )
    
    with st.expander(f"📌 {target_univ} 평가요소 및 기출 경향"):
        st.markdown(f"**면접 스타일:**\n{current_rubric.get('interview_style', '')}")
        st.markdown("**평가 배점:**")
        for factor in current_rubric.get("evaluation_factors", []):
            st.markdown(f"- **{factor['name']} ({factor['ratio']})**: {factor['criteria']}")
        
        if "example_questions" in current_rubric:
            st.markdown("**대표 기출 및 예시 문항:**")
            for q in current_rubric["example_questions"]:
                st.markdown(f"- *{q}*")

    st.divider()
    st.subheader("📄 생기부 입력")
    input_mode = st.radio("입력 방식", ["PDF 업로드 (나이스)", "사진 업로드 (JPG, PNG)", "직접 텍스트 입력"], horizontal=True)

    if input_mode == "PDF 업로드 (나이스)":
        uploaded_file = st.file_uploader("생기부 PDF 업로드", type=["pdf"])
        if uploaded_file is not None and uploaded_file.name != st.session_state.last_uploaded_file:
            with st.spinner("PDF에서 텍스트를 추출하고 있습니다..."):
                file_bytes = uploaded_file.read()
                st.session_state.parsed_record = extract_text_from_pdf(file_bytes)
                st.session_state.last_uploaded_file = uploaded_file.name
            st.success("PDF 텍스트 파싱 완료!")

    elif input_mode == "사진 업로드 (JPG, PNG)":
        uploaded_images = st.file_uploader(
            "생기부 사진 업로드 (여러 장 가능)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True
        )
        if uploaded_images:
            st.caption(f"선택된 사진: {len(uploaded_images)}장")
            if st.button("📷 사진에서 텍스트 자동 추출", use_container_width=True):
                with st.spinner("AI가 사진 속 텍스트를 읽어오는 중입니다..."):
                    st.session_state.parsed_record = extract_text_from_images(uploaded_images, client, MODEL_ID)
                st.success("사진 텍스트 추출 완료!")

    if input_mode in ["PDF 업로드 (나이스)", "사진 업로드 (JPG, PNG)"]:
        student_record = st.text_area(
            "추출된 텍스트 확인/수정",
            value=st.session_state.parsed_record,
            height=200,
            placeholder="파일을 올리면 추출된 내용이 표시됩니다."
        )
    else:
        student_record = st.text_area(
            "세특 및 탐구활동 직접 입력",
            height=200,
            placeholder="[화학II] 르샤틀리에 원리를 이용한 폐수 중금속 침전 실험을 설계하고..."
        )

    st.divider()
    st.session_state.max_turns = st.slider("면접 질문 횟수 (턴)", min_value=2, max_value=6, value=3)

    if st.button("🚀 모의면접 시작", type="primary", use_container_width=True):
        if not student_record.strip():
            st.error("생기부 내용을 입력하거나 파일을 업로드해주세요.")
        else:
            st.session_state.active_record = student_record
            st.session_state.target_univ = target_univ
            st.session_state.target_major = target_major
            st.session_state.current_rubric = current_rubric
            st.session_state.interview_focus = interview_focus
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.interview_active = True
            st.session_state.evaluation_result = None

            rubric_str = "\n".join([f"- {f['name']} ({f['ratio']}): {f['criteria']}" for f in current_rubric.get("evaluation_factors", [])])
            example_q_str = "\n".join([f"- {q}" for q in current_rubric.get("example_questions", [])])
            
            # 이전에 질문했던 기록들을 모아서 중복 배제 프롬프트 생성
            past_q_filter = ""
            if st.session_state.history_of_all_questions:
                past_q_summary = "\n".join([f"- {q}" for q in st.session_state.history_of_all_questions[-8:]])
                past_q_filter = f"""
[★ 중복 금지 필수 규칙]
지원자는 이미 이전 모의면접 세션에서 아래의 질문들을 받았습니다.
아래에 등장한 활동/소재/과목은 **절대 다시 질문하지 마세요.**
생기부의 다른 페이지, 다른 학년, 다른 과목의 세특이나 창체 활동을 새로 발굴하여 질문해야 합니다.
[이전 세션 질문 목록]:
{past_q_summary}
"""

            # 첫 번째 질문 생성
            with st.spinner(f"{target_univ} 기준 첫 번째 질문을 구성 중입니다..."):
                system_prompt = f"""
당신은 {target_univ} {target_major} 학생부종합전형의 전문 입학사정관입니다.

[대학별 면접 기조]
{current_rubric.get('interview_style', '')}

[평가 핵심 요소]
{rubric_str}

[해당 대학의 대표적 질문 경향]
{example_q_str}

[이번 세션의 집중 검증 포커스]: {interview_focus}
(만약 지원 대학이 '인하대학교'이고 포커스가 기초교과 검증이라면, 고교 화학/물리/생명과학/수학 교과서의 기본 법칙 및 개념 원리를 구술하도록 직접 질문하세요.)

{past_q_filter}

[지원자 생기부]
{student_record[:6000]}

[질문 지침]
1. 이번 세션의 집중 검증 포커스({interview_focus})에 맞춰 첫 질문을 던지세요.
2. 예의 바르고 날카로운 면접관 어조(~바랍니다, ~습니까?)를 유지하세요.
3. 질문은 1개만 제시하세요.
"""
                try:
                    res = client.chat.completions.create(
                        model=MODEL_ID,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"면접을 시작합니다. {target_univ} {target_major} 입학사정관으로서 첫 번째 질문을 제시하세요."}
                        ],
                        temperature=0.8
                    )
                    first_q = res.choices[0].message.content
                    st.session_state.messages.append({"role": "assistant", "content": first_q})
                    st.session_state.history_of_all_questions.append(first_q)
                    st.rerun()
                except Exception as e:
                    st.error(f"질문 생성 실패: {e}")

# --- 메인 화면 인터페이스 ---
st.title("🎓 학생부 모의면접")

if not st.session_state.interview_active and not st.session_state.evaluation_result:
    st.info("👈 왼쪽 사이드바에서 **지원 대학**, **검증 초점**, **생기부 파일**을 설정한 뒤 **[모의면접 시작]**을 눌러주세요.")

# 대화 내용 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# --- 질의응답 진행 루프 ---
if st.session_state.interview_active:
    st.caption(f"진행 상황: 질문 {st.session_state.turn_count + 1} / {st.session_state.max_turns} | {st.session_state.target_univ} {st.session_state.target_major} ({st.session_state.interview_focus})")

    user_input = st.chat_input("면접 답변을 입력하세요...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.turn_count += 1

        if st.session_state.turn_count < st.session_state.max_turns:
            with st.spinner("답변을 분석하여 꼬리질문을 생성하고 있습니다..."):
                rubric = st.session_state.current_rubric
                example_q_str = "\n".join([f"- {q}" for q in rubric.get("example_questions", [])])
                
                followup_prompt = f"""
당신은 {st.session_state.target_univ} {st.session_state.target_major} 입학사정관입니다.
면접 기조: {rubric.get('interview_style', '')}
참고 질문 스타일:
{example_q_str}

[생기부 내용]
{st.session_state.active_record[:6000]}

[지침]
1. 직전 지원자의 답변에서 학문적 근거가 부족하거나 고교 기초 교과 원리 설명이 미흡하다면 날카롭게 파고드는 꼬리질문을 하세요.
2. 만약 답변이 충분히 완결되었다면, 이번 세션의 초점({st.session_state.interview_focus})과 연계된 다른 활동으로 주제를 넘기세요.
3. 꼬리질문 1개만 정중하게 출력하세요.
"""
                conversation = [{"role": "system", "content": followup_prompt}]
                for m in st.session_state.messages:
                    conversation.append({"role": m["role"], "content": m["content"]})

                try:
                    res = client.chat.completions.create(
                        model=MODEL_ID,
                        messages=conversation,
                        temperature=0.7
                    )
                    next_q = res.choices[0].message.content
                    st.session_state.messages.append({"role": "assistant", "content": next_q})
                    st.session_state.history_of_all_questions.append(next_q)
                    st.rerun()
                except Exception as e:
                    st.error(f"꼬리질문 생성 실패: {e}")
        else:
            st.session_state.interview_active = False
            st.rerun()

# --- 최종 종합 채점 및 피드백 ---
if not st.session_state.interview_active and st.session_state.turn_count >= st.session_state.max_turns:
    if st.session_state.evaluation_result is None:
        with st.spinner(f"{st.session_state.target_univ} 공식 평가요소에 맞춰 채점표를 작성하고 있습니다..."):
            transcript = "\n".join([f"[{'면접관' if m['role']=='assistant' else '지원자'}]: {m['content']}" for m in st.session_state.messages])
            rubric = st.session_state.current_rubric
            rubric_str = "\n".join([f"- {f['name']} ({f['ratio']}): {f['criteria']}" for f in rubric.get("evaluation_factors", [])])

            eval_prompt = f"""
당신은 {st.session_state.target_univ} 학생부종합전형 수석 평가위원입니다.
지원자의 생기부와 면접 전체 기록을 바탕으로 {st.session_state.target_univ} 공식 채점표를 작성하세요.

[지원 대학/학과]: {st.session_state.target_univ} {st.session_state.target_major}
[대학 공식 평가요소 및 배점 비율]:
{rubric_str}

[생기부 내용]:
{st.session_state.active_record[:6000]}

[면접 기록]:
{transcript}

[작성 요구사항]
1. 위 [대학 공식 평가요소 및 배점 비율]의 항목별 점수 산출 및 세부 평가 이유 작성 (인하대의 경우 '기초학업역량'의 교과 개념 구술 정확도 엄격 심사)
2. 종합 환산 총점 (100점 만점 기준)
3. 💡 우수했던 점 2가지
4. ⚠️ 실전 면접 대비 보완할 점 2가지
5. 📌 모범 답변 피드백 (가장 아쉬웠던 답변 1개를 골라 개선된 예시 답변 제공)
"""
            try:
                eval_res = client.chat.completions.create(
                    model=MODEL_ID,
                    messages=[{"role": "user", "content": eval_prompt}],
                    temperature=0.3
                )
                st.session_state.evaluation_result = eval_res.choices[0].message.content
                st.rerun()
            except Exception as e:
                st.error(f"채점표 생성 실패: {e}")

    st.success(f"🎉 {st.session_state.target_univ} 모의면접이 완료되었습니다! 아래 채점표를 확인하세요.")
    st.markdown(st.session_state.evaluation_result)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 새로운 면접 시작 (이전 질문 제외)", use_container_width=True):
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.evaluation_result = None
            st.session_state.interview_active = False
            st.rerun()
    with col2:
        if st.button("🗑️ 모든 기록 리셋 (초기 상태로)", use_container_width=True):
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.evaluation_result = None
            st.session_state.interview_active = False
            st.session_state.history_of_all_questions = []
            st.rerun()
