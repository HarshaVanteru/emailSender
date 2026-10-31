from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.responses import private_response
from app.features.mailbox.label_service import mutate

router = APIRouter(prefix='/accounts/{account_id}', tags=['labels'], dependencies=[Depends(private_response)])


class LabelName(BaseModel):
    name: str = Field(min_length=1, max_length=225)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError('Use a nonempty label name without control characters.')
        return value.strip()


class LabelChange(BaseModel):
    add: list[str] = Field(default_factory=list, max_length=20)
    remove: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid_ids(self):
        if not self.add and not self.remove or set(self.add) & set(self.remove):
            raise ValueError('Choose distinct labels to add or remove.')
        if any(not value or len(value) > 128 for value in [*self.add, *self.remove]):
            raise ValueError('Invalid label identifier.')
        return self


@router.post('/labels', status_code=201)
def create(account_id: int, request: LabelName, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return mutate(db, user.id, account_id, 'create', name=request.name)


@router.patch('/labels/{label_id}')
def rename(account_id: int, label_id: str, request: LabelName, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return mutate(db, user.id, account_id, 'rename', label_id=label_id, name=request.name)


@router.delete('/labels/{label_id}')
def delete(account_id: int, label_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return mutate(db, user.id, account_id, 'delete', label_id=label_id)


@router.post('/emails/{email_id}/labels')
def assign(account_id: int, email_id: int, request: LabelChange, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return mutate(db, user.id, account_id, 'assign', message_id=email_id, add=request.add, remove=request.remove)
