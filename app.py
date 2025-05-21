import streamlit as st
import google.generativeai as genai
import re
from typing import Optional, List, Dict
from dataclasses import dataclass
from enum import Enum
import logging
from youtube_transcript_api import YouTubeTranscriptApi

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 상수 정의
class SummaryMode(Enum):
    KEY_POINTS = "핵심 요약"
    TIMELINE = "타임라인 요약"
    KEYWORDS = "키워드 요약"

CHUNK_SIZE = 4000
MAX_RETRIES = 3

@dataclass
class TranscriptEntry:
    start: float
    text: str

class TranscriptFetcher:
    def __init__(self):
        self.available_langs = []
        self.status = st.empty()
        
    def fetch(self, video_id: str) -> Optional[List[TranscriptEntry]]:
        try:
            self.status.info("1. 자막 목록을 확인하는 중...")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            self.available_langs = [t.language_code for t in transcript_list]
            self.status.info(f"2. 사용 가능한 자막: {self.available_langs}")
            
            # 한국어 자막 우선
            if 'ko' in self.available_langs:
                return self._fetch_transcript(transcript_list, 'ko')
            # 영어 자막 fallback
            elif 'en' in self.available_langs:
                return self._fetch_transcript(transcript_list, 'en')
                
            self.status.info("3. 지원하는 언어의 자막을 찾을 수 없습니다.")
            return None
            
        except Exception as e:
            logger.error(f"자막 가져오기 실패: {str(e)}")
            self.status.error(f"오류 발생: {str(e)}")
            return None
            
    def _fetch_transcript(self, transcript_list, lang: str) -> Optional[List[TranscriptEntry]]:
        try:
            self.status.info(f"3. {lang} 자막을 가져오는 중...")
            transcript = transcript_list.find_transcript([lang])
            self.status.empty()  # 자막 가져오기 완료 메시지 제거
            return [TranscriptEntry(start=entry['start'], text=entry['text']) 
                   for entry in transcript.fetch()]
        except Exception as e:
            logger.error(f"{lang} 자막 가져오기 실패: {str(e)}")
            return None

class TranscriptFormatter:
    @staticmethod
    def format_with_timestamps(transcript: List[TranscriptEntry]) -> str:
        return "\n".join(f"[{format_seconds(entry.start)}] {entry.text}" 
                        for entry in transcript)
    
    @staticmethod
    def format_plain(transcript: List[TranscriptEntry]) -> str:
        return " ".join(entry.text for entry in transcript)

class TranscriptChunker:
    @staticmethod
    def chunk_text(text: str, max_length: int = CHUNK_SIZE) -> List[str]:
        chunks = []
        while len(text) > max_length:
            split_index = text.rfind('.', 0, max_length)
            if split_index == -1:
                split_index = max_length
            chunks.append(text[:split_index].strip())
            text = text[split_index:].strip()
        chunks.append(text)
        return chunks

class SummaryGenerator:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-pro")
        self.status = st.empty()
        
    def build_prompt(self, transcript: str, mode: SummaryMode) -> str:
        prompts = {
            SummaryMode.KEY_POINTS: """
다음은 유튜브 영상의 자막입니다. 자막 언어와 무관하게 내용을 **한국어**로 간단히 요약해줘.
중요한 핵심 내용만 **3~5문장**으로 정리해줘.

자막:
{transcript}
""",
            SummaryMode.TIMELINE: """
다음 유튜브 자막을 보고 **시간 흐름 순서에 따라** 내용을 정리해줘.
자막 언어와 상관없이 **한국어**로 정리하고, **타임스탬프 기준으로 구간별 요점**을 알려줘.

형식:
- 00:00~02:30: 내용 요약

자막:
{transcript}
""",
            SummaryMode.KEYWORDS: """
다음 자막에서 중요한 **핵심 키워드** 5~10개를 추출해줘.
각 키워드마다 **간단한 설명**을 붙이고, 자막 언어와 관계없이 반드시 **한국어**로 출력해줘.

형식:
- 키워드: 설명

자막:
{transcript}
"""
        }
        return prompts[mode].format(transcript=transcript)
        
    def generate_summary(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"요약 생성 실패: {str(e)}")
            raise
            
    def summarize_in_chunks(self, transcript: str, mode: SummaryMode) -> str:
        chunks = TranscriptChunker.chunk_text(transcript)
        summaries = []
        
        self.status.info(f"[{mode.value}] 자막을 {len(chunks)}개 구간으로 나누었습니다.")
        
        for i, chunk in enumerate(chunks):
            self.status.info(f"[{mode.value}] 자막을 분석하는 중... ({i+1}/{len(chunks)})")
            prompt = self.build_prompt(chunk, mode)
            summary = self.generate_summary(prompt)
            summaries.append(summary)
            self.status.info(f"[{mode.value}] {i+1}번째 구간 분석 완료!")
            
        self.status.info(f"[{mode.value}] 최종 요약을 생성하는 중...")
        final_prompt = f"다음은 영상 요약 조각들입니다. 이들을 하나의 요약으로 통합해줘.\n\n{'\n'.join(summaries)}"
        final_summary = self.generate_summary(final_prompt)
        self.status.info(f"[{mode.value}] 최종 요약 생성 완료!")
        
        return final_summary

def format_seconds(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02}:{s:02}"

def extract_video_id(url: str) -> Optional[str]:
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def main():
    st.set_page_config(page_title="유튜브 자막 요약기", page_icon="🎥")
    st.title("🎥 유튜브 자막 요약기")
    st.write("유튜브 영상 링크를 입력하고 요약 방식을 선택하면, 자막을 한국어로 요약해드립니다.")

    # Gemini API 키 설정
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

    url: str = st.text_input("유튜브 링크를 입력하세요:")
    selected_modes: List[str] = st.multiselect(
        "원하는 요약 방식을 모두 선택하세요",
        [mode.value for mode in SummaryMode]
    )

    if st.button("요약 시작") and url and selected_modes:
        video_id: Optional[str] = extract_video_id(url)
        if not video_id:
            st.error("유효한 유튜브 링크를 입력해주세요.")
            return

        # 자막 가져오기
        fetcher = TranscriptFetcher()
        transcript_data = fetcher.fetch(video_id)

        if not transcript_data:
            st.error("이 영상은 자막이 없어 요약할 수 없습니다.")
            return

        # 요약 생성
        formatter = TranscriptFormatter()
        generator = SummaryGenerator()
        summaries_output = {}

        for mode_str in selected_modes:
            mode = SummaryMode(mode_str)
            try:
                formatted_transcript = (formatter.format_with_timestamps(transcript_data) 
                                     if mode == SummaryMode.TIMELINE 
                                     else formatter.format_plain(transcript_data))
                
                summary = generator.summarize_in_chunks(formatted_transcript, mode)
                summaries_output[mode] = summary
                
            except Exception as e:
                st.error(f"[{mode.value}] 요약 생성에 실패했습니다. 다시 시도해주세요.")
                logger.exception(e)
                continue

        # 결과 출력
        st.success("요약 완료!")
        for mode, summary in summaries_output.items():
            st.subheader(f"📌 {mode.value}")
            st.write(summary)
            st.download_button(
                f"📄 {mode.value} 다운로드",
                summary,
                file_name=f"{mode.value}.txt"
            )

if __name__ == "__main__":
    main()
