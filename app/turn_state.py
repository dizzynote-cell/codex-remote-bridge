TERMINAL = {'completed','failed','interrupted','cancelled'}

def status(turn):
    value=turn.get('status')
    return value.get('type') if isinstance(value,dict) else value

def successor(thread, target):
    turns=thread.get('turns') or []
    index=next((i for i,t in enumerate(turns) if t.get('id')==target.get('id')),len(turns))
    return turns[-1] if status(target) in {'interrupted','cancelled'} and index<len(turns)-1 else None

def message(turn):
    state=status(turn)
    final=any(i.get('type')=='agentMessage' and i.get('phase') in {'final_answer','final'} for i in turn.get('items',[]))
    return {'completed':'任务已完成','failed':'任务执行失败','cancelled':'任务已取消',
            'interrupted':'本轮已中断 · 已有回复，请确认结果是否完整' if final else '本轮已中断，未生成最终答案'}.get(state,'Codex 正在处理')
