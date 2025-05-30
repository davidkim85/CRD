from enum import Enum
from typing import List, Optional
from fastapi import Form
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


###############Address###################33

class RoleEnum(str, Enum):
    USER = "user"
    ADMIN = "admin"

class ImageReportBase(BaseModel):
    url: str

class ImageReportCreate(ImageReportBase):
    pass

class ImageReportRead(ImageReportBase):
    id: int
    report_id: int

    class Config:
        from_attributes = True
class AddressBase(BaseModel):
    street: str
    city: str
    country: str

class AddressCreate(AddressBase):
    pass

class AddressRead(AddressBase):
    id: int
    class Config:
        from_attributes = True
class ReportBase(BaseModel):
    title: str
    latitude: float
    longitude: float
    icon: str
    color:str
    created: datetime
    updated: datetime

class ReportCreate(ReportBase):
    images: List[ImageReportCreate] = []


class UserGet(BaseModel):
    email: EmailStr
    firstname: str
    lastname: str
    role: RoleEnum
    isVerified: bool
    isActive: bool
    photo: str
    created: datetime
    updated: datetime

    class Config:
        from_attributes = True

class ReportRead(ReportBase):
    id: int
    user:UserGet
    images: List[ImageReportRead] = []
    class Config:
        from_attributes = True




class UserBase(BaseModel):
    email: EmailStr
    hashed_password: str
    firstname: str
    lastname: str
    role: RoleEnum
    isVerified: bool
    isActive: bool
    photo: str
    created: datetime
    updated: datetime

class UserCreate(UserBase):
    address: Optional[AddressCreate]=None
    reports: Optional[List[ReportCreate]] = []

class UserRead(UserBase):
    id: int
    address: Optional[AddressRead]
    reports: List[ReportRead] = []
    class Config:
        from_attributes = True



class AddressForm(BaseModel):
    street: str
    city: str
    country: str
    @classmethod
    def as_form(cls, street: str = Form(),city: str = Form(),country: str = Form()):
        return cls(street=street,city=city,country=country)


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    @classmethod
    def as_form(
            cls,
            email: EmailStr = Form(),
            password: str = Form()):
        return cls(email=email, password=password)

class UserPasswordConfirm(BaseModel):
    email:EmailStr
    password1: str
    password2: str
    @classmethod
    def as_form(
            cls,
            email: EmailStr = Form(),
            password1: str = Form(),
            password2: str = Form()):
        return cls(email=email,password1=password1, password2=password2)


class UserRegistration(BaseModel):
    email: EmailStr=Field(min_length=3, max_length=50)
    hashed_password: str=Field(max_length=16,min_length=8)
    confirm_password: str=Field(max_length=16,min_length=8,exclude=True)
    firstname: str=Field(max_length=50)
    lastname: str=Field(max_length=50)


    @classmethod
    def as_form(cls, email: EmailStr = Form(),
                hashed_password: str = Form(),
                confirm_password:str = Form(),
                firstname: str=Form(),
                lastname: str = Form()):
        return cls(email=email,hashed_password=hashed_password,confirm_password=confirm_password, firstname=firstname,lastname=lastname)



class ReportForm(BaseModel):
    title: str
    latitude: float
    longitude: float
    @classmethod
    def as_form(cls,
                title: str = Form(),
                latitude: float = Form(),
                longitude: float = Form()
                ):
        return cls(title=title,latitude=latitude, longitude=longitude)

class GetData(BaseModel):
    count_reports:int
    reports:List[ReportRead]=Field(default_factory=list)


class PasswordCheck(BaseModel):
    password: str


class PasswordCheckRequest(BaseModel):
    password: str