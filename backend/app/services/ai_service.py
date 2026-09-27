import os

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.core.config import GROQ_API_KEY
from app.schemas.ai import ChatMessage, GeneratedEmail

SYSTEM_PROMPT = """
Write short, natural, human-sounding job application emails on behalf of the user.

User Details:

Name:
Harsha Vardhan Reddy Vanteru

Location:
Hyderabad, Telangana, India

Internship Experience:
Software Trainee at Ahex Technologies
February 2026 - July 2026

Worked with:
Python, FastAPI, LLMs, LangChain, RAG, AI applications,
REST APIs, MongoDB, LangSmith, SQL.

Skills:
Python, SQL, FastAPI, REST APIs, Generative AI, LLMs,
Prompt Engineering, AI Agents, RAG, LangChain, LangGraph,
Embeddings, Vector Databases, Machine Learning, NumPy,
Pandas, MySQL, Git, GitHub, Postman, VS Code

Contact:
Phone: +91 9502633801
Email: vanteruharshareddy@gmail.com
LinkedIn: https://www.linkedin.com/in/harshavanteru/
GitHub: https://github.com/HarshaVardhanReddy1

Email style:
- dont halucinate.
- Keep the email short, simple, natural, and professional.
- Make it sound like a real person, not an AI-generated cover letter.
- The main purpose is usually to introduce the candidate and send the resume.
- Do not include every skill or personal detail in every email.
- Mention only information that is relevant to the job or necessary for the
  application.
- When no detailed job description is provided, keep the email general and
  briefly mention relevant experience such as Python, FastAPI, AI, LLMs, or RAG.
- When a job description is provided, naturally mention the skills and
  experience that match it.
- If the job description specifically asks for certain experience or details,
  include those details when they are supported by the user's information.
- Never invent, exaggerate, or claim experience the user does not have.
- Do not copy the job description or make the email sound like a resume.
- Prefer 2-4 short paragraphs.
- Include LinkedIn and GitHub when appropriate.
- Keep the closing simple.
"""

class AiService:
    def __init__(self):
        self.llm = ChatGroq(
            model="openai/gpt-oss-120b",
            api_key=GROQ_API_KEY or os.getenv("GROQ_API_KEY"),
            temperature=0.3,
        )
        self.structured_llm = self.llm.with_structured_output(GeneratedEmail, method="json_mode")

    def build_conversation(self, instruction: str, history: list[ChatMessage] | None = None, name: str | None = None, signature: str | None = None, preferences: str | None = None):
        json_instruction = (
            SYSTEM_PROMPT
            + "\n\nCRITICAL INSTRUCTION: You must respond in valid JSON format matching this schema: "
            + '{"to": "recipient email string", "subject": "email subject string", "body": "email body string"}.'
        )
        
        if name or preferences or signature:
            json_instruction += "\n\nUSER PROFILE INFORMATION:\n"
            if name:
                json_instruction += f"User's name: {name}\n"
            if preferences:
                json_instruction += f"User's writing preferences: {preferences}\n"
            if signature:
                json_instruction += f"Include this signature at the end if generating a full email: {signature}\n"

        messages = [SystemMessage(content=json_instruction)]

        for message in history or []:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            elif message.role == "assistant":
                messages.append(AIMessage(content=message.content))

        messages.append(HumanMessage(content=instruction))
        return messages

    def generate_email(self, instruction: str, history: list[ChatMessage] | None = None, name: str | None = None, signature: str | None = None, preferences: str | None = None) -> GeneratedEmail:
        conversation = self.build_conversation(
            instruction=instruction,
            history=history,
            name=name,
            signature=signature,
            preferences=preferences,
        )
        return self.structured_llm.invoke(conversation)

ai_service = AiService()
