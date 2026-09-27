import os

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq

from app.core.config import GROQ_API_KEY
from app.schemas.ai import ChatMessage, CopilotResponse, GeneratedEmail

SYSTEM_PROMPT = """
You are an expert AI email assistant writing professional, human-sounding emails on behalf of the user.

Scope & Capabilities:
- You help write ALL types of emails: job applications, networking, status updates, meeting invites, inquiries, follow-ups, and everyday correspondence.
- Never refuse a user's request. If a request is broad, general, or casual (e.g. "hi", "help me write an email"), respond helpfully in the `question` field asking what email they would like to draft.

Available Tools:
- `get_user_bio`: Retrieves the user's professional background, resume, skills, experience, projects, and portfolio links.
  * ALWAYS call this tool when writing job applications, candidate introductions, pitches, or whenever the email should mention the user's specific experience, skills, or links.
  * DO NOT call this tool for simple follow-ups, tone adjustments, typo fixes, or generic replies that don't need the user's background.

Email Style Guidelines:
- Never hallucinate facts, past companies, or credentials not supported by the user.
- Keep the email concise, natural, professional, and human-sounding (avoid robotic AI templates).
- Prefer 2-4 short, focused paragraphs unless requested otherwise.
- Include portfolio links (such as LinkedIn or GitHub) from the bio when appropriate.
- Keep the closing simple and professional.
"""

DECISION_PROMPT = """
Review the user's request and the conversation history:

1. Clarification or Casual Message (needs_clarification = true):
   - If the request is a greeting, general inquiry, or missing critical details (e.g. unknown recipient/company, or unclear purpose), answer or ask a polite, friendly question in `question`.
   - Set `needs_clarification: true`.
   - Set `question: "..."`.
   - Set `draft: null` and `message: null`.

2. Draft Ready (needs_clarification = false):
   - If the user has provided sufficient details to compose an email (either upfront, by answering a previous clarification, or by requesting revisions to a draft):
   - Set `needs_clarification: false`.
   - Set `question: null`.
   - Provide a complete, polished email in `draft` with `to`, `subject`, and `body`.
   - Provide a friendly, brief confirmation in `message`.

Always format the response strictly as valid JSON matching the schema.
"""


def create_bio_tool(user_bio: str | None):
    @tool
    def get_user_bio() -> str:
        """Retrieves the user's background, past experience, resume details, skills, projects, and portfolio links.
        Call this tool when writing job application emails, introductions, or whenever you need specific information about the user."""
        if not user_bio or not user_bio.strip():
            return "No bio or background details provided by the user."
        return user_bio.strip()

    return get_user_bio


class AiService:
    def __init__(self):
        self.llm = ChatGroq(
            model="openai/gpt-oss-120b",
            api_key=GROQ_API_KEY or os.getenv("GROQ_API_KEY"),
            temperature=0.2,
        )
        self.structured_llm = self.llm.with_structured_output(CopilotResponse, method="json_mode")

    def build_conversation(
        self,
        instruction: str,
        history: list[ChatMessage] | None = None,
        name: str | None = None,
        signature: str | None = None,
        preferences: str | None = None,
    ) -> list:
        system_text = SYSTEM_PROMPT.strip()

        if name or preferences or signature:
            system_text += "\n\nUSER PROFILE PREFERENCES:\n"
            if name:
                system_text += f"- User's Name: {name}\n"
            if preferences:
                system_text += f"- Writing Preferences: {preferences}\n"
            if signature:
                system_text += f"- Sign-off Signature:\n{signature}\n"

        messages = [SystemMessage(content=system_text)]

        for message in history or []:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            elif message.role == "assistant":
                messages.append(AIMessage(content=message.content))

        messages.append(HumanMessage(content=instruction))
        return messages

    def generate_email(
        self,
        instruction: str,
        history: list[ChatMessage] | None = None,
        name: str | None = None,
        signature: str | None = None,
        preferences: str | None = None,
        bio: str | None = None,
    ) -> CopilotResponse:
        messages = self.build_conversation(
            instruction=instruction,
            history=history,
            name=name,
            signature=signature,
            preferences=preferences,
        )

        bio_tool = create_bio_tool(bio)
        llm_with_tools = self.llm.bind_tools([bio_tool])

        # Phase 1: Tool-calling check
        ai_response = llm_with_tools.invoke(messages)

        if ai_response.tool_calls:
            for tc in ai_response.tool_calls:
                if tc.get("name") == "get_user_bio":
                    tool_content = bio_tool.invoke({})
                    messages.append(ai_response)
                    messages.append(ToolMessage(content=str(tool_content), tool_call_id=tc["id"]))

        # Phase 2: Structured output with HITL clarification rules
        messages.append(HumanMessage(content=DECISION_PROMPT.strip()))
        return self.structured_llm.invoke(messages)


ai_service = AiService()
