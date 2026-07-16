from aiogram.fsm.state import State, StatesGroup

class FolderCreation(StatesGroup):
    choosing_company = State()    
    confirm_creation = State()     
    editing_name = State()         