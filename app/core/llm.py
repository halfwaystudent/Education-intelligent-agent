from app.core.config import get_settings


def get_chat_llm():
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError:
        return None
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.2,
    )
