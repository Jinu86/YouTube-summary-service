import streamlit as st
from googleapiclient.discovery import build
import google.generativeai as genai
import re
from typing import Optional
import yt_dlp

# API 키 설정
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

# API 클라이언트 초기화
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
genai.configure(api_key=GOOGLE_API_KEY)

# -----------------------------
# Helper Functions
# -----------------------------

def extract_video_id(url: str) -> Optional[str]:
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def format_seconds(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02}:{s:02}"

def get_best_transcript(video_id: str) -> Optional[list[dict]]:
    try:
        st.write("1. 영상 정보를 가져오는 중...")
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'ko'],
            'skip_download': True,
            'quiet': True,
            'cookiesfrombrowser': ('chrome',),  # Chrome 쿠키 사용
            'cookiefile': 'cookies.txt',  # 쿠키 파일 사용
            'nocheckcertificate': True,  # 인증서 검증 건너뛰기
            'ignoreerrors': True,  # 오류 무시
            'no_warnings': True,  # 경고 메시지 숨기기
            'extract_flat': True,  # 플랫 모드로 추출
            'force_generic_extractor': True  # 일반 추출기 사용
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            st.write("2. 자막 목록을 확인하는 중...")
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if 'subtitles' in info:
                available_langs = list(info['subtitles'].keys())
                st.write(f"3. 사용 가능한 자막: {available_langs}")
                
                # 영어 자막이 있으면 가져오기
                if 'en' in available_langs:
                    st.write("4. 영어 자막을 가져오는 중...")
                    subtitle_url = info['subtitles']['en'][0]['url']
                    response = ydl.urlopen(subtitle_url).read().decode('utf-8')
                    st.write("5. 영어 자막 가져오기 완료!")
                    return parse_srt(response)
                    
                # 한국어 자막이 있으면 가져오기
                if 'ko' in available_langs:
                    st.write("4. 한국어 자막을 가져오는 중...")
                    subtitle_url = info['subtitles']['ko'][0]['url']
                    response = ydl.urlopen(subtitle_url).read().decode('utf-8')
                    st.write("5. 한국어 자막 가져오기 완료!")
                    return parse_srt(response)
                    
            st.write("4. 지원하는 언어의 자막을 찾을 수 없습니다.")
            return None
            
    except Exception as e:
        st.write(f"오류 발생: {str(e)}")
        return None

def parse_srt(srt_content: str) -> list[dict]:
    """SRT 형식의 자막을 파싱하여 리스트로 변환"""
    entries = []
    current_entry = {}
    
    for line in srt_content.split('\n'):
        line = line.strip()
        if not line:
            if current_entry:
                entries.append(current_entry)
                current_entry = {}
            continue
            
        if '-->' in line:
            start_time = line.split('-->')[0].strip()
            current_entry['start'] = srt_time_to_seconds(start_time)
        elif not line.isdigit() and not current_entry.get('text'):
            current_entry['text'] = line
            
    if current_entry:
        entries.append(current_entry)
        
    return entries

def srt_time_to_seconds(srt_time: str) -> float:
    """SRT 시간 형식(HH:MM:SS,mmm)을 초 단위로 변환"""
    hours, minutes, seconds = srt_time.replace(',', '.').split(':')
    return float(hours) * 3600 + float(minutes) * 60 + float(seconds)

def format_transcript_with_timestamps(transcript: list[dict]) -> str:
    formatted = ""
    for entry in transcript:
        start_time = format_seconds(entry['start'])
        formatted += f"[{start_time}] {entry['text']}\n"
    return formatted

def chunk_text(text: str, max_length: int = 4000) -> list[str]:
    chunks = []
    while len(text) > max_length:
        split_index = text.rfind('.', 0, max_length)
        if split_index == -1:
            split_index = max_length
        chunks.append(text[:split_index].strip())
        text = text[split_index:].strip()
    chunks.append(text)
    return chunks

def build_prompt(transcript: str, mode: str) -> str:
    if mode == "핵심 요약":
        return f"""
다음은 유튜브 영상의 자막입니다. 자막 언어와 무관하게 내용을 **한국어**로 간단히 요약해줘.
중요한 핵심 내용만 **3~5문장**으로 정리해줘.

자막:
{transcript}
"""
    elif mode == "타임라인 요약":
        return f"""
다음 유튜브 자막을 보고 **시간 흐름 순서에 따라** 내용을 정리해줘.
자막 언어와 상관없이 **한국어**로 정리하고, **타임스탬프 기준으로 구간별 요점**을 알려줘.

형식:
- 00:00~02:30: 내용 요약

자막:
{transcript}
"""
    elif mode == "키워드 요약":
        return f"""
다음 자막에서 중요한 **핵심 키워드** 5~10개를 추출해줘.
각 키워드마다 **간단한 설명**을 붙이고, 자막 언어와 관계없이 반드시 **한국어**로 출력해줘.

형식:
- 키워드: 설명

자막:
{transcript}
"""
    else:
        return transcript

def summarize_with_gemini(prompt: str) -> str:
    model = genai.GenerativeModel("gemini-1.5-pro")
    response = model.generate_content(prompt)
    return response.text

def summarize_in_chunks(transcript: str, mode: str, status_container) -> str:
    chunks = chunk_text(transcript)
    summaries = []
    
    status_container.info(f"[{mode}] 자막을 {len(chunks)}개 구간으로 나누었습니다.")
    
    for i, chunk in enumerate(chunks):
        status_container.info(f"[{mode}] 자막을 분석하는 중... ({i+1}/{len(chunks)})")
        prompt = build_prompt(chunk, mode)
        summary = summarize_with_gemini(prompt)
        summaries.append(summary)
        status_container.info(f"[{mode}] {i+1}번째 구간 분석 완료!")
        
    status_container.info(f"[{mode}] 최종 요약을 생성하는 중...")
    final_prompt = f"다음은 영상 요약 조각들입니다. 이들을 하나의 요약으로 통합해줘.\n\n{'\n'.join(summaries)}"
    final_summary = summarize_with_gemini(final_prompt)
    status_container.info(f"[{mode}] 최종 요약 생성 완료!")
    
    return final_summary

# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="유튜브 자막 요약기", page_icon="🎥")
st.title("🎥 유튜브 자막 요약기")
st.write("유튜브 영상 링크를 입력하고 요약 방식을 선택하면, 자막을 한국어로 요약해드립니다.")

url: str = st.text_input("유튜브 링크를 입력하세요:")
selected_modes: list[str] = st.multiselect(
    "원하는 요약 방식을 모두 선택하세요",
    ["핵심 요약", "타임라인 요약", "키워드 요약"]
)

if st.button("요약 시작") and url and selected_modes:
    status = st.empty()
    status.info("자막을 가져오는 중...")

    video_id: Optional[str] = extract_video_id(url)
    if not video_id:
        status.empty()
        st.error("유효한 유튜브 링크를 입력해주세요.")
    else:
        transcript_data: Optional[list[dict]] = get_best_transcript(video_id)

        if not transcript_data:
            status.empty()
            st.error("이 영상은 자막이 없어 요약할 수 없습니다.")
        else:
            summaries_output = {}
            for mode in selected_modes:
                formatted_transcript: str = format_transcript_with_timestamps(transcript_data) if mode == "타임라인 요약" else " ".join([entry['text'] for entry in transcript_data])
                try:
                    summary: str = summarize_in_chunks(formatted_transcript, mode, status)
                    summaries_output[mode] = summary
                except Exception as e:
                    status.empty()
                    st.error(f"[{mode}] 요약 생성에 실패했습니다. 다시 시도해주세요.")
                    st.exception(e)

            status.empty()
            st.success("요약 완료!")
            for mode, summary in summaries_output.items():
                st.subheader(f"📌 {mode}")
                st.write(summary)
                st.download_button(f"📄 {mode} 다운로드", summary, file_name=f"{mode}.txt")
