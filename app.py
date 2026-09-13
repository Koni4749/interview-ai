import streamlit as st
from openai import OpenAI
import pdfplumber
import io
import json
import os

st.set_page_config(page_title="학생부 모의면접", page_icon="🎓", layout="wide")

# --- Secrets 검증 및 모델 고정 ---
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
    json_path = "universities.json"
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "default": {
            "interview_style": "서류 기반 진위 확인 면접",
            "evaluation_factors": [
                {"name": "학업역량", "ratio": "40%", "criteria": "교과 원리 이해 및 탐구력"},
                {"name": "진로역량", "ratio": "40%", "criteria": "전공 적합성 및 주도성"},
                {"name": "공동체역량", "ratio": "20%", "criteria": "협업 및 소통 능력"}
            ]
        }
    }

UNIV_DATA = load_university_rubrics()
UNIV_CHOICES = [k for k in UNIV_DATA.keys() if k != "default"] + ["직접 입력"]

# --- PDF 텍스트 추출 함수 ---
def extract_text_from_pdf(file_bytes) -> str:
    text_content = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if page_text:
                text_content.append(f"--- [Page {idx}] ---\n{page_text.strip()}")
    return "\n\n".join(text_content)

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

# --- 사이드바 설정 ---
with st.sidebar:
    st.header("⚙️ 모의면접 설정")
    
    selected_univ = st.selectbox("지원 대학 선택", UNIV_CHOICES, index=0)
    
    if selected_univ == "직접 입력":
        target_univ = st.text_input("대학명을 입력하세요", placeholder="예: 한국대학교")
        current_rubric = UNIV_DATA.get("default")
    else:
        target_univ = selected_univ
        current_rubric = UNIV_DATA.get(selected_univ, UNIV_DATA.get("default"))

    target_major = st.text_input("지원 학과", value="컴퓨터공학과")
    
    # 선택된 대학의 평가 기준 실시간 표시
    with st.expander(f"📌 {target_univ} 평가요소 확인"):
        st.markdown(f"**면접 스타일:**\n{current_rubric['interview_style']}")
        st.markdown("**평가 배점:**")
        for factor in current_rubric["evaluation_factors"]:
            st.markdown(f"- **{factor['name']} ({factor['ratio']})**: {factor['criteria']}")

    st.divider()
    st.subheader("📄 생기부 입력")
    input_mode = st.radio("입력 방식", ["PDF 업로드 (나이스 생기부)", "직접 텍스트 붙여넣기"], horizontal=True)

    if input_mode == "PDF 업로드 (나이스 생기부)":
        uploaded_file = st.file_uploader("생기부 PDF 업로드", type=["pdf"])
        if uploaded_file is not None and uploaded_file.name != st.session_state.last_uploaded_file:
            with st.spinner("PDF에서 생기부 텍스트를 파싱하는 중입니다..."):
                file_bytes = uploaded_file.read()
                st.session_state.parsed_record = extract_text_from_pdf(file_bytes)
                st.session_state.last_uploaded_file = uploaded_file.name
            st.success("텍스트 파싱 완료!")

        student_record = st.text_area(
            "추출된 텍스트 확인/수정",
            value=st.session_state.parsed_record,
            height=200,
            placeholder="PDF 텍스트가 표시됩니다. 불필요한 인적사항 등은 지우셔도 됩니다."
        )
    else:
        student_record = st.text_area(
            "세특 및 탐구활동 직접 입력",
            height=200,
            placeholder="[정보] 알고리즘 원리를 탐구하고 직접 구현한 경험..."
        )

    st.divider()
    st.session_state.max_turns = st.slider("면접 질문 횟수 (턴)", min_value=2, max_value=6, value=3)

    if st.button("🚀 모의면접 시작", type="primary", use_container_width=True):
        if not target_univ.strip():
            st.error("지원 대학을 지정해주세요.")
        elif not student_record.strip():
            st.error("생기부 내용을 입력하거나 PDF를 올려주세요.")
        else:
            st.session_state.active_record = student_record
            st.session_state.target_univ = target_univ
            st.session_state.target_major = target_major
            st.session_state.current_rubric = current_rubric
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.interview_active = True
            st.session_state.evaluation_result = None

            # 평가 기준 텍스트화
            rubric_str = "\n".join([f"- {f['name']} ({f['ratio']}): {f['criteria']}" for f in current_rubric["evaluation_factors"]])

            # 첫 번째 질문 생성
            with st.spinner(f"{target_univ} 평가 기준을 바탕으로 첫 질문을 구성 중입니다..."):
                system_prompt = f"""
당신은 {target_univ} {target_major} 학생부종합전형의 전문 입학사정관입니다.

[대학별 면접 기조]
{current_rubric['interview_style']}

[평가 핵심 요소]
{rubric_str}

[지원자 생기부]
{student_record[:6000]}

[질문 지침]
1. 단순 사실 확인이 아닌, 지원 대학의 평가 기조에 맞춰 '탐구 과정의 주도성', '원리 이해도', '어려움 극복 경험'을 확인하는 첫 질문을 던지세요.
2. 예의 바르고 단호한 면접관 어조(~바랍니다, ~습니까?)를 사용하세요.
3. 질문은 반드시 1개만 제시하세요.
"""
                try:
                    res = client.chat.completions.create(
                        model=MODEL_ID,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": "면접을 시작합니다. 첫 번째 질문을 해주세요."}
                        ],
                        temperature=0.7
                    )
                    first_q = res.choices[0].message.content
                    st.session_state.messages.append({"role": "assistant", "content": first_q})
                    st.rerun()
                except Exception as e:
                    st.error(f"질문 생성 실패: {e}")

# --- 메인 화면 인터페이스 ---
st.title("🎓 학생부 모의면접")

if not st.session_state.interview_active and not st.session_state.evaluation_result:
    st.info("👈 왼쪽 사이드바에서 **지원 대학**과 **생기부**를 설정한 후 **[모의면접 시작]**을 눌러주세요.")

# 대화 내용 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# --- 질의응답 진행 루프 ---
if st.session_state.interview_active:
    st.caption(f"진행 상황: 질문 {st.session_state.turn_count + 1} / {st.session_state.max_turns} (목표: {st.session_state.target_univ} {st.session_state.target_major})")

    user_input = st.chat_input("면접 답변을 입력하세요...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.turn_count += 1

        if st.session_state.turn_count < st.session_state.max_turns:
            with st.spinner("답변을 분석하여 꼬리질문을 생성하고 있습니다..."):
                rubric = st.session_state.current_rubric
                followup_prompt = f"""
당신은 {st.session_state.target_univ} {st.session_state.target_major} 입학사정관입니다.
{st.session_state.target_univ}의 면접 기조: {rubric['interview_style']}

[생기부 내용]
{st.session_state.active_record[:6000]}

[질문 지침]
1. 직전 답변에서 논리적 비약이나 모호한 개념이 있다면 날카롭게 파고드는 꼬리질문을 하세요.
2. 답변이 충분했다면 평가 요소(학업, 진로, 공동체) 중 아직 검증되지 않은 다른 영역으로 질문을 전환하세요.
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
            rubric_str = "\n".join([f"- {f['name']} ({f['ratio']}): {f['criteria']}" for f in rubric["evaluation_factors"]])

            eval_prompt = f"""
당신은 {st.session_state.target_univ} 학생부종합전형 수석 평가위원입니다.
제공된 지원자의 생기부와 면접 전체 기록을 바탕으로 {st.session_state.target_univ} 공식 채점표를 작성하세요.

[지원 대학/학과]: {st.session_state.target_univ} {st.session_state.target_major}
[대학 평가요소 및 배점 비율]:
{rubric_str}

[생기부 내용]:
{st.session_state.active_record[:6000]}

[면접 기록]:
{transcript}

[작성 요구사항]
1. 위 [대학 평가요소 및 배점 비율]에 명시된 항목별로 정확히 구분하여 점수 산출(예: 34 / 40점) 및 세부 평가 이유 작성
2. 종합 환산 총점 (100점 만점 기준)
3. 💡 {st.session_state.target_univ} 입학사정관 기준 우수했던 점 2가지
4. ⚠️ 실전 면접 대비 보완할 점 2가지
5. 📌 모범 답변 피드백 (답변 중 가장 아쉬웠던 1개를 골라 수정된 모범 답변 예시 제시)
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

    if st.button("🔄 새로운 면접 시작"):
        st.session_state.messages = []
        st.session_state.turn_count = 0
        st.session_state.evaluation_result = None
        st.session_state.interview_active = False
        st.rerun()
