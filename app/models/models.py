import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import DateTime, Integer, String, func, Enum, Boolean, event, ForeignKey, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from zoneinfo import ZoneInfo
class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"

    def __str__(self) -> str:
        return self.name.capitalize()


class Address(Base):
    __tablename__ = 'addresses'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    user: Mapped["User"] = relationship(back_populates="address")
    country: Mapped[str] = mapped_column(String, nullable=False)
    street: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)

    def __repr__(self):
        return f"<Address(id={self.id},country={self.country}, street={self.street}, city={self.city})>"

# Naive datetime function (removes timezone info)
def israel_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Jerusalem")).replace(tzinfo=None)

class ImageReport(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String,nullable=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    # Many-to-one relationship
    report: Mapped["Report"] = relationship(back_populates="images")

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    images: Mapped[List["ImageReport"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    icon: Mapped[str] = mapped_column(String, nullable=True)
    color: Mapped[str] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship(back_populates="reports")
    created: Mapped[datetime] = mapped_column(
        DateTime, default=israel_now, nullable=False, index=True
    )
    updated: Mapped[datetime] = mapped_column(
        DateTime, default=israel_now, onupdate=israel_now
    )

    def __repr__(self):
        return f"<Report(id={self.id}, content={self.title})>"

suspect = "app/uploads/markers/suspect.ico"
civil="app/uploads/markers/civil.ico"
un_solder="app/uploads/markers/un_solder.ico"
leb_solder="app/uploads/markers/leb_solder.ico"


@event.listens_for(Report, "before_insert")
@event.listens_for(Report, "before_update")
def set_icon_and_color(mapper, connection, target):
    if target.title == "Civilian":
        target.icon = civil
        target.color = "#1dff16"
    elif target.title == "Suspect":
        target.icon = suspect
        target.color = "#fd0808"
    elif target.title == "Lebanon Forces":
        target.icon = leb_solder
        target.color = "#232222"
    elif target.title == "UN Forces":
        target.icon = un_solder
        target.color = "rgba(56,168,248,0.6)"



class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=True)
    firstname: Mapped[str] = mapped_column(String(255), nullable=False)
    lastname: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Enum[Role]] = mapped_column(Enum(Role), default=Role.USER, nullable=False)
    isVerified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    isActive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    photo: Mapped[str] = mapped_column(String, nullable=True)
    address: Mapped[Optional["Address"]] = relationship(back_populates="user", uselist=False)
    reports: Mapped[List["Report"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    created: Mapped[datetime] = mapped_column(
        DateTime, default=israel_now, nullable=False, index=True
    )
    updated: Mapped[datetime] = mapped_column(
        DateTime, default=israel_now, onupdate=israel_now
    )
    def __repr__(self):
        return f"<User(id={self.id}, name={self.email})>"
    # @staticmethod
    # def calculate_age(birthday:datetime)->int:
    #     today = datetime.today().date()
    #     age = today.year - birthday.year
    #     if today.month < birthday.month or (today.month == birthday.month and today.day < birthday.day):
    #         age -= 1
    #     return age


filename_user = "app/uploads/user.jpg"


@event.listens_for(User, "before_insert")
def receive_before_insert_photo(mapper, connection, target):
    if not target.photo:
        target.photo = filename_user




