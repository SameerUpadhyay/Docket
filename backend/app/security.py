"""Authentication boundary, tenant context and safe HTTP defaults."""
import logging,time,uuid
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from app import auth,config
from app.models import database as db
logger=logging.getLogger('docket.requests')
PUBLIC={'/api/health','/api/ready','/api/public/config','/api/public/privacy','/api/public/terms','/api/auth/register','/api/auth/login','/api/auth/verify','/api/auth/resend','/api/auth/forgot','/api/auth/reset'}
# This one endpoint authenticates the receiving provider in its own handler.
PUBLIC.add('/api/v1/email/inbound-webhook')

async def security_boundary(request:Request,call_next):
    started=time.monotonic(); request_id=uuid.uuid4().hex
    tokens=[]
    try:
        origin=request.headers.get('origin')
        if request.method in ('POST','PATCH','PUT','DELETE') and origin and origin not in config.ALLOWED_ORIGINS:
            raise HTTPException(403,'Changes from this website origin are not allowed.')
        length=request.headers.get('content-length','0')
        if length.isdigit() and int(length)>12*1024*1024: raise HTTPException(413,'Request exceeds the 12 MB limit.')
        if request.url.path.startswith('/api/') and request.url.path not in PUBLIC and request.method!='OPTIONS':
            bearer=request.headers.get('authorization','')
            token=bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get('docket_session','')
            if not token and config.DEMO_MODE:
                tokens=[(db.scope,db.scope.set('demo')),(db.actor,db.actor.set('demo')),(db.role,db.role.set('owner'))]
            else:
                if token and not bearer and request.method in ('POST','PATCH','PUT','DELETE') and request.headers.get('x-docket-request')!='1':
                    raise HTTPException(403,'The required request header is missing.')
                user=await run_in_threadpool(auth.identity,token)
                selected,_=await run_in_threadpool(auth.workspace,user['id'],request.headers.get('x-workspace-id'))
                request.state.user=user; request.state.token=token
                tokens=[(db.scope,db.scope.set(selected['id'])),(db.actor,db.actor.set(user['id'])),(db.role,db.role.set(selected['role']))]
                if request.method in ('PATCH','PUT','DELETE') and '/notices/' in request.url.path: auth.writable()
                if request.method=='POST' and (('/notices/analyze' in request.url.path or '/ocr/ingest-and-triage' in request.url.path) or '/evidence/' in request.url.path): auth.writable()
                if request.method!='GET': await run_in_threadpool(auth.throttle,'mutations:'+user['id'],120,60)
        response=await call_next(request)
    except HTTPException as exc:
        response=JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers=exc.headers)
    except Exception as exc:
        logger.error('request_failed request_id=%s error_type=%s',request_id,type(exc).__name__)
        response=JSONResponse({'detail':'The service could not complete this request. Try again or contact support with the request ID.'},status_code=500)
    finally:
        for variable,token in reversed(tokens): variable.reset(token)
    response.headers['X-Request-ID']=request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    if config.PRODUCTION: response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    # Deliberately exclude URL paths (case IDs), bodies, query strings and auth headers.
    logger.info('request_id=%s method=%s status=%s duration_ms=%d',request_id,request.method,response.status_code,(time.monotonic()-started)*1000)
    return response


class BodyLimitMiddleware:
    """Count streamed bytes before multipart parsing can spool an unbounded file."""
    def __init__(self,app,maximum=12*1024*1024): self.app,self.maximum=app,maximum
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        received=0
        async def bounded_receive():
            nonlocal received
            message=await receive()
            if message['type']=='http.request':
                received+=len(message.get('body',b''))
                if received>self.maximum: raise HTTPException(413,'Request exceeds the 12 MB limit.')
            return message
        return await self.app(scope,bounded_receive,send)
