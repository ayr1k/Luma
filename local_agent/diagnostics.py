"""Explicit synthetic probes. Never execute model-returned tools or use user history."""
import json
from .model import LANModel
from .model_profiles import safe_failure

def run_probe(settings, options, probe):
    model=LANModel(settings,options)
    try:
        if probe=='models':
            passed=settings.model in model.list_models()
            return {'passed':passed,'code':'ok' if passed else 'not_visible','detail':'连接、认证、模型列表读取成功，当前模型可见。' if passed else '列表读取成功，但当前模型不可见。'}
        with model._client() as client:
            kwargs=dict(model=settings.model,messages=[{'role':'user','content':'Reply with OK.'}],
                        temperature=options.temperature,top_p=options.top_p,max_tokens=options.max_tokens)
            if options.reasoning_effort!='default':kwargs['reasoning_effort']=options.reasoning_effort
            if probe=='streaming':
                with client.chat.completions.create(**kwargs,stream=True) as stream:
                    received=False;finish=None
                    for chunk in stream:
                        if chunk.choices:
                            c=chunk.choices[0];received=received or bool(c.delta.content);finish=c.finish_reason or finish
                passed=received and finish=='stop'
            elif probe=='tools':
                kwargs['messages']=[{'role':'user','content':'Call luma_probe with value OK. This is a diagnostic, no real action will run.'}]
                kwargs['tools']=[{'type':'function','function':{'name':'luma_probe','description':'Harmless diagnostic signal; never executed.','parameters':{'type':'object','properties':{'value':{'type':'string','enum':['OK']}},'required':['value'],'additionalProperties':False}}}]
                kwargs['tool_choice']={'type':'function','function':{'name':'luma_probe'}}
                response=client.chat.completions.create(**kwargs);choice=response.choices[0]
                calls=choice.message.tool_calls or []
                passed=choice.finish_reason=='tool_calls' and len(calls)==1 and calls[0].function.name=='luma_probe' and json.loads(calls[0].function.arguments)=={'value':'OK'}
            else:
                if probe=='reasoning' and options.reasoning_effort=='default':
                    return {'passed':False,'code':'not_configured','detail':'先为当前模型选择非默认思考强度，再测试参数是否被路由接受。'}
                response=client.chat.completions.create(**kwargs);choice=response.choices[0]
                passed=choice.finish_reason=='stop' and bool(choice.message.content)
        detail=('思考参数被接受；这不证明内部推理强度或思考内容会返回。' if probe=='reasoning' else
                '返回有效工具调用；未执行任何工具。' if probe=='tools' else '固定诊断请求通过。') if passed else '未收到符合探针要求的完整结果；检查输出上限、路由和模型能力。'
        return {'passed':passed,'code':'ok' if passed else 'unexpected_response','detail':detail}
    except Exception as exc:
        code,detail=safe_failure(exc)
        return {'passed':False,'code':code,'detail':detail}
