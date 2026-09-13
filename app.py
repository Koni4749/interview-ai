import streamlit as st
import google.generativeai as genai
import pdfplumber
import io

st.set_page_config(page_title="Gemma 4 학생부 모의면접", page_icon="🎓", layout="wide")

# --- PDF 텍스트 추출 헬퍼 함수 ---
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

# --- 사이드바: 모델 설정 및 생기부 입력 ---
with st.sidebar:
    st.header("⚙️ 면접 환경 설정")
    api_key = st.text_input("Gemma API Key", type="password", help="발급받은 통합 API 키를 입력하세요.")
    model_name = st.text_input("적용 모델명", value="gemma-4", help="API 제공처의 모델 식별자(예: gemma-4, gemma-2-27b-it 등)")
    
    target_univ = st.text_input("지원 대학", value="한국대학교")
    target_major = st.text_input("지원 학과", value="컴퓨터공학과")
    
    st.divider()
    st.subheader("📄 생기부 입력 방식")
    input_mode = st.radio("입력 방식 선택", ["PDF 업로드 (나이스 생기부)", "직접 텍스트 붙여넣기"], horizontal=True)

    if input_mode == "PDF 업로드 (나이스 생기부)":
        uploaded_file = st.file_uploader("생기부 PDF 업로드", type=["pdf"])
        if uploaded_file is not None and uploaded_file.name != st.session_state.last_uploaded_file:
            with st.spinner("PDF에서 생기부 텍스트를 파싱 중입니다..."):
                file_bytes = uploaded_file.read()
                st.session_state.parsed_record = extract_text_from_pdf(file_bytes)
                st.session_state.last_uploaded_file = uploaded_file.name
            st.success("추출 완료!")

        student_record = st.text_area(
            "추출된 텍스트 확인/수정",
            value=st.session_state.parsed_record,
            height=200,
            placeholder="PDF 텍스트가 여기에 표시됩니다. 인적사항 등 불필요한 부분은 삭제할 수 있습니다."
        )
    else:
        student_record = st.text_area(
            "세특 및 활동 직접 입력",
            height=200,
            placeholder="[정보] 객체지향 프로그래밍 원리를 학습하고 알고리즘을 활용한 프로젝트를 진행함..."
        )

    st.divider()
    st.session_state.max_turns = st.slider("면접 질문 횟수 (총 턴 수)", min_value=2, max_value=6, value=3)

    if st.button("🚀 모의면접 시작", type="primary", use_container_width=True):
        if not api_key:
            st.error("API Key를 입력해주세요.")
        elif not student_record.strip():
            st.error("생기부 내용을 입력하거나 PDF를 올려주세요.")
        else:
            try:
                genai.configure(api_key=api_key)
                st.session_state.model = genai.GenerativeModel(model_name)
                st.session_state.active_record = student_record
                st.session_state.messages = []
                st.session_state.turn_count = 0
                st.session_state.interview_active = True
                st.session_state.evaluation_result = None

                # 첫 번째 질문 생성
                with st.spinner(f"Gemma 모델({model_name})이 생기부를 분석 중입니다..."):
                    first_prompt = f"""
당신은 {target_univ} {target_major} 학생부종합전형의 전문 입학사정관입니다.
지원자의 학교생활기록부를 엄격히 검증하는 첫 번째 면접 질문을 던지세요.

[생기부 내용]
{student_record[:6000]}

[질문 지침]
1. 단순 요약이 아닌, 지원자가 직접 수행한 '탐구 방법의 타당성', '어려웠던 점의 극복 과정', '개념 원리 이해도'를 확인하세요.
2. 예의 바르고 단호한 면접관 어조(~바랍니다, ~습니까?)를 유지하세요.
3. 오직 첫 번째 질문 1개만 출력하세요.
"""
                    res = st.session_state.model.generate_content(first_prompt)
                    st.session_state.messages.append({"role": "assistant", "content": res.text})
                st.rerun()
            except Exception as e:
                st.error(f"모델 호출 중 오류 발생: {e}")

# --- 메인 화면 인터페이스 ---
st.title("🎓 Gemma 4 기반 학생부 모의면접")

if not st.session_state.interview_active and not st.session_state.evaluation_result:
    st.info("👈 왼쪽 사이드바에서 **API Key**, **Gemma 모델명**, **생기부**를 입력하고 시작 버튼을 눌러주세요.")

# 대화 내용 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# --- 질의응답 루프 ---
if st.session_state.interview_active:
    st.caption(f"진행 상황: 질문 {st.session_state.turn_count + 1} / {st.session_state.max_turns}")

    user_input = st.chat_input("면접 답변을 입력하세요...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.turn_count += 1

        if st.session_state.turn_count < st.session_state.max_turns:
            with st.spinner("답변을 분석하여 꼬리질문을 구성하고 있습니다..."):
                transcript = "\n".join([f"{'면접관' if m['role']=='assistant' else '지원자'}: {m['content']}" for m in st.session_state.messages])
                
                followup_prompt = f"""
당신은 {target_univ} {target_major} 입학사정관입니다.
지원자의 직전 답변과 생기부를 대조하여 심층 꼬리질문을 1개만 제시하세요.

[생기부 내용]
{st.session_state.active_record[:6000]}

[지금까지의 면접 대화]
{transcript}

[질문 지침]
1. 방금 한 지원자 답변에서 개념적 오류, 논리적 비약, 과장된 부분이 있다면 이를 집중 검증하세요.
2. 직전 질문에 충분히 잘 답했다면 생기부 내 다른 주요 활동으로 화제를 전환하세요.
3. 다른 사족 없이 꼬리질문 1개만 정중하게 출력하세요.
"""
                res = st.session_state.model.generate_content(followup_prompt)
                st.session_state.messages.append({"role": "assistant", "content": res.text})
                st.rerun()
        else:
            st.session_state.interview_active = False
            st.rerun()

# --- 최종 종합 평가 리포트 ---
if not st.session_state.interview_active and st.session_state.turn_count >= st.session_state.max_turns:
    if st.session_state.evaluation_result is None:
        with st.spinner("면접 기록을 바탕으로 입학사정관 채점표를 작성하고 있습니다..."):
            transcript = "\n".join([f"{'면접관' if m['role']=='assistant' else '지원자'}: {m['content']}" for m in st.session_state.messages])
            
            eval_prompt = f"""
당신은 {target_univ} 학생부종합전형 수석 평가위원입니다.
제공된 지원자의 생기부와 면접 전체 기록을 바탕으로 공식 채점표를 작성하세요.

[지원 학과]: {target_major}
[생기부 내용]:
{st.session_state.active_record[:6000]}

[면접 기록]:
{transcript}

[평가 기준]
1. 학업역량 (40점): 전공 교과 원리 이해도 및 탐구 진실성
2. 진로역량 (40점): 전공 탐색의 주도성 및 발전 가능성
3. 공동체역량 (20점): 논리적 소통력 및 면접 태도

[출력 형식]
- 항목별 점수 산출(예: 36 / 40점) 및 세부 평가 이유
- 종합 총점 (100점 만점)
- 💡 우수했던 점 2가지
- ⚠️ 보완할 점 2가지 (실제 면접장 대비 팁)
- 📌 모범 답변 피드백 (아쉬웠던 답변 1개를 선정하여 구체적 수정 예시 제시)
"""
            eval_res = st.session_state.model.generate_content(eval_prompt)
            st.session_state.evaluation_result = eval_res.text
            st.rerun()

    st.success("🎉 모의면접이 완료되었습니다. 아래 채점 결과를 확인하세요.")
    st.markdown(st.session_state.evaluation_result)

    if st.button("🔄 새로운 면접 시작"):
        st.session_state.messages = []
        st.session_state.turn_count = 0
        st.session_state.evaluation_result = None
        st.session_state.interview_active = False
        st.rerun()
