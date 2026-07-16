from aiogram import Router

def get_handlers_router() -> Router:
    from . import common, creation
    
    router = Router()
    router.include_router(common.router)
    router.include_router(creation.router)
    
    return router