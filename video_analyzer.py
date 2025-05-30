import streamlit as st
from google.cloud import speech
from google.cloud import storage
import google.generativeai as genai
from pytube import YouTube
import os
import tempfile
from typing import Optional, List
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoAnalyzer:
    def __init__(self):
        self.speech_client = speech.SpeechClient()
        self.storage_client = storage.Client()
        self.status = st.empty()
        
    def download_audio(self, video_id: str) -> Optional[str]:
        """YouTube 영상에서 오디오를 다운로드합니다."""
        try:
            self.status.info("1. 영상에서 오디오를 추출하는 중...")
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            audio_stream = yt.streams.filter(only_audio=True).first()
            
            # 임시 파일로 저장
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                audio_path = temp_file.name
                audio_stream.download(filename=audio_path)
                
            self.status.info("2. 오디오 추출 완료!")
            return audio_path
            
        except Exception as e:
            logger.error(f"오디오 다운로드 실패: {str(e)}")
            self.status.error(f"오디오 추출 실패: {str(e)}")
            return None
            
    def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """오디오 파일을 텍스트로 변환합니다."""
        try:
            self.status.info("3. 음성을 텍스트로 변환하는 중...")
            
            # 오디오 파일 읽기
            with open(audio_path, "rb") as audio_file:
                content = audio_file.read()
                
            # 오디오 설정
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="ko-KR",  # 한국어 우선
                enable_automatic_punctuation=True,
            )
            
            # 음성 인식 요청
            operation = self.speech_client.long_running_recognize(
                config=config, audio=audio
            )
            
            self.status.info("4. 음성 인식 중... (잠시만 기다려주세요)")
            response = operation.result(timeout=90)
            
            # 결과 처리
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript + "\n"
                
            self.status.info("5. 음성 인식 완료!")
            return transcript
            
        except Exception as e:
            logger.error(f"음성 인식 실패: {str(e)}")
            self.status.error(f"음성 인식 실패: {str(e)}")
            return None
            
        finally:
            # 임시 파일 삭제
            try:
                os.unlink(audio_path)
            except:
                pass
                
    def analyze_video(self, video_id: str) -> Optional[str]:
        """영상을 분석하여 텍스트로 변환합니다."""
        # 오디오 다운로드
        audio_path = self.download_audio(video_id)
        if not audio_path:
            return None
            
        # 음성 인식
        transcript = self.transcribe_audio(audio_path)
        if not transcript:
            return None
            
        return transcript

def main():
    st.set_page_config(page_title="유튜브 영상 분석기", page_icon="🎥")
    st.title("🎥 유튜브 영상 분석기")
    st.write("자막이 없는 유튜브 영상도 분석할 수 있습니다.")
    
    url = st.text_input("유튜브 링크를 입력하세요:")
    
    if st.button("분석 시작") and url:
        # 비디오 ID 추출
        video_id = None
        if "youtube.com" in url or "youtu.be" in url:
            if "v=" in url:
                video_id = url.split("v=")[1].split("&")[0]
            else:
                video_id = url.split("/")[-1]
                
        if not video_id:
            st.error("유효한 유튜브 링크를 입력해주세요.")
            return
            
        # 영상 분석
        analyzer = VideoAnalyzer()
        transcript = analyzer.analyze_video(video_id)
        
        if transcript:
            st.success("분석 완료!")
            st.subheader("📝 변환된 텍스트")
            st.write(transcript)
            
            # 다운로드 버튼
            st.download_button(
                "📄 텍스트 다운로드",
                transcript,
                file_name="transcript.txt"
            )
        else:
            st.error("영상 분석에 실패했습니다.")

if __name__ == "__main__":
    main() 