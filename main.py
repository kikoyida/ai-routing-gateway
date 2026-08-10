from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware # 【新增】引入跨域通行证模块
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

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

# ================= FastAPI 路由区 =================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserInput(BaseModel):
    prompt: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/gateway")
def gateway_api(data: UserInput, db: Session = Depends(get_db)):
    user_message = data.prompt
    lower_message = user_message.lower() 
    
    # 1. 路由判断规则
    hard_keywords = ["代码", "c++", "算法", "bug", "优化", "时间复杂度"]
    is_hard_task = any(keyword in lower_message for keyword in hard_keywords)
    
    # 2. 模拟网关调度与 Mock 返回值
    if is_hard_task or len(user_message) > 50:
        target_model = "deepseek-coder"
        estimated_cost = "0.015"
        # 【Mock 数据】伪造高级模型的硬核回复
        ai_reply_text = f"【系统拦截】正在本地 Mock 运行。检测到硬核逻辑，若连接真实 API，{target_model} 将为您输出完整代码。"
    else:
        target_model = "deepseek-chat" 
        estimated_cost = "0.001"
        # 【Mock 数据】伪造基础模型的闲聊回复
        ai_reply_text = f"【系统拦截】正在本地 Mock 运行。这是简单的闲聊，{target_model} 认为您刚才说的话很有趣。"
        
    # 3. 将数据存入本地数据库
    new_log = ApiLog(
        original_prompt=user_message,
        selected_model=target_model,
        cost=estimated_cost,
        ai_response=ai_reply_text 
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    
    # 4. 返回最终结果
    return {
        "status": "Success",
        "selected_model": target_model,
        "ai_reply": ai_reply_text 
    }

@app.get("/api/logs")
def get_all_logs(db: Session = Depends(get_db)):
    logs = db.query(ApiLog).all()
    return {"total_records": len(logs), "history": logs}