from typing import Type, TypeVar, Generic, Optional, List
from fastapi import Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, asc, desc, or_
from sqlalchemy.orm import selectinload

from app.configurations.database import get_async_session

ModelType = TypeVar("ModelType")

class Pagination(Generic[ModelType]):
    def __init__(
        self,
        model: Type[ModelType],
        db: AsyncSession,
        page: int = 1,
        per_page: int = 10,
        search: Optional[str] = "",
        search_fields: Optional[List[str]] = ["title"],
        sort_by: Optional[str] = "created",
        sort_order: Optional[str] = "desc",
    ):
        self.model = model
        self.db = db
        self.page = page
        self.per_page = per_page
        self.search = search
        self.search_fields = search_fields
        self.sort_by = sort_by
        self.sort_order = sort_order

    async def paginate(self) -> dict:
        base_query = select(self.model)

        # Apply search
        if self.search:
            search_conditions = []
            for field in self.search_fields:
                column = getattr(self.model, field, None)
                if column is not None:
                    search_conditions.append(column.ilike(f"%{self.search}%"))
            if search_conditions:
                base_query = base_query.where(or_(*search_conditions))

        # Apply sorting
        sort_column = getattr(self.model, self.sort_by, None)
        if sort_column is not None:
            order_clause = asc(sort_column) if self.sort_order.lower() == "asc" else desc(sort_column)
            base_query = base_query.order_by(order_clause)

        # Count
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Apply eager load for relationships
        data_query = base_query
        if hasattr(self.model, "images") and hasattr(self.model, "user"):
            data_query = data_query.options(selectinload(self.model.images),selectinload(self.model.user))
        if hasattr(self.model,"address") and hasattr(self.model,"reports"):
            data_query=data_query.options(selectinload(self.model.address),selectinload(self.model.reports))

        # Pagination
        offset = (self.page - 1) * self.per_page
        result = await self.db.execute(data_query.offset(offset).limit(self.per_page))
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": self.page,
            "pages": (total // self.per_page) + (1 if total % self.per_page else 0),
        }

# Dependency to inject pagination parameters into the route
async def get_pagination_params(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, le=100),
    search: str = Query("", max_length=100),
    sort_by: str = Query("created"),
    sort_order: str = Query("desc"),
    search_fields: Optional[List[str]] = Query(["title"]),
    db: AsyncSession = Depends(get_async_session),
):
    return {
        "db": db,
        "page": page,
        "per_page": per_page,
        "search": search,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "search_fields": search_fields,
    }
