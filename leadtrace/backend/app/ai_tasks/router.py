from uuid import UUID
from fastapi import APIRouter,Depends,Header,Query,Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai_tasks import service
from app.ai_tasks.models import AiTask
from app.workspaces.models import PaperWorkspace, WorkspaceState
from app.ai_tasks.contracts import StartTask,RetryTask,LimitUpdate,RepairRequest,AcceptRepair
from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import RouteAccess,declare_route_access,require_permission,require_request_csrf
from app.security.policies import Action,Principal


def create_ai_tasks_router(settings:Settings):
    router=APIRouter(tags=['Admin AI tasks'])
    permission=require_permission(Action.MANAGE_PAPER_CATALOG)
    def csrf(p,token):require_request_csrf(p,token,settings.session_secret.get_secret_value())
    def load(session,id,lock=False):
        q=select(AiTask).where(AiTask.id==id)
        job=session.scalar(q.with_for_update() if lock else q)
        if not job:raise APIError(404,'RESOURCE_NOT_FOUND','Task not found')
        return job
    def error(e):return APIError(409,e.code,str(e))
    @router.get('/api/v2/admin/ai-tasks/options')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def get_options(session:Session=Depends(get_db_session),principal:Principal=Depends(permission)):
        with session.begin():return service.options(session,settings)
    @router.put('/api/v2/admin/ai-tasks/settings')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def update_settings(body:LimitUpdate,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        with session.begin():service.set_limit(session,body.max_concurrent)
        return body.model_dump()
    @router.get('/api/v2/admin/ai-tasks')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def list_jobs(paper_id:UUID|None=None,limit:int=Query(default=100,ge=1,le=500),session:Session=Depends(get_db_session),principal:Principal=Depends(permission)):
        with session.begin():
            query=select(AiTask).join(PaperWorkspace,PaperWorkspace.id==AiTask.workspace_id).where(PaperWorkspace.state!=WorkspaceState.ARCHIVED)
            if paper_id:query=query.where(AiTask.paper_id==paper_id)
            jobs=list(session.scalars(query.order_by(AiTask.created_at.desc(),AiTask.id).limit(limit)))
            return {'items':[service.job_response(session,j) for j in jobs],'total':len(jobs),**service.options(session,settings)}
    @router.get('/api/v2/admin/ai-tasks/{job_id}/report')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def get_report(job_id:UUID,session:Session=Depends(get_db_session),principal:Principal=Depends(permission)):
        from app.ai_tasks.execution import report_for
        with session.begin():
            job=load(session,job_id)
            if job.state in service.OPEN or (job.action=='prefill' and not job.result_summary.get('report_available')):
                raise APIError(409,'REPORT_NOT_READY','Task check report is not available yet')
            try:return report_for(settings,job)
            except service.TaskError as e:raise error(e) from None
            except (ValueError,OSError):raise APIError(409,'REPORT_UNAVAILABLE','The saved report could not be verified') from None
    @router.get('/api/v2/admin/ai-tasks/{job_id}')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def get_job(job_id:UUID,session:Session=Depends(get_db_session),principal:Principal=Depends(permission)):
        with session.begin():return service.job_response(session,load(session,job_id))
    @router.post('/api/v2/admin/papers/{paper_id}/ai-tasks')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def start(paper_id:UUID,body:StartTask,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        try:
            with session.begin():return service.job_response(session,service.enqueue(session,settings,paper_id=paper_id,actor_id=principal.user_id,request=body))
        except service.TaskError as e:raise error(e) from None
    @router.post('/api/v2/admin/ai-tasks/{job_id}/cancel')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def cancel(job_id:UUID,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        with session.begin():return service.job_response(session,service.cancel_job(session,load(session,job_id,True)))
    @router.post('/api/v2/admin/ai-tasks/{job_id}/deliver')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def deliver_saved(job_id:UUID,request:Request,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        with session.begin():load(session,job_id)
        from app.ai_tasks.execution import deliver_result
        try:
            deliver_result(request.app.state.session_factory,settings,job_id,{},deliver_saved=True,delivery_actor_id=principal.user_id)
        except service.TaskError as e:raise error(e) from None
        except (ValueError,OSError):raise APIError(409,'SAVED_RESULT_UNAVAILABLE','Saved files or process ownership could not be verified; nothing was imported') from None
        with session.begin():
            session.expire_all()
            return service.job_response(session,load(session,job_id))
    @router.post('/api/v2/admin/ai-tasks/{job_id}/repair')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def prepare_repair(job_id:UUID,body:RepairRequest,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        from app.ai_tasks.repair import enqueue_repair
        try:
            with session.begin():
                load(session,job_id)
                return service.job_response(session,enqueue_repair(session,settings,review_id=job_id,actor_id=principal.user_id,request=body))
        except service.TaskError as e:raise error(e) from None
        except (ValueError,OSError):raise APIError(409,'REVIEW_UNAVAILABLE','The saved review could not be verified; no repair was started') from None
    @router.post('/api/v2/admin/ai-tasks/{job_id}/accept')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def accept_saved_repair(job_id:UUID,body:AcceptRepair,request:Request,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        with session.begin():load(session,job_id)
        from app.ai_tasks.repair import accept_repair
        from sqlalchemy.exc import SQLAlchemyError
        try:
            accept_repair(request.app.state.session_factory,settings,job_id,actor_id=principal.user_id,proposal_sha256=body.proposal_sha256)
        except service.TaskError as e:raise error(e) from None
        except (ValueError,OSError):raise APIError(409,'PROPOSAL_UNAVAILABLE','The proposal or draft could not be verified; no changes were applied') from None
        except SQLAlchemyError:raise APIError(409,'REPAIR_WRITE_FAILED','Repair could not be saved; draft changes were rolled back') from None
        with session.begin():
            session.expire_all()
            return service.job_response(session,load(session,job_id))
    @router.post('/api/v2/admin/ai-tasks/{job_id}/retry')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def retry(job_id:UUID,body:RetryTask,session:Session=Depends(get_db_session),principal:Principal=Depends(permission),token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(principal,token)
        try:
            with session.begin():
                old=load(session,job_id)
                if old.state not in service.RETRYABLE or old.delivery_state=='applied':raise service.TaskError('RETRY_NOT_AVAILABLE','This task cannot be retried; start a new review of the current draft instead')
                if old.action=='repair':
                    from app.ai_tasks.repair import enqueue_repair
                    review_id=UUID(old.config['review_job_id'])
                    return service.job_response(session,enqueue_repair(session,settings,review_id=review_id,actor_id=principal.user_id,request=RepairRequest(preset_id=old.preset_id,reasoning_effort=old.reasoning_effort,timeout_seconds=old.timeout_seconds,idempotency_key=body.idempotency_key)))
                request=StartTask(action=old.action,preset_id=old.preset_id,reasoning_effort=old.reasoning_effort,expected_workspace_id=old.workspace_id,expected_task_version=old.task_version,expected_workspace_version=old.workspace_version,timeout_seconds=old.timeout_seconds,idempotency_key=body.idempotency_key,auto_review=old.config.get('auto_review'))
                return service.job_response(session,service.enqueue(session,settings,paper_id=old.paper_id,actor_id=principal.user_id,request=request,parent_job=old))
        except service.TaskError as e:raise error(e) from None
        except (ValueError,OSError):raise APIError(409,'REVIEW_UNAVAILABLE','The saved review could not be verified; no retry was started') from None
    return router
