import os
import json
import logging
from openai import AsyncOpenAI

def get_openrouter_client():
    """Инициализирует клиент OpenRouter с принудительной передачей заголовков."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    
    if not api_key:
        logging.error("❌ КРИТИЧЕСКАЯ ОШИБКА: OPENROUTER_API_KEY равен None! Проверь файл .env!")
        return None
        
    masked_key = api_key[:10] + "..." + api_key[-5:] if len(api_key) > 15 else "слишком короткий"
    logging.info(f"Инициализация OpenRouter с ключом: {masked_key}")
    
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/holding-bot",
            "X-Title": "Holding Bot Helper"
        }
    )

def get_groq_client():
    """Инициализирует клиент Groq."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logging.error("❌ КРИТИЧЕСКАЯ ОШИБКА: GROQ_API_KEY равен None! Проверь файл .env!")
        return None
    return AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key
    )

async def transcribe_voice(file_path: str) -> str:
    """
    Распознает аудиофайл через Groq Whisper API (whisper-large-v3-turbo).
    """
    try:
        logging.info(f"Отправка файла {file_path} на Groq Whisper...")
        client = get_groq_client()
        if not client:
            return ""
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="ru"
            )
        return transcript.text
    except Exception as e:
        logging.error(f"Ошибка при распознавании голоса через Groq: {e}")
        return ""

async def analyze_user_intent(text: str, allowed_companies: list) -> dict:
    """
    Анализирует текст пользователя через OpenRouter.
    """
    companies_str = ", ".join(allowed_companies)
    
    system_prompt = f"""
Ты — умный ИИ-ассистент в Telegram-боте для управления папками на Google Дисках.
Твоя задача — проанализировать запрос пользователя и понять его намерение.

Пользователю доступны следующие компании: {companies_str}.

Ты должен извлечь:
1. Имя папки, которую он хочет создать (очисти его от мусорных слов вроде "создай", "папку", "плиз" и т.д.).
   Если пользователь указал только ID сделки AmoCRM (число), верни folder_name: null — название будет получено из CRM отдельно.
   Если название проекта содержит бренд или сленг (например "ПИК ИИ ролики"), выдели его целиком ("ПИК ИИ ролики").
2. Компанию, для которой нужно создать эту папку.

Правила определения компании:
- Если пользователь упоминает "культ", "cult", "кюльт", "культа" и тд -> компания "cult".
- Если пользователь упоминает "бластер", "blaster" -> компания "blaster".
- Если из контекста фразы компания абсолютно неясна (например, просто "Создай папку Проект Х"), верни "unknown".

Ответь СТРОГО в формате JSON без каких-либо Markdown-разметки (без ```json), только сырой JSON:
{{
    "company": "cult" или "blaster" или "unknown",
    "folder_name": "Имя Папки" или null (если имя папки не указано)
}}
"""

    try:
        client = get_openrouter_client()
        if not client:
            return {"company": "unknown", "folder_name": None}
            
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.0
        )
        
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
            
        return json.loads(result_text)
    except Exception as e:
        logging.error(f"Ошибка OpenRouter: {e}")
        return {"company": "unknown", "folder_name": None}