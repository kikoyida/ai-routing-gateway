from fastapi import FastAPI
from fastapi.responses import StreamingResponse # 【新增】流式响应组件
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
from openai import OpenAI  # 【新增】OpenAI 官方工具包
import os
from dotenv import load_dotenv

load_dotenv()

# ================= 数据库配置区 =================
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

# ================= AI 客户端配置 =================
API_KEY = os.getenv("API_KEY", "") 
client = OpenAI(api_key=API_KEY, base_url="https://api.chatanywhere.tech/v1")

# ================= FastAPI 路由区 =================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Target-Model"] # 允许前端读取我们自定义的请求头
)

class UserInput(BaseModel):
    prompt: str

@app.post("/api/gateway")
def gateway_api(data: UserInput):
    user_message = data.prompt
    lower_message = user_message.lower() 
    
    # 1. 动态路由判断规则
    # 扩充特征词库，精准捕获高难度算法与平台特征
    hard_keywords = [
        "c++", "算法", "优化", "时间复杂度", "空间复杂度", 
        "codeforces", "luogu", "nowcoder", "dp", "贪心", 
        "图论", "线段树", "树状数组", "二分"
    ]
    is_hard_task = any(keyword in lower_message for keyword in hard_keywords)
    
    if is_hard_task or len(user_message) > 50:
        target_model = "gpt-4o-mini" # 路由至高算力模型
        estimated_cost = "0.015"
        
        # 注入System Prompt，要求输出高质量的代码
        system_prompt = (
            "你是一个拥有丰富经验的 ACM 竞赛金牌教练。请完全使用 C++ 编写代码，"
            "给出时间复杂度与空间复杂度最优的题解。代码风格需极客、严谨，"
            "并且必须在注释中说明核心状态转移方程或算法思想，严格注意数组越界与边界条件的判断。"
        )
    else:
        target_model = "gpt-3.5-turbo" # 路由至低成本模型
        estimated_cost = "0.001"
        system_prompt = "你是一个效率极高的全栈工程师助手，请用简短、干练的语气回答用户的日常问题，字数尽量控制在 50 字以内。"

    # 2. 核心：构建流式生成器
    def generate_stream():
        full_reply = ""
        try:
            # 开启 stream=True，让 AI 像打字机一样一段一段返回
            response = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                stream=True 
            )
            for chunk in response:
                # 【修复】加一层数组长度判空，防止读取最后一个结束包时越界
                if len(chunk.choices) > 0 and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_reply += text
                    yield text
        except Exception as e:
            error_msg = f"API调用失败: {str(e)}"
            full_reply += error_msg
            yield error_msg
            
        # 3. 流式输出全部结束后，再把拼接好的完整句子偷偷存入数据库
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

    # 将数据流返回给前端，并在请求头上带上我们命中路由的模型名字
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