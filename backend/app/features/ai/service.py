import os

from langchain_groq import ChatGroq
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
)

from app.features.ai.prompts import SYSTEM_PROMPT
from app.features.ai.schema import ChatMessage, GeneratedEmail


llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.4,
)

structured_llm = llm.with_structured_output(GeneratedEmail)


def build_conversation(
    instruction: str,
    history: list[ChatMessage] | None = None,
):
    messages = [
        SystemMessage(content=SYSTEM_PROMPT)
    ]

    for message in history or []:

        if message.role == "user":
            messages.append(
                HumanMessage(content=message.content)
            )

        elif message.role == "assistant":
            messages.append(
                AIMessage(content=message.content)
            )

    # Current user instruction
    messages.append(
        HumanMessage(content=instruction)
    )

    return messages


def generate_email(
    instruction: str,
    history: list[ChatMessage] | None = None,
) -> GeneratedEmail:

    conversation = build_conversation(
        instruction=instruction,
        history=history,
    )

    response = structured_llm.invoke(conversation)

    return response