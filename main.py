from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

# Database Configuration
SQLALCHEMY_DATABASE_URL = "sqlite:///./gateway_logs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ApiLog(Base):
    __tablename__ = "api_logs"
    id = Column(Integer, primary_key=True, index=True)
    original_prompt = Column(String, index=True)
    selected_model = Column(String)
    cost = Column(String)
    ai_response = Column(String) 

Base.metadata.create_all(bind=engine)

# OpenAI Client Configuration
API_KEY = os.getenv("API_KEY", "") 
client = OpenAI(api_key=API_KEY, base_url="https://api.chatanywhere.tech/v1")

# FastAPI Initialization
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Target-Model"]
)

class UserInput(BaseModel):
    prompt: str

@app.post("/api/gateway")
def gateway_api(data: UserInput):
    user_message = data.prompt
    lower_message = user_message.lower() 
    
    # 1. Routing Rules (支持中英双语特征词)
    coding_keywords = [
        "c++", "算法", "优化", "复杂度", "codeforces", "luogu", "nowcoder", "dp", "贪心", "图论", "线段树", "树状数组", "二分", "bug", "报错",
        "algorithm", "optimize", "complexity", "error", "debug", "segment tree"
    ]
    generation_keywords = [
        "翻译", "总结", "润色", "文章", "邮件", "扩写", "大纲", "提取",
        "translate", "summarize", "rewrite", "article", "email", "outline", "generate"
    ]
    knowledge_keywords = [
        "什么是", "历史", "原理", "概念", "解释", "区别", "怎么理解", "为什么",
        "what is", "history", "principle", "concept", "explain", "difference", "why", "how to"
    ]

    lang_instruction = " IMPORTANT: You must reply in the exact same language as the user's prompt."

    # Dispatch Logic
    if any(k in lower_message for k in coding_keywords):
        target_model = "gpt-4o-mini"
        estimated_cost = "0.015"
        system_prompt = (
            "你是一个拥有丰富经验的 ACM 竞赛金牌教练。请完全使用 C++ 编写代码，"
            "给出时间复杂度与空间复杂度最优的题解。严格注意数组越界与边界条件的判断。" 
            + lang_instruction
        )
        
    elif any(k in lower_message for k in generation_keywords):
        target_model = "gpt-4o-mini"
        estimated_cost = "0.015"
        system_prompt = "你是一个优秀的排版与创作助手。请输出格式清晰、语言流畅的文本。" + lang_instruction
        
    elif any(k in lower_message for k in knowledge_keywords) or len(user_message) > 40:
        target_model = "gpt-4o-mini"
        estimated_cost = "0.015"
        system_prompt = "你是一个知识渊博的百科助手。请客观、准确、简明扼要地解答用户的疑问。" + lang_instruction
        
    else:
        target_model = "gpt-3.5-turbo"
        estimated_cost = "0.001"
        system_prompt = "你是一个友好的 AI 助手，请用简短、轻松的语气回应用户。" + lang_instruction

    # 2. Streaming Generator
    def generate_stream():
        full_reply = ""
        try:
            response = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                stream=True 
            )
            for chunk in response:
                # 判空防止越界
                if len(chunk.choices) > 0 and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_reply += text
                    yield text
        except Exception as e:
            error_msg = f"API调用失败: {str(e)}"
            full_reply += error_msg
            yield error_msg
            
        # 3. Persist Log
        db = SessionLocal()
        new_log = ApiLog(
            original_prompt=user_message,
            selected_model=target_model,
            cost=estimated_cost,
            ai_response=full_reply 
        )
        db.add(new_log)
        db.commit()
        db.close()

    return StreamingResponse(
        generate_stream(), 
        media_type="text/plain", 
        headers={"X-Target-Model": target_model}
    )

@app.get("/api/logs")
def get_all_logs():
    db = SessionLocal()
    logs = db.query(ApiLog).all()
    db.close()
    return {"total_records": len(logs), "history": logs}