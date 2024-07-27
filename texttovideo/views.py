import logging
import fal_client
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import TextToVideo
from .serializers import TextToVideoSerializer
from user.models import User
import environ
import langdetect
import requests

# 환경 변수 로드
env = environ.Env()
environ.Env.read_env()

# FAL API 키 설정
fal_api_key = env("FAL_KEY")
openai_api_key = env("OPENAI_API_KEY")

# 로거 설정
logger = logging.getLogger(__name__)


# 텍스트를 비디오로 변환하는 함수
def generate_video(prompt):
    handler = fal_client.submit(
        "fal-ai/fast-svd/text-to-video",
        arguments={
            "prompt": prompt,
            "motion_bucket_id": 127,
            "cond_aug": 0.02,
            "steps": 20,
            "deep_cache": "none",
            "fps": 10,
            "negative_prompt": "unrealistic, saturated, high contrast, big nose, painting, drawing, sketch, cartoon, anime, manga, render, CG, 3d, watermark, signature, label",
            "video_size": "landscape_16_9"
        },
    )
    result = handler.get()
    return result['video']['url']


# GPT-3.5 Turbo를 사용하여 한국어를 영어로 번역하는 함수
def translate_to_english(korean_text):
    headers = {
        'Authorization': f'Bearer {openai_api_key}',  # OpenAI API 키를 헤더에 포함
        'Content-Type': 'application/json'
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Translate the following Korean text to English."},
            {"role": "user", "content": korean_text}
        ],
        "max_tokens": 50  # 최대 토큰 수를 50으로 설정
    }

    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
    response.raise_for_status()
    response_json = response.json()
    english_text = response_json['choices'][0]['message']['content'].strip().strip('\"')
    return english_text


# Swagger를 이용한 API 문서화와 비디오 생성 API
@swagger_auto_schema(
    method='post',
    operation_id='비디오 생성',
    operation_description='프롬프트를 입력받아 비디오를 생성합니다.',
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'prompt': openapi.Schema(type=openapi.TYPE_STRING, description='The prompt for video generation'),
            'user_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='ID of the user creating the video'),
        },
        required=['prompt', 'user_id']
    ),
    responses={
        201: openapi.Response(
            description='비디오 생성 성공',
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'prompt': openapi.Schema(type=openapi.TYPE_STRING),
                    'video_url': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            examples={
                'application/json': {
                    "id": 1,
                    "prompt": "A rocket flying that is about to take off",
                    "video_url": "https://storage.googleapis.com/example.mp4",
                }
            }
        ),
        400: '잘못된 요청',
    }
)
@api_view(['POST'])
def create_video(request):
    serializer = TextToVideoSerializer(data=request.data)
    if serializer.is_valid():
        data = serializer.validated_data

        prompt = data['prompt']
        user_id = data['user_id']

        # 사용자 객체 가져오기
        user = get_object_or_404(User, id=user_id)

        # 프롬프트의 언어를 감지하여 한국어일 경우 번역
        try:
            detected_language = langdetect.detect(prompt)
            if detected_language == 'ko':
                translated_prompt = translate_to_english(prompt)
            else:
                translated_prompt = prompt
        except langdetect.lang_detect_exception.LangDetectException:
            translated_prompt = prompt

        # 비디오 생성
        video_url = generate_video(translated_prompt)

        # TextToVideo 객체 생성 및 저장
        video = TextToVideo.objects.create(
            prompt=prompt,
            video_url=video_url,
            user=user
        )

        response_data = {
            "id": video.id,
            "prompt": video.prompt,
            "video_url": video.video_url,
        }

        return Response(response_data, status=status.HTTP_201_CREATED)

    return Response({"code": 400, "message": "비디오 생성 실패", "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST)


# 특정 TextToVideo 객체 조회, 수정, 삭제 API
@swagger_auto_schema(
    method='get',
    operation_id='비디오 조회',
    operation_description='특정 비디오를 조회합니다.',
    responses={
        200: openapi.Response(
            description='비디오 조회 성공',
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'prompt': openapi.Schema(type=openapi.TYPE_STRING),
                    'video_url': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            examples={
                'application/json': {
                    "id": 1,
                    "prompt": "A rocket flying that is about to take off",
                    "video_url": "https://storage.googleapis.com/example.mp4",
                }
            }
        ),
        404: '비디오를 찾을 수 없음',
    }
)
@swagger_auto_schema(
    method='delete',
    operation_id='비디오 삭제',
    operation_description='특정 비디오를 삭제합니다.',
    responses={
        200: openapi.Response(
            description='비디오 삭제 성공',
            examples={
                'application/json': {
                    "message": "삭제 성공"
                }
            }
        ),
        404: '비디오를 찾을 수 없음',
    }
)
@api_view(['GET', 'DELETE'])
def handle_video(request, videoId):
    video = get_object_or_404(TextToVideo, id=videoId)

    if request.method == 'GET':
        response_data = {
            "id": video.id,
            "prompt": video.prompt,
            "video_url": video.video_url,
        }
        return Response(response_data, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        video.delete()
        return Response({"message": "삭제 성공"}, status=status.HTTP_200_OK)