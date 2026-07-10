"""智能助手路由 - KAG 式知识图谱推理问答 + 会话管理"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Project, AssistantSession, AssistantMessage
from app.utils.security import get_current_user
from app.services.assistant_engine import chat_with_graph

router = APIRouter()


# ==================== 会话管理 ====================

class SessionCreate(BaseModel):
    title: Optional[str] = "新会话"


class SessionUpdate(BaseModel):
    title: str


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0

    class Config:
        from_attributes = True


@router.get("/{project_id}/sessions", response_model=List[SessionOut])
async def list_sessions(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户在指定项目下的所有会话"""
    sessions = db.query(AssistantSession).filter(
        AssistantSession.project_id == project_id,
        AssistantSession.user_id == current_user.id,
    ).order_by(AssistantSession.updated_at.desc()).all()
    
    result = []
    for s in sessions:
        result.append(SessionOut(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at.isoformat() + "Z" if s.created_at else "",
            updated_at=s.updated_at.isoformat() + "Z" if s.updated_at else "",
            message_count=len(s.messages),
        ))
    return result


@router.post("/{project_id}/sessions", response_model=SessionOut)
async def create_session(
    project_id: UUID,
    req: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新建会话"""
    session = AssistantSession(
        project_id=project_id,
        user_id=current_user.id,
        title=req.title or "新会话",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionOut(
        id=str(session.id),
        title=session.title,
        created_at=session.created_at.isoformat() + "Z" if session.created_at else "",
        updated_at=session.updated_at.isoformat() + "Z" if session.updated_at else "",
        message_count=0,
    )


@router.put("/{project_id}/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    project_id: UUID,
    session_id: UUID,
    req: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重命名会话"""
    session = db.query(AssistantSession).filter(
        AssistantSession.id == session_id,
        AssistantSession.project_id == project_id,
        AssistantSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.title = req.title
    db.commit()
    db.refresh(session)
    return SessionOut(
        id=str(session.id),
        title=session.title,
        created_at=session.created_at.isoformat() + "Z" if session.created_at else "",
        updated_at=session.updated_at.isoformat() + "Z" if session.updated_at else "",
        message_count=len(session.messages),
    )


@router.delete("/{project_id}/sessions/{session_id}")
async def delete_session(
    project_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话（级联删除消息）"""
    session = db.query(AssistantSession).filter(
        AssistantSession.id == session_id,
        AssistantSession.project_id == project_id,
        AssistantSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"message": "会话已删除"}


# ==================== 消息管理 ====================

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    reasoning_path: Optional[dict] = None
    subgraph_stats: Optional[dict] = None
    sources: Optional[list] = None
    created_at: str

    class Config:
        from_attributes = True


@router.get("/{project_id}/sessions/{session_id}/messages", response_model=List[MessageOut])
async def list_messages(
    project_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话的所有消息"""
    session = db.query(AssistantSession).filter(
        AssistantSession.id == session_id,
        AssistantSession.project_id == project_id,
        AssistantSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return [MessageOut(
        id=str(m.id),
        role=m.role,
        content=m.content,
        reasoning_path=m.reasoning_path,
        subgraph_stats=m.subgraph_stats,
        sources=m.sources,
        created_at=m.created_at.isoformat() + "Z" if m.created_at else "",
    ) for m in session.messages]


# ==================== 问答 ====================

class ChatRequest(BaseModel):
    question: str
    project_ids: Optional[List[str]] = None
    session_id: Optional[str] = None  # 关联会话


class ChatResponse(BaseModel):
    answer: str
    reasoning_path: dict
    subgraph_stats: dict
    sources: list
    message_id: Optional[str] = None


@router.post("/{project_id}/chat", response_model=ChatResponse)
async def chat(
    project_id: UUID,
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """智能助手问答接口 - 支持会话历史"""
    target_ids = req.project_ids or [str(project_id)]
    
    for pid in target_ids:
        proj = db.query(Project).filter(Project.id == pid).first()
        if not proj:
            raise HTTPException(status_code=404, detail=f"项目 {pid} 不存在")
    
    # 获取或创建会话
    session = None
    if req.session_id:
        session = db.query(AssistantSession).filter(
            AssistantSession.id == req.session_id,
            AssistantSession.project_id == project_id,
            AssistantSession.user_id == current_user.id,
        ).first()
    
    # 收集对话历史
    conversation_history = []
    if session:
        for m in session.messages[-12:]:  # 最近12条
            conversation_history.append({"role": m.role, "content": m.content})
    
    # 保存用户消息
    if session:
        user_msg = AssistantMessage(
            session_id=session.id,
            role="user",
            content=req.question,
        )
        db.add(user_msg)
        db.commit()
        # 如果是第一条消息，自动更新标题
        if len(session.messages) == 1:
            session.title = req.question[:50] + ("..." if len(req.question) > 50 else "")
            db.commit()
    
    # 调用推理引擎
    result = chat_with_graph(
        db=db,
        project_ids=target_ids,
        question=req.question,
        conversation_history=conversation_history,
    )
    
    # 保存助手回复
    assistant_msg_id = None
    if session:
        assistant_msg = AssistantMessage(
            session_id=session.id,
            role="assistant",
            content=result["answer"],
            reasoning_path=result["reasoning_path"],
            subgraph_stats=result["subgraph_stats"],
            sources=result["sources"],
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)
        assistant_msg_id = str(assistant_msg.id)
    
    result["message_id"] = assistant_msg_id
    return result


@router.get("/{project_id}/suggested-questions")
async def suggested_questions(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """返回推荐的示例问题"""
    from app.models import TripleRaw, TripleFused, EntityFused
    
    raw = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "FUSED"]),
    ).limit(50).all()
    fused = db.query(TripleFused).filter(TripleFused.project_id == project_id).limit(20).all()
    
    entities = set()
    predicates = set()
    for t in raw:
        entities.add(t.subject)
        entities.add(t.object)
        predicates.add(t.predicate)
    for t in fused:
        predicates.add(t.predicate)
    
    entity_list = list(entities)[:5]
    
    questions = []
    if entity_list:
        for e in entity_list[:3]:
            questions.append(f"{e}有哪些相关关系？")
            questions.append(f"介绍一下{e}")
    if len(predicates) >= 1:
        pred_list = list(predicates)[:2]
        for p in pred_list:
            questions.append(f"哪些实体之间存在「{p}」关系？")
    if len(entity_list) >= 2:
        questions.append(f"{entity_list[0]}和{entity_list[1]}之间有什么关系？")
    
    questions.append("图谱中总共有哪些实体？")
    questions.append("总结一下这个知识图谱的主要内容")
    
    return {"questions": questions[:8]}
